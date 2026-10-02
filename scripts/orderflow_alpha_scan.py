#!/usr/bin/env python3
"""Deterministic ORDERFLOW_ALPHA-0.1 research scanner.

Consumes three authentic BTCUSDT USD-M perpetual capture directories. No network
access and no order submission occur here. Capture 1 is development-only; captures
2 and 3 are untouched OOS validation.

The scan uses a finite preregistered rule family:
  signal = sign(feature) when |feature| exceeds a threshold, else no-trade
Thresholds are fixed training quantiles from capture 1.

Gross edge is the mean signed future-mid return in basis points. The economic gate
is gross > 5.4 bps, corresponding to 3.4 bps round-trip taker cost plus 2.0 bps
safety buffer.
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import statistics
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

HORIZONS_MS = (250, 500, 1000, 2000, 5000, 10000, 30000, 60000)
FLOW_WINDOWS_MS = (100, 250, 500, 1000)
QUANTILES = (0.80, 0.90, 0.95)

ROUND_TRIP_COST_BPS = 3.4
SAFETY_BUFFER_BPS = 2.0
GROSS_GATE_BPS = ROUND_TRIP_COST_BPS + SAFETY_BUFFER_BPS
OOS_MIN_OBS = 50

@dataclass
class Depth:
    ts_ns: int
    U: int
    u: int
    pu: int
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]

@dataclass
class Trade:
    ts_ns: int
    price: float
    qty: float
    signed_qty: float

class Book:
    def __init__(self, snapshot: dict[str, Any]) -> None:
        self.bids = {float(p): float(q) for p, q in snapshot["bids"]}
        self.asks = {float(p): float(q) for p, q in snapshot["asks"]}
        self.last = int(snapshot["lastUpdateId"])
        self.bridged = False

    def apply(self, d: Depth) -> None:
        if d.u <= self.last:
            return
        if not self.bridged:
            if not ((d.U <= self.last <= d.u) or (d.pu == self.last)):
                raise ValueError(
                    "invalid depth bootstrap: first event does not span snapshot lastUpdateId"
                )
            self.bridged = True
        elif d.pu != self.last:
            raise ValueError(
                f"sequence gap while scanning: expected pu={self.last}, got {d.pu}"
            )
        for p, q in d.bids:
            if q == 0:
                self.bids.pop(p, None)
            else:
                self.bids[p] = q
        for p, q in d.asks:
            if q == 0:
                self.asks.pop(p, None)
            else:
                self.asks[p] = q
        self.last = d.u

    def state(self, levels: int = 10) -> tuple[float, float, float, float, float, float]:
        if not self.bids or not self.asks:
            raise ValueError("empty book")
        bid_levels = sorted(self.bids.items(), reverse=True)[:levels]
        ask_levels = sorted(self.asks.items())[:levels]
        bb = bid_levels[0][0]
        ba = ask_levels[0][0]
        if bb >= ba:
            raise ValueError("crossed book")
        mid = (bb + ba) / 2.0
        bq = bid_levels[0][1]
        aq = ask_levels[0][1]
        micro = (ba * bq + bb * aq) / (bq + aq) if (bq + aq) > 0 else mid
        bi5 = _imbalance(bid_levels[:5], ask_levels[:5])
        bi10 = _imbalance(bid_levels[:10], ask_levels[:10])
        return mid, (ba - bb) * 10000.0 / mid, micro, bi5, bi10, sum(q for _, q in bid_levels[:5]) + sum(q for _, q in ask_levels[:5])

def _imbalance(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> float:
    b = sum(q for _, q in bids)
    a = sum(q for _, q in asks)
    return (b - a) / (b + a) if b + a else 0.0

def _raw_events(capture: Path) -> list[dict[str, Any]]:
    rows = []
    with (capture / "events.jsonl").open("r", encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            if row.get("event_type") in {"depthUpdate", "aggTrade", "markPriceUpdate"}:
                rows.append(row)
    return rows

def _parse_capture(capture: Path) -> tuple[dict[str, Any], list[Depth], list[Trade]]:
    manifest = json.loads((capture / "manifest.json").read_text())
    if manifest.get("symbol") != "BTCUSDT" or manifest.get("market") != "USD-M" or manifest.get("instrument") != "PERPETUAL":
        raise ValueError(f"{capture}: wrong instrument scope")
    if manifest.get("sequence_gaps", 0) != 0 or manifest.get("reconnects", 0) != 0:
        raise ValueError(f"{capture}: invalid integrity flags")
    if manifest.get("bootstrap", {}).get("status") != "BRIDGED":
        raise ValueError(f"{capture}: bootstrap not bridged")

    snapshot = json.loads((capture / "snapshot.json").read_text())
    depth: list[Depth] = []
    trades: list[Trade] = []
    for row in _raw_events(capture):
        raw = json.loads(row["raw_json"])
        data = raw.get("data", raw)
        event = data.get("e")
        if event == "depthUpdate":
            depth.append(Depth(
                ts_ns=int(data.get("E", row.get("received_ns", 0))) * 1_000_000,
                U=int(data["U"]), u=int(data["u"]), pu=int(data.get("pu", 0)),
                bids=[(float(p), float(q)) for p, q in data["b"]],
                asks=[(float(p), float(q)) for p, q in data["a"]],
            ))
        elif event == "aggTrade":
            qty=float(data["q"])
            # Binance aggTrade m=true means buyer is maker -> aggressor is SELL.
            signed= -qty if bool(data.get("m", False)) else qty
            trades.append(Trade(
                ts_ns=int(data.get("T", data.get("E", row.get("received_ns", 0)))) * 1_000_000,
                price=float(data["p"]), qty=qty, signed_qty=signed,
            ))
    depth.sort(key=lambda x: x.ts_ns)
    trades.sort(key=lambda x: x.ts_ns)
    if not depth or not trades:
        raise ValueError(f"{capture}: missing depth or trades")
    return manifest, depth, trades

def _build_panel(capture: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, depth, trades = _parse_capture(capture)
    snapshot = json.loads((capture / "snapshot.json").read_text())
    book = Book(snapshot)

    # Replay observations chronologically. The depth sequence is independently
    # enforced by Book.apply(); trade features only use trades timestamped <= obs ts.
    trade_i = 0
    flow_q: dict[int, deque[tuple[int, float]]] = {w: deque() for w in FLOW_WINDOWS_MS}
    flow_signed: dict[int, float] = {w: 0.0 for w in FLOW_WINDOWS_MS}
    flow_abs: dict[int, float] = {w: 0.0 for w in FLOW_WINDOWS_MS}
    mids: list[tuple[int, float]] = []
    records: list[dict[str, float | int]] = []
    prev_depth5: float | None = None
    mid_hist: deque[tuple[int, float]] = deque()
    trade_time_q: deque[int] = deque()

    for d in depth:
        while trade_i < len(trades) and trades[trade_i].ts_ns <= d.ts_ns:
            t = trades[trade_i]
            trade_time_q.append(t.ts_ns)
            for w in FLOW_WINDOWS_MS:
                cutoff = t.ts_ns - w * 1_000_000
                q = flow_q[w]
                while q and q[0][0] < cutoff:
                    _, old = q.popleft()
                    flow_signed[w] -= old
                    flow_abs[w] -= abs(old)
                q.append((t.ts_ns, t.signed_qty))
                flow_signed[w] += t.signed_qty
                flow_abs[w] += abs(t.signed_qty)
            trade_i += 1

        try:
            book.apply(d)
            mid, spread, micro, bi5, bi10, depth5 = book.state()
        except ValueError:
            continue

        while trade_time_q and trade_time_q[0] < d.ts_ns - 1_000_000_000:
            trade_time_q.popleft()

        mids.append((d.ts_ns, mid))
        mid_hist.append((d.ts_ns, mid))
        while mid_hist and mid_hist[0][0] < d.ts_ns - 5_000_000_000:
            mid_hist.popleft()

        def rv_ms(window_ms: int) -> float:
            cutoff = d.ts_ns - window_ms * 1_000_000
            vals = [m for ts, m in mid_hist if ts >= cutoff]
            if len(vals) < 3:
                return 0.0
            rets = np.diff(np.log(np.asarray(vals, dtype=float)))
            return float(np.std(rets) * 10_000.0)

        f: dict[str, float | int] = {
            "ts_ns": d.ts_ns,
            "mid": mid,
            "spread_bps": spread,
            "microprice_bps": (micro - mid) * 10000.0 / mid,
            "book_imbalance_5": bi5,
            "book_imbalance_10": bi10,
            "depth_change_5": 0.0 if prev_depth5 in (None, 0.0) else (depth5 - prev_depth5) / prev_depth5,
            "vol_1s_bps": rv_ms(1000),
            "vol_5s_bps": rv_ms(5000),
        }
        prev_depth5 = depth5
        for w in FLOW_WINDOWS_MS:
            denom = flow_abs[w]
            f[f"flow_imbalance_{w}ms"] = flow_signed[w] / denom if denom > 0 else 0.0
            f[f"flow_abs_{w}ms"] = denom
        f["flow_x_vol"] = float(f["flow_imbalance_500ms"]) * float(f["vol_1s_bps"])
        f["trade_intensity_1s"] = sum(1 for t in trades if d.ts_ns - 1_000_000_000 <= t.ts_ns <= d.ts_ns)
        records.append(f)

    # Fast forward labels by binary search over reconstructed mids.
    times = [ts for ts, _ in mids]
    prices = [m for _, m in mids]
    for r in records:
        ts = int(r["ts_ns"])
        m0 = float(r["mid"])
        for h in HORIZONS_MS:
            j = bisect.bisect_left(times, ts + h * 1_000_000)
            if j < len(prices):
                r[f"ret_{h}ms"] = (prices[j] / m0 - 1.0) * 10_000.0
            else:
                r[f"ret_{h}ms"] = float("nan")
    return manifest, {"records": records, "n_depth": len(depth), "n_trades": len(trades)}

def _candidate_specs(train_records: list[dict[str, float | int]]) -> list[dict[str, Any]]:
    features = [
        "flow_imbalance_100ms", "flow_imbalance_250ms", "flow_imbalance_500ms",
        "flow_imbalance_1000ms", "book_imbalance_5", "book_imbalance_10",
        "microprice_bps", "depth_change_5", "flow_x_vol", "trade_intensity_1s"
    ]
    specs: list[dict[str, Any]] = []
    for feature in features:
        vals = np.asarray([abs(float(r[feature])) for r in train_records if math.isfinite(float(r.get(feature, 0.0)))])
        if len(vals) < 20:
            continue
        for q in QUANTILES:
            threshold = float(np.quantile(vals, q))
            if threshold <= 0:
                continue
            for h in HORIZONS_MS:
                specs.append({"feature": feature, "threshold": threshold, "horizon_ms": h})
    return specs

def _gross(records: list[dict[str, float | int]], spec: dict[str, Any]) -> tuple[float, int, float]:
    f = spec["feature"]; th = spec["threshold"]; h = spec["horizon_ms"]
    vals=[]
    for r in records:
        x=float(r.get(f, 0.0))
        y=float(r.get(f"ret_{h}ms", float("nan")))
        if not math.isfinite(x) or not math.isfinite(y) or abs(x) < th:
            continue
        vals.append((1.0 if x > 0 else -1.0) * y)
    if not vals:
        return float("nan"), 0, float("nan")
    return float(np.mean(vals)), len(vals), float(np.std(vals, ddof=1) / math.sqrt(len(vals))) if len(vals) > 1 else float("nan")

def _bootstrap_ci(values: np.ndarray, seed: int = 17, reps: int = 1000, block: int = 50) -> tuple[float, float]:
    if len(values) < 2:
        return float("nan"), float("nan")
    rng=np.random.default_rng(seed)
    n=len(values)
    # Non-overlapping blocks preserve local dependence without assuming iid fills.
    starts=np.arange(0, n, block)
    blocks=[values[s:min(s+block,n)] for s in starts]
    means=[]
    for _ in range(reps):
        sample=np.concatenate([blocks[int(i)] for i in rng.integers(0,len(blocks),size=len(blocks))])
        means.append(float(np.mean(sample)))
    return float(np.quantile(means,0.025)), float(np.quantile(means,0.975))

def _values(records: list[dict[str, float | int]], spec: dict[str, Any]) -> np.ndarray:
    f=spec["feature"]; th=spec["threshold"]; h=spec["horizon_ms"]
    out=[]
    for r in records:
        x=float(r.get(f,0.0)); y=float(r.get(f"ret_{h}ms",float("nan")))
        if math.isfinite(x) and math.isfinite(y) and abs(x)>=th:
            out.append((1.0 if x>0 else -1.0)*y)
    return np.asarray(out,dtype=float)

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--capture", action="append", required=True, help="repeat exactly 3 times")
    ap.add_argument("--output", type=Path, required=True)
    args=ap.parse_args()
    if len(args.capture)!=3:
        raise SystemExit("--capture must be supplied exactly 3 times")

    panels=[]
    manifests=[]
    for c in args.capture:
        manifest,panel=_build_panel(Path(c))
        manifests.append(manifest)
        panels.append(panel)

    train=panels[0]["records"]
    specs=_candidate_specs(train)

    scored=[]
    for s in specs:
        gross,n,_=_gross(train,s)
        if math.isfinite(gross):
            scored.append((gross,n,s))
    scored.sort(key=lambda x:x[0],reverse=True)
    top=scored[:20]

    oos=[]
    for gross_dev,n_dev,s in top:
        session_rows=[]
        oos_values_by_session=[]
        for idx in (1,2):
            vals=_values(panels[idx]["records"],s)
            oos_values_by_session.append(vals)
            gross=float(np.mean(vals)) if len(vals) else float("nan")
            ci=_bootstrap_ci(vals)
            net=gross-ROUND_TRIP_COST_BPS if math.isfinite(gross) else float("nan")
            session_rows.append({
                "capture_index":idx+1,"observations":int(len(vals)),
                "gross_bps":gross,"net_bps":net,
                "ci95_gross_bps":[ci[0],ci[1]],
                "passes_gross_gate":bool(math.isfinite(gross) and gross>GROSS_GATE_BPS),
                "passes_net_gate":bool(math.isfinite(net) and net>0),
            })
        nonempty=[vals for vals in oos_values_by_session if len(vals)]
        pooled_vals=np.concatenate(nonempty) if nonempty else np.asarray([], dtype=float)
        pg=float(np.mean(pooled_vals)) if len(pooled_vals) else float("nan")
        pci=_bootstrap_ci(pooled_vals)
        oos.append({
            "spec":s,
            "dev":{"gross_bps":gross_dev,"observations":n_dev},
            "oos_sessions":session_rows,
            "oos_pooled":{"observations":int(len(pooled_vals)),
                          "gross_bps":pg,"net_bps":pg-ROUND_TRIP_COST_BPS if math.isfinite(pg) else float("nan"),
                          "ci95_gross_bps":[pci[0],pci[1]]},
            "economic_candidate":bool(
                len(pooled_vals)>=OOS_MIN_OBS and math.isfinite(pg) and
                pg>GROSS_GATE_BPS and (pg-ROUND_TRIP_COST_BPS)>0 and
                all(x["passes_gross_gate"] and x["passes_net_gate"] for x in session_rows)
            ),
        })

    report={
        "hypothesis":"ORDERFLOW_ALPHA-0.1",
        "instrument":"BTCUSDT",
        "market":"USD-M",
        "instrument_type":"PERPETUAL",
        "economic_gate":{"round_trip_cost_bps":ROUND_TRIP_COST_BPS,
                         "safety_buffer_bps":SAFETY_BUFFER_BPS,
                         "gross_edge_gate_bps":GROSS_GATE_BPS},
        "data":[
            {"capture_index":i+1,"session_id":m.get("session_id"),
             "schema_version":m.get("schema_version"),
             "event_count":m.get("event_count"),
             "depth_events":m.get("depth_events"),
             "trade_events":m.get("trade_events"),
             "mark_price_events":m.get("mark_price_events"),
             "sequence_gaps":m.get("sequence_gaps"),
             "reconnects":m.get("reconnects"),
             "bootstrap":m.get("bootstrap")}
            for i,m in enumerate(manifests)
        ],
        "development_candidates_tested":len(scored),
        "top_oos_candidates":oos,
        "deployment":"NO_DEPLOY",
        "economic_certification":"NOT_CERTIFIED",
    }
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))
    return 0

if __name__=="__main__":
    raise SystemExit(main())
