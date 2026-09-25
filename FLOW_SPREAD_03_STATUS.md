FLOW-SPREAD-0.3
================================================================================
Research:        PASS / candidate retained
In-sample:       +$390.62 (5 captures, retrospective)
True OOS:        +$1,888.33 (1 untouched capture)
OOS breaches:    0
Parameter:       FROZEN
Robustness:      NOT YET ESTABLISHED
Certification:   NOT CERTIFIED (6/7 gates pass)
Deployment:      NO_DEPLOY
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