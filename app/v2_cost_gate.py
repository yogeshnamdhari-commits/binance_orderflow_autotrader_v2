"""V2 economic gate — net edge = expected gross edge - measured execution cost.

Costs are EMPIRICAL, from the existing calibration artifacts:
  - taker round-trip: data/hist/research/execution_calibration.json
        `effective_taker_roundtrip.{notional_usd}.p90_bps` (+ latency, impact)
  - fees: fees_per_side_bps / maker_fee_rt_bps / taker_fee_rt_bps
  - maker adverse selection: median(gross_unconditional - e_fill_return) over
        the `oos_fill` block (the only untouched-sample fill evidence).
        NOTE: no ms-horizon fill calibration exists yet for V2; the measured
        5s+ adverse-selection drag is used as a conservative proxy and flagged.
  - p_fill proxy: median `p_fill_same_tick` over oos_fill cells.

Gating is conservative: taker uses the p90 cost tail; maker includes the
adverse-selection drag and the (1-p_fill) reprice penalty. LONG and SHORT are
gated independently.

Constants below match the V1 execution-cost-module conventions so the V1/V2
cost views are comparable.
"""

import json
from pathlib import Path

DEFAULT_CAL_PATH = Path("data/hist/research/execution_calibration.json")
DEFAULT_NOTIONAL_USD = 1000.0
IMPACT_ALLOWANCE_BPS = 0.10
LATENCY_COST_BPS = 0.05
NON_FILL_REPRICE_COST_BPS = 0.50


def _load(cal_path=DEFAULT_CAL_PATH):
    return json.load(open(cal_path))


def _adjacent(arr, key):
    ts = sorted(int(k) for k in arr)
    best = None
    for t in ts:
        if t >= key:
            best = t
            break
        best = t
    return ts[0] if ts else None


def taker_cost_bps(cal, notional_usd=DEFAULT_NOTIONAL_USD, lat_cost_bps=LATENCY_COST_BPS):
    band = _adjacent(cal["effective_taker_roundtrip"], notional_usd)
    rt = cal["effective_taker_roundtrip"][str(band)]["p90_bps"]
    return round(float(rt) + IMPACT_ALLOWANCE_BPS + lat_cost_bps, 6)


def _median(xs):
    xs = sorted(xs)
    m = len(xs) // 2
    if len(xs) % 2:
        return xs[m]
    return (xs[m - 1] + xs[m]) / 2.0


def maker_components(cal):
    oos = cal.get("oos_fill", {})
    drags, pfills = [], []
    for cell in oos.values():
        g = cell.get("gross_unconditional_bps")
        e = cell.get("e_fill_return_bps")
        if g is not None and e is not None:
            drags.append(g - e)
        if cell.get("p_fill_same_tick") is not None:
            pfills.append(cell["p_fill_same_tick"])
    drag = _median(drags) if drags else 0.50
    p_fill = _median(pfills) if pfills else 0.70
    return {"adverse_selection_bps": round(drag, 4),
            "p_fill": round(p_fill, 4),
            "n_cells": len(oos),
            "note": "measured on V1 5s+ touched-OOS fill block; ms-horizon V2 fill calibration pending"}


def maker_cost_bps(cal, lat_cost_bps=LATENCY_COST_BPS):
    comp = maker_components(cal)
    maker_fee = float(cal.get("maker_fee_rt_bps", 2.0))
    non_fill = NON_FILL_REPRICE_COST_BPS * (1.0 - comp["p_fill"])
    total = maker_fee + comp["adverse_selection_bps"] + non_fill + lat_cost_bps
    return round(total, 6), comp


def net_edges(gross_bps, cal, notional_usd=DEFAULT_NOTIONAL_USD, style="taker"):
    """Returns {'long': bps, 'short': bps, 'cost': bps, 'components': ...}."""
    if style == "taker":
        cost = taker_cost_bps(cal, notional_usd)
        comp = {"style": "taker", "notional_usd": float(notional_usd),
                "cost_bps": cost, "basis": "effective_taker_roundtrip.p90 + impact + latency"}
    elif style == "maker":
        cost, comp = maker_cost_bps(cal)
        comp = {"style": "maker", **comp, "cost_bps": cost,
                "basis": "maker_fee_rt + adverse_selection + (1-p_fill)*reprice + latency"}
    else:
        raise ValueError("unknown style %r" % style)
    return {"long": round(gross_bps - cost, 6),
            "short": round(-gross_bps - cost, 6),
            "gross_bps": round(gross_bps, 6), "cost_bps": cost, "components": comp}


def decide(gross_bps, cal, notional_usd=DEFAULT_NOTIONAL_USD, style="taker"):
    e = net_edges(gross_bps, cal, notional_usd, style)
    long_ok = e["long"] > 0.0
    short_ok = e["short"] > 0.0
    if long_ok and short_ok:
        state = "LONG" if e["long"] >= e["short"] else "SHORT"
    elif long_ok:
        state = "LONG"
    elif short_ok:
        state = "SHORT"
    else:
        state = "NO_TRADE"
    e["state"] = state
    return e


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--gross-bps", type=float, required=True)
    ap.add_argument("--notional-usd", type=float, default=DEFAULT_NOTIONAL_USD)
    ap.add_argument("--style", default="taker", choices=("taker", "maker"))
    a = ap.parse_args()
    print(json.dumps(decide(a.gross_bps, _load(), a.notional_usd, a.style), indent=1))