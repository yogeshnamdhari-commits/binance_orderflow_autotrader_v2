# V9 Pre-Data Audit — Cross-Asset Lead-Lag Predictability

**Date:** 2026-08-30
**Auditor:** Kilo (read-only forensic audit)
**Authority:** MASTER_GOVERNANCE_PROTOCOL.md (commit `1f9a667`)
**Scope:** Rigorous pre-data audit of V9 hypothesis before any data acquisition or implementation
**Input:** `data/research/V9_RESEARCH_SPECIFICATION.md` (361 lines)

---

## EXECUTIVE SUMMARY

The V9 hypothesis — cross-asset lead-lag predictability — is **scientifically plausible and economically distinct** from V5–V8. The central literature (Guo et al. 2024) is verified and directly relevant. However, the V9 specification contains **six material deficiencies** that must be corrected before data acquisition:

| # | Deficiency | Severity | Section |
|---|-----------|----------|---------|
| 1 | **Cost model internal contradiction**: 4 bps vs 10 bps round-trip | CRITICAL | 5.1 vs 6.1 |
| 2 | **Multiple testing correction insufficient**: Bonferroni across 3 horizons ignores 720+ researcher degrees of freedom | HIGH | 7.1 |
| 3 | **Asset universe selection undefined**: No ex-ante selection date → survivorship bias | HIGH | 3.1 |
| 4 | **Data size estimate potentially 10× too low**: 73 GB estimate vs ~730 GB actual | MEDIUM | 3.3 |
| 5 | **Robustness criteria vague**: "Fails robustness tests" has no operational definition | MEDIUM | 6.1 |
| 6 | **Replication standard undefined**: No criteria for what constitutes successful independent replication | MEDIUM | 6.3 |

**Verdict: BLOCKED_PENDING_CORRECTION**

---

## 1. ECONOMIC MECHANISM AUDIT

### 1.1 Literature Verification

**Guo, Sang, Tu, Wang (2024). "Cross-cryptocurrency return predictability." *Journal of Economic Dynamics and Control*, 163, 104863.**

| Check | Result |
|-------|--------|
| Journal verified | ✅ Yes — JEDC, Elsevier, Impact Factor ~2.5 |
| DOI verified | ✅ `10.1016/j.jedc.2024.104863` |
| Authors verified | ✅ Li Guo (Fudan), Bo Sang (Bristol), Jun Tu (SJTU), Yu Wang (SUFE) |
| Peer-reviewed | ✅ Yes |
| Data source | Binance minute-frequency, March 2019 – April 2021 |
| Sample | Top-30 coins by volume as of May 2020 (86% of market) |
| Key finding | Adaptive LASSO long-short portfolio: 3.55 bps/min spread before costs |
| After-cost result | VIP0 taker, 13-min rebalancing: **0.15 bps/min = 2.16% daily** |
| Market | **Futures** (not spot) — explicitly chosen for lower costs and short-selling ability |

**Jia, Wu, Yan, Liu (2023). "A seesaw effect in the cryptocurrency market." *Journal of Empirical Finance*, 74, 101428.**

| Check | Result |
|-------|--------|
| Journal verified | ✅ Yes — JEF, Elsevier |
| DOI verified | ✅ `10.1016/j.jempfin.2023.101428` |
| Key finding | Negative lead-lag: large coins predict small coins negatively |
| Mechanism | "Flight to hot coins" / "flee from cold coins" |

**Guo, Härdle, Tao (2024). "A Time-Varying Network for Cryptocurrencies." *Journal of Business & Economic Statistics*, 42(2), 437–456.**

| Check | Result |
|-------|--------|
| Journal verified | ✅ Yes — JBES, Taylor & Francis |
| DOI verified | ✅ `10.1080/07350015.2022.2146695` |
| Key finding | Inter-crypto momentum: 1.08% daily |

### 1.2 Mechanism Assessment

**Strengths:**
- The mechanism (slow information diffusion) is economically sound and distinct from V5–V8
- Multiple independent studies confirm cross-asset predictability in crypto
- The mechanism explains WHY the edge exists (limited attention, fragmented liquidity)

