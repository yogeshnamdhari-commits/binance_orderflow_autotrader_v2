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