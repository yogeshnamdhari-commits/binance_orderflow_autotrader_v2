================================================================================
V10 BINANCE ORDER-FLOW AUTOTRADER — FINAL EVIDENCE-CHAIN REPORT
Generated: 2026-09-04T23:45:29.567379+00:00
================================================================================

EXECUTIVE SUMMARY
--------------------------------------------------------------------------------

ORIGINAL OOS PROVENANCE: UNRECOVERABLE
  - Original 11 V10 OOS sessions not found in workspace, git, filesystem, or documented locations
  - Original 1,062 calibration observations not persisted
  - Original frozen calibration artifact does not exist

NEW CLEAN CALIBRATION EXPERIMENT: COMPLETED WITH LIMITATIONS
  - 10 new calibration sessions captured
  - 1,034 observations generated
  - Frozen calibration artifact created: data/research/v10_frozen_calibration.json
  - CRITICAL LIMITATION: Calibration sessions temporally AFTER forward session

INDEPENDENT FORWARD TEST: PASS (with caveats)
  - Forward session: a81b222592ed47f3ad4a357b0d0f6845
  - 28 forward observations evaluated
  - Theoretical realized EV: +0.597 bps/order (using config assumptions)
  - Actual market net EV: +0.0073 bps/order (using real market spread)
  - Fill rate: 67.9%
  - Forward gate: PASS

CRITICAL FINDING: Config/Reality Mismatch
  - Configured spread_capture_bps: 2.0 bps
  - Actual market spread: 0.013 bps
  - The strategy economics assume spread capture far exceeding market reality
  - Forward validator PASSES based on config assumptions, not actual market conditions

SCIENTIFIC LIMITATIONS:
  1. Original V10 OOS provenance is permanently unavailable
  2. Calibration sessions temporally AFTER forward session (temporal inversion)
  3. Cannot claim original V10 OOS edge independently validated
  4. Forward sample size is small (28 observations)
  5. Net EV is NOT statistically significant (p=0.789, 95% CI includes zero)
  6. Execution costs estimated, not measured
  7. Regime analysis is underpowered
  8. Config assumptions (spread_capture_bps=2.0) vastly exceed actual market spread (0.013 bps)

================================================================================

CONSOLIDATED GATE TABLE
--------------------------------------------------------------------------------

| Gate | Status | Evidence | Blocker |
|------|--------|----------|---------|
| Research/OOS | PASS | 10/10 folds, +0.1854 bps, 1,062 obs (historical) | — |
| Original OOS provenance | FAIL | Sessions not found in any accessible location | Original OOS sessions permanently unavailable |
| Frozen calibration artifact | PASS | v10_frozen_calibration.json created from new data | — |
| Forward data integrity | PASS | 1,131 events, proper metadata, no malformed rows | — |
| Temporal independence | BLOCKED | Calibration sessions AFTER forward session | Cannot obtain pre-forward order book depth data |
| Independent unseen forward test | PASS | 28 obs, theoretical EV +0.597 bps, fill rate 67.9% | Based on config assumptions, not actual market conditions |
| Real execution-cost validation | FAIL | Actual net EV +0.0073 bps, 95% CI [-0.0033, +0.0174] bps | Config spread_capture_bps=2.0 >> actual spread=0.013 bps |
| Robustness/regime validation | PARTIAL | 28 obs, limited regime variation | Small sample size |
| Statistical robustness | FAIL | Net EV p=0.789, 95% CI includes zero, Cohen's d=0.26 | Effect not statistically significant |
| Paper trading | NOT STARTED | Requires all prior gates to pass | Multiple blockers |
| Live trading | LOCKED | Requires paper trading success + authorization | Multiple blockers |

================================================================================

PHASE 1 — PROVENANCE INVESTIGATION
--------------------------------------------------------------------------------

ORIGINAL_OOS_CALIBRATION_SOURCE = PERMANENTLY_UNAVAILABLE

Exhaustive search results:
  - data/v10/ (workspace): Only forward session a81b222592ed47f3ad4a357b0d0f6845
  - data/research/: No V10 calibration parquet/obs files
  - data/hist/research/: V2/V3/V5/V6 calibration only (no V10)
  - data/hist/normalized/: Only aggregated trades, no order book depth
  - /tmp/, /private/tmp/: No V10 directories
  - Filesystem search: Zero files with OOS session IDs
  - Git history: No commits with V10 session data
  - .gitignore: data/v10/ explicitly excluded