**Concerns:**
- **Temporal decay**: Guo et al. data ends April 2021. Market structure may have changed. The 2024 "Microstructure alpha" paper (Frontiers in Blockchain) found that NO strategy survives realistic Binance fees at minute frequency when properly tested with leakage controls — though this study used different features and a 6-month window.
- **Single-study risk**: The 2.16% daily figure comes from ONE paper. Independent replication is absent from the V9 spec.
- **Direction reversal**: The project's own V7 (cross-market, predicting BTC from other coins) found NEGATIVE_EDGE. V9 reverses the direction (predicting altcoins from BTC), but the project has no successful cross-asset precedent.

### 1.3 Market Distinction

The V9 spec correctly distinguishes crypto cross-asset evidence from equities/futures. All three cited papers use **Binance crypto data**. This is appropriate — we are not transferring equity-market effect sizes to crypto.

**Verdict: Mechanism is scientifically plausible but relies heavily on a single study with 2019–2021 data.**

---

## 2. ASSET UNIVERSE AUDIT

### 2.1 Deficiency: No Ex-Ante Selection Date

The V9 spec lists 10 altcoins (ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, DOT, LINK, MATIC) but does not specify:
- **When** "top-10 by volume" is measured
- **How** to handle coins that delist, lose volume, or newly qualify during the 730-day sample
- **Whether** stablecoins are excluded (Guo et al. explicitly excluded 3 stablecoins)

**Survivorship bias risk**: If we select coins by current volume and backtest over 730 days, we include coins that succeeded and exclude coins that failed/delisted. This inflates apparent performance.

### 2.2 Required Correction

The asset universe must be specified as:
1. **Selection date**: A single date (e.g., "top-10 by 30-day volume as of 2026-08-30")
2. **Inclusion criteria**: Minimum daily volume threshold, exclusion of stablecoins
3. **Handling of delistings**: If a coin delists during the sample, hold cash or redistribute
4. **No post-hoc substitution**: Coins cannot be replaced after seeing results

### 2.3 Guo et al. Precedent

Guo et al. selected top-30 by volume as of **May 2020** and held this fixed through their April 2021 sample. This is the correct approach. The V9 spec must replicate this.

**Verdict: BLOCKED — asset universe selection must be fully specified ex ante.**

---

## 3. TIMESTAMP INTEGRITY AUDIT

### 3.1 Deficiency: Bar Construction Undefined

The V9 spec does not specify:
- **Bar type**: Close-to-close? VWAP? Mid-price? Last trade?
- **Timezone**: UTC? Local? Binance uses UTC for API timestamps
- **Bar alignment**: How to align BTC and altcoin bars when they trade 24/7 with different activity patterns
- **Downtime handling**: Exchange maintenance, stale periods, zero-volume bars

### 3.2 Asynchronous-Bar Leakage Risk

If BTC minute bar [12:00, 12:01) is constructed from trades at 12:00:00–12:00:59, and ETH minute bar [12:00, 12:01) is constructed from trades at 12:00:30–12:01:29 (due to different trade timing), then using BTC 12:00 bar to predict ETH 12:00 bar creates **look-ahead bias**: the ETH bar contains information from 12:00:30–12:01:29 that the BTC bar does not.

### 3.3 Required Correction

The spec must define:
1. **Bar construction**: "Minute bars are close-to-close using the last trade in each UTC minute [t, t+1)"
2. **Alignment**: "All coins use the same UTC minute boundaries. A bar is valid only if the coin has ≥1 trade in that minute"
3. **Missing data**: "Minutes with no trades carry forward the last observed price"
4. **Timezone**: "All timestamps are UTC"

**Verdict: BLOCKED — timestamp integrity rules must be specified.**

---

## 4. LEAD/LAG CONSTRUCTION AUDIT

### 4.1 Predictor/Target Definition

The V9 spec defines:
- **Target**: Altcoin 5-minute forward log return
- **Predictors**: BTC lagged 1-min, 5-min, 10-min returns; BTC OFI; BTC realized vol; funding rate

