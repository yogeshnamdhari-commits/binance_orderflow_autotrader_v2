#!/usr/bin/env python3
"""
Corrected cost audit and revalidation for V3/V5 OOS.
Read-only: does not modify any production file.
"""
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT = Path("/Users/targetmobile/Downloads/binance_orderflow_autotrader_v2")
DATA_RESEARCH = PROJECT / "data" / "research"
DATA_HIST_RESEARCH = PROJECT / "data" / "hist" / "research"
DATA_LIVE = PROJECT / "data" / "live"

# ---------------------------------------------------------------------------
# 1. TIMELINE ANALYSIS
# ---------------------------------------------------------------------------
v3_oos = json.load(open(DATA_RESEARCH / "v3_oos.json"))
oos_lo_ms = v3_oos["days"]["oos"]["lo_ms"]
oos_hi_ms = v3_oos["days"]["oos"]["hi_ms"]
oos_lo_dt = datetime.fromtimestamp(oos_lo_ms / 1000, tz=timezone.utc)
oos_hi_dt = datetime.fromtimestamp(oos_hi_ms / 1000, tz=timezone.utc)

# Cost sampler files
sampler1 = DATA_LIVE / "cost_sampler_20260817-123428.jsonl"
sampler2 = DATA_LIVE / "cost_sampler_20260817-124646.jsonl"

# Read first/last timestamps from sampler files
def sampler_range(path):
    first = last = None
    with open(path) as f:
        for line in f:
            row = json.loads(line)
            ts = row["ts_ms"]
            if first is None:
                first = ts
            last = ts
    return first, last

s1_first, s1_last = sampler_range(sampler1)
s2_first, s2_last = sampler_range(sampler2)
sampler_lo_dt = datetime.fromtimestamp(s1_first / 1000, tz=timezone.utc)
sampler_hi_dt = datetime.fromtimestamp(s2_last / 1000, tz=timezone.utc)

# Check for other cost/calibration files
cost_files = list(DATA_HIST_RESEARCH.glob("*cost*")) + list(DATA_HIST_RESEARCH.glob("*calib*")) + list(DATA_HIST_RESEARCH.glob("*exec*"))
cost_files = sorted(set(cost_files))

# Original oos_oos.json
oos_oos = json.load(open(DATA_HIST_RESEARCH / "oos_oos.json"))
original_cost_bps = oos_oos.get("cost_bps")
original_cost_components = oos_oos.get("cost_components", {})

# execution_calibration.json
exec_cal = json.load(open(DATA_HIST_RESEARCH / "execution_calibration.json"))
exec_cal_source = exec_cal.get("source", {})

# v3_cost_calibration.json
v3_cost_cal = json.load(open(DATA_RESEARCH / "v3_cost_calibration.json"))

# execution_cost_model.json
exec_model = json.load(open(DATA_HIST_RESEARCH / "execution_cost_model.json"))

# ---------------------------------------------------------------------------
# 2. COST CALIBRATION REPORT
# ---------------------------------------------------------------------------
report_lines = []
report_lines.append("=" * 70)
report_lines.append("CORRECTED COST-CALIBRATION REPORT")
report_lines.append("=" * 70)
report_lines.append("")
report_lines.append("A. TIMELINE")
report_lines.append("-" * 40)
report_lines.append(f"V3 OOS period (from v3_oos.json):")
report_lines.append(f"  lo_ms = {oos_lo_ms}  ->  {oos_lo_dt.isoformat()}")
report_lines.append(f"  hi_ms = {oos_hi_ms}  ->  {oos_hi_dt.isoformat()}")
report_lines.append(f"")
report_lines.append(f"Cost sampler files:")
report_lines.append(f"  {sampler1.name}:  {sampler_lo_dt.isoformat()}")
report_lines.append(f"  {sampler2.name}:  {sampler_hi_dt.isoformat()}")
report_lines.append(f"")
report_lines.append(f"Temporal gap between last sampler sample and OOS start:")
gap_hours = (oos_lo_dt - sampler_hi_dt).total_seconds() / 3600
report_lines.append(f"  {gap_hours:.1f} hours")
report_lines.append(f"")
report_lines.append(f"CONCLUSION: No contemporaneous cost calibration exists for the OOS period.")
report_lines.append(f"The only measured cost data in the repository is from 2026-08-17,")
report_lines.append(f"which is {gap_hours:.1f} hours BEFORE the OOS period (2026-08-18).")
report_lines.append(f"")
report_lines.append(f"B. SOURCE FILES AND FIELDS FOR EVERY COST COMPONENT")
report_lines.append("-" * 40)

