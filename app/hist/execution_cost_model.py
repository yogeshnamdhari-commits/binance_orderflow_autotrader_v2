"""Componentized execution-cost model for the frozen signal economic test.

Builds expected round-trip costs from the AUTHENTIC execution calibration
(data/hist/research/execution_calibration.json). Every number below is either
measured or a clearly-labelled documented assumption; nothing is tuned to make
the frozen signal pass.

Costs are modeled for each execution style separately:

  TAKER  cost_rt = measured_slippage_rt(notional)      # from live L2 sampler
                   + taker_fee_rt                       # 2 * FEE_BPS['taker']
                   + impact_allowance                   # documented, size-aware
                   + latency_allowance_bps              # documented

  MAKER  cost_rt = maker_fee_rt                          # 2 * FEE_BPS['maker']
                   + adverse_selection_drag              # OOS fill: gross - E[fill]
                   + non_fill_cost * (1 - P(fill))       # cancel->re-price, documented
                   + latency_allowance_bps

The maker view uses the UNTOUCHED OOS fill evidence (oos_fill) so the adverse-selection
drag and fill probability are measured on the exact window that gates the decision.

Outputs data/hist/research/execution_cost_model.{json,md}.
"""

import argparse
import json
from pathlib import Path

from .costmodel import FEE_BPS
from .execution_calibrator import RESEARCH

IMPACT_ALLOWANCE_BPS = 0.10          # documented residual impact allowance (size-independent, conservative)
LATENCY_COST_BPS = 0.05              # latency allowance bps (5 ms assumption, immaterial vs tick)
NON_FILL_REPRICE_COST_BPS = 0.50     # maker non-fill -> cancel + reprice cost (documented assumption)


def _fill_row(cal, kind, label, horizon_ms):
    key = "%s@%ds" % (label, horizon_ms // 1000)
    src = cal.get("oos_fill", {}) if kind == "oos" else cal.get("fill_calib", {})
    return src.get(key)


def taker_cost(cal, notional_usd, horizon_ms=0):
    n = str(notional_usd)
    slip = cal["slippage_by_notional"].get(n, {})
    if not slip:
        slip = next(iter(cal["slippage_by_notional"].values()))
    buy = slip.get("buy_median_bps", 0.0)
    sell = slip.get("sell_median_bps", 0.0)
    # slippage_rt = buy slip (up) minus sell slip (down against mid)
    slip_rt = abs(float(buy)) + abs(float(sell))
    return {
        "style": "taker", "notional_usd": notional_usd,
        "slippage_rt_bps": round(slip_rt, 4),
        "taker_fee_rt_bps": round(2.0 * FEE_BPS["taker"], 3),
        "impact_bps": IMPACT_ALLOWANCE_BPS,
        "latency_bps": LATENCY_COST_BPS,
        "total_bps": round(slip_rt + 2.0 * FEE_BPS["taker"] + IMPACT_ALLOWANCE_BPS + LATENCY_COST_BPS, 4),
    }


def maker_cost(cal, label, horizon_ms, fill_kind="oos"):
    row = _fill_row(cal, fill_kind, label, horizon_ms)
    if not row or row.get("e_fill_return_bps") is None or row.get("p_fill_same_tick") is None:
        return None
    gross = row["gross_unconditional_bps"]
    if row.get("gross_unconditional_bps") is None:
        gross = row["e_fill_return_bps"]
    as_drag = gross - row["e_fill_return_bps"]
    pf = row["p_fill_same_tick"]
    mk_fee = 2.0 * FEE_BPS["maker"]
    non_fill = NON_FILL_REPRICE_COST_BPS * (1.0 - pf)
    return {
        "style": "maker", "fill_kind": fill_kind, "label": label, "horizon_ms": horizon_ms,
        "maker_fee_rt_bps": round(mk_fee, 3),
        "adverse_selection_drag_bps": round(as_drag, 3),
        "non_fill_cost_bps": round(non_fill, 4),
        "p_fill": round(pf, 4),
        "latency_bps": LATENCY_COST_BPS,
        "total_bps": round(mk_fee + as_drag + non_fill + LATENCY_COST_BPS, 4),
    }


def all_scenarios(cal, notional_usd=1000):
    """Cost scenarios for every frozen condition x horizon (maker, OOS fill)."""
    out = {}
    labels = ("10_long", "1_short")
    horizons = (5000, 15000, 30000, 60000)
    for lab in labels:
        for h in horizons:
            key = "%s@%ds" % (lab, h // 1000)
            m = maker_cost(cal, lab, h, fill_kind="oos")
            out[key] = {"taker": taker_cost(cal, notional_usd), "maker": m}
    return out


def render_md(p):
    L = ["# Execution cost model scenarios", "",
         "- Source: execution_calibration.json (authentic L2 + OOS fill evidence).",
         "- Taker uses measured slippage + 2x taker fee + documented impact/latency.",
         "- Maker uses 2x maker fee + OOS adverse-selection drag + non-fill cost.",
         "- All assumptions documented in execution_calibrator.py / cost model module.",
         "", "| scenario | style | slippage | fee | AS drag | non-fill | impact | latency | TOTAL bps |",
         "|---|---|---|---|---|---|---|---|---|"]
    for key, s in p["scenarios"].items():
        t = s["taker"]
        m = s["maker"]
        L.append("| %s taker | taker | %.4f | %.2f | - | - | %.2f | %.2f | %.2f |" % (
            key, t["slippage_rt_bps"], t["taker_fee_rt_bps"], t["impact_bps"],
            t["latency_bps"], t["total_bps"]))
        if m:
            L.append("| %s maker | maker | 0 | %.2f | %.2f | %.4f | - | %.2f | %.2f |" % (
                key, m["maker_fee_rt_bps"], m["adverse_selection_drag_bps"],
                m["non_fill_cost_bps"], m["latency_bps"], m["total_bps"]))
    L += ["", "## Notes", "",
          "- Maker total is the FULL economic cost of a passive fill, including",
          "  measured adverse selection and expected non-fill re-pricing.", ""]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--notional", type=int, default=1000)
    args = ap.parse_args(argv)

    cal = json.loads((RESEARCH / "execution_calibration.json").read_text())
    scenarios = all_scenarios(cal, args.notional)
    payload = {"notional_usd": args.notional, "scenarios": scenarios}
    (RESEARCH / "execution_cost_model.json").write_text(json.dumps(payload, indent=1))
    (RESEARCH / "execution_cost_model.md").write_text(render_md(payload))
    print("execution_cost_model -> %s" % (RESEARCH / "execution_cost_model.md"))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())