FLOW-SPREAD-0.3
================================================================================
Research:        PASS / candidate retained
In-sample:       +$390.62 (5 captures, retrospective)
True OOS #1:     +$1,888.33 (capture 91317697)
True OOS #2:     -$1,075.19 (capture 898e6421)
OOS breaches:    0 (both captures)
Parameter:       FROZEN
Robustness:      NOT ESTABLISHED (1 positive, 1 negative OOS)
Certification:   NOT CERTIFIED (6/7 on OOS #1, 5/7 on OOS #2)
Deployment:      NO_DEPLOY
================================================================================

SECOND UNTOUCHED OOS CAPTURE
--------------------------------------------------------------------------------
  session_id:  898e6421285a4ad88e921a955fa52f41
  duration:    3,601.4 s
  events:      1,149,599 (35,279 depth, 89,942 trade, 1,024,377 bookTicker, 1 reconnect)
  bootstrap:   BRIDGED, snapshot_source=REST
  collected:   AFTER candidate frozen (commit b3e95f2, sha256 6d43d31d)
  provenance:   candidate config identical to OOS #1

OOS #2 RESULT
  fills:                   303
  gross_spread_capture:    $0.2865
  fees:                    $2.95
  realized_pnl:            -$1,075.19
  net_pnl:                 -$3.69
  inventory_carry:         -$1,072.53
  inventory_max:           $1,485.80 (cap $5,000)
  inventory_limit_breaches: 0
  pnl_per_fill:            -$3.55

CERTIFICATION GATES (5/7 pass)
  attribution_reconciled:      PASS
  gross_capture_positive:       PASS
  inventory_within_limit:       PASS
  no_inventory_breaches:        PASS
  sufficient_fills:            PASS
  realized_pnl_positive:        FAIL  (OOS #1 passed this gate)
  net_pnl_positive:             FAIL

FORENSIC ON OOS #2
  Diagnosis: PERSISTENT_CARRY (not endpoint artifact)

  Endpoint   Inventory     Mid        MTM        Net PnL
  10%         -0.01070    $84,152    -$900.13    -$1,975.32
  25%         -0.00832    $84,103    -$699.47    -$1,774.66
  50%         +0.00581    $83,809    +$404.04    -$588.45
  75%         +0.01657    $83,635    +$1,385.85    +$310.65
  90%         +0.01280    $83,614    +$1,069.95     -$5.25
  95%         +0.01639    $83,588    +$1,369.73    +$294.53
  100%        +0.01280    $83,673    +$1,071.38     -$3.82

  Net oscillates between -$1,975 and +$311 across endpoints. Realized
  PnL itself is negative -- this is not an endpoint-marking artifact.
  The candidate is directionally unstable across captures.

CONCLUSION
--------------------------------------------------------------------------------
A single positive untouched OOS does not establish robustness. OOS #1 was
+$1,888.33 realized; OOS #2 is -$1,075.19 realized, opposite sign, with
realized_pnl_positive now failing. The candidate config (6d43d31d) is
identical across both captures; no parameters were changed.

The flow-spread mechanism is NOT disproven, but it is NOT established.
The first OOS result was likely favorable market conditions, not a
durable edge. Candidate remains FROZEN, NOT CERTIFIED, NO_DEPLOY.

Next legitimate step is NOT another parameter sweep. It is to understand
why the candidate is directionally unstable -- specifically whether the
0.3 bps spread point interacts with market regime in a way that produces
sign-flipping PnL. That requires analysis, not re-tuning.

FORENSIC RECONCILIATION OF THE BINDING NET PnL GATE
--------------------------------------------------------------------------------
The candidate shows realized +$1,888.33 but net -$6.53, failing the
net_pnl_positive gate. scripts/v20_inventory_carry_forensic.py replays
the frozen config once and projects net PnL at hypothetical endpoints
along the inventory trajectory. It does NOT change the candidate.

Diagnosis: ENDPOINT_ARTIFACT (not persistent carry).

  Endpoint   Inventory     Mid        MTM        Net PnL
  10%         +0.00597    $83,859    +$500.55    +$2,388.88
  25%         +0.00500    $83,626    +$418.08    +$2,306.40
  50%         +0.00482    $83,793    +$404.04    +$2,292.36
  75%         -0.00967    $83,774    -$810.44    +$1,077.89
  90%         -0.01543    $83,917   -$1,294.48    +$593.85
  95%         -0.02119    $83,970   -$1,779.09    +$109.23
  100%        -0.02257    $83,966   -$1,894.70    -$6.37

Net PnL is positive at every sampled endpoint from 10% through 95%.
Only the final capture endpoint flips it negative. The residual
position is 0.0226 BTC (~$960 notional) at endpoint -- small. The drag
is price movement against a tiny short, not accumulated inventory carry.

Inventory persistence: 100% of trajectory points have nonzero inventory,
but max absolute inventory is 0.0226 BTC. The strategy holds a small
position throughout; the economic deficit is endpoint mark-to-market,
not trading losses.

Certification status is NOT changed by this finding. The net_pnl gate
is deterministic and currently fails; the gate was not modified using
the OOS result.
================================================================================

FROZEN CANDIDATE (sha256 6d43d31db37a1cc9d570a5d796f45b7757c82ee9f0987ac2bcfacfa36ca74a1a)
  inventory_suppression_enabled: true
  inventory_suppression_power:    1.0
  directional_flow_enabled:        true
  directional_flow_threshold:      0.3
  directional_flow_weight:         0.0
  directional_flow_spread_bps:     0.3
  All other params identical to baseline config_v20_eco_v1_actual_fees.json.

EVIDENCE CHAIN
--------------------------------------------------------------------------------
Stage                          Fills   Realized PnL   Gross capture   Max inv   Breaches
--------------------------------------------------------------------------------
Baseline (V20)                 1,719      -$8,169.93        $0.0724      $4,993       10
Directional flow 0.3 (ref)       903      -$1,823.50        $0.0364      $4,491        0
Flow-weighted 1.0 (rejected)     576      -$1,025.44        $0.0141      $1,364        0
Flow-spread 0.3bps (in-sample)   708      +$390.62          $0.6515      $2,841        0
Flow-spread 0.5bps (rejected)    629      -$760.98          $0.8338      $2,341        0
Flow-spread 1.0bps (rejected)    416      -$32.71           $0.6360      $1,420        0
Flow-spread 0.3bps (OOS)         456      +$1,888.33         $0.3696      $1,895        0
--------------------------------------------------------------------------------

TRUE OOS CAPTURE
  session_id:  913176970ae64234b93809d8bde47fff
  duration:    3,601.5 s
  events:      1,670,792 (35,282 depth, 101,436 trade, 1,534,073 bookTicker, 1 reconnect)
  bootstrap:   BRIDGED, snapshot_source=REST
  collected:   AFTER candidate frozen (commit 76d4c34, sha256 6d43d31d)
  provenance:   manifest sha256 50d4cb29, snapshot sha256 9b83de37,
                events sha256 4f465cafb91d505479fd23672103ae559a0346ee6b6c2f7675f8383d8717adb0

OOS RESULT
  fills:                   456
  gross_spread_capture:    $0.3696
  fees:                    $4.27
  realized_pnl:            +$1,888.33
  net_pnl:                 -$6.53
  inventory_carry:         -$1,892.22
  inventory_max:           $1,895.37 (cap $5,000)
  inventory_limit_breaches: 0
  pnl_per_fill:            +$4.14
  gross_capture_per_fill:  $0.00081046

CERTIFICATION GATES (6/7 pass)
  attribution_reconciled:      PASS
  gross_capture_positive:       PASS
  inventory_within_limit:       PASS
  no_inventory_breaches:        PASS
  sufficient_fills:            PASS
  realized_pnl_positive:        PASS
  net_pnl_positive:             FAIL  (net -$6.53; realized +$1,888.33 but
                                       inventory_carry -$1,892.22 drags net down)

CORRECTED GROSS-CAPTURE MULTIPLIER (precise per-fill, not rounded)
  baseline per-fill:      $0.00004213
  dir-flow-0.3 per-fill:  $0.00004027
  flow-spread per-fill:   $0.00092020   -> 21.8x vs baseline, 22.9x vs dir-flow
  OOS per-fill:           $0.00081046   -> 19.2x vs baseline
  (Earlier 18x figure used rounded values and understated the effect.)

MECHANISM INTERPRETATION
  directional flow
    -> inventory suppression
    -> remaining-side quote repricing
    -> better price selection
    -> higher capture per executed fill

  This is a PRICE-SELECTION mechanism, materially different from
  flow-weighting, which is an EXPOSURE-CONTROL mechanism:
  directional flow -> quantity reduction -> less exposure -> lower absolute loss.

PARAMETER NOTE
  0.3 bps is the best-performing TESTED point and was subsequently validated
  on an untouched OOS capture. The curve is non-monotonic (0.5bps = -$760.98),
  so this does not establish a mathematical optimum across the continuous
  parameter space. Do not retune 0.2/0.4/0.5 around the OOS result.

NEXT STEPS (not yet done)
  1. A second untouched OOS capture to establish robustness (single capture
     does not establish it).
  2. Investigate the net_pnl gate: inventory carry drag is the binding
     constraint. This is a mark-to-market effect on open position, not a
     trading loss, but the gate is deterministic and currently fails.
  3. Only after robustness is established should certification proceed.
  4. Live deployment remains NO_DEPLOY throughout.

REGIME DECOMPOSITION ANALYSIS
--------------------------------------------------------------------------------
scripts/v20_regime_decomposition.py compares OOS #1 vs OOS #2 using invariant
capture session IDs from certification outputs.

OOS #1 (91317697) - Diagnosis: ENDPOINT_ARTIFACT
  Realized PnL:       +$1,888.33
  Net PnL:            -$6.53
  Inventory carry:    +$1,892.22
  Final inventory:    -0.022565 BTC (short)
  Fills:              456
  Gross capture:      $0.37

  Regime distribution (fills per regime):
    HIGH_INVENTORY:    13 fills
    MEDIUM_INVENTORY:  68 fills
    LOW_INVENTORY:     69 fills
    NEUTRAL_INVENTORY: 306 fills

  Net PnL positive at all earlier endpoints (10%-95%), only flips at 100%.

OOS #2 (898e6421) - Diagnosis: PERSISTENT_CARRY
  Realized PnL:       -$1,075.19
  Net PnL:            -$3.69
  Inventory carry:    -$1,072.53
  Final inventory:    +0.012804 BTC (long)
  Fills:              303
  Gross capture:      $0.29

  Regime distribution (fills per regime):
    MEDIUM_INVENTORY:   25 fills
    LOW_INVENTORY:      69 fills
    NEUTRAL_INVENTORY: 209 fills

  Net PnL negative at ALL endpoints - persistent carry pattern.

Comparison
  Realized PnL delta:    +$2,963.52 (OOS #1 - OOS #2)
  Inventory carry delta: +$2,964.76 (OOS #1 - OOS #2)
  Fills delta:           +153 (OOS #1 - OOS #2)

Sign-flipping cause: OOS #2 had persistent negative realized PnL (trading loss),
OOS #1 had positive trading but negative mark-to-market on residual position.

FINAL EVIDENCE INTERPRETATION
--------------------------------------------------------------------------------
The regime decomposition adds an important distinction: the two OOS failures
have different mechanisms.

OOS #1 (91317697): ENDPOINT_ARTIFACT
  - Realized PnL is positive (+$1,888.33) -- the trading was profitable.
  - Net PnL is negative (-$6.53) only at the final endpoint.
  - All earlier endpoints (10%-95%) show positive net PnL.
  - The deficit is a small residual short (-0.022565 BTC, ~$960 notional)
    marked to market at the capture cutoff, not accumulated trading losses.

OOS #2 (898e6421): PERSISTENT_CARRY
  - Realized PnL is already negative (-$1,075.19) -- the trading was unprofitable.
  - Net PnL is negative at ALL endpoints, including the earliest.
  - This is not an endpoint-marking artifact; the trading itself was negative.

CLEAN CONCLUSION
--------------------------------------------------------------------------------
  Execution edge observed          ✅
  Inventory breaches                ✅ 0
  Positive realized OOS             ✅ on OOS #1
  Negative realized OOS             ❌ on OOS #2
  Cross-capture consistency         ❌
  Robustness                        ❌ NOT ESTABLISHED
  Certification                     ❌
  Deployment                        🔒 NO_DEPLOY

The candidate is not simply suffering from an accounting artifact. The two
untouched captures show different realized-P&L behavior under exactly the
same frozen configuration.

The next research question is no longer "Which spread parameter should we
choose?" It is:

  Under what observable market conditions does the frozen flow-spread
  mechanism produce positive versus negative realized economics?

That is a regime-dependence question, not a parameter-optimization question.

The analysis should remain frozen and be used to identify relationships among:

  flow imbalance
  volatility
  trade intensity
  spread stability
  inventory direction
  adverse selection
  fill-side asymmetry
  realized spread capture

without changing the candidate or using OOS results to retune it.

BOOKKEEPING RECONCILIATION REQUIREMENT
--------------------------------------------------------------------------------
The OOS #1 diagnosis depends on distinguishing realized trading economics
from terminal mark-to-market effects. Inventory carry, realized P&L, fees,
and terminal net P&L must reconcile exactly at every endpoint:

  net_pnl = realized_pnl + inventory_mtm
  inventory_mtm = final_inventory * mid_at_endpoint
  realized_pnl = gross_spread_capture + inventory_carry - fees - adverse_selection

This reconciliation is verified by scripts/v20_inventory_carry_forensic.py
and scripts/v20_certify_frozen_candidate.py. The attribution_residual_usd
field is asserted to be zero (<= 1e-6) before certification proceeds.

Current authoritative status: 5d0d762 documents a frozen, non-certified
candidate with mixed OOS realized performance. No certification and no live
deployment.

THIRD UNTOUCHED OOS CAPTURE (OOS #3)
--------------------------------------------------------------------------------
  session_id:  fe02163990f04b4890908d834c1b3fdd
  duration:    3,597.3 s
  events:      1,359,827 (35,270 depth, 141,385 trade, 1,183,172 bookTicker)
  bootstrap:   BRIDGED, snapshot_source=REST
  collected:   AFTER candidate frozen (commit cb399c5, sha256 6d43d31d)
  provenance:   manifest sha256 dab602fafc29e46509524bda19518add08a47f60da398570c49be21608b69827,
                snapshot sha256 42bad92cb2a42fa9f8f68f0b5dec45e5cf226564d43ce2429ccc0c637c9ac9d8,
                events sha256 980475bff8de95e6e892d62c8073a7e946d232c327f75f6c40de590f60c6fc7e
  quality_gate: PASS (BTCUSDT, 3597s, 0 parse errors, BRIDGED, REST)

OOS #3 RESULT
  fills:                   592
  gross_spread_capture:    $0.4031
  fees:                    $5.25
  realized_pnl:            -$3,329.51
  net_pnl:                 -$16.25
  inventory_carry:         -$3,324.66
  inventory_max:           $4,997.02 (cap $5,000)
  inventory_limit_breaches: 27
  pnl_per_fill:            -$5.62
  gross_capture_per_fill:  $0.00068092

CERTIFICATION GATES (4/7 pass)
  attribution_reconciled:      PASS
  gross_capture_positive:       PASS
  inventory_within_limit:       PASS
  no_inventory_breaches:        FAIL  (27 breaches)
  sufficient_fills:            PASS
  realized_pnl_positive:        FAIL
  net_pnl_positive:             FAIL

OOS #3 DIAGNOSIS: PERSISTENT_CARRY (negative realized throughout)
  - Negative realized P&L (-$3,329.51) is the dominant economic result
  - Inventory breaches: 27 (exceeds 0 limit)
  - Inventory max: $4,997.02 (near cap $5,000)
  - Net P&L negative at all endpoints (persistent carry pattern)

3-CAPTURE ROBUSTNESS ASSESSMENT
--------------------------------------------------------------------------------
  OOS #1 (91317697): +$1,888.33 realized, 6/7 gates, ENDPOINT_ARTIFACT
  OOS #2 (898e6421): -$1,075.19 realized, 5/7 gates, PERSISTENT_CARRY
  OOS #3 (fe021639): -$3,329.51 realized, 4/7 gates, PERSISTENT_CARRY

  Aggregate: 1,351 fills, -$1,516.37 realized P&L, -$26.47 net P&L

  Positive realized captures: 1 of 3
  Negative realized captures: 2 of 3
  Cross-capture consistency: NOT ESTABLISHED

  Inventory breaches: 0, 0, 27 (OOS #3 violates no_inventory_breaches)

  The candidate fails 3 of 7 gates on OOS #3, including both realized and net P&L.

FINAL DISPOSITION
--------------------------------------------------------------------------------
  Candidate:        FROZEN
  Research evidence: COMPLETE
  OOS #1:           Positive realized
  OOS #2:           Negative realized
  OOS #3:           Negative realized
  Robustness:       NOT ESTABLISHED
  Certification:    NOT CERTIFIED
  Deployment:       NO_DEPLOY
  Remote sync:      COMPLETE (commit cb399c5)

  The frozen candidate produces inconsistent realized economics across three
  untouched captures. Two of three are negative, and OOS #3 additionally
  violates the inventory breach gate. There is no valid basis to certify
  this candidate or deploy it.

  The next legitimate research phase is a new experiment from a clean
  branch, not further parameter tuning of FLOW-SPREAD-0.3.

  NO LIVE ORDERS. NO PARAMETER RETUNING. NO CERTIFICATION BY EXCEPTION.

===============================================================================