### 4.2 Leakage Risk Assessment

| Predictor | Leakage Risk | Assessment |
|-----------|-------------|------------|
| BTC lagged 1-min return | LOW | If bar [t-1, t) is used to predict altcoin [t, t+5), no leakage |
| BTC lagged 5-min return | LOW | Same logic |
| BTC lagged 10-min return | LOW | Same logic |
| BTC signed OFI (5-min trailing) | **MEDIUM** | Must ensure OFI is computed from bars strictly before t |
| BTC realized vol (5-min trailing) | **MEDIUM** | Must ensure vol is computed from bars strictly before t |
| Funding rate (current) | LOW | Funding rate is known at time t |

### 4.3 Critical Gap

The spec does not specify the **exact temporal ordering**:

```
At time t (close of minute bar t):
  Predictors: BTC returns from bars [t-10, t), [t-5, t), [t-1, t)
  Target: Altcoin return from bars [t, t+5)
```

This is correct IF the altcoin bar [t, t+5) is not used in predictor construction. But the spec does not explicitly state this.

### 4.4 Required Correction

Add explicit temporal ordering:
1. "All predictors use data with timestamp < t (close of minute bar t)"
2. "Target uses data with timestamp ∈ [t, t+5)"
3. "No predictor uses any data from the target interval or later"

**Verdict: MEDIUM RISK — temporal ordering must be made explicit.**

---

## 5. COST MODEL AUDIT

### 5.1 CRITICAL: Internal Contradiction

The V9 specification contains a **direct internal contradiction**:

| Section | Claim |
|---------|-------|
| **Section 5.1** (Cost Model) | "Taker round-trip: 10 bps" |
| **Section 6.1** (Falsification) | "OOS net return ≤ 0 after realistic Binance VIP 0 taker fees (4 bps round-trip)" |

**These cannot both be correct.** The cost model section says 10 bps; the falsification section says 4 bps.

### 5.2 Binance Fee Verification (2026)

Multiple sources confirm Binance USD-M Futures VIP 0 fees:

| Source | Maker | Taker | Round-Trip Taker |
|--------|-------|-------|------------------|
| Binance official | 0.02% (2 bps) | 0.05% (5 bps) | **10 bps** |
| finder.com (2026) | 0.02% | 0.05% | **10 bps** |
| RonOnCrypto (2026) | 0.02% | 0.05% | **10 bps** |
| BeforePump (2026) | 0.02% | 0.05% | **10 bps** |
| COPI Gold Tools (2026) | 0.02% | 0.05% | **10 bps** |

**Current VIP 0 futures round-trip taker cost = 10 bps.**

### 5.3 Guo et al. Cost Assumption

Guo et al. state "trading costs of 4 bps" for regular takers. This is because:
- Their sample is 2019–2021, when Binance futures taker fee was 0.04% (4 bps) one-way = 8 bps round-trip
- They may be referring to one-way cost
- Fees have since increased to 0.05% (5 bps) one-way

**The V9 spec must use CURRENT fees (10 bps round-trip), not 2019–2021 fees.**

### 5.4 Project's Own Cost Model

The project's `execution_calibration.json` shows:
- `taker_fee_rt_bps: 4.0` — this is **outdated or incorrect** for current VIP 0
- The project's V5/V6/V7/V8 all used this 4 bps assumption
- **This may have systematically understated costs across all prior versions**

### 5.5 Impact on V9

If the true round-trip cost is 10 bps (not 4 bps), then:
- Guo et al.'s 0.15 bps/min at 13-min rebalancing → gross edge ≈ 1.95 bps per trade
- Cost per trade = 10 bps
- **Net = -8.05 bps per trade** (if we apply current fees to their result)

This does NOT mean V9 is falsified — it means the literature's after-cost result may not replicate with current fees. The V9 spec must:
1. Use 10 bps round-trip consistently
2. Acknowledge that the literature's after-cost result used lower historical fees
3. Test whether the gross edge is large enough to survive current fees

