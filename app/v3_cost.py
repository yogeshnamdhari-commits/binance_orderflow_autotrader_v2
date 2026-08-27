"""V3 execution-cost model and economic gate.

Cost is measured, not assumed:
  taker:  p90 effective taker round-trip (from execution_calibration.json)
          + market-impact allowance + latency cost
  maker:  maker fee round-trip + adverse selection (measured from the V1
          touched-OOS fill block) + (1 - P(fill)) reprice penalty + latency

P(fill | queue state) is the empirical p_fill_same_tick from the fill
calibration; it is treated as a state-dependent parameter within the maker
expected-PnL, never as "maker is cheaper so use maker".

SAFETY_MARGIN_BPS is predeclared (fixed before any OOS examination) and is the
minimum expected net edge required per side. The gate:

  LONG   iff  E[ΔP] - Cost_taker - margin > 0   (directional evidence bullish)
  SHORT  iff -E[ΔP] - Cost_taker - margin > 0   (directional evidence bearish)
  NO_TRADE otherwise

The gate is applied PER STYLE (taker / maker); changing a threshold to
manufacture trades is explicitly out of scope.
"""

import json
from pathlib import Path

DEFAULT_CAL_PATH = Path("data/hist/research/execution_calibration.json")
DEFAULT_NOTIONAL_USD = 1000.0
SAFETY_MARGIN_BPS = 0.5   # predeclared, fixed before OOS
IMPACT_ALLOWANCE_BPS = 0.10
LATENCY_COST_BPS = 0.05
NON_FILL_REPRICE_COST_BPS = 0.50
P_FILL_DEFAULT = 0.70


def load_cal(cal_path=DEFAULT_CAL_PATH):
    return json.load(open(cal_path))


def _adjacent(arr, key):
    ts = sorted(int(k) for k in arr)
    best = ts[0] if ts else None
    for t in ts:
        if t >= key:
            best = t
            break
        best = t
    return best


def taker_cost_bps(cal, notional_usd=DEFAULT_NOTIONAL_USD):
    band = _adjacent(cal.get("effective_taker_roundtrip", {}), notional_usd)
    if band is None:
        return round(2.5 + IMPACT_ALLOWANCE_BPS + LATENCY_COST_BPS, 6)
    rt = cal["effective_taker_roundtrip"][str(band)]["p90_bps"]
    return round(float(rt) + IMPACT_ALLOWANCE_BPS + LATENCY_COST_BPS, 6)


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
    p_fill = _median(pfills) if pfills else P_FILL_DEFAULT
    return {"adverse_selection_bps": round(drag, 4), "p_fill": round(p_fill, 4),
            "n_cells": len(oos)}


def maker_cost_bps(cal):
    comp = maker_components(cal)
    fee = float(cal.get("maker_fee_rt_bps", 2.0))
    reprice = NON_FILL_REPRICE_COST_BPS * (1.0 - comp["p_fill"])
    total = fee + comp["adverse_selection_bps"] + reprice + LATENCY_COST_BPS
    return round(total, 6), comp


def cost_model(cal, notional_usd=DEFAULT_NOTIONAL_USD, margin_bps=SAFETY_MARGIN_BPS):
    tak, mak_comp = taker_cost_bps(cal, notional_usd), maker_components(cal)
    mak, _ = maker_cost_bps(cal)
    return {
        "notional_usd": float(notional_usd),
        "safety_margin_bps": margin_bps,
        "taker": {"total_bps": tak, "margin_bps": margin_bps,
                  "gate_bps": tak + margin_bps,
                  "components": {
                      "basis": "effective_taker_roundtrip.p90 + impact + latency",
                      "spread_bps": cal.get("spread", {}).get("p90_bps"),
                      "slippage_bps": cal.get("slippage_by_notional", {})
                                       .get(str(int(notional_usd)), {})
                                       .get("buy_p90_bps")}},
        "maker": {"total_bps": mak, "margin_bps": margin_bps,
                  "gate_bps": mak + margin_bps,
                  "components": {"adverse_selection_bps":
                                     mak_comp["adverse_selection_bps"],
                                 "p_fill": mak_comp["p_fill"],
                                 "maker_fee_rt_bps":
                                     cal.get("maker_fee_rt_bps", 2.0)}},
    }


def decide(gross_bps, cost, style="taker"):
    """Economic gate: expected move vs measured cost + predeclared margin."""
    base = cost[style]["total_bps"] + cost["safety_margin_bps"]
    net_long = gross_bps - base
    net_short = -gross_bps - base
    if net_long > 0 and net_short > 0:
        state = "LONG" if net_long >= net_short else "SHORT"
    elif net_long > 0:
        state = "LONG"
    elif net_short > 0:
        state = "SHORT"
    else:
        state = "NO_TRADE"
    return {"state": state, "gross_bps": gross_bps,
            "gate_bps": base, "net_long_bps": net_long,
            "net_short_bps": net_short, "style": style}


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--gross-bps", type=float, required=True)
    ap.add_argument("--style", default="taker", choices=("taker", "maker"))
    a = ap.parse_args()
    cost = cost_model(load_cal())
    print(json.dumps(decide(a.gross_bps, cost, a.style), indent=1))
    print(json.dumps(cost, indent=1))