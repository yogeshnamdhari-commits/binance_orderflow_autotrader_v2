"""V21 learned order-flow market-maker research.

This is the first V21 path that connects learned causal order-flow estimates
to a deterministic passive execution replay.

Training is strictly earlier-session first-half data. Test is a later-session
second half. The decision layer uses:
  P(move) * P(direction | move) * E[abs move | move]
minus maker fee and side-specific expected adverse selection.

No random fills and no order submission are used.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.linear_model import HuberRegressor, LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.mm.book import OrderBook
from app.mm.config import V20Config
from app.mm.execution_replay import PassiveQuoteReplay, QuoteIntent, Side, TradeEvent
from app.mm.event_backtest import run_event_backtest
from scripts.v20_event_backtest_capture import load_events, load_snapshot
from scripts.v21_orderflow_dataset import FEATURES, HORIZONS_MS
from scripts.v21_toxicity_model import _future_mid
from scripts.v21_orderflow_core import BookTop, CausalOrderFlowState


MAKER_FEE_BPS = 1.0
HALF_SPREAD_BPS = 2.5
INVENTORY_PENALTY_BPS = 2.0
MAX_POSITION_NOTIONAL_USD = 5000.0
QUOTE_SIZE_USD = 100.0
MIN_EDGE_BPS = 0.10
TOXICITY_HORIZON_MS = 100


@dataclass
class FoldModels:
    move: Pipeline
    direction: Pipeline
    magnitude: HuberRegressor
    toxicity_buy: HuberRegressor
    toxicity_sell: HuberRegressor
    feature_scale: Pipeline | None = None


def _logit(class_weight=None) -> Pipeline:
    return Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "logit",
                LogisticRegression(
                    C=1.0,
                    max_iter=3000,
                    solver="lbfgs",
                    class_weight=class_weight,
                    random_state=0,
                ),
            ),
        ]
    )


def _huber(x: pd.DataFrame, y: pd.Series) -> HuberRegressor:
    model = HuberRegressor(epsilon=1.35, alpha=1.0, max_iter=2000)
    model.fit(x, y)
    return model


def _clean_training(df: pd.DataFrame, target: str, horizon: int) -> pd.DataFrame:
    cols = ["timestamp_ms", "split_start_ms", *FEATURES, target]
    out = df[cols].replace([np.inf, -np.inf], np.nan).dropna()
    out = out[out["timestamp_ms"] <= out["split_start_ms"] - max(HORIZONS_MS)]
    return out


def _build_models(
    dataset: pd.DataFrame,
    toxicity: pd.DataFrame,
    train_sessions: list[str],
) -> tuple[FoldModels, dict[str, int]]:
    train = dataset[dataset["session"].isin(train_sessions) & (dataset["half"] == 0)].copy()
    train_sizes: dict[str, int] = {"rows": int(len(train))}

    # Use the 250 ms horizon for the economic signal. It is far enough ahead
    # to matter for passive fills while retaining usable sample counts.
    horizon = 250
    move_train = _clean_training(train, "move_250ms", horizon)
    direction_train = move_train[move_train["move_250ms"] == 1].copy()
    abs_move = (
        (direction_train["future_mid_250ms"] - direction_train["mid"]).abs()
        * 10_000.0
        / direction_train["mid"]
    )
    # Reconstruct the future magnitude column from the parquet target.
    move_mag_train = direction_train.copy()
    move_mag_train["abs_move_bps"] = abs_move

    if len(move_train) < 500 or len(direction_train) < 50:
        raise ValueError(
            f"insufficient alpha training data: rows={len(move_train)}, moves={len(direction_train)}"
        )

    y_move = move_train["move_250ms"].astype(int)
    move_model = _logit(None)
    move_model.fit(move_train[FEATURES], y_move)

    y_direction = direction_train["direction_250ms"].astype(int)
    if y_direction.nunique() < 2:
        raise ValueError("direction training contains one class")
    direction_model = _logit(None)
    direction_model.fit(direction_train[FEATURES], y_direction)

    magnitude_model = _huber(direction_train[FEATURES], move_mag_train["abs_move_bps"])

    tox = toxicity[
        toxicity["session"].isin(train_sessions) & (toxicity["half"] == 0)
    ].replace([np.inf, -np.inf], np.nan).dropna(
        subset=FEATURES + ["adverse_bps_100ms", "side", "timestamp_ms", "split_start_ms"]
    )
    tox = tox[tox["timestamp_ms"] <= tox["split_start_ms"] - TOXICITY_HORIZON_MS]
    tox_buy = tox[tox["side"] == "BUY"]
    tox_sell = tox[tox["side"] == "SELL"]
    if len(tox_buy) < 100 or len(tox_sell) < 100:
        raise ValueError(f"insufficient toxicity training data: buy={len(tox_buy)} sell={len(tox_sell)}")

    return (
        FoldModels(
            move=move_model,
            direction=direction_model,
            magnitude=magnitude_model,
            toxicity_buy=_huber(tox_buy[FEATURES], tox_buy["adverse_bps_100ms"]),
            toxicity_sell=_huber(tox_sell[FEATURES], tox_sell["adverse_bps_100ms"]),
        ),
        {
            **train_sizes,
            "move_rows": int(len(move_train)),
            "move_events": int(len(direction_train)),
            "toxicity_buy_rows": int(len(tox_buy)),
            "toxicity_sell_rows": int(len(tox_sell)),
        },
    )


def _future_mid_series(snapshot, depth):
    book = OrderBook.from_snapshot(snapshot)
    times: list[int] = []
    mids: list[float] = []
    for e in sorted(depth, key=lambda x: (x.timestamp_ns, x.final_update_id)):
        book.apply_update(e)
        mid = book.get_mid_price()
        if mid > 0:
            times.append(e.timestamp_ns // 1_000_000)
            mids.append(mid)
    return times, mids


def _top(book: OrderBook) -> BookTop | None:
    bids = book.get_depth("bid", levels=1)
    asks = book.get_depth("ask", levels=1)
    if not bids or not asks:
        return None
    return BookTop(
        bid_price=bids[0][0],
        bid_qty=bids[0][1],
        ask_price=asks[0][0],
        ask_qty=asks[0][1],
    )


def _side_queue(book: OrderBook, side: str, price: float) -> float:
    return sum(
        qty for p, qty in book.get_depth(side, levels=50)
        if abs(p - price) <= max(price * 1e-9, 1e-8)
    )


def _features(state: CausalOrderFlowState, timestamp_ms: int) -> np.ndarray:
    f = state.snapshot(timestamp_ms)
    # Match the training dataset feature order exactly.
    return np.asarray(
        [
            f.queue_imbalance,
            f.microprice_edge_bps,
            f.ofi_100ms,
            f.ofi_500ms,
            f.ofi_1000ms,
            f.trade_imbalance_100ms,
            f.trade_imbalance_500ms,
            f.trade_imbalance_1000ms,
            f.trade_intensity_notional_s,
            f.spread_bps,
            f.mid_return_100ms_bps,
            f.mid_return_500ms_bps,
            0.0,  # depth_5_imbalance filled below
        ],
        dtype=float,
    )


def _snapshot_features(state: CausalOrderFlowState, book: OrderBook, timestamp_ms: int) -> tuple[np.ndarray, BookTop]:
    f = state.snapshot(timestamp_ms)
    bids = book.get_depth("bid", levels=5)
    asks = book.get_depth("ask", levels=5)
    if not bids or not asks:
        raise ValueError("missing top of book")
    bid5 = sum(q for _, q in bids)
    ask5 = sum(q for _, q in asks)
    depth5 = (bid5 - ask5) / (bid5 + ask5) if bid5 + ask5 > 0 else 0.0
    x = np.asarray(
        [
            f.queue_imbalance,
            f.microprice_edge_bps,
            f.ofi_100ms,
            f.ofi_500ms,
            f.ofi_1000ms,
            f.trade_imbalance_100ms,
            f.trade_imbalance_500ms,
            f.trade_imbalance_1000ms,
            f.trade_intensity_notional_s,
            f.spread_bps,
            f.mid_return_100ms_bps,
            f.mid_return_500ms_bps,
            depth5,
        ],
        dtype=float,
    ).reshape(1, -1)
    return x, BookTop(
        bid_price=bids[0][0],
        bid_qty=bids[0][1],
        ask_price=asks[0][0],
        ask_qty=asks[0][1],
    )


def _decision(
    models: FoldModels,
    x: np.ndarray,
    top: BookTop,
    inventory: float,
) -> tuple[QuoteIntent, dict[str, float | bool]] | None:
    p_move = float(models.move.predict_proba(x)[:, 1][0])
    p_up = float(models.direction.predict_proba(x)[:, 1][0])
    abs_move = max(0.0, float(models.magnitude.predict(x)[0]))
    expected_signed = p_move * (2.0 * p_up - 1.0) * abs_move

    tox_buy = max(0.0, float(models.toxicity_buy.predict(x)[0]))
    tox_sell = max(0.0, float(models.toxicity_sell.predict(x)[0]))

    inventory_fraction = max(-1.0, min(1.0, inventory * top.mid / MAX_POSITION_NOTIONAL_USD))
    inventory_shift = -inventory_fraction * INVENTORY_PENALTY_BPS
    reservation_shift = expected_signed + inventory_shift
    reservation = top.mid * (1.0 + reservation_shift / 10_000.0)
    half = HALF_SPREAD_BPS / 10_000.0
    raw_bid = reservation * (1.0 - half)
    raw_ask = reservation * (1.0 + half)

    bid = np.floor(raw_bid / 0.1) * 0.1
    ask = np.ceil(raw_ask / 0.1) * 0.1

    bid_cross = bid >= top.ask_price
    ask_cross = ask <= top.bid_price
    if bid_cross:
        bid = None
    if ask_cross:
        ask = None

    bid_edge = (
        ((top.mid - bid) * 10_000.0 / top.mid if bid else 0.0)
        + expected_signed
        - MAKER_FEE_BPS
        - tox_buy
    )
    ask_edge = (
        ((ask - top.mid) * 10_000.0 / top.mid if ask else 0.0)
        - expected_signed
        - MAKER_FEE_BPS
        - tox_sell
    )

    bid_enabled = bid is not None and bid_edge >= MIN_EDGE_BPS
    ask_enabled = ask is not None and ask_edge >= MIN_EDGE_BPS

    if not bid_enabled and not ask_enabled:
        return None, {
            "p_move": p_move,
            "p_up": p_up,
            "abs_move_bps": abs_move,
            "expected_signed_move_bps": expected_signed,
            "tox_buy_bps": tox_buy,
            "tox_sell_bps": tox_sell,
            "bid_edge_bps": bid_edge,
            "ask_edge_bps": ask_edge,
            "quote_enabled": False,
        }

    quote = QuoteIntent(
        quote_id="",
        timestamp_ns=0,
        bid_price=float(bid) if bid_enabled else 0.0,
        bid_qty=QUOTE_SIZE_USD / float(bid) if bid_enabled and bid > 0 else 0.0,
        ask_price=float(ask) if ask_enabled else 0.0,
        ask_qty=QUOTE_SIZE_USD / float(ask) if ask_enabled and ask > 0 else 0.0,
    )
    return quote, {
        "p_move": p_move,
        "p_up": p_up,
        "abs_move_bps": abs_move,
        "expected_signed_move_bps": expected_signed,
        "tox_buy_bps": tox_buy,
        "tox_sell_bps": tox_sell,
        "bid_edge_bps": bid_edge,
        "ask_edge_bps": ask_edge,
        "quote_enabled": True,
    }


def replay_test_session(
    capture_dir: Path,
    session: str,
    models: FoldModels,
) -> dict[str, Any]:
    snapshot = load_snapshot(capture_dir)
    depth, trades, counts = load_events(capture_dir)
    all_times, all_mids = _future_mid_series(snapshot, depth)
    split_start = (all_times[0] + all_times[-1]) // 2

    # Train/test scope: only replay the untouched second half.
    book = OrderBook.from_snapshot(snapshot)
    state = CausalOrderFlowState()
    replay = PassiveQuoteReplay()
    inventory = 0.0
    cash = 0.0
    fees = 0.0
    last_quote: QuoteIntent | None = None
    decision_stats = {
        "events": 0,
        "quote_enabled": 0,
        "bid_enabled": 0,
        "ask_enabled": 0,
        "fills": 0,
        "filled_qty": 0.0,
        "toxicity_suppressed": 0,
    }

    # Replay the complete session to warm the causal state. Strategy decisions
    # and P&L accounting are activated only after the untouched split boundary.
    events: list[tuple[int, int, object]] = []
    events.extend((e.timestamp_ns, 0, e) for e in depth)
    events.extend((e.timestamp_ns, 1, e) for e in trades)
    events.sort(key=lambda z: (z[0], z[1]))

    activated = False
    split_book = OrderBook.from_snapshot(snapshot)
    for e in sorted(depth, key=lambda x: (x.timestamp_ns, x.final_update_id)):
        if e.timestamp_ns // 1_000_000 > split_start:
            break
        split_book.apply_update(e)
    validation_snapshot = type(snapshot)(
        timestamp_ns=split_book.timestamp_ns,
        last_update_id=split_book.last_update_id,
        bids=split_book.get_depth("bid", levels=1000),
        asks=split_book.get_depth("ask", levels=1000),
    )
    test_depth_events = [
        e for e in depth if e.timestamp_ns // 1_000_000 > split_start
    ]
    test_trade_events = [
        e for e in trades if e.timestamp_ns // 1_000_000 > split_start
    ]
    baseline_cfg = V20Config(
        symbol="BTCUSDT",
        base_half_spread_bps=HALF_SPREAD_BPS,
        max_half_spread_bps=4.0,
        inventory_target=0.0,
        inventory_penalty_bps=INVENTORY_PENALTY_BPS,
        max_position_notional_usd=MAX_POSITION_NOTIONAL_USD,
        quote_size_usd=QUOTE_SIZE_USD,
        maker_fee_bps=MAKER_FEE_BPS,
        taker_fee_bps=2.0,
        live_order_submission=False,
    )
    baseline_result = run_event_backtest(
        validation_snapshot,
        test_depth_events,
        test_trade_events,
        baseline_cfg,
    )
    for ts_ns, kind, event in events:
        now = ts_ns // 1_000_000
        if kind == 0:
            depth_event = event
            book.apply_update(depth_event)
            top = _top(book)
            if top is None or not top.valid:
                continue

            state.update_book(now, top)
            if now <= split_start:
                continue
            if not activated:
                replay = PassiveQuoteReplay()
                last_quote = None
                inventory = 0.0
                cash = 0.0
                fees = 0.0
                activated = True
            x, top = _snapshot_features(state, book, now)
            quote_decision = _decision(models, x, top, inventory)
            decision_stats["events"] += 1

            if quote_decision[0] is None:
                decision_stats["toxicity_suppressed"] += 1
                replay.cancel()
                last_quote = None
                continue

            desired, diag = quote_decision
            if diag["quote_enabled"]:
                decision_stats["quote_enabled"] += 1
            decision_stats["bid_enabled"] += int(desired.bid_qty > 0)
            decision_stats["ask_enabled"] += int(desired.ask_qty > 0)

            desired = QuoteIntent(
                quote_id=f"v21-{decision_stats['events']}",
                timestamp_ns=ts_ns,
                bid_price=desired.bid_price,
                bid_qty=desired.bid_qty,
                ask_price=desired.ask_price,
                ask_qty=desired.ask_qty,
            )
            # Any material change replaces the quote and resets queue-ahead.
            if (
                last_quote is None
                or abs(desired.bid_price - last_quote.bid_price) > max(top.mid * 1e-10, 1e-8)
                or abs(desired.ask_price - last_quote.ask_price) > max(top.mid * 1e-10, 1e-8)
                or (desired.bid_qty <= 0) != (last_quote.bid_qty <= 0)
                or (desired.ask_qty <= 0) != (last_quote.ask_qty <= 0)
            ):
                bid_queue = _side_queue(book, "bid", desired.bid_price) if desired.bid_qty > 0 else 0.0
                ask_queue = _side_queue(book, "ask", desired.ask_price) if desired.ask_qty > 0 else 0.0
                replay.activate(
                    desired,
                    visible_bid_qty_at_price=bid_queue,
                    visible_ask_qty_at_price=ask_queue,
                )
                last_quote = desired
            continue

        trade = event
        if now <= split_start:
            state.update_trade(
                now,
                float(trade.qty) if trade.aggressor_side is Side.BUY else -float(trade.qty),
                float(trade.qty) * float(trade.price),
            )
            continue
        if not activated:
            continue
        for fill in replay.on_trade(trade):
            notional = fill.price * fill.qty
            fee = notional * MAKER_FEE_BPS / 10_000.0
            fees += fee
            if fill.side is Side.BUY:
                inventory += fill.qty
                cash -= notional
            else:
                inventory -= fill.qty
                cash += notional
            cash -= fee
            decision_stats["fills"] += 1
            decision_stats["filled_qty"] += fill.qty
        state.update_trade(
            now,
            float(trade.qty) if trade.aggressor_side is Side.BUY else -float(trade.qty),
            float(trade.qty) * float(trade.price),
        )

    final_mid = all_mids[-1] if all_mids else 0.0
    net_pnl = cash + inventory * final_mid
    return {
        "session": session,
        "net_pnl_usd": float(net_pnl),
        "realized_cash_usd": float(cash),
        "fees_usd": float(fees),
        "baseline_net_pnl_usd": float(baseline_result.net_pnl_usd),
        "improvement_vs_fixed_baseline_usd": float(net_pnl - baseline_result.net_pnl_usd),
        "baseline_fills": int(baseline_result.fills),
        "final_inventory": float(inventory),
        "stats": decision_stats,
        "test_depth_events": sum(1 for e in depth if e.timestamp_ns // 1_000_000 > split_start),
        "test_trade_events": sum(1 for e in trades if e.timestamp_ns // 1_000_000 > split_start),
    }


def run(captures_root: Path, toxicity_path: Path, dataset_path: Path) -> dict[str, Any]:
    dataset = pd.read_parquet(dataset_path)
    toxicity = pd.read_parquet(toxicity_path)
    sessions = sorted(dataset["session"].unique())

    results: dict[str, Any] = {}
    for i in range(1, len(sessions)):
        test_session = sessions[i]
        prior = sessions[:i]
        models, sizes = _build_models(dataset, toxicity, prior)
        results[test_session] = {
            "training_sessions": prior,
            "training_sizes": sizes,
            "replay": replay_test_session(
                captures_root / test_session,
                test_session,
                models,
            ),
        }

    return {
        "protocol": "train earlier-session first halves; replay later-session second halves",
        "sessions": sessions,
        "config": {
            "maker_fee_bps": MAKER_FEE_BPS,
            "half_spread_bps": HALF_SPREAD_BPS,
            "inventory_penalty_bps": INVENTORY_PENALTY_BPS,
            "min_edge_bps": MIN_EDGE_BPS,
            "max_position_notional_usd": MAX_POSITION_NOTIONAL_USD,
        },
        "folds": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--captures-root", type=Path, required=True)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--toxicity", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.captures_root, args.toxicity, args.dataset)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
