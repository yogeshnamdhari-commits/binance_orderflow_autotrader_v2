"""Economic gate for the frozen signal against authentic execution costs.

Rules (from datasource-for-real, next_PROTOCOL.md):
  TRADE only if  ExpectedNetEdge > SafetyMargin > 0
  ExpectedGrossEdge = OOS gross info edge (untouched window), per condition x horizon.
  ExpectedExecutionCost = maker or taker cost from execution_cost_model.py.
  NetEdge  = ExpectedGrossEdge - ExpectedExecutionCost
  SafetyMargin = z * SE(day-level net edge) computed from the OOS per-day
                 distribution of net edge. This is an ESTIMATE FROM THE OOS
                 DISTRIBUTION OF EXECUTION COSTS + edge variance (not an
                 arbitrary constant). z defaults to 1 (documented).

Long and short are evaluated INDEPENDENTLY. Maker and taker are separate.
The gate NEVER changes the signal; it can only fail it.

Outputs data/hist/research/economic_gate.{json,md}.
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np

from .execution_calibrator import RESEARCH

Z_SAFETY = 1.0   # safety-margin z-score (default, documented)
MIN_TRADES = 1000


def _load():
    cal = json.loads((RESEARCH / "execution_calibration.json").read_text())
    cm = json.loads((RESEARCH / "execution_cost_model.json").read_text())
    oos = json.loads((RESEARCH / "oos_oos.json").read_text())
    return cal, cm, oos


def _row(oos, label, horizon_ms):
    for r in oos["rows"]:
        if r["label"] == label and r["horizon_ms"] == horizon_ms:
            return r
    return None


def _cost_tail_buffer(cal):
    """Documented safety buffer from the OOS distribution of execution costs.

    Uses the measured cost tail: (p90 - median) of spread plus of buy/sell
    slippage, summed as a round-trip tail. This is the dispersion of the
    RAW execution cost that a strategy would face, estimated from authentic
    L2 sampling -- exactly the safety margin source the protocol requires.
    """
    sp = cal["spread"]
    spread_tail = sp["p90_bps"] - sp["median_bps"]
    tail = 0.0
    for v in cal["slippage_by_notional"].values():
        tail += (v["buy_p90_bps"] - v["buy_median_bps"]) + (v["sell_p90_bps"] - v["sell_median_bps"])
    # spread crossed once per side; slippage tail already per side in the loop
    return round(spread_tail + tail, 4)


def _day_net(row, cost_bps):
    dm = np.asarray(row["per_day_mean_bps"], dtype=np.float64)
    return dm - cost_bps


def evaluate(cal, cm, oos, labels, horizons, z=Z_SAFETY, min_trades=MIN_TRADES):
    decisions = []
    cost_tail = _cost_tail_buffer(cal)
    for label in labels:
        for h in horizons:
            row = _row(oos, label, h)
            if not row:
                continue
            gross = row["gross_mean_bps"]
            n = row["n"]
            if n < min_trades:
                continue
            for style in ("maker", "taker"):
                scen = cm["scenarios"].get("%s@%ds" % (label, h // 1000), {})
                cost = (scen.get(style) or {}).get("total_bps")
                if cost is None:
                    continue
                net_mean = gross - cost
                net_day = _day_net(row, cost)
                se = float(np.std(net_day, ddof=1)) / math.sqrt(len(net_day)) if len(net_day) > 1 else 0.0
                margin = z * se + cost_tail
                clear = net_mean - margin > 0.0
                decisions.append({
                    "label": label,
                    "direction": "long" if label.endswith("long") else "short",
                    "horizon_ms": h,
                    "style": style,
                    "n": n,
                    "gross_bps": round(gross, 3),
                    "cost_bps": round(cost, 3),
                    "net_bps": round(net_mean, 3),
                    "safety_margin_bps": round(margin, 3),
                    "safety_edge_se_bps": round(z * se, 4),
                    "safety_cost_tail_bps": round(cost_tail, 4),
                    "net_minus_margin_bps": round(net_mean - margin, 3),
                    "net_day_mean_bps": round(float(np.mean(net_day)), 3),
                    "net_day_se_bps": round(se, 3),
                    "decision": "TRADE" if clear else "NO_TRADE",
                    "reason": "net > margin" if clear else (
                        "gross %.2f <= cost %.2f" % (gross, cost) if net_mean <= 0 else "net within safety margin"),
                })
    return decisions


def render_md(p):
    L = ["# Economic gate — frozen signal vs authentic execution costs", "",
         "- Source: execution_calibration.json, execution_cost_model.json, oos_oos.json.",
         "- Long/short INDEPENDENT; maker/taker separate; signal unchanged.",
         "- Safety margin = z x SE(day-level net edge) + measured cost tail",
         "  (p90-median of spread+slippage from authentic L2 sampling), z=%.1f." % p["z"],
         "- TRADE iff net - margin > 0 (resolved above OOS noise AND cost tail).", "",
         "| condition | dir | h | style | n | gross | cost | net | margin | net-margin | decision |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in p["decisions"]:
        L.append("| %s | %s | %ds | %s | %d | %+.2f | %.2f | %+.2f | %.2f | %+.2f | %s |" % (
            d["label"], d["direction"], d["horizon_ms"] // 1000, d["style"],
            d["n"], d["gross_bps"], d["cost_bps"], d["net_bps"], d["safety_margin_bps"],
            d["net_minus_margin_bps"], d["decision"]))
    trades = [d for d in p["decisions"] if d["decision"] == "TRADE"]
    L += ["", "## Verdict", "",
          "- %d of %d candidate (condition x horizon x style) evaluate to TRADE."
          % (len(trades), len(p["decisions"]))]
    if trades:
        L.append("- Candidate trades exist; but see next_PROTOCOL gates 4-6 before any paper/live.")
    else:
        L.append("- **NO candidate clears the economic gate.** Frozen signal does not")
        L.append("  monetize under authentic execution evidence -> STAGE 3 outcome: FAIL.")
    L += ["", "- A positive result would NOT be sufficient: it still needs a new untouched",
          "  OOS (gate 4) and independent replication (gate 5) before any deployment."]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--z", type=float, default=Z_SAFETY)
    ap.add_argument("--min-trades", type=int, default=MIN_TRADES)
    args = ap.parse_args(argv)

    cal, cm, oos = _load()
    decisions = evaluate(cal, cm, oos, labels=("10_long", "1_short"),
                         horizons=(5000, 15000, 30000, 60000),
                         z=args.z, min_trades=args.min_trades)
    payload = {"z": args.z, "min_trades": args.min_trades, "decisions": decisions}
    (RESEARCH / "economic_gate.json").write_text(json.dumps(payload, indent=1))
    (RESEARCH / "economic_gate.md").write_text(render_md(payload))
    print("economic_gate -> %s" % (RESEARCH / "economic_gate.md"))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())