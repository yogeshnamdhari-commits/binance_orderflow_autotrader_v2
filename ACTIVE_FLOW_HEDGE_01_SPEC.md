# ACTIVE_FLOW_HEDGE-0.1 Pre-Registration

## Specification Freeze Date: 2026-09-27

This specification is frozen before any implementation or data analysis. 
All changes require explicit amendment to this document.

## 1. Mechanism Definition

Four independent mechanisms compose ACTIVE_FLOW_HEDGE-0.1, each activated
relative to the FLOW-SPREAD-0.3 baseline:

### 1.1 Active Flow Quote Bias
- **Variable:** `flow_quote_bias_bps` (baseline = 1.0 bps)
- **Variable:** `flow_weight` (baseline = 0.5)
- **Effect:** Quote price adjustment = mid ± (base_spread/2) + flow_weight * flow_measurement * flow_quote_bias_bps
- **Direction:** positive flow_measurement → widen ask, tighten bid (or vice versa
  depending on sign convention); sign determined at implementation
- **Comparison vs FLOW-SPREAD-0.3:** FLOW-SPREAD-0.3 has `directional_flow_weight: 0.0`
  and no active flow bias. This mechanism makes flow influence quoting.

### 1.2 Active Inventory Hedge
- **Variable:** `hedge_threshold_notional` (baseline = 20% of max_position_notional_usd = $1,000)
- **Variable:** `hedge_ratio` (baseline = 0.5)
- **Effect:** When |inventory_usd| > hedge_threshold_notional, submit offsetting
  passive orders for `hedge_ratio` * sign(inventory) * (|inventory| - hedge_threshold)
  notional per quote interval. Orders are POST-only to minimize adverse selection.
- **Comparison vs FLOW-SPREAD-0.3:** FLOW-SPREAD-0.3 has NO active hedging. 
  Only spread widening and adverse selection cancellation. This mechanism
  actively reduces inventory exposure.

### 1.3 Nonlinear Inventory Penalty
- **Variable:** `inventory_penalty_base_bps` (baseline = 1.0 bps)
- **Variable:** `inventory_penalty_slope` (baseline = 0.5 bps per 10% of limit)
- **Effect:** Effective spread surcharge = inventory_penalty_base_bps + 
  inventory_penalty_slope * ceil(inventory_usd / (max_position_notional_usd/10))
  = 1.0 + 0.5 * ceil(inventory_usd / 500)
  Example: at 20% limit ($1,000): 1.0 + 0.5*2 = 2.0 bps
  At 50% limit ($2,500): 1.0 + 0.5*5 = 3.5 bps
  At 95% limit ($4,750): 1.0 + 0.5*10 = 6.0 bps
- **Comparison vs FLOW-SPREAD-0.3:** FLOW-SPREAD-0.3 has linear `inventory_penalty_bps: 2.0`
  (constant regardless of inventory level). This mechanism provides escalating
  penalty as inventory grows, with near-zero penalty when inventory is small.

### 1.4 Breach-Response Sizing
- **Variable:** `max_inventory_breaches_allowed` (baseline = 0, strict)
- **Variable:** `quote_size_reduction_after_breach` (baseline = 0.5, i.e., 50% reduction)
- **Effect:** After the first inventory limit breach (inventory_usd exceeds
  max_position_notional_usd or goes below -max_position_notional_usd):
  - Quote size reduces to `quote_size_usd * (1 - quote_size_reduction_after_breach)`
    = $50, i.e., 50% reduction from $100
  - Reduction persists for the remainder of the capture
  - If a 2nd breach occurs, candidate is auto-marked FAIL (gate: no_inventory_breaches)
- **Comparison vs FLOW-SPREAD-0.3:** FLOW-SPREAD-0.3 has `no_inventory_breaches` gate
  but NO automatic quote-size reduction or persistent consequences. After a breach,
  the candidate continues with the same quote size and penalty.

## 2. Baseline and Comparison