================================================================================

PHASE 2 — NEW CLEAN CALIBRATION EXPERIMENT
--------------------------------------------------------------------------------

Calibration sessions captured: 10
Total observations: 1,034
Calibration data range: 1788563186723991000 to 1788564444618168000
Forward session start_ns: 1788546346959786000

TEMPORAL INVERSION WARNING:
  Calibration sessions are temporally AFTER the forward session.
  This is a documented scientific limitation.
  The forward session was NOT used for calibration.
  The calibration artifact is frozen and independent of forward data.
  However, the calibration cannot legitimately claim to be 'before' the forward test.

Session provenance:
  09c2364b75e5: start_ns=1788563248285447000, events=4227, obs=118
  303431ba2ed3: start_ns=1788563673377370000, events=4061, obs=66
  4e17ca1b058d: start_ns=1788563432244713000, events=2920, obs=118
  55fdcf3422c5: start_ns=1788564444618168000, events=5277, obs=118
  6182cb031940: start_ns=1788563186723991000, events=8502, obs=118
  9848fe41eba1: start_ns=1788564292969660000, events=8130, obs=118
  a8a9a991483f: start_ns=1788564230889836000, events=16635, obs=118
  b5e84d4ed9a5: start_ns=1788563370925260000, events=2404, obs=118
  d7246c4fd38f: start_ns=1788563309699010000, events=3624, obs=118
  ffbf2f9e0989: start_ns=1788563738990948000, events=4586, obs=24

================================================================================

PHASE 3 — FORWARD VALIDATION
--------------------------------------------------------------------------------

Forward session: a81b222592ed47f3ad4a357b0d0f6845
Forward observations: 28
Status: PASS (based on config assumptions)

Results:
  - Theoretical realized EV: +0.597 bps/order (config: spread_capture_bps=2.0)
  - Predicted EV: +1.177 bps/order
  - EV prediction error: -0.581 bps
  - Fill rate: 67.9%
  - Predicted fill probability: 61.8%
  - Fill prediction error: -0.293
  - Calibration drift fill: +0.063
  - Calibration drift EV: +0.411 bps

Gate conditions:
  - positive_realized_ev: True
  - positive_fill_rate: True
  - fill_drift_within_tolerance: True
  - ev_drift_within_tolerance: True
  - edge_survives_execution: True

CAVEAT: Forward validator uses configured spread_capture_bps=2.0
  Actual market spread is 0.013 bps. The validator's PASS status
  does not reflect real market conditions.

================================================================================

PHASE 4 — EXECUTION-COST VALIDATION
--------------------------------------------------------------------------------

Market-data-derived costs:
  - Mean spread: 0.100 USD (0.013 bps)
  - Spread cost (half): 0.006 bps
  - Maker fee: -0.014 bps (rebate)
  - Total cost: -0.007 bps (negative = net rebate)
  - Adverse selection: 0.000 bps
  - Net EV: +0.007 bps

CRITICAL FINDING: Config/Reality Mismatch
  - Configured spread_capture_bps: 2.0 bps
  - Actual market spread: 0.013 bps
  - Strategy assumes 153x more spread capture than market provides
  - This is a fundamental economics mismatch

Sensitivity analysis:
  - Slippage=0.0 bps: net EV = +0.007 bps
  - Slippage=0.01 bps: net EV = -0.003 bps
  - Slippage=0.05 bps: net EV = -0.043 bps
  - Slippage=0.1 bps: net EV = -0.093 bps
  - Slippage=0.5 bps: net EV = -0.493 bps

CONCLUSION: Strategy is not economically viable at actual market spreads.
The configured spread_capture_bps=2.0 is not achievable in BTCUSDT market.

================================================================================

PHASE 5 — ROBUSTNESS/REGIME VALIDATION
--------------------------------------------------------------------------------

Sample size: 28 observations

Spread regimes (liquidity):
  - medium_spread (0.01-0.05 bps): n=28, fill_rate=67.9%, gross_ev=0.0000 bps, net_ev=0.0073 bps

Queue regimes (execution difficulty):
  - low_queue (<0.5): n=12, fill_rate=75.0%, gross_ev=0.0073 bps, net_ev=0.0160 bps
  - medium_queue (0.5-1.0): n=9, fill_rate=66.7%, gross_ev=0.0000 bps, net_ev=0.0070 bps
  - high_queue (>1.0): n=7, fill_rate=57.1%, gross_ev=-0.0126 bps, net_ev=-0.0074 bps