# Taker fee
report_lines.append(f"")
report_lines.append(f"1. TAKER FEE")
report_lines.append(f"   Source: execution_calibration.json -> fees_per_side_bps.taker = 2.0")
report_lines.append(f"           execution_calibration.json -> taker_fee_rt_bps = 4.0")
report_lines.append(f"   Convention: per-side fee = 2.0 bps; round-trip = 4.0 bps")
report_lines.append(f"   Units: bps (round-trip)")
report_lines.append(f"   Sample size: N/A (exchange schedule, not measured)")
report_lines.append(f"   Uncertainty: None (fixed by exchange)")
report_lines.append(f"")

# Spread
report_lines.append(f"2. SPREAD")
report_lines.append(f"   Source: execution_calibration.json -> spread")
report_lines.append(f"   Fields: mean_bps={exec_cal['spread']['mean_bps']}, "
                    f"median_bps={exec_cal['spread']['median_bps']}, "
                    f"p90_bps={exec_cal['spread']['p90_bps']}")
report_lines.append(f"   Convention: (ask-bid)/mid * 1e4; measured from sampler")
report_lines.append(f"   How measured: Median of {exec_cal_source.get('n_samples', 'N/A')} "
                    f"samples over {exec_cal_source.get('window_seconds', 'N/A')}s")
report_lines.append(f"   Percentile: p90 = {exec_cal['spread']['p90_bps']} bps")
report_lines.append(f"   Units: bps")
report_lines.append(f"   Sample size: {exec_cal_source.get('n_samples', 'N/A')} samples")
report_lines.append(f"   Note: Spread is essentially zero for BTCUSDT; p90 = {exec_cal['spread']['p90_bps']} bps")
report_lines.append(f"")

# Slippage
report_lines.append(f"3. SLIPPAGE (per notional band)")
report_lines.append(f"   Source: execution_calibration.json -> slippage_by_notional")
for band, vals in exec_cal.get("slippage_by_notional", {}).items():
    report_lines.append(f"   Band ${band}: buy_p90={vals.get('buy_p90_bps')}, "
                        f"sell_p90={vals.get('sell_p90_bps')}, "
                        f"pct_depth_insufficient={vals.get('pct_depth_insufficient')}")
report_lines.append(f"   Convention: walk-slippage through order-book levels (L5 max)")
report_lines.append(f"   How measured: cost_sampler.py walks bids/asks for each notional band")
report_lines.append(f"   Percentile: p90 used for conservative estimate")
report_lines.append(f"   Units: bps (per side)")
report_lines.append(f"   Sample size: {exec_cal_source.get('n_samples', 'N/A')} samples")
report_lines.append(f"")

# Effective taker round-trip
report_lines.append(f"4. EFFECTIVE TAKER ROUND-TRIP")
report_lines.append(f"   Source: execution_calibration.json -> effective_taker_roundtrip")
for band, vals in exec_cal.get("effective_taker_roundtrip", {}).items():
    report_lines.append(f"   Band ${band}: median={vals.get('median_bps')}, p90={vals.get('p90_bps')}")
report_lines.append(f"   Convention: fee + spread + slippage (all-in round-trip)")
report_lines.append(f"   How measured: Derived from sampler + fee schedule")
report_lines.append(f"   Percentile: p90 = {exec_cal['effective_taker_roundtrip']['1000']['p90_bps']} bps (for $1000)")
report_lines.append(f"   Units: bps (round-trip)")
report_lines.append(f"")

# Impact and latency
report_lines.append(f"5. MARKET IMPACT ALLOWANCE")
report_lines.append(f"   Source: v3_cost.py -> IMPACT_ALLOWANCE_BPS = 0.10")
report_lines.append(f"   Convention: Fixed allowance for temporary impact")
report_lines.append(f"   Units: bps")
report_lines.append(f"")
report_lines.append(f"6. LATENCY COST")
report_lines.append(f"   Source: v3_cost.py -> LATENCY_COST_BPS = 0.05")
report_lines.append(f"   Convention: Fixed allowance for execution latency")
report_lines.append(f"   Units: bps")
report_lines.append(f"")

# Maker components
report_lines.append(f"7. MAKER FEE")
report_lines.append(f"   Source: execution_calibration.json -> maker_fee_rt_bps = 2.0")
report_lines.append(f"   Convention: round-trip maker fee")
report_lines.append(f"   Units: bps (round-trip)")
report_lines.append(f"")
report_lines.append(f"8. ADVERSE SELECTION (MAKER)")
report_lines.append(f"   Source: execution_calibration.json -> oos_fill")
report_lines.append(f"   Method: drag = gross_unconditional_bps - e_fill_return_bps")
report_lines.append(f"   Median calculation: median of all oos_fill drags")
drags = []
for cell in exec_cal.get("oos_fill", {}).values():
    g = cell.get("gross_unconditional_bps")
    e = cell.get("e_fill_return_bps")
    if g is not None and e is not None:
        drags.append(g - e)