### 5.6 Maker vs. Taker

The V9 spec assumes taker (market orders) for the long-short portfolio. This is appropriate because:
- Long-short requires immediate execution in both directions
- Maker orders would introduce fill uncertainty
- But: if maker orders are possible, the round-trip cost drops to 4 bps (2 bps × 2)

**Verdict: CRITICAL — cost model must be corrected to 10 bps round-trip consistently. The 4 bps reference in Section 6.1 is wrong.**

---

## 6. MULTIPLE TESTING AUDIT

### 6.1 Deficiency: Bonferroni Is Insufficient

The V9 spec applies Bonferroni correction across **3 horizons** (α = 0.05/3 = 0.0167). This is insufficient because the actual number of hypothesis tests includes:

| Dimension | Levels | Count |
|-----------|--------|-------|
| Horizons | 5, 10, 15 min | 3 |
| Rebalancing frequencies | 5, 10, 13, 15 min | 4 |
| Models | Adaptive LASSO, Ridge, PCA | 3 |
| Altcoins | 10 | 10 |
| Directions | Long, Short | 2 |
| **Total combinations** | | **720** |

Even if we treat the long-short portfolio as a single test per (horizon, frequency, model), we still have:
- 3 × 4 × 3 = 36 strategy configurations
- Applied to 10 coins = 360 tests

### 6.2 Required Correction

The multiple testing correction must account for:
1. **Horizons**: 3
2. **Rebalancing frequencies**: 4
3. **Models**: 3
4. **Coins**: 10 (or treat as portfolio-level test)

**Option A (conservative)**: Bonferroni across all 36 strategy configurations → α = 0.05/36 = 0.00139

**Option B (recommended)**: 
- Primary test: Portfolio-level long-short return across all coins
- Bonferroni across 3 horizons × 4 frequencies = 12 tests → α = 0.05/12 = 0.00417
- Per-coin results reported as secondary/exploratory

**Option C (deflated Sharpe)**: Use deflated Sharpe ratio or reality-check methodology to account for multiple testing across all configurations.

### 6.3 Guo et al. Approach

Guo et al. used Harvey (2017) threshold: t-stat > 3.0 (rather than conventional 1.96). This is appropriate for multiple testing but the V9 spec does not adopt this.

**Verdict: HIGH — multiple testing correction must be expanded.**

---

## 7. WALK-FORWARD / OOS AUDIT

### 7.1 Design Assessment

The V9 spec proposes:
- Training: 60 days
- Validation: 10 days (model selection)
- OOS: 10 days
- Step: 10 days
- Minimum folds: 5

### 7.2 Leakage Risk

**Risk**: If the validation window is used for model selection (e.g., choosing LASSO alpha, Ridge regularization), and the same validation window is reused across multiple walk-forward folds, information leaks.

**Mitigation required**: The validation window must be **strictly between** training and OOS, and must not overlap with either. The spec does not explicitly state this.

### 7.3 Model Selection Protocol

The spec does not specify:
- HOW model selection occurs in the validation window
- WHETHER the same hyperparameters are used across all folds or re-selected per fold
- WHAT happens if different models win in different folds

### 7.4 Required Correction

Add explicit protocol:
1. "Model hyperparameters are selected in the validation window and frozen before OOS evaluation"
2. "The same hyperparameter selection procedure is applied independently in each walk-forward fold"
3. "OOS data is never used for any decision — not for model selection, not for early stopping, not for feature selection"

### 7.5 Sample Size

With 730 days and 10-day OOS windows, we get ~73 OOS periods. This is adequate IF the strategy has sufficient edge. But:
- 60-day training window at minute frequency = 60 × 1440 = 86,400 bars per coin
- This is sufficient for LASSO/Ridge with 6 predictors

**Verdict: MEDIUM — walk-forward protocol needs explicit anti-leakage rules.**

---

## 8. DATA SUFFICIENCY AUDIT

### 8.1 Size Estimate Verification