Side regimes:
  - ask: n=14, fill_rate=57.1%, gross_ev=-0.0063 bps, net_ev=-0.0011 bps
  - bid: n=14, fill_rate=78.6%, gross_ev=0.0063 bps, net_ev=0.0157 bps

Time regimes (chronological subperiods):
  - early: n=9, fill_rate=55.6%, gross_ev=0.0000 bps, net_ev=0.0048 bps
  - mid: n=9, fill_rate=77.8%, gross_ev=0.0000 bps, net_ev=0.0093 bps
  - late: n=10, fill_rate=70.0%, gross_ev=0.0000 bps, net_ev=0.0077 bps

LIMITATION: Only 28 observations, limited regime variation.
  - All observations in single spread regime
  - High-queue regime shows negative EV but n=7 (not statistically reliable)

================================================================================

PHASE 6 — STATISTICAL ROBUSTNESS
--------------------------------------------------------------------------------

Sample size: 28 observations

Net EV:
  - Mean: 0.0073 bps
  - Std: 0.0277 bps
  - 95% Bootstrap CI: [-0.0033, +0.0174] bps
  - Permutation p-value: 0.789
  - Cohen's d: 0.263 (small effect)

Fill rate:
  - Mean: 0.679
  - 95% Bootstrap CI: [0.500, 0.857]

Serial dependence:
  - Lag-1 autocorrelation: -0.463 (no concerning serial dependence)

Multiple comparison:
  - Bonferroni-corrected alpha (5 tests): 0.010
  - Net EV not significant after correction

CONCLUSION: Net EV is NOT statistically significant with n=28.
The forward test's PASS status is based on config assumptions, not statistical evidence.

================================================================================

PHASE 7 — FINAL EVIDENCE CHAIN
--------------------------------------------------------------------------------

The evidence chain reveals a CRITICAL finding:

The V10 strategy economics are FUNDAMENTALLY MISALIGNED with actual market conditions.

Config assumptions vs Reality:
  - spread_capture_bps (config): 2.0 bps
  - Actual BTCUSDT spread: 0.013 bps
  - Discrepancy: 153x

The forward validator PASSES because it uses config assumptions (spread_capture_bps=2.0)
to compute theoretical EV. It does NOT validate against actual market conditions.

When actual market spread is used:
  - Net EV: +0.007 bps (theoretical)
  - Net EV 95% CI: [-0.003, +0.017] bps
  - Statistically significant: NO (p=0.789)
  - Economically meaningful: NO (net edge < 0.01 bps)

================================================================================

FINAL GATE TABLE
--------------------------------------------------------------------------------

| Gate | Status | Evidence | Blocker |
|------|--------|----------|---------|
| Research/OOS | PASS | 10/10 folds, +0.1854 bps, 1,062 obs | — |
| Original OOS provenance | FAIL | Sessions permanently unavailable | Original OOS sessions unrecoverable |
| Frozen calibration artifact | PASS | v10_frozen_calibration.json created | — |
| Forward data integrity | PASS | 1,131 events, proper metadata | — |
| Temporal independence | BLOCKED | Calibration AFTER forward session | No pre-forward order book depth data |
| Independent unseen forward test | PASS (config-based) | 28 obs, theoretical EV +0.597 bps | Not validated against actual market |
| Real execution-cost validation | FAIL | Actual net EV +0.007 bps, CI includes zero | spread_capture_bps=2.0 >> actual spread=0.013 bps |
| Robustness/regime validation | PARTIAL | 28 obs, limited regime variation | Small sample size |
| Statistical robustness | FAIL | Net EV p=0.789, CI includes zero | Effect not statistically significant |
| Paper trading | NOT STARTED | Requires all prior gates to pass | Multiple blockers |
| Live trading | LOCKED | Not authorized | Multiple blockers |

================================================================================

PRODUCTION READINESS: NOT READY

The V10 project cannot be authorized for production trading because:

  1. Original OOS provenance cannot be verified
  2. Calibration data is temporally AFTER forward session (temporal inversion)
  3. The strategy economics (spread_capture_bps=2.0) are fundamentally misaligned
     with actual BTCUSDT market conditions (spread=0.013 bps)
  4. Forward sample is small (28 observations)
  5. Net EV is NOT statistically significant (p=0.789)
  6. Execution costs are estimated, not measured
  7. Regime analysis is underpowered
  8. Paper trading has not started

Live trading remains DISABLED.

================================================================================