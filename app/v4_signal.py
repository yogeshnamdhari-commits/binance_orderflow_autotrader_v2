"""V4 signal layer — stale V3 signal fed into the maker execution chain.

This module does NOT re-estimate the predictive model: it loads the FROZEN
v3_model.json and evaluates it on the identical V4 event rows (whose feature
columns are produced by the unmodified ReplayV3._row), so predictions are
byte-identical to V3 for every shared event.

Trading rule (predeclared, no parameter search):
  - entry posted only when the model is directionally confident enough to cover
    the measured ENTRY cost (maker fee per side + latency + predeclared margin):
        |pred| >= POST_GATE_BPS = 1.55 bps
  - LONG posts a passive BUY at best_bid; SHORT posts a passive SELL at
    best_ask; position sized at NOTIONAL_USD / mid
  - fills, partial fills, queue position and sweep fills measured by
    v4_fill.sim_maker_leg from the L2 stream (deterministic)
  - hold HORIZON_MS after entry fill, then post the mirror exit leg; any
    unfilled remainder is closed as a TAKER (crossing) at the measured taker
    cost so positions never leak
  - per-signal net = realized move (entry fill -> effective exit) scaled by
    fill ratios, minus maker fees (filled notional), taker fees (taker-closed
    notional), non-fill/cancel cost (unfilled notional) and latency

Fees come from the measured calibration (maker_rt 2.0 bps / taker_rt 4.0 bps
on Binance USD-M). SAFETY_MARGIN is the same predeclared 0.5 bps as V3.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .v3_features import MODEL_FEATURES
from .v3_model import load_model, predict
from .v4_fill import sim_maker_leg, MAX_WAIT_MS

HORIZON_MS = 500
NOTIONAL_USD = 1000.0
MAKER_FEE_PER_SIDE_BPS = 1.0      # maker fee rt 2.0 bps -> 1.0 bps per side
TAKER_FEE_PER_SIDE_BPS = 2.0      # taker fee rt 4.0 bps -> 2.0 bps per side
SAFETY_MARGIN_BPS = 0.5           # predeclared (same as V3)
CANCEL_OR_NONFILL_COST_BPS = 0.5  # predeclared non-fill / reprice cost
LATENCY_BPS_TOTAL = 0.10          # 0.05 bps entry + 0.05 bps exit (measured)
POST_GATE_BPS = MAKER_FEE_PER_SIDE_BPS + LATENCY_BPS_TOTAL / 2 + SAFETY_MARGIN_BPS


def _forward(ts, mid, t0, h_ms=HORIZON_MS):
    """Forward mid return (bps) from arbitrary t0, or None past session end."""
    i0 = int(np.searchsorted(ts, t0))
    if i0 >= len(ts) or not mid[i0]:
        return None
    i1 = int(np.searchsorted(ts, t0 + h_ms))
    if i1 >= len(ts):
        return None
    return float((mid[i1] - mid[i0]) / mid[i0] * 1e4)


def session_signals(session_name, rows, model_d, oos_mask,
                    notional_usd=NOTIONAL_USD):
    """Run the frozen model over one session's V4 rows on its OOS slice and
    simulate the maker round trips. Returns (samples, session_stats).

    Posting rule (V2/V3-consistent): a maker quote is posted on EVERY directional
    signal — LONG when pred > 0 (passive buy at best_bid), SHORT when pred < 0
    (passive sell at best_ask), sized at NOTIONAL_USD / mid, cancelled after
    MAX_WAIT_MS. The economic gate is NOT applied as a pre-entry magnitude
    screen (that would censor the very fill/adverse-selection dynamics this
    layer exists to measure, and would be inconsistent with how V2/V3 applied
    their gate at decision time); it IS reported as LONG/SHORT/NO_TRADE
    decision states per sample on the same frozen model, exactly as V3 did.
    """
    n = len(rows)
    if n == 0:
        return [], {}
    df = pd.DataFrame(rows)
    pred = predict(model_d, df, HORIZON_MS)
    ts = np.array([r["ts_ms"] for r in rows], dtype=np.int64)
    mid = np.array([(r.get("mid") or 0.0) for r in rows], dtype=float)

    from .v4_fill import SessionStream
    ss = SessionStream(rows)

    samples = []
    i = 0
    while i < n:
        if not oos_mask[i]:
            i += 1
            continue
        p = float(pred[i])
        fwd = _forward(ts, mid, int(ts[i]))
        if abs(p) < 1e-12:
            samples.append(_sample(session_name, rows, i, p, posted=False,
                                   state="NO_TRADE"))
            i += 1
            continue
        side = 1 if p > 0 else -1
        qty = float(notional_usd) / (mid[i] if mid[i] else 1.0)
        entry = sim_maker_leg(ss, i, side, qty, MAX_WAIT_MS)
        s = _sample(session_name, rows, i, p, posted=True, state="NO_MARKET",
                    entry=entry)
        s["_placed_ms"] = int(ts[i])
        s["_gated_forward_bps"] = fwd
        if not entry["placed"]:
            samples.append(s)
            i += 1
            continue
        if entry["filled_ratio"] <= 0:
            s["state"] = "NO_FILL"
            s["net_bps"] = -(CANCEL_OR_NONFILL_COST_BPS + LATENCY_BPS_TOTAL / 2)
            samples.append(s)
            i += 1
            continue
        s.update({"state": "OPEN", "side": side,
                  "_post_fill_bps": _forward(ts, mid, int(entry["fill_time_ms"])),
                  "_signal_forward_bps": fwd})
        s["_adverse_bps"] = (-1 * side * s["_post_fill_bps"]
                             if s["_post_fill_bps"] is not None else None)
        s["entry_fill_time_ms"] = entry["fill_time_ms"]
        entry_px = entry["fill_price"]
        entry_fill_t = entry["fill_time_ms"]
        hold = int(entry_fill_t) + HORIZON_MS
        i_exit = int(np.searchsorted(ts, hold))
        i_exit = min(max(i_exit, i + 1), n - 1)
        exit_side = -side
        pos_qty = qty * entry["filled_ratio"]
        exit_leg = sim_maker_leg(ss, i_exit, exit_side, pos_qty, MAX_WAIT_MS)
        # taker close for any unfilled exit remainder
        i_close = int(np.searchsorted(ts, ts[i_exit] + MAX_WAIT_MS))
        i_close = min(max(i_close, i_exit), n - 1)
        close_px = ss.best(i_close, 0 if exit_side < 0 else 1) or 0.0
        ex_pos = exit_leg["filled_ratio"]
        ex_price = (exit_leg["fill_price"] if ex_pos > 0 else close_px)
        eff_exit = ex_pos * ex_price + (1 - ex_pos) * close_px if close_px else ex_price
        move_bps = (eff_exit - entry_px) / (mid[i] or 1e-9) * 1e4 * side
        r_in = entry["filled_ratio"]
        fees = (MAKER_FEE_PER_SIDE_BPS * r_in) \
            + (MAKER_FEE_PER_SIDE_BPS * r_in * ex_pos) \
            + (TAKER_FEE_PER_SIDE_BPS * r_in * (1 - ex_pos)) \
            + (CANCEL_OR_NONFILL_COST_BPS * (1 - r_in)) \
            + LATENCY_BPS_TOTAL
        s.update({
            "state": "FLAT",
            "entry_fill_ratio": r_in,
            "exit_fill_ratio": ex_pos,
            "entry_fill_price": entry_px,
            "exit_fill_price": ex_price,
            "taker_close_price": close_px if ex_pos < 1 else None,
            "move_bps": move_bps,
            "fees_bps": fees,
            "net_bps": move_bps - fees,
        })
        samples.append(s)
        i_end = max(i_close, i_exit) + 1
        i = max(i + 1, i_end)
    stats = _session_stats(samples)
    return samples, stats


def _sample(session_name, rows, i, pred, posted, state, entry=None):
    r = rows[i]
    return {"session": session_name, "ts_ms": int(r["ts_ms"]),
            "kind": r["kind"], "pred_bps": float(pred), "posted": bool(posted),
            "state": state, "entry": (entry or {})}


def _session_stats(samples):
    fs = [s for s in samples if s.get("net_bps") is not None]
    posted = [s for s in samples if s.get("posted")]
    entry_attempts = len(posted)
    fills = [s for s in posted if (s.get("entry") or {}).get("filled_ratio", 0) > 0]
    net = np.array([s["net_bps"] for s in fs], dtype=float) if fs else np.array([])
    if len(fs):
        wins = net[net > 0]
        losses = -net[net <= 0]
        pf = float(wins.sum() / losses.sum()) if losses.sum() > 0 \
            else (float("inf") if wins.sum() > 0 else 0.0)
        sd = net.std(ddof=1) if len(net) > 1 else 0.0
    else:
        wins = losses = np.array([])
        pf, sd = 0.0, 0.0
    return {
        "signals": len(samples),
        "no_trade": len([s for s in samples if s["state"] == "NO_TRADE"]),
        "entry_attempts": entry_attempts,
        "posted_positive": len([s for s in samples if s.get("posted") and s["pred_bps"] > 0]),
        "posted_negative": len([s for s in samples if s.get("posted") and s["pred_bps"] < 0]),
        "entries_filled": len(fills),
        "entry_fill_rate": round(len(fills) / entry_attempts, 6) if entry_attempts else None,
        "net_mean_bps": round(float(net.mean()), 6) if len(fs) else None,
        "net_median_bps": round(float(np.median(net)), 6) if len(fs) else None,
        "profit_factor": pf,
        "sharpe": round(float(net.mean() / (sd / np.sqrt(len(net)))), 6)
        if len(net) > 1 and sd > 0 else None,
    }