### 2.1 Frozen Candidate: FLOW-SPREAD-0.3
- Config sha256: 6d43d31d
- Commit: 5d0d762 (immutable, never modified)
- Directional flow weight: 0.0 (disabled)
- Inventory penalty: linear 2.0 bps (constant)
- Inventory hedging: none
- Inventory breach response: none (only widens spreads)
- Max position notional: $5,000
- Directional flow threshold: 0.3 (unitless, no active effect)
- Inventory suppression enabled: true, power 1.0, target 0.0

### 2.2 New Hypothesis: ACTIVE_FLOW_HEDGE-0.1
- Same base parameters as FLOW-SPREAD-0.3 EXCEPT the four mechanisms above
- All other parameters identical (adverse_selection_threshold_bps: 0.75,
  base_half_spread_bps: 2.5, max_half_spread_bps: 4.0, quote_interval_ms: 100,
  quote_size_usd: 100.0, maker_fee_bps: 2.0, taker_fee_bps: 5.0,
  microprice_skew_bps: 1.0, min_top_level_qty: 0.0, live_order_submission: false,
  cancel_on_adverse_selection: true, toxicity_filter_enabled: true,
  toxicity_flow_threshold: 0.6, toxicity_imbalance_threshold: 0.65)

## 3. Primary Economic Gates (defined BEFORE seeing results)

All gates must be reported. Failure of any gate is an automatic FAIL for that
OOS capture, regardless of realized P&L sign.

