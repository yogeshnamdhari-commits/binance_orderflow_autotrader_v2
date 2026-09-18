"""Build and evaluate a causal side-specific passive-fill toxicity model.

A fill opportunity is created only when an observed aggressive trade reaches the
current BBO. Queue position is not assumed; these are toxicity opportunities,
not claimed historical fills.
"""

from __future__ import annotations

import argparse
import json
from bisect import bisect_left
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.mm.book import OrderBook
from app.mm.execution_replay import Side
from scripts.v20_event_backtest_capture import load_events, load_snapshot
from scripts.v21_orderflow_dataset import FEATURES


def _past_mid(mid_history: deque[tuple[int, float]], now: int, window: int) -> float | None:
    target = now - window
    candidate = None
    for ts, mid in mid_history:
        if ts > target:
            break
        candidate = mid
    return candidate


def _future_mid(times: list[int], mids: list[float], now: int, horizon: int) -> float | None:
    idx = bisect_left(times, now + horizon)
    return mids[idx] if idx < len(mids) else None


def extract_toxicity_session(capture_dir: Path, session: str) -> pd.DataFrame:
    snapshot = load_snapshot(capture_dir)
    depth, trades, counts = load_events(capture_dir)
    if counts["depth_events"] < 500 or counts["trade_events"] < 500:
        raise ValueError(f"{session}: insufficient events")

    # Build future mid timeline first.
    future_book = OrderBook.from_snapshot(snapshot)
    mid_times: list[int] = []
    mids: list[float] = []
    for e in sorted(depth, key=lambda x: (x.timestamp_ns, x.final_update_id)):
        future_book.apply_update(e)
        mid = future_book.get_mid_price()
        if mid > 0:
            mid_times.append(e.timestamp_ns // 1_000_000)
            mids.append(mid)

    session_midpoint = (mid_times[0] + mid_times[-1]) // 2

    book = OrderBook.from_snapshot(snapshot)
    previous_bid = None
    previous_ask = None
    ofi_history: deque[tuple[int, float]] = deque()
    trade_history: deque[tuple[int, float, float]] = deque()
    mid_history: deque[tuple[int, float]] = deque()
    current_feature: dict[str, Any] | None = None
    samples: list[dict[str, Any]] = []

    merged = [(e.timestamp_ns, 0, e) for e in depth] + [(e.timestamp_ns, 1, e) for e in trades]
    merged.sort(key=lambda x: (x[0], x[1]))

    for ts_ns, kind, event in merged:
        now = ts_ns // 1_000_000

        if kind == 0:
            book.apply_update(event)
            bids = book.get_depth("bid", levels=5)
            asks = book.get_depth("ask", levels=5)
            if not bids or not asks:
                continue

            current_bid = bids[0]
            current_ask = asks[0]
            if previous_bid is None or previous_ask is None:
                ofi = 0.0
            else:
                bp, bq = previous_bid
                ap, aq = previous_ask
                cbp, cbq = current_bid
                cap, caq = current_ask
                bid_component = cbq if cbp > bp else (-bq if cbp < bp else cbq - bq)
                ask_component = -caq if cap < ap else (aq if cap > ap else -(caq - aq))
                ofi = bid_component + ask_component

            previous_bid = current_bid
            previous_ask = current_ask
            ofi_history.append((now, ofi))
            mid = (current_bid[0] + current_ask[0]) / 2.0
            mid_history.append((now, mid))
            cutoff = now - 2000
            while ofi_history and ofi_history[0][0] < cutoff:
                ofi_history.popleft()
            while mid_history and mid_history[0][0] < cutoff:
                mid_history.popleft()

            bid5 = sum(q for _, q in bids)
            ask5 = sum(q for _, q in asks)
            qi_den = current_bid[1] + current_ask[1]
            micro = (
                current_ask[0] * current_bid[1] + current_bid[0] * current_ask[1]
            ) / qi_den if qi_den > 0 else mid
            depth5_imb = (
                (bid5 - ask5) / (bid5 + ask5) if (bid5 + ask5) > 0 else 0.0
            )
            past100 = _past_mid(mid_history, now, 100)
            past500 = _past_mid(mid_history, now, 500)
            current_feature = {
                "timestamp_ms": now,
                "session": session,
                "half": 0 if now <= session_midpoint else 1,
                "queue_imbalance": (
                    (current_bid[1] - current_ask[1]) / qi_den if qi_den > 0 else 0.0
                ),
                "microprice_edge_bps": (micro - mid) * 10_000.0 / mid,
                "ofi_100ms": sum(v for ts, v in ofi_history if ts >= now - 100),
                "ofi_500ms": sum(v for ts, v in ofi_history if ts >= now - 500),
                "ofi_1000ms": sum(v for ts, v in ofi_history if ts >= now - 1000),
                "trade_imbalance_100ms": 0.0,
                "trade_imbalance_500ms": 0.0,
                "trade_imbalance_1000ms": 0.0,
                "trade_intensity_notional_s": 0.0,
                "spread_bps": (current_ask[0] - current_bid[0]) * 10_000.0 / mid,
                "mid_return_100ms_bps": (
                    (mid / past100 - 1.0) * 10_000.0 if past100 and past100 > 0 else 0.0
                ),
                "mid_return_500ms_bps": (
                    (mid / past500 - 1.0) * 10_000.0 if past500 and past500 > 0 else 0.0
                ),
                "depth_5_imbalance": depth5_imb,
                "_mid": mid,
                "_bid": current_bid,
                "_ask": current_ask,
                "split_start_ms": session_midpoint,
            }
            continue

        if current_feature is None:
            continue

        trade = event
        qty = float(trade.qty)
        notional = float(trade.qty) * float(trade.price)
        signed = qty if trade.aggressor_side is Side.BUY else -qty

        # Feature state deliberately excludes the current trade event.
        cutoff = now - 2000
        while trade_history and trade_history[0][0] < cutoff:
            trade_history.popleft()

        def ti(window: int) -> float:
            cutoff_w = now - window
            signed_w = sum(s for ts, s, _ in trade_history if ts >= cutoff_w)
            abs_w = sum(abs(s) for ts, s, _ in trade_history if ts >= cutoff_w)
            return signed_w / abs_w if abs_w > 0 else 0.0

        current_feature["trade_imbalance_100ms"] = ti(100)
        current_feature["trade_imbalance_500ms"] = ti(500)
        current_feature["trade_imbalance_1000ms"] = ti(1000)
        current_feature["trade_intensity_notional_s"] = (
            sum(n for ts, _, n in trade_history if ts >= now - 1000)
        )

        bid_price = current_feature["_bid"][0]
        ask_price = current_feature["_ask"][0]

        if trade.aggressor_side is Side.SELL and float(trade.price) <= bid_price:
            side = "BUY"
            fill_price = bid_price
        elif trade.aggressor_side is Side.BUY and float(trade.price) >= ask_price:
            side = "SELL"
            fill_price = ask_price
        else:
            trade_history.append((now, signed, notional))
            continue

        future = _future_mid(mid_times, mids, now, 100)
        if future is None:
            trade_history.append((now, signed, notional))
            continue

        if side == "BUY":
            adverse_bps = max(0.0, (fill_price - future) * 10_000.0 / fill_price)
        else:
            adverse_bps = max(0.0, (future - fill_price) * 10_000.0 / fill_price)

        row = {k: current_feature[k] for k in FEATURES}
        row.update(
            {
                "timestamp_ms": now,
                "session": session,
                "half": current_feature["half"],
                "split_start_ms": current_feature.get("split_start_ms", session_midpoint),
                "side": side,
                "adverse_bps_100ms": adverse_bps,
                "toxic": int(adverse_bps > 0.0),
                "fill_price": fill_price,
            }
        )
        samples.append(row)
        trade_history.append((now, signed, notional))

    return pd.DataFrame(samples)


def _fit_eval(train: pd.DataFrame, test: pd.DataFrame) -> dict[str, Any]:
    train = train.replace([np.inf, -np.inf], np.nan).dropna(subset=FEATURES + ["toxic"])
    test = test.replace([np.inf, -np.inf], np.nan).dropna(subset=FEATURES + ["toxic"])
    train = train[train["timestamp_ms"] <= (train["split_start_ms"] - 100)]
    if len(train) < 100 or len(test) < 30:
        return {"status": "INSUFFICIENT_DATA", "train_rows": len(train), "test_rows": len(test)}

    y_train = train["toxic"].astype(int)
    y_test = test["toxic"].astype(int)
    if y_train.nunique() < 2 or y_test.nunique() < 2:
        return {"status": "INSUFFICIENT_CLASSES", "train_rows": len(train), "test_rows": len(test)}

    model = Pipeline(
        [
            ("scale", StandardScaler()),
            ("logit", LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced", random_state=0)),
        ]
    )
    model.fit(train[FEATURES], y_train)
    p = model.predict_proba(test[FEATURES])[:, 1]
    return {
        "status": "OK",
        "train_rows": int(len(train)),
        "test_rows": int(len(test)),
        "test_toxic_rate": float(y_test.mean()),
        "auc": float(roc_auc_score(y_test, p)),
        "brier": float(brier_score_loss(y_test, p)),
        "log_loss": float(log_loss(y_test, p, labels=[0, 1])),
        "accuracy_at_0_5": float(accuracy_score(y_test, p >= 0.5)),
        "mean_observed_adverse_bps": float(test["adverse_bps_100ms"].mean()),
        "mean_predicted_toxicity": float(p.mean()),
    }


def run(path: Path) -> dict[str, Any]:
    df = pd.read_parquet(path)
    out: dict[str, Any] = {
        "rows": int(len(df)),
        "sessions": sorted(df["session"].unique().tolist()),
        "features": FEATURES,
        "split": "forward: train on earlier sessions half=0, test on later session half=1",
        "folds": {},
    }
    sessions = sorted(df["session"].unique())
    for i in range(1, len(sessions)):
        test_session = sessions[i]
        prior = sessions[:i]
        train = df[df["session"].isin(prior) & (df["half"] == 0)]
        test = df[(df["session"] == test_session) & (df["half"] == 1)]
        out["folds"][test_session] = {}
        for side in ("BUY", "SELL"):
            out["folds"][test_session][side] = _fit_eval(
                train[train["side"] == side],
                test[test["side"] == side],
            )
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.input)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "
", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
