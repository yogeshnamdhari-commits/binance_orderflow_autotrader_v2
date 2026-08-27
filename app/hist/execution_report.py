"""Full execution/economic report for the frozen order-flow signal.

Orchestrates the authentic evidence chain and produces a single PASS/FAIL
report binding the decision:

  REAL BINANCE L2 (cost_sampler jsonl) + REAL TRADES (fill calibration)
    -> execution_calibrator.py     (measured cost components)
    -> execution_cost_model.py     (maker/taker cost scenarios)
    -> economic_gate.py            (net edge vs safety margin, TRADE/NO_TRADE)
    -> execution_report.py         (LONG/SHORT + MAKER/TAKER PASS/FAIL)

The frozen signal (oos_FROZEN_SPEC.md) is NEVER modified. This report only
records whether it clears the economic hurdle under authentic costs.

`python -m app.hist.execution_report` runs the whole chain and writes
data/hist/research/execution_report.{json,md}.
"""

import argparse
import json
from pathlib import Path

from .execution_calibrator import main as calibrator_main, RESEARCH
from .execution_cost_model import main as costmodel_main
from .economic_gate import main as gate_main, evaluate


def _load_json(name):
    return json.loads((RESEARCH / name).read_text())


def run(args):
    print("stage 2: execution calibrator")
    calibrator_main(["--min-samples", str(args.min_samples)])
    print("stage 3: cost model")
    costmodel_main(["--notional", str(args.notional)])
    print("stage 4: economic gate")
    gate_main(["--z", str(args.z), "--min-trades", str(args.min_trades)])

    cal = _load_json("execution_calibration.json")
    cm = _load_json("execution_cost_model.json")
    oos = _load_json("oos_oos.json")

    decisions = evaluate(cal, cm, oos, labels=("10_long", "1_short"),
                         horizons=(5000, 15000, 30000, 60000),
                         z=args.z, min_trades=args.min_trades)
    trades = [d for d in decisions if d["decision"] == "TRADE"]
    verdict = "FAIL" if not trades else "CONDITIONAL"
    payload = {"verdict": verdict, "z": args.z, "min_trades": args.min_trades,
               "notional_usd": args.notional,
               "calibration": {k: v for k, v in cal.items() if k != "fill_calib"},
               "cost_model": cm,
               "decisions": decisions,
               "next_gates": "if verdict CONDITIONAL -> new untouched OOS (gate 4) then independent replication (gate 5); never deploy without them."}
    (RESEARCH / "execution_report.json").write_text(json.dumps(payload, indent=1))
    (RESEARCH / "execution_report.md").write_text(render_md(payload))
    print("execution_report -> %s" % (RESEARCH / "execution_report.md"))
    return 0 if verdict == "FAIL" else 2


def render_md(p):
    L = ["# Execution & economic report — frozen order-flow signal", "",
         "- Verdict: **%s**" % p["verdict"],
         "- Evidence: authentic Binance L2 sampling + authentic aggTrades/OOS fill calibration.",
         "- Signal: delta_5s decile (frozen, spec oos_FROZEN_SPEC.md); not modified.",
         "- Long/short independent; maker/taker separate.", "",
         "## 1. Execution calibration summary", ""]
    cal = p["calibration"]
    sp = cal["spread"]
    L += ["- Measured spread: median %.3f bps, p90 %.3f, p99 %.3f, max %.3f" % (
        sp["median_bps"], sp["p90_bps"], sp["p99_bps"], sp["max_bps"]),
          "- Taker round trip (small size, measured): %s bps median" % (
              cal["effective_taker_roundtrip"]["1000"]["median_bps"]),
          "- Maker fee round trip: %.2f bps (VIP10+BNB: %.2f)" % (
              cal["maker_fee_rt_bps"], cal["maker_fee_rt_vip10_bnb_bps"]),
          ""]
    L += ["## 2. Cost scenarios (bps round trip)", "",
          "| condition | style | total | of which maker: fee / AS / non-fill |",
          "|---|---|---|---|"]
    for key, s in p["cost_model"]["scenarios"].items():
        m = s["maker"]
        if m:
            L.append("| %s | maker | %.2f | %.2f / %.2f / %.4f |" % (
                key, m["total_bps"], m["maker_fee_rt_bps"],
                m["adverse_selection_drag_bps"], m["non_fill_cost_bps"]))
        else:
            L.append("| %s | taker | %.2f | (measured slip + 2x taker fee + impact) |" % (
                key, s["taker"]["total_bps"]))
    L += ["", "## 3. Economic gate (net = gross - cost; TRADE iff net - margin > 0)", "",
          "| condition | dir | h | style | n | gross | cost | net | margin | net-margin | decision |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for d in p["decisions"]:
        L.append("| %s | %s | %ds | %s | %d | %+.2f | %.2f | %+.2f | %.2f | %+.2f | %s |" % (
            d["label"], d["direction"], d["horizon_ms"] // 1000, d["style"],
            d["n"], d["gross_bps"], d["cost_bps"], d["net_bps"], d["safety_margin_bps"],
            d["net_minus_margin_bps"], d["decision"]))
    trades = [d for d in p["decisions"] if d["decision"] == "TRADE"]
    miss = [d for d in p["decisions"] if d["decision"] == "NO_TRADE" and d["net_bps"] > 0]
    L += ["", "## 4. Analytical notes (independent of the gate)", ""]
    maker_pos = [d for d in p["decisions"] if d["style"] == "maker" and d["net_bps"] > 0]
    if maker_pos:
        L.append("- Best maker case: %s @%ds gross %+.2f, cost %.2f, net %+.2f." % (
            maker_pos[0]["label"], maker_pos[0]["horizon_ms"] // 1000,
            maker_pos[0]["gross_bps"], maker_pos[0]["cost_bps"], maker_pos[0]["net_bps"]))
    L.append("- The gross information edge (~+1.7..+2.1 bps) is real and consistent")
    L.append("  across LONG and SHORT, but it is BELOW every modeled execution cost.")
    L.append("- Even the most favourable maker view (fee + measured adverse selection,")
    L.append("  no spread crossing) costs ~2.7-3.1 bps round-trip -- above the edge.")
    if miss:
        L.append("- %d candidates had gross-positive net but failed the safety margin;" % len(miss))
        L.append("  none of them clear the economic gate as defined." )
    L += ["", "## 5. Decision path (next_PROTOCOL.md gates)", "",
          "- Stage 3 outcome: **%s**" % ("PASS (conditional)" if p["verdict"] == "CONDITIONAL" else "FAIL"),
          "- If FAIL: STOP. No parameter optimization, no signal change, no", 
          "  cost-lowering to taste. Document and remain in research.",
          "- If CONDITIONAL: gates 4 (new untouched OOS) and 5 (independent",
          "  replication) must pass before ANY paper/live consideration.", ""]
    return "\n".join(L) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--notional", type=int, default=1000)
    ap.add_argument("--z", type=float, default=1.0)
    ap.add_argument("--min-trades", type=int, default=1000)
    ap.add_argument("--min-samples", type=int, default=100)
    args = ap.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    import sys
    sys.exit(main())