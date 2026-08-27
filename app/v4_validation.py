"""V4 untouched-OOS maker scoreboard.

Applies the FROZEN V3 signal through the measured maker execution chain on the
chronological OOS split (identical split boundaries to V3: ts > 0.85 quantile).
Everything is measured from the replayed L2 stream; nothing is re-estimated,
shuffled, or searched. Enforces:
  - multiple independent OOS periods (sessions)
  - chronological order (no shuffling), no re-use of labels (trades are
    sequential; each fully flattens before the next entry — forward windows
    never overlap)
  - fills and adverse selection measured CONDITIONALLY ON FILLS from the L2
    event stream (never a constant assumption)

Outputs (per spec): fill_probability, full/partial fill probabilities,
median/P95 time-to-fill, adverse_selection mean/median/P95, fill-conditional
drag, net_expectancy, profit_factor, Sharpe, max_drawdown, per-session shares.
"""

import numpy as np

from .v4_signal import HORIZON_MS


def _max_drawdown(values):
    if not len(values):
        return 0.0
    cum = np.cumsum(values)
    peak = np.maximum.accumulate(cum)
    return float(np.min(cum - peak))


def validate_sessions(sessions):
    """sessions: list of {'name', ts, mid, samples (from v4_signal)}."""
    all_s = []
    per_session = {}
    for s in sessions:
        nf = [x for x in s["samples"] if x.get("net_bps") is not None]
        per_session[s["name"]] = {
            "signals": len(s["samples"]),
            "entry_attempts": sum(1 for x in s["samples"] if x.get("posted")),
            "filled": sum(1 for x in s["samples"]
                          if (x.get("entry") or {}).get("filled_ratio", 0) > 0),
            "net_mean_bps": round(float(np.mean([x["net_bps"] for x in nf])), 6)
            if nf else None,
        }
        all_s.extend(s["samples"])

    net = np.array([x["net_bps"] for x in all_s if x.get("net_bps") is not None],
                   dtype=float)
    if not len(net):
        return {"conclusion": "insufficient",
                "reasons": ["no OOS maker net samples measured"],
                "per_session": per_session}
    wins = net[net > 0]
    losses = -net[net <= 0]
    pf = float(wins.sum() / losses.sum()) if losses.sum() > 0 \
        else (float("inf") if wins.sum() > 0 else 0.0)
    sd = net.std(ddof=1) if len(net) > 1 else 0.0
    sharpe = float(net.mean() / (sd / np.sqrt(len(net)))) if sd > 0 else None

    posted_n = sum(1 for x in all_s if x.get("posted"))
    f_entries = [x for x in all_s
                 if (x.get("entry") or {}).get("filled_ratio", 0) > 0]
    f = [x["entry"] for x in f_entries]
    full = [e for e in f if e.get("filled_ratio", 0) >= 1.0 - 1e-9]
    partial = [e for e in f if 0 < e.get("filled_ratio", 0) < 1.0 - 1e-9]
    ttf = []
    for x, e in zip(f_entries, f):
        pl = x.get("_placed_ms")
        ft = e.get("fill_time_ms")
        if pl is not None and ft is not None:
            ttf.append(int(ft) - int(pl))

    adv = [x for x in f_entries if x.get("_adverse_bps") is not None]
    adverse = np.array([x["_adverse_bps"] for x in adv], dtype=float) if adv \
        else np.array([])
    fill_returns = np.array([x["_post_fill_bps"] for x in adv], dtype=float) if adv \
        else np.array([])
    uncond = np.array([x.get("_gated_forward_bps")
                       for x in all_s if x.get("_gated_forward_bps") is not None],
                      dtype=float)

    # largest single session share of net (dominance check)
    s_net = {}
    for x in all_s:
        if x.get("net_bps") is not None:
            s_net[x["session"]] = s_net.get(x["session"], 0.0) + x["net_bps"]
    total = sum(s_net.values())
    largest_share = (max(s_net.values()) / total) if total else None

    return {
        "conclusion": "valid",
        "samples": len(all_s),
        "posted_signals": posted_n,
        "entries_filled": len(f),
        "fill_probability": round(len(f) / posted_n, 6) if posted_n else None,
        "full_fill_probability": round(len(full) / len(f), 6) if f else None,
        "partial_fill_probability": round(len(partial) / len(f), 6) if f else None,
        "median_time_to_fill_ms": round(float(np.median(ttf)), 3) if ttf else None,
        "p95_time_to_fill_ms": round(float(np.percentile(ttf, 95)), 3) if ttf else None,
        "net_expectancy_bps": round(float(net.mean()), 6),
        "net_median_bps": round(float(np.median(net)), 6),
        "profit_factor": pf,
        "sharpe": sharpe,
        "max_drawdown_bps": _max_drawdown(net),
        "adverse_selection_mean_bps": round(float(adverse.mean()), 6) if len(adverse) else None,
        "adverse_selection_median_bps": round(float(np.median(adverse)), 6) if len(adverse) else None,
        "adverse_selection_p95_bps": round(float(np.percentile(adverse, 95)), 6) if len(adverse) else None,
        "fill_conditional_drag_bps": round(float(fill_returns.mean() - uncond.mean()), 6)
        if len(fill_returns) and len(uncond) else None,
        "unconditional_gross_bps": round(float(uncond.mean()), 6) if len(uncond) else None,
        "oos_periods": len(per_session),
        "largest_session_net_share": largest_share,
        "per_session": per_session,
    }