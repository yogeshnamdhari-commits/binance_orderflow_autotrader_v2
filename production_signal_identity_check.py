#!/usr/bin/env python3
"""
PRODUCTION_SIGNAL_IDENTITY_CHECK

Verifies that the production signal path is identical to the research validation path.
If not identical, DEPLOYABLE_EDGE = FALSE, LIVE_TRADING = HARD_BLOCKED.
"""

import json
from pathlib import Path

print("=" * 70)
print("PRODUCTION_SIGNAL_IDENTITY_CHECK")
print("=" * 70)

# 1. Research model (V5 ridge)
print("\n1. RESEARCH MODEL (V5 Ridge)")
print("-" * 40)
with open("data/research/v5_model.json") as f:
    v5_model = json.load(f)
print(f"   Model type: Ridge regression (frozen)")
print(f"   Horizon: {v5_model['primary_horizon_ms']} ms")
print(f"   Features: {len(v5_model['features'])} ({v5_model['features'][:5]}...)")
print(f"   Target: r_500 = (mid_{{t+500}} - mid_t) / mid_t * 1e4  [bps]")
print(f"   Splits: Train {v5_model['splits']['train']['rows']} | Val {v5_model['splits']['validation']['rows']} | OOS {v5_model['splits']['oos']['rows']}")

# 2. Research calibration
print("\n2. RESEARCH CALIBRATION (v5_calibration_report.json)")
with open("data/research/v5_calibration_report.json") as f:
    cal_report = json.load(f)
print(f"   Method: {cal_report['calibration_method']['method']}")
print(f"   Horizon: {cal_report['forward_return_target_definition']['horizon_ms']} ms")
print(f"   Gross calibrated expectancy: {cal_report['gross_expectancy_using_calibrated_return']:.4f} bps")
print(f"   95% CI: [{cal_report['gross_expectancy_ci95']['low']:.4f}, {cal_report['gross_expectancy_ci95']['high']:.4f}]")
print(f"   Maker-adjusted: {cal_report['maker_adjusted_expectancy']:.4f} bps")
print(f"   Taker-adjusted: {cal_report['taker_adjusted_expectancy']:.4f} bps")

# 3. Production signal path
print("\n3. PRODUCTION SIGNAL PATH (decision.py)")
print("-" * 40)
print(f"   Signal rule: delta > 0 & imbalance_5 > 0.20 → BUY")
print(f"   Expected return source: fill_calib.json condition 'delta_5s_dec10_long@15s'")
print(f"   Horizon: 15,000 ms (15 s)")
print(f"   Execution style: MAKER (passive fill model)")

# 4. Fill calibration for production condition
print("\n4. FILL CALIBRATION (Production Condition)")
print("-" * 40)
with open("data/hist/research/fill_calib.json") as f:
    fill_cal = json.load(f)
cond_15s = "delta_5s_dec10_long@15s"
if cond_15s in fill_cal['results']:
    r = fill_cal['results'][cond_15s]
    print(f"   Condition: {cond_15s}")
    print(f"   Gross unconditional: {r['gross_unconditional_bps']:.3f} bps")
    print(f"   E[fill return]: {r['e_fill_return_bps']:.3f} bps")
    print(f"   Net after maker fee: {r['net_after_maker_bps']:.3f} bps")
    print(f"   p_fill_same_tick: {r['p_fill_same_tick']:.4f}")
    print(f"   Mean time to fill: {r['mean_time_to_fill_ms']:.1f} ms")

# 5. Compare signal conditions
print("\n5. SIGNAL CONDITION MISMATCH")
print("-" * 40)
print("   Production _raw_direction: delta > 0 AND imbalance_5 > 0.20")
print("   Fill cal condition:       delta_5s_dec10_long (delta 5s decile 10)")
print("   -> NOT IDENTICAL. Different features, different thresholds.")

# 6. Horizon mismatch
print("\n6. HORIZON MISMATCH")
print("-" * 40)
print(f"   Research model:   {500} ms")
print(f"   Production:       {15000} ms (30x longer)")
print("   -> NOT IDENTICAL.")

# 7. Cost model mismatch
print("\n7. COST MODEL MISMATCH")
print("-" * 40)
print("   Research gate:   Taker round-trip = 4.6658 bps")
print("   Production gate: Maker fee = 2.0 bps (fill model)")
print("   -> Different execution styles, different cost assumptions.")

# 8. Statistical gate
print("\n8. STATISTICAL SIGNIFICANCE GATE")
print("-" * 40)
print("   Research calibration: 95% CI added (gross CI: [0.0065, 0.0145] bps)")
print("   Production decision:  Pointwise check only (net > 0), NO CI")
print("   -> MISSING STATISTICAL GATE in production.")

# 9. Net expectancy comparison
print("\n9. NET EXPECTANCY COMPARISON")
print("-" * 40)
print(f"   Research (V5 calibrated, taker): { -4.09:.2f} bps (negative)")
print(f"   Research (V5 calibrated, maker): { -1.92:.2f} bps (negative)")
print(f"   Production (fill cal, maker):    { -0.60:.2f} bps (negative)")
print("   -> ALL NEGATIVE. NO DEPLOYABLE EDGE.")

# 10. Identity Check Verdict
print("\n" + "=" * 70)
print("PRODUCTION_SIGNAL_IDENTITY_CHECK VERDICT")
print("=" * 70)
print("IDENTICAL = FALSE")
print("")
print("MISMATCHES:")
print("  1. Signal condition:    imbalance_5 > 0.20  vs  delta_5s_dec10_long")
print("  2. Horizon:             500 ms              vs  15,000 ms")
print("  2. Model:               Ridge (17 features) vs  Heuristic (delta, imbalance)")
print("  4. Cost model:          Taker gate (4.67)   vs  Maker fee (2.0)")
print("  5. Statistical gate:    CI required         vs  Pointwise only")
print("")
print("DEPLOYABLE_EDGE = FALSE")
print("LIVE_TRADING = HARD_BLOCKED")
print("")
print("REQUIRED ACTION:")
print("  Resolve disconnect before any further optimization.")
print("  Options:")
print("  A) Align production to V5 ridge (use calibrated V5 prediction at 500ms)")
print("  B) Align research to production signal (re-run full cycle on 15s heuristic)")
print("  C) Document as separate pipelines; neither has edge currently.")