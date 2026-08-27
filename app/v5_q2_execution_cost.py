"""V5 Q2 — Contemporaneous execution cost measurement.

Compares fresh live execution cost against the historical V5 cost gate (4.6658 bps).

Process:
  1. Collect live cost samples via CostSampler for a defined window
  2. Summarize with cost_calibrate
  3. Compute contemporaneous gate via v3_cost.cost_model
  4. Compare historical (4.6658 bps) vs contemporaneous
  5. Produce Q2 report with verdict

The report answers:
  - Is the historical cost gate conservative, accurate, or optimistic?
  - Can the V5 signal's gross expectancy (0.07-0.08 bps) survive at contemporaneous cost?
  - What is the minimum gross expectancy needed for taker/maker/hybrid viability?
  - What is the contemporaneous P(fill) and adverse selection cost?
"""

import json
import math
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .config import Config, V5_BASELINE_NO_LIVE_TRADE
from .cost_calibrate import summarize as calibrate_summarize
from .cost_sampler import CostSampler, walk_slippage_bps
from .v3_cost import cost_model, load_cal as _load_cal, DEFAULT_CAL_PATH, \
    SAFETY_MARGIN_BPS, IMPACT_ALLOWANCE_BPS, LATENCY_COST_BPS, \
    NON_FILL_REPRICE_COST_BPS, P_FILL_DEFAULT

DATA = Path("data")
LIVE = DATA / "live"
RESEARCH = DATA / "research"
HIST_RESEARCH = DATA / "hist" / "research"

# Defaults
DEFAULT_MINUTES = 30.0
DEFAULT_CADENCE_S = 1.0
DEFAULT_NOTIONAL_USD = 1000.0
DEFAULT_REPORT_EVERY_MIN = 5.0

# Historical V5 gate components (for reference)
HISTORICAL_GATE_BPS = 4.6658
HISTORICAL_TOTAL_BPS = 4.1658  # effective_taker_roundtrip.p90 + impact + latency
HISTORICAL_SAFETY_MARGIN = 0.5

# Signal expectancy from Tier-A (frozen 500 ms signal, non-contemporaneous cost)
SIGNAL_GROSS_BPS_LOW = 0.0685
SIGNAL_GROSS_BPS_HIGH = 0.0801


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _bps_to_pct(bps):
    return bps / 10000.0


def _contemporaneous_gate(calibration_stats, notional_usd=DEFAULT_NOTIONAL_USD):
    """Compute contemporaneous taker gate from measured calibration stats.

    Mirrors v3_cost.cost_model but reads from the summarized calibration dict
    rather than the JSON file, so it can be called with fresh measurements.
    """
    # Find the closest notional band
    rt_dict = calibration_stats.get("effective_roundtrip_taker", {})
    band = _adjacent_band(rt_dict, notional_usd)
    if band is None:
        # Fallback to a reasonable estimate if no data for this notional
        rt_p90 = 3.5
    else:
        rt_p90 = rt_dict[str(band)].get("taker_rt_p90_bps")
        if rt_p90 is None:
            rt_p90 = rt_dict[str(band)].get("taker_rt_median_bps", 3.5)

    spread_p90 = calibration_stats.get("spread", {}).get("p90_bps", 0.0)

    # Taker gate = p90 round-trip + impact + latency + safety margin
    tak = round(float(rt_p90) + IMPACT_ALLOWANCE_BPS + LATENCY_COST_BPS, 6)
    gate = round(tak + SAFETY_MARGIN_BPS, 6)

    return {
        "notional_usd": float(notional_usd),
        "taker_roundtrip_p90_bps": round(float(rt_p90), 4),
        "spread_p90_bps": round(spread_p90, 4),
        "impact_bps": IMPACT_ALLOWANCE_BPS,
        "latency_bps": LATENCY_COST_BPS,
        "safety_margin_bps": SAFETY_MARGIN_BPS,
        "taker_total_bps": tak,
        "gate_bps": gate,
    }


def _adjacent_band(rt_dict, notional_usd):
    """Find the closest notional band in the calibration."""
    if not rt_dict:
        return None
    bands = sorted(int(k) for k in rt_dict.keys())
    best = bands[0]
    for b in bands:
        if b >= notional_usd:
            best = b
            break
        best = b
    return best


def _maker_gate_from_calibration(calibration_stats):
    """Compute contemporaneous maker gate."""
    maker_fee = calibration_stats.get("maker", {}).get("fee_rt_mean_bps", 2.0)
    # Adverse selection from oos_fill if available; otherwise default
    adverse_sel = 0.50  # conservative default
    # Use the calibration JSON for fill data if present
    cal_path = HIST_RESEARCH / "execution_calibration.json"
    if cal_path.exists():
        try:
            cal = _load_cal(cal_path)
            comp_mak = {}
            from .v3_cost import maker_components
            comp_mak = maker_components(cal)
            adverse_sel = comp_mak.get("adverse_selection_bps", adverse_sel)
            p_fill = comp_mak.get("p_fill", P_FILL_DEFAULT)
        except Exception:
            p_fill = P_FILL_DEFAULT
    else:
        p_fill = P_FILL_DEFAULT

    reprice = NON_FILL_REPRICE_COST_BPS * (1.0 - p_fill)
    total = maker_fee + adverse_sel + reprice + LATENCY_COST_BPS
    gate = round(total + SAFETY_MARGIN_BPS, 6)
    return {
        "maker_fee_rt_bps": round(maker_fee, 4),
        "adverse_selection_bps": round(adverse_sel, 4),
        "p_fill": round(p_fill, 4),
        "non_fill_reprice_bps": NON_FILL_REPRICE_COST_BPS,
        "reprice_component_bps": round(reprice, 4),
        "latency_bps": LATENCY_COST_BPS,
        "safety_margin_bps": SAFETY_MARGIN_BPS,
        "maker_total_bps": round(total, 6),
        "gate_bps": gate,
    }


def collect(minutes=DEFAULT_MINUTES, cadence_s=DEFAULT_CADENCE_S,
            out_dir=LIVE, symbol="btcusdt", log=print):
    """Collect live cost samples for the specified window.

    Returns the path to the written jsonl file.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = Config()
    sampler = CostSampler(cfg=cfg, symbol=symbol, out_dir=out_dir,
                          cadence_s=cadence_s)
    log("[Q2] collecting cost samples for %.1f min ..." % minutes)
    path = sampler.run(minutes=minutes)
    log("[Q2] samples written to %s (n=%d)" % (path, sampler.rows))
    return path


def summarize(sample_path, out_dir=None):
    """Summarize cost samples into calibration stats and report.

    Returns the calibration stats dict and the output directory.
    """
    sample_path = Path(sample_path)
    out_dir = Path(out_dir) if out_dir else sample_path.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    stats = calibrate_summarize(sample_path, out_dir=out_dir)
    return stats, out_dir


def compare(contemporaneous_gate, maker_gate, signal_gross_bps_low=SIGNAL_GROSS_BPS_LOW,
            signal_gross_bps_high=SIGNAL_GROSS_BPS_HIGH):
    """Compare contemporaneous cost with historical gate and signal expectancy.

    Returns a structured comparison dict.
    """
    cont_gate = contemporaneous_gate["gate_bps"]
    cont_total = contemporaneous_gate["taker_total_bps"]
    hist_gate = HISTORICAL_GATE_BPS
    hist_total = HISTORICAL_TOTAL_BPS

    # Difference (positive = contemporary is more expensive)
    gate_diff = round(cont_gate - hist_gate, 4)
    total_diff = round(cont_total - hist_total, 4)

    # Cost ratio: how many times larger is cost than signal?
    ratio_low = round(cont_gate / max(signal_gross_bps_low, 0.001), 1)
    ratio_high = round(cont_gate / max(signal_gross_bps_high, 0.001), 1)

    # Taker net expectancy at low/high signal gross
    taker_net_low = round(signal_gross_bps_low - cont_gate, 4)
    taker_net_high = round(signal_gross_bps_high - cont_gate, 4)

    # Maker net (simplified: no fill prob / adverse selection model here)
    maker_net_low = round(signal_gross_bps_low - maker_gate["gate_bps"], 4)
    maker_net_high = round(signal_gross_bps_high - maker_gate["gate_bps"], 4)

    # Verdict on cost gate itself
    if gate_diff > 0.5:
        gate_verdict = "CONTEMPORANEOUS_COST_HIGHER"
    elif gate_diff < -0.5:
        gate_verdict = "CONTEMPORANEOUS_COST_LOWER"
    else:
        gate_verdict = "CONTEMPORANEOUS_COST_SIMILAR"

    # Verdict on signal viability
    if taker_net_low > 0 and taker_net_high > 0:
        viability = "PASS — taker viable"
    elif maker_net_low > 0 or maker_net_high > 0:
        viability = "CONDITIONAL — maker may be viable"
    else:
        viability = "FAIL — net negative at all signal levels"

    return {
        "historical_gate_bps": hist_gate,
        "contemporaneous_gate_bps": cont_gate,
        "gate_difference_bps": gate_diff,
        "gate_verdict": gate_verdict,
        "historical_total_bps": hist_total,
        "contemporaneous_total_bps": cont_total,
        "total_difference_bps": total_diff,
        "cost_to_signal_ratio_low": ratio_low,
        "cost_to_signal_ratio_high": ratio_high,
        "taker_net_at_low_signal_bps": taker_net_low,
        "taker_net_at_high_signal_bps": taker_net_high,
        "maker_net_at_low_signal_bps": maker_net_low,
        "maker_net_at_high_signal_bps": maker_net_high,
        "signal_viability": viability,
    }


def build_report(sample_path, stats, out_dir):
    """Build the Q2 report (JSON + MD)."""
    cont_gate = _contemporaneous_gate(stats)
    maker_gate = _maker_gate_from_calibration(stats)
    comparison = compare(cont_gate, maker_gate)

    report = {
        "generated_at": _now_iso(),
        "protocol": (
            "Q2: contemporaneous execution cost measurement. "
            "Frozen V5 model is read-only; no re-fitting, no threshold changes."
        ),
        "governance": {
            "ORDERFLOW_BASELINE_V5_NO_LIVE_TRADE": V5_BASELINE_NO_LIVE_TRADE,
            "note": "Live trading is blocked until Q2 cost is measured and compared.",
        },
        "historical_cost": {
            "gate_bps": HISTORICAL_GATE_BPS,
            "total_bps": HISTORICAL_TOTAL_BPS,
            "safety_margin_bps": HISTORICAL_SAFETY_MARGIN,
            "components": {
                "taker_roundtrip_p90_bps": 4.0158,
                "impact_bps": 0.10,
                "latency_bps": 0.05,
                "safety_margin_bps": 0.50,
            },
            "note": (
                "Historical non-contemporaneous taker round-trip cost. "
                "Derived from execution_calibration.json collected BEFORE the V5 OOS window."
            ),
        },
        "contemporaneous_cost": cont_gate,
        "maker_cost": maker_gate,
        "signal_expectancy_bps": {
            "low": SIGNAL_GROSS_BPS_LOW,
            "high": SIGNAL_GROSS_BPS_HIGH,
            "source": "Tier-A: frozen 500 ms signal evaluated at 2s/5s/10s/30s horizons",
        },
        "comparison": comparison,
        "cost_calibration_summary": {
            "n_samples": stats.get("n_samples"),
            "window_seconds": stats.get("window_seconds"),
            "spread_p90_bps": stats.get("spread", {}).get("p90_bps"),
            "taker_rt_p90_bps_1000usd": stats.get("effective_roundtrip_taker", {})
                                         .get("1000", {}).get("taker_rt_p90_bps"),
            "maker_fee_rt_bps": stats.get("maker", {}).get("fee_rt_mean_bps"),
        },
        "sample_path": str(sample_path),
    }

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "v5_q2_report.json").write_text(json.dumps(report, indent=2))

    md = _render_md(report)
    (out_dir / "v5_q2_report.md").write_text(md)

    return report


def _render_md(report):
    c = report["contemporaneous_cost"]
    m = report["maker_cost"]
    comp = report["comparison"]
    lines = [
        "# V5 Q2 — Contemporaneous execution cost measurement",
        "",
        "- **Generated**: %s" % report["generated_at"],
        "- **Protocol**: %s" % report["protocol"],
        "",
        "## Governance",
        "",
        "- **ORDERFLOW_BASELINE_V5 NO LIVE TRADING**: %s" % report["governance"]["ORDERFLOW_BASELINE_V5_NO_LIVE_TRADE"],
        "- %s" % report["governance"]["note"],
        "",
        "## Historical cost (non-contemporaneous reference)",
        "",
        "| component | bps |",
        "|---|---|",
        "| taker round-trip p90 | %.4f |" % report["historical_cost"]["components"]["taker_roundtrip_p90_bps"],
        "| impact | %.2f |" % report["historical_cost"]["components"]["impact_bps"],
        "| latency | %.2f |" % report["historical_cost"]["components"]["latency_bps"],
        "| safety margin | %.2f |" % report["historical_cost"]["components"]["safety_margin_bps"],
        "| **gate** | **%.4f** |" % report["historical_cost"]["gate_bps"],
        "",
        "## Contemporaneous cost (measured live)",
        "",
        "| component | bps |",
        "|---|---|",
        "| taker round-trip p90 | %.4f |" % c["taker_roundtrip_p90_bps"],
        "| spread p90 | %.4f |" % c["spread_p90_bps"],
        "| impact | %.2f |" % c["impact_bps"],
        "| latency | %.2f |" % c["latency_bps"],
        "| safety margin | %.2f |" % c["safety_margin_bps"],
        "| taker total | %.4f |" % c["taker_total_bps"],
        "| **gate** | **%.4f** |" % c["gate_bps"],
        "",
        "## Maker cost (contemporaneous)",
        "",
        "| component | bps |",
        "|---|---|",
        "| maker fee round-trip | %.4f |" % m["maker_fee_rt_bps"],
        "| adverse selection | %.4f |" % m["adverse_selection_bps"],
        "| P(fill) | %.2f |" % m["p_fill"],
        "| non-fill reprice | %.4f |" % m["non_fill_reprice_bps"],
        "| reprice component | %.4f |" % m["reprice_component_bps"],
        "| latency | %.2f |" % m["latency_bps"],
        "| safety margin | %.2f |" % m["safety_margin_bps"],
        "| maker total | %.4f |" % m["maker_total_bps"],
        "| **gate** | **%.4f** |" % m["gate_bps"],
        "",
        "## Comparison: historical vs contemporaneous",
        "",
        "| metric | historical | contemporaneous | diff |",
        "|---|---|---|---|",
        "| gate (bps) | %.4f | %.4f | %+.4f |" % (
            report["historical_cost"]["gate_bps"], c["gate_bps"], comp["gate_difference_bps"]),
        "| total (bps) | %.4f | %.4f | %+.4f |" % (
            report["historical_cost"]["total_bps"], c["taker_total_bps"], comp["total_difference_bps"]),
        "",
        "**Gate verdict**: %s" % comp["gate_verdict"],
        "",
        "## Signal viability at contemporaneous cost",
        "",
        "| signal gross (bps) | taker net (bps) | maker net (bps) |",
        "|---|---|---|",
        "| %.4f | %.4f | %.4f |" % (
            report["signal_expectancy_bps"]["low"],
            comp["taker_net_at_low_signal_bps"],
            comp["maker_net_at_low_signal_bps"]),
        "| %.4f | %.4f | %.4f |" % (
            report["signal_expectancy_bps"]["high"],
            comp["taker_net_at_high_signal_bps"],
            comp["maker_net_at_high_signal_bps"]),
        "",
        "**Viability verdict**: %s" % comp["signal_viability"],
        "",
        "## Cost calibration sample summary",
        "",
        "- Samples: %d" % report["cost_calibration_summary"]["n_samples"],
        "- Window: %.1f s" % report["cost_calibration_summary"]["window_seconds"],
        "- Spread p90: %.4f bps" % report["cost_calibration_summary"]["spread_p90_bps"],
        "- Taker RT p90 (1000 USD): %s" % report["cost_calibration_summary"]["taker_rt_p90_bps_1000usd"],
        "- Maker fee RT: %.4f bps" % report["cost_calibration_summary"]["maker_fee_rt_bps"],
        "",
        "## Next step",
        "",
        "- If contemporaneous gate is similar or lower than historical: Q2 confirms "
        "the historical gate was not optimistic; proceed to Q3 (contemporaneous "
        "signal expectancy measurement).",
        "- If contemporaneous gate is materially higher: historical gate was "
        "conservative; update the measured gate and re-evaluate signal viability "
        "before any further research steps.",
        "",
    ]
    return "\n".join(lines) + "\n"


def run(minutes=DEFAULT_MINUTES, cadence_s=DEFAULT_CADENCE_S,
        notional_usd=DEFAULT_NOTIONAL_USD, symbol="btcusdt",
        out_dir=RESEARCH / "v5" / "Q2",
        report_every_min=DEFAULT_REPORT_EVERY_MIN,
        log=print):
    """Run the full Q2 pipeline: collect -> summarize -> report."""
    log("[Q2] ORDERFLOW_BASELINE_V5 contemporaneous execution cost measurement")
    log("[Q2] governance: NO LIVE TRADING for baseline")
    log("[Q2] collecting %.1f min of live cost samples ..." % minutes)

    # Step 1: collect
    sample_path = collect(minutes=minutes, cadence_s=cadence_s,
                          out_dir=LIVE, symbol=symbol, log=log)

    # Step 2: summarize
    stats, calib_out = summarize(sample_path, out_dir=LIVE)

    # Step 3: build report
    report = build_report(sample_path, stats, out_dir)

    log("[Q2] report written to %s" % (out_dir / "v5_q2_report.json"))
    log("[Q2] markdown written to %s" % (out_dir / "v5_q2_report.md"))
    log("[Q2] gate verdict: %s" % report["comparison"]["gate_verdict"])
    log("[Q2] signal viability: %s" % report["comparison"]["signal_viability"])

    return report


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="V5 Q2: contemporaneous execution cost measurement")
    ap.add_argument("--minutes", type=float, default=DEFAULT_MINUTES,
                    help="sampling window in minutes")
    ap.add_argument("--cadence", type=float, default=DEFAULT_CADENCE_S,
                    help="seconds between samples")
    ap.add_argument("--notional", type=float, default=DEFAULT_NOTIONAL_USD,
                    help="notional USD for gate computation")
    ap.add_argument("--symbol", type=str, default="btcusdt")
    ap.add_argument("--out", type=str, default=str(RESEARCH / "v5" / "Q2"),
                    help="output directory for Q2 report")
    ap.add_argument("--report-every", type=float, default=DEFAULT_REPORT_EVERY_MIN,
                    help="regenerate calibration report every N minutes")
    args = ap.parse_args(argv)

    if V5_BASELINE_NO_LIVE_TRADE:
        print("GOVERNANCE: ORDERFLOW_BASELINE_V5 NO LIVE TRADING")
        print("Q2 cost measurement runs in paper/observation mode only.")
        print("No orders will be placed.\n")

    r = run(minutes=args.minutes, cadence_s=args.cadence,
            notional_usd=args.notional, symbol=args.symbol,
            out_dir=Path(args.out),
            report_every_min=args.report_every)
    print(json.dumps({
        "verdict": r["comparison"]["signal_viability"],
        "gate_verdict": r["comparison"]["gate_verdict"],
        "contemporaneous_gate_bps": r["contemporaneous_cost"]["gate_bps"],
        "historical_gate_bps": r["historical_cost"]["gate_bps"],
        "taker_net_at_low_signal_bps": r["comparison"]["taker_net_at_low_signal_bps"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