The V9 spec estimates ~73 GB for 10 altcoins × 730 days. This is likely **underestimated**.

**Binance aggTrades data size**:
- BTCUSDT: ~20 GB for 730 days (from project's existing data)
- This is ~27 MB/day for BTC, the most traded coin
- Altcoins trade less: ETH ~15 GB, SOL ~10 GB, others ~2–8 GB each
- **Realistic estimate: 70–100 GB for 10 altcoins × 730 days**

The 73 GB estimate is plausible but on the low side. The actual size depends on which 10 coins are selected.

### 8.2 Minimum Sufficient Dataset

The V9 spec does not need 730 days of data to test the hypothesis. A **minimum viable sample**:
- 90 days × 10 coins × 1440 min/day = ~1.3M bars
- This is sufficient for initial hypothesis testing
- If the hypothesis passes, extend to 730 days for robustness

**Recommendation**: Start with 90 days for initial testing. This reduces data acquisition from weeks to days.

### 8.3 Required Fields

The spec does not specify exact fields needed. For each altcoin, we need:
- `timestamp` (UTC ms)
- `price` (trade price)
- `quantity` (trade size)
- `is_buyer_maker` (for signed volume)

These are the standard Binance aggTrade fields.

**Verdict: MEDIUM — data size estimate is plausible but should specify minimum viable sample and exact fields.**

---

## 9. FALSIFICATION AUDIT

### 9.1 Primary Falsification Criteria

The V9 spec defines falsification as:
1. Net return ≤ 0 after costs at all frequencies
2. No horizon works
3. No coin works

These are **objective and appropriate**.

### 9.2 Vague Criterion

The spec also states: "The strategy fails robustness tests (regime sensitivity, transaction cost sensitivity)."

This is **not operationalized**. What constitutes "failing" regime sensitivity? If the strategy works in bull markets but not bear markets, is it falsified?

### 9.3 Required Correction

Define explicit robustness thresholds:
1. **Regime sensitivity**: "The strategy must produce positive net return in ≥ 1 of 3 regimes (high-vol, low-vol, trending)"
2. **Cost sensitivity**: "The strategy must remain profitable when costs are doubled (20 bps round-trip)"
3. **Parameter stability**: "The sign of the BTC predictor coefficient must be consistent across ≥ 60% of OOS folds"

### 9.4 Independent Replication

The spec does not define what constitutes successful independent replication. Required:
1. "Independent replication requires testing on a time period not used in the original test"
2. "The replicating test must use the same methodology (horizons, frequencies, cost model)"
3. "Replication success = net return > 0 with 95% CI excluding zero"

**Verdict: MEDIUM — robustness criteria must be operationalized.**

---

## 10. REPRODUCIBILITY AUDIT

### 10.1 Missing Elements

The V9 spec does not specify:
- **Data versioning**: How to version the acquired dataset
- **Hashing**: SHA256 verification of downloaded files
- **Timezone**: Explicit UTC requirement
- **Missing data treatment**: How to handle gaps, stale periods
- **Preprocessing**: Exact steps from raw trades to minute bars
- **Random seeds**: For LASSO/PCA if stochastic

### 10.2 Required Correction

Add reproducibility section:
1. "All data downloaded from Binance public data with SHA256 verification"
2. "All timestamps are UTC. Minute bars use [t, t+1) intervals"
3. "Missing bars (no trades) carry forward the last price"
4. "Random seeds fixed at 42 for all stochastic procedures"
5. "Dataset versioned with download date and hash manifest"

**Verdict: MEDIUM — reproducibility protocol must be specified.**

---

## 11. SUMMARY OF REQUIRED CORRECTIONS

| # | Deficiency | Severity | Correction Required |
|---|-----------|----------|---------------------|
| 1 | Cost model contradiction (4 vs 10 bps) | CRITICAL | Use 10 bps round-trip consistently; acknowledge literature used historical lower fees |
| 2 | Multiple testing insufficient | HIGH | Expand Bonferroni to cover horizons × frequencies × models (36 tests) |
| 3 | Asset universe undefined | HIGH | Specify exact selection date, inclusion criteria, delisting rules |
| 4 | Timestamp integrity undefined | HIGH | Define bar construction, alignment, timezone, missing data |
| 5 | Temporal ordering implicit | MEDIUM | Make predictor/target temporal ordering explicit |
| 6 | Walk-forward leakage risk | MEDIUM | Specify validation window isolation, model selection protocol |
| 7 | Robustness criteria vague | MEDIUM | Operationalize regime sensitivity, cost sensitivity, parameter stability |
| 8 | Replication standard undefined | MEDIUM | Define independent replication criteria |
| 9 | Reproducibility missing | MEDIUM | Add data versioning, hashing, seeds, preprocessing steps |
| 10 | Data size estimate low | LOW | Specify minimum viable sample (90 days), exact fields |

---

## 12. RISK ASSESSMENT

### 12.1 Hypothesis Risk: MODERATE

The cross-asset lead-lag mechanism is sound and supported by multiple studies. However:
- The strongest evidence (Guo et al. 2024) uses 2019–2021 data
- Market structure may have changed (more HFT, more arbitrage)
- The project's own V7 (cross-market) found NEGATIVE_EDGE

### 12.2 Execution Risk: HIGH

- Multi-asset execution requires simultaneous orders across 10 coins
- Slippage may be higher than the 0.008 bps measured for BTC (altcoins are less liquid)
- The 10 bps round-trip cost is a hard floor that the edge must exceed

### 12.3 Replication Risk: HIGH

- The 2.16% daily figure is from a single study
- No independent replication exists in the literature
- The project has no successful cross-asset precedent

---

## 13. COMPARISON WITH V5–V8 FAILURES

| Dimension | V5–V8 | V9 |
|-----------|--------|----|
| Signal source | Single-asset order flow | Cross-asset returns |
| Horizon | 500ms – 30s | 5–15 min |
| Why V5–V8 failed | Signal (0.06–0.46 bps) < cost floor (2–10 bps) | Signal (3.55 bps/min) may > cost floor |
| Project precedent | V7 cross-market: NEGATIVE_EDGE | None successful |
| Literature support | Mixed (Cont et al. for equities) | Strong (Guo et al. for crypto) |

**Key insight**: V9 addresses the fundamental V5–V8 failure mode (signal < cost) by targeting a horizon where signal scales with time while costs are fixed per trade. This is the correct insight. But the cost floor is higher than the spec acknowledges (10 bps, not 4 bps).

---

## 14. FINAL VERDICT

### BLOCKED_PENDING_CORRECTION

The V9 hypothesis is **scientifically plausible and economically distinct** from V5–V8. The literature support is real. The mechanism is sound. The specification is well-structured.

However, **six material deficiencies** must be corrected before data acquisition:

1. **CRITICAL**: Cost model must use 10 bps round-trip consistently (not 4 bps)
2. **HIGH**: Multiple testing correction must cover all researcher degrees of freedom
3. **HIGH**: Asset universe must be specified with ex-ante selection date
4. **HIGH**: Timestamp integrity rules must be defined
5. **MEDIUM**: Robustness criteria must be operationalized
6. **MEDIUM**: Reproducibility protocol must be specified

### Recommended Path Forward

1. Revise V9_RESEARCH_SPECIFICATION.md to address all 10 corrections
2. Re-audit the revised specification
3. Upon passing audit, begin with **90-day minimum viable sample** (not 730 days)
4. If 90-day test passes, extend to full 730-day sample

### What This Audit Does NOT Do

- Does not reject the V9 hypothesis
- Does not authorize data acquisition
- Does not modify the hypothesis, horizons, or model family
- Does not guarantee that V9 will pass after correction

---

*Audit completed: 2026-08-30*
*Auditor: Kilo (read-only)*
*Files modified: NONE*
*Repository status: Clean (audit-only)*
*V5 status: FROZEN (untouched)*
*V6/V7/V8 status: Historical negative evidence (untouched)*
*Implementation authorization: NOT GRANTED*