| Gate | Definition | Pass Criterion |
|------|-----------|----------------|
| **attribution_reconciled** | net_pnl = realized_pnl + inventory_mtm (residual ≤ 1e-6) | true |
| **gross_capture_positive** | gross_spread_capture_usd > 0 | true |
| **inventory_within_limit** | |inventory_final| ≤ 0.1 (near-flat final inventory) |
| **no_inventory_breaches** | inventory_limit_breaches = 0 | true (strict: 0 tolerated) |
| **sufficient_fills** | fills ≥ 300 per capture (≥ 80% of OOS #1 baseline) | true |
| **realized_pnl_positive** | realized_pnl_usd > 0 | true (primary economic gate) |
| **net_pnl_positive** | net_pnl_usd > 0 | true (primary economic gate) |

## 4. Data Protocol

### 4.1 Retrospective Testing (MANDATORY, must pass before fresh OOS)
- **Captures:** Same three historical OOS captures used for FLOW-SPREAD-0.3:
  - OOS #1: `913176970ae64234b93809d8bde47fff` (Sep 25, 2026)
  - OOS #2: `898e6421285a4ad88e921a955fa52f41` (Sep 26, 2026)
  - OOS #3: `fe02163990f04b4890908d834c1b3fdd` (Sep 27, 2026)
- **Condition:** ACTIVE_FLOW_HEDGE-0.1 must pass ALL 7 certification gates
  on all 3 captures **before** any fresh unseen capture is collected.
- **If ANY gate fails on ANY capture:** Mechanism is NOT viable. Stop. Do not
  collect fresh OOS. Return to post-mortem analysis.

### 4.2 Fresh Unseen Capture (only if retrospective passes)
- Collect via `app/v10_capture.py --symbol BTCUSDT --duration 60m`
- Must pass `scripts/v20_capture_quality_gate.py` (same conditions as OOS #3)
- Then run `scripts/v20_certify_frozen_candidate.py` against ACTIVE_FLOW_HEDGE-0.1 config
- Economic gates evaluated as in Section 3

### 4.3 Prohibited Practices (explicit)
- Do NOT reuse old captures and relabel as OOS #N
- Do NOT modify FLOW-SPREAD-0.3 config (sha256 6d43d31d) or evidence
- Do NOT retune 0.3 bps inside the frozen experiment
- Do NOT change certification gates after seeing results
- Do NOT skip the retrospective 3-capture requirement

## 5. Sign Convention Standardization

### 5.1 Unified Convention: net_pnl = realized_pnl + inventory_mtm

This convention is NOW DEFINITIVE across all reports and will be enforced:

| Component | Sign Meaning | OOS #1 | OOS #2 |
|-----------|-------------|--------|--------|
| **realized_pnl_usd** | Cumulative P&L from aggressive fills (aggressive buys sold, aggressive buys bought) | +1,888.33 | -1,075.19 |
| **inventory_carry_usd** | Running P&L from holding inventory over the capture period; = sum of (price_movement * inventory_delta) during capture | +1,892.22 | -1,072.53 |
| **inventory_mtm_usd** | Terminal mark-to-market adjustment: final_inventory * mid_at_endpoint; adjusts the reconciliation | -1,894.85 | +1,071.50 |
| **net_pnl_usd** | Final economics: realized_pnl + inventory_mtm | -6.53 | -3.69 |
| **Reconciliation check** | net_pnl = realized_pnl + inventory_mtm (residual ≤ 1e-6) | -6.53 = 1,888.33 + (-1,894.85) ✓ | -3.69 = -1,075.19 + 1,071.50 ✓ |

### 5.2 Previous Inconsistency (now resolved)
- Earlier status documents sometimes presented inventory_carry_usd with sign
  relative to "positive = favorable." The table above uses the unified convention
  where inventory_carry_usd has the same sign as realized_pnl when inventory
  moves favorably, and opposite sign when inventory moves against the strategy.
- The reconciliation net_pnl = realized_pnl + inventory_mtm is the authoritative
  relationship. inventory_carry_usd is an intermediate accounting variable.

### 5.3 Going Forward
- All new experiment reports MUST follow this convention
- scripts/v20_certify_frozen_candidate.py already outputs using this convention
- Any new script must conform or be flagged as non-compliant
- Deviations from this convention in legacy reports are documented and accepted
  as historical artifacts, not current standard

## 6. Implementation Guardrails

### 6.1 No Modification to FLOW-SPREAD-0.3
- Config sha256 6d43d31d: **immutable**
- Evidence/status commit b763107: **immutable**
- OOS captures: **untouched, no relabeling**
- NO_DEPLOY: **permanently locked** for FLOW-SPREAD-0.3

### 6.2 Implementation Order
1. Freeze this specification (DONE)
2. Implement ACTIVE_FLOW_HEDGE-0.1 in `app/mm/quote_engine_v21.py`
   and `app/mm/config_v21_active_flow_hedge_01bps.json`
3. Run retrospective 3-capture test using `scripts/v20_certify_frozen_candidate.py`
   (modified to accept new config)
4. Evaluate all 7 economic gates on all 3 captures
5. ONLY IF ALL GATES PASS on all 3: collect fresh unseen capture
6. If ANY gate FAILS on ANY capture: STOP. Return to post-mortem.

### 6.3 Gate Evaluation Order (strict)
Gates are evaluated in the order listed in Section 3. If gate K fails, gates
K+1 through 7 are not evaluated for that capture, and the capture is marked FAIL
at gate K. This prevents p-hacking by multiple comparisons.

## 7. Success Criteria for Phase Transition

ACTIVE_FLOW_HEDGE-0.1 transitions from "retrospective hypothesis" to "viable
new experiment" if and only if:

1. All 7 gates pass on OOS #1, AND
2. All 7 gates pass on OOS #2, AND
3. All 7 gates pass on OOS #3

If 1 or 2 pass but 3 fails: document failure mechanism, return to post-mortem.
If fewer than 1 pass: major mechanism redesign required.

## 8. Record Keeping

This specification is committed to the git repository at:
- Path: NEXT_HYPOTHESIS.md (pre-registration, frozen)
- Branch: research/flow-spread-postmortem-0.3
- Commit: will reference this spec number in implementation commits

Any deviation from this specification requires a new pre-registration on a new
branch. Retroactive changes to this document are not permitted.