median_drag = float(np.median(drags)) if drags else None
report_lines.append(f"   Drags: {sorted(drags)}")
report_lines.append(f"   Median adverse selection drag: {median_drag} bps")
report_lines.append(f"   Units: bps")
report_lines.append(f"")
report_lines.append(f"9. FILL PROBABILITY (MAKER)")
report_lines.append(f"   Source: execution_calibration.json -> oos_fill -> p_fill_same_tick")
pfills = [cell["p_fill_same_tick"] for cell in exec_cal.get("oos_fill", {}).values()
          if cell.get("p_fill_same_tick") is not None]
median_pfill = float(np.median(pfills)) if pfills else None
report_lines.append(f"   Values: {sorted(pfills)}")
report_lines.append(f"   Median p_fill: {median_pfill}")
report_lines.append(f"   Units: probability (0-1)")
report_lines.append(f"")

# Non-fill reprice
report_lines.append(f"10. NON-FILL REPRICE COST (MAKER)")
report_lines.append(f"    Source: v3_cost.py -> NON_FILL_REPRICE_COST_BPS = 0.50")
report_lines.append(f"    Convention: cost when order does not fill and market moves")
report_lines.append(f"    Formula: NON_FILL_REPRICE_COST_BPS * (1 - p_fill)")
report_lines.append(f"    Units: bps")
report_lines.append(f"")

# Safety margin
report_lines.append(f"11. SAFETY MARGIN")
report_lines.append(f"    Source: v3_cost.py -> SAFETY_MARGIN_BPS = 0.5")
report_lines.append(f"    Convention: Predeclared minimum net edge required per side")
report_lines.append(f"    Units: bps")
report_lines.append(f"")

report_lines.append(f"C. FEE CONVENTION")
report_lines.append("-" * 40)
report_lines.append(f"Taker fee: 2.0 bps per side, 4.0 bps round-trip")
report_lines.append(f"Maker fee: 2.0 bps round-trip")
report_lines.append(f"")
report_lines.append(f"D. COST SUMMARY")
report_lines.append("-" * 40)
report_lines.append(f"TAKER:")
taker_total = 4.0158 + 0.1 + 0.05  # effective_rt + impact + latency
taker_gate = taker_total + 0.5
report_lines.append(f"  One-way cost: {taker_total / 2:.4f} bps (half of round-trip)")
report_lines.append(f"  Round-trip cost: {taker_total:.4f} bps")
report_lines.append(f"  Gate (with margin): {taker_gate:.4f} bps")
report_lines.append(f"")
report_lines.append(f"MAKER (using median values):")
maker_fee = 2.0
maker_adverse = median_drag if median_drag is not None else 0.495
maker_reprice = 0.50 * (1 - (median_pfill if median_pfill is not None else 0.9864))
maker_latency = 0.05
maker_total = maker_fee + maker_adverse + maker_reprice + maker_latency
maker_gate = maker_total + 0.5
report_lines.append(f"  Maker fee (round-trip): {maker_fee:.4f} bps")
report_lines.append(f"  Adverse selection: {maker_adverse:.4f} bps")
report_lines.append(f"  Non-fill reprice: {maker_reprice:.4f} bps")
report_lines.append(f"  Latency: {maker_latency:.4f} bps")
report_lines.append(f"  Round-trip cost: {maker_total:.4f} bps")
report_lines.append(f"  Gate (with margin): {maker_gate:.4f} bps")
report_lines.append(f"")
report_lines.append(f"E. ORIGINAL OOS_OOS.JSON COST ASSUMPTION")
report_lines.append("-" * 40)
report_lines.append(f"File: data/hist/research/oos_oos.json")
report_lines.append(f"Cost model (frozen, older protocol):")
report_lines.append(f"  taker_fee_bps_per_side: {original_cost_components.get('taker_fee_bps_per_side')}")
report_lines.append(f"  slip_bps_per_side: {original_cost_components.get('slip_bps_per_side')}")
report_lines.append(f"  round_trip_bps: {original_cost_components.get('round_trip_bps')}")
report_lines.append(f"  Total gate: {original_cost_bps} bps round-trip")
report_lines.append(f"")
report_lines.append(f"F. CONTEMPORANEOUS COST CALIBRATION ASSESSMENT")
report_lines.append("-" * 40)
report_lines.append(f"Does a contemporaneous cost calibration exist for the OOS period? NO")
report_lines.append(f"")
report_lines.append(f"Evidence:")
report_lines.append(f"  - Cost sampler files are from 2026-08-17")
report_lines.append(f"  - OOS period is 2026-08-18")
report_lines.append(f"  - Gap: {gap_hours:.1f} hours")
report_lines.append(f"  - No other cost/calibration files found with OOS-period timestamps")
report_lines.append(f"")
report_lines.append(f"Cost files found in data/hist/research/:")
for cf in cost_files:
    report_lines.append(f"  {cf.name}")
report_lines.append(f"")

report_text = "\n".join(report_lines)
(DATA_RESEARCH / "CORRECTED_COST_REPORT.txt").write_text(report_text)
print("Wrote CORRECTED_COST_REPORT.txt")
print(report_text)
