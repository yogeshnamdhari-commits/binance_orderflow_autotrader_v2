# V9 Research Specification — Cross-Asset Lead-Lag Predictability

**Date:** 2026-08-30
**Version:** 2.0 (post-audit corrected)
**Status:** RESEARCH PHASE — Pre-registered specification (no implementation authorized)
**Authority:** MASTER_GOVERNANCE_PROTOCOL.md (commit `1f9a667`)
**Supersedes:** V9_RESEARCH_SPECIFICATION.md v1.0
**Preserved as negative evidence:** V5 (frozen), V6 (falsified), V7 (data insufficient), V8 (rejected), EXP-001 through EXP-018 (all rejected)

---

## 1. V9 HYPOTHESIS

### 1.1 Primary Hypothesis

**H1 (V9 Cross-Asset Lead-Lag):** The lagged returns of Bitcoin (BTC) predict the returns of altcoins at horizons of 5–15 minutes, and this predictability generates positive net expectancy after current Binance execution costs when traded as a long-short portfolio across altcoins.

**H0 (Null):** After accounting for current Binance execution costs, the expected net return of a cross-asset lead-lag strategy is ≤ 0.

### 1.2 Falsification Criterion (Deterministic)

V9 is **FALSIFIED** if ANY of the following hold in walk-forward OOS testing:

1. **Primary endpoint fails:** Net portfolio return ≤ 0 OR 95% CI includes zero OR HAC-robust t-stat ≤ 3.0
2. **Consistency fails:** Positive net return in < 60% of OOS folds
3. **Cost sensitivity fails:** Net return ≤ 0 when all costs are doubled (×2)
4. **Permutation control fails:** Strategy return ≤ 95th percentile of permuted-label null distribution

V9 **PASSES** if ALL of the following hold:

1. **Primary endpoint:** Net > 0, CI excludes zero, t > 3.0
2. **Consistency:** Positive in ≥ 60% of OOS folds
3. **Cost sensitivity:** Net > 0 at 2× costs
4. **Permutation control:** Return > 95th percentile of null

**No post-hoc threshold modification is permitted.**

---

## 2. ECONOMIC MECHANISM AND LITERATURE

### 2.1 Mechanism: Slow Information Diffusion Across Crypto Assets

The economic mechanism is **information spillover with limited attention**:

1. **BTC as information leader:** Bitcoin has the deepest liquidity, highest institutional coverage, and fastest price discovery. New information is impounded into BTC first.
2. **Gradual diffusion to altcoins:** Due to limited investor attention and fragmented liquidity, the same information is incorporated into altcoin prices with a lag of minutes.
3. **Exploitable predictability:** This lag creates a window where BTC returns predict altcoin returns, and a long-short portfolio can capture the spread.

This is fundamentally different from V5–V8, which all attempted to predict BTCUSDT from its own order flow at sub-second horizons. V9 exploits **cross-asset** predictability at **minute** horizons.

### 2.2 Literature Support

| Paper | Finding | Relevance to V9 |
|-------|---------|-----------------|
| **Guo, Sang, Tu, Wang (2024).** "Cross-cryptocurrency return predictability." *Journal of Economic Dynamics and Control*, 163, 104863. DOI: `10.1016/j.jedc.2024.104863` | Minute-frequency Binance data. BTC lagged returns predict all other coins. Adaptive LASSO long-short portfolio: 3.55 bps/min spread before costs. After VIP0 taker costs (4 bps, 2019-2021 rates) with 13-min rebalancing: **0.15 bps/min = 2.16% daily**. | **Direct evidence** that cross-asset predictability survives costs. Note: used historical lower fees. |
| **Jia, Wu, Yan, Liu (2023).** "A seesaw effect in the cryptocurrency market." *Journal of Empirical Finance*, 74, 101428. DOI: `10.1016/j.jempfin.2023.101428` | Negative lead-lag: large coins (BTC, ETH) negatively predict small coins. "Flight to hot coins" mechanism. Trading strategies yield significant profits. | Confirms cross-asset predictability with different mechanism. |
| **Guo, Härdle, Tao (2024).** "A Time-Varying Network for Cryptocurrencies." *Journal of Business & Economic Statistics*, 42(2), 437–456. DOI: `10.1080/07350015.2022.2146695` | Cross-predictability network. Inter-crypto momentum strategy earns **1.08% daily**. | Confirms economic significance. |
| **Easley, O'Hara, et al. (2024).** "Microstructure and Market Dynamics in Crypto Markets." SSRN 4814346. | BTC VPIN and Roll measures predict cross-market dynamics. AUC > 0.55 for volatility/sign predictions. | Supports BTC-as-leader mechanism. |
| **Ait-Sahalia, et al. (2026).** "Price Transmission from Bitcoin to Altcoins." *Asia-Pacific Financial Markets*. DOI: `10.1007/s10690-026-09589-z` | Small-cap cryptos exhibit delayed responses to BTC. Granger causality from BTC to ALTs. Lag trading strategy outperforms buy-and-hold. | Direct evidence of exploitable lag. |

### 2.3 Why V9 Is Different from V5–V8

| Dimension | V5–V8 | V9 |
|-----------|--------|----|
| **Prediction target** | BTCUSDT from its own order flow | Altcoin returns from BTC returns |
| **Horizon** | 500ms – 30s | 5 – 15 minutes |
| **Signal source** | Single-asset microstructure | Cross-asset information spillover |
| **Economic mechanism** | Order flow predicts own price | Information diffuses across assets |
| **Why V5–V8 failed** | Signal (0.06–0.46 bps) < cost floor (4+ bps) | Signal (3.55 bps/min) may > cost floor |

---

## 3. ASSET UNIVERSE (EX-ANTE, FROZEN)

### 3.1 Selection Rule

| Criterion | Specification |
|-----------|---------------|
| Selection date | **2026-08-30** (frozen, cannot be altered) |
| Eligibility universe | All USDT-margined perpetual futures on Binance |
| Liquidity criterion | 30-day average daily volume ≥ $50M (as of selection date) |
| Listing-age criterion | Listed on Binance Futures for ≥ 90 days (as of selection date) |
| Data completeness criterion | ≥ 95% of expected minute bars available for 730 days preceding selection date |
| Quote currency | USDT |
| Exchange | Binance USD-M Futures |
| Stablecoins | Excluded (USDC, FDUSD, TUSD, USDP, etc.) |
| BTC | Excluded (used as predictor, not target) |

### 3.2 Selected Universe

| Rank | Coin | Tier | Liquidity Multiplier |
|------|------|------|---------------------|
| 1 | ETHUSDT | 1 | 2× |
| 2 | SOLUSDT | 1 | 2× |
| 3 | BNBUSDT | 1 | 2× |
| 4 | XRPUSDT | 2 | 3× |
| 5 | ADAUSDT | 2 | 3× |
| 6 | AVAXUSDT | 2 | 3× |
| 7 | DOTUSDT | 2 | 3× |
| 8 | LINKUSDT | 3 | 5× |
| 9 | MATICUSDT | 3 | 5× |
| 10 | DOGEUSDT | 3 | 5× |

### 3.3 Handling of Changes During Sample Period

- **Delisted coins:** Hold cash for that coin's weight (no substitution)
- **Newly listed coins:** NOT added (universe is frozen)
- **Volume drop below threshold:** Coin remains in universe
- **Stablecoin reclassification:** Excluded from that point forward

### 3.4 Survivorship Bias Mitigation

- Universe selected by volume at a SINGLE point in time (2026-08-30)
- Coins delisted before this date are NOT included (acknowledged limitation)
- **Delisting sensitivity test:** Re-run analysis excluding any coin that delisted during the sample period

---

## 4. TIMESTAMP AND DATA INTEGRITY

### 4.1 Timezone

All timestamps are **UTC**. Binance API returns UTC milliseconds. UTC does not observe daylight saving.

### 4.2 1-Minute Bar Construction

```
For each coin c and each UTC minute [t, t+1):
  - open[c,t] = price of first trade in [t, t+1)
  - high[c,t] = max price of all trades in [t, t+1)
  - low[c,t] = min price of all trades in [t, t+1)
  - close[c,t] = price of last trade in [t, t+1)
  - volume[c,t] = sum of all trade quantities in [t, t+1)
  - Bar is VALID iff ≥ 1 trade occurred in [t, t+1)
```

### 4.3 Return Convention

```
r[c,t] = ln(close[c,t] / close[c,t-1])
```

### 4.4 Predictor/Target Temporal Ordering

**Predictor information set at time t:**
```
PREDICTOR INFORMATION SET(t) = {close[BTC, τ] : τ ≤ t}
```

**Target return interval:**
```
TARGET RETURN INTERVAL(t) = {close[c, τ] : τ ∈ (t, t+5]}
```

**Mathematical proof of no look-ahead:**
```
max(PREDICTOR INFORMATION SET(t)) = t
min(TARGET RETURN INTERVAL(t)) = t + ε

Since t < t + ε, no predictor contains information from the target interval.
∴ No look-ahead leakage.
```

### 4.5 Asynchronous Asset Handling

- All coins use the SAME UTC minute boundaries
- A bar is valid only if the coin has ≥ 1 trade in that minute
- Predictors use only valid bars
- If > 5% of bars are invalid for a coin in a 60-day training window, that coin is excluded from that fold

### 4.6 Missing Data Treatment

- Minutes with no trades: bar marked invalid, NO forward fill
- Predictor computation skips invalid bars
- Stale prices (no new trades) are still valid bars
- Exchange outages: all coins have no bars; periods excluded from training and OOS

### 4.7 Data Arrival/Order Rules

- Binance aggTrades published in real-time via WebSocket
- Historical data from Binance Vision (data.binance.vision)
- Data sorted by trade time (not by reorderable trade IDs)

---

## 5. TARGET AND HORIZON

### 5.1 Target Variable

**Dependent variable:** Altcoin 5-minute forward log return

```
target[c,t] = ln(close[c, t+5] / close[c, t])
```

**Independent variables (pre-registered):**

| Predictor | Definition | Source |
|-----------|-----------|--------|
| BTC lagged 1-min return | r[BTC, t-1] | BTC minute bars |
| BTC lagged 5-min return | ln(close[BTC,t-1]/close[BTC,t-6]) | BTC minute bars |
| BTC lagged 10-min return | ln(close[BTC,t-1]/close[BTC,t-11]) | BTC minute bars |
| BTC signed OFI (5-min trailing) | Σ(buy_volume - sell_volume) / Σ(volume) over [t-6, t) | BTC minute bars |
| BTC realized volatility (5-min trailing) | Std(r[BTC, τ]) for τ ∈ [t-6, t) | BTC minute bars |
| Funding rate (current) | Most recent funding rate, pro-rated to 5-min | Binance API |

### 5.2 Prediction Horizon

**Pre-registered horizon set (fixed, no additions after seeing results):**

| Horizon ID | Duration | Rationale |
|------------|----------|-----------|
| H1 | 5 minutes | Shortest horizon where cross-asset diffusion is measurable |
| H2 | 10 minutes | Intermediate; literature shows predictability up to 10 min |
| H3 | 15 minutes | Upper bound; beyond this, diffusion is complete |

These three horizons are the **complete** evaluation set. No other horizons may be tested.

### 5.3 Rebalancing Frequency

**Pre-registered rebalancing set:** {5, 10, 13, 15} minutes

---

## 6. COST MODEL (EX-ANTE, FROZEN)

### 6.1 Cost Decomposition (Per Coin, Per Side, Per Rebalance)

| Component | Value | Source | Classification |
|-----------|-------|--------|----------------|
| A. Exchange taker fee | 10.0 bps round-trip | Binance official fee schedule (2026) | **Externally sourced** |
| B. Spread crossing | 0.016 bps | `execution_calibration.json` (BTC median) | **Measured** |
| C. Slippage | 0.008 bps | `execution_calibration.json` (BTC, $1K notional, p90) | **Measured** |
| D. Market impact | 0.1 bps | `execution_cost_model.json` | **Assumed** |
| E. Adverse selection | 0.5 bps | `execution_cost_model.json` / V6 calibration | **Estimated** |
| F. Latency | 0.05 bps | `execution_cost_model.json` | **Assumed** |
| **G. Total per-coin per-side** | **~10.57 bps** | Sum of A-F | **Computed** |

### 6.2 Altcoin Liquidity Multiplier

Costs above are measured on BTC (most liquid). Altcoins are less liquid:

| Tier | Coins | Multiplier | Per-coin Cost |
|------|-------|------------|---------------|
| Tier 1 | ETH, SOL, BNB | 2× | ~21 bps |
| Tier 2 | XRP, ADA, AVAX, DOT | 3× | ~32 bps |
| Tier 3 | LINK, MATIC, DOGE | 5× | ~53 bps |

### 6.3 Portfolio Cost Per Rebalance

The strategy holds ~4 active positions (long top quintile + short bottom quintile of 10 coins). At each rebalance:

**Base case (no liquidity multiplier):**
- Close 4 positions: 4 × 10.57 = 42.3 bps
- Open 4 new positions: 4 × 10.57 = 42.3 bps
- **Total: ~85 bps per rebalance**

**Conservative case (with liquidity multiplier):**
- Close: 2×21 + 2×32 = 106 bps (assuming 2 Tier-1 + 2 Tier-2 in top/bottom quintiles)
- Open: same = 106 bps
- **Total: ~212 bps per rebalance**

### 6.4 Breakeven Requirement

| Scenario | Cost per Rebalance | At 13-min Rebalancing |
|----------|-------------------|----------------------|
| Base case | 85 bps | >6.5 bps/min gross |
| Conservative case | 212 bps | >16.3 bps/min gross |

### 6.5 Justification for 10 bps Taker Fee

A trader opening a Binance USD-M Futures account today at VIP 0 pays:
- 0.05% taker fee on entry (5 bps on notional)
- 0.05% taker fee on exit (5 bps on notional)
- Total: 10 bps round-trip

This is the published fee schedule (verified 2026-08-30 from Binance official source). Using 4 bps would understate actual execution costs by 2.5× and is scientifically invalid.

**Note on V5-V8:** The project's `execution_calibration.json` uses `taker_fee_rt_bps: 4.0`, which corresponds to approximately VIP 4 tier or an old fee schedule. V9 uses the correct current VIP 0 rate. This is a methodological improvement.

### 6.6 Net-Return Equation

For each rebalancing interval:

```
E[NetReturn | signal] = E[CrossAssetPredictability | signal]
                        − PortfolioCostPerRebalance
                        − AdverseSelection
                        − UncertaintyBuffer
```

Where:
- PortfolioCostPerRebalance = 85 bps (base) or 212 bps (conservative)
- AdverseSelection = included in per-coin cost
- UncertaintyBuffer = 0 (costs are already conservative)

---

## 7. MULTIPLE TESTING

### 7.1 Hypothesis Family

| Dimension | Levels | Count |
|-----------|--------|-------|
| Horizons | 5, 10, 15 min | 3 |
| Rebalancing frequencies | 5, 10, 13, 15 min | 4 |
| Models | Adaptive LASSO, Ridge, PCA | 3 |
| Asset universe | 10 altcoins | 10 |
| Directions | Long leg, Short leg | 2 |
| **Total combinations** | | **720** |

### 7.2 Correction Procedure

**Primary endpoint (pre-registered):**
- Portfolio-level long-short return (equal-weighted across all 10 coins)
- This is a SINGLE test per (horizon, frequency, model) combination

**Multiple testing correction:**
- **Primary:** Bonferroni across 3 horizons × 4 frequencies = 12 tests → α = 0.05/12 = **0.00417**
- **Secondary (per-coin results):** Reported as exploratory, not confirmatory
- **Tertiary (model comparison):** Best model selected by validation performance; only the best model's OOS results are confirmatory

**Additional safeguards:**
- **Harvey (2017) threshold:** t-stat > 3.0 required for significance
- **Deflated Sharpe ratio:** Reported to account for multiple testing
- **Permutation control:** 1000 permuted-label null distributions

### 7.3 Why This Is Appropriate

1. The portfolio-level return is the economically meaningful quantity
2. Per-coin results are inherently correlated (same BTC signal drives all)
3. Testing 720 combinations with full Bonferroni would be overly conservative (α = 0.000069)
4. The Harvey (2017) threshold (t > 3.0) provides additional protection against false positives

---

## 8. LEAKAGE CONTROLS

### 8.1 Pre-Registered Controls

| Control | Implementation |
|---------|---------------|
| Chronological ordering | Preserved (no random shuffling) |
| Purge buffer | Minimum 10-minute gap between train and OOS |
| Embargo | No overlapping events between splits |
| Feature timestamps | All features use only data with timestamp < t |
| Label construction | Forward return measured from t to t+5 |
| Standardization | Mean/sd computed on train slice only |
| Walk-forward | Expanding or rolling window; aggregate across OOS folds |
| Multiple-testing correction | Bonferroni across 12 primary tests (α = 0.00417) |

### 8.2 Anti-Leakage Rules

1. **No future data:** Altcoin data from time t+k cannot enter the model at time t.
2. **No look-ahead in features:** BTC features at time t use only data with timestamp < t.
3. **No parameter fishing:** Model hyperparameters frozen before OOS evaluation.
4. **No horizon selection:** All 3 pre-registered horizons tested; no others permitted.
5. **No rebalancing selection:** All 4 pre-registered frequencies tested.
6. **No asset substitution:** Asset universe frozen at selection date.

---

## 9. OUT-OF-SAMPLE PROTOCOL

### 9.1 Walk-Forward Design

1. **Training window:** 60 days of minute data
2. **Validation window:** 10 days (hyperparameter tuning only, strictly between train and OOS)
3. **OOS test window:** 10 days
4. **Step forward:** 10 days, repeat
5. **Minimum OOS folds:** 5 (covering ≥ 50 days)

### 9.2 Model Selection Protocol

1. Model hyperparameters selected in the validation window
2. Hyperparameters frozen before OOS evaluation
3. Same hyperparameter selection procedure applied independently in each walk-forward fold
4. OOS data is NEVER used for any decision (not for model selection, early stopping, or feature selection)

### 9.3 Minimum OOS Requirements

| Requirement | Threshold |
|-------------|-----------|
| Independent OOS periods | ≥ 5 |
| Minimum OOS days | ≥ 50 |
| Minimum trades per direction | ≥ 200 |
| Minimum valid coins per fold | ≥ 8 of 10 |
| Market regimes covered | ≥ 2 (bull/bear or high-vol/low-vol) |

### 9.4 Robustness Tests (Operational)

| Test | Criterion | Threshold |
|------|-----------|-----------|
| Regime sensitivity | Net > 0 in ≥ 1 of 3 regimes | Required |
| Cost sensitivity | Net > 0 at 2× costs | Required |
| Parameter stability | BTC coefficient sign consistent in ≥ 60% of folds | Required |
| Permutation control | Return > 95th percentile of null | Required |
| Consistency | Positive in ≥ 60% of OOS folds | Required |

**Regime definitions:**
| Regime | Definition |
|--------|------------|
| High volatility | BTC realized vol > 75th percentile (trailing 24h) |
| Low volatility | BTC realized vol < 25th percentile (trailing 24h) |
| Trending | BTC 24h return > 1% absolute |

---

## 10. DATA REQUIREMENTS

### 10.1 Required Data

| Data | Source | Frequency | Status |
|------|--------|-----------|--------|
| BTCUSDT minute-level trades | Binance Vision | 1 minute | **Available** (730 days) |
| Altcoin minute-level trades (10 coins) | Binance Vision | 1 minute | **NOT AVAILABLE** — must be downloaded |
| BTC funding rates | Binance API | 8 hours | **Available** (2,214 records) |
| Altcoin funding rates | Binance API | 8 hours | **NOT AVAILABLE** — must be downloaded |

### 10.2 Data Specification

| Item | Specification |
|------|---------------|
| Source | Binance Vision: https://data.binance.vision/ |
| Endpoint | `data/vision/futures/um/daily/aggTrades/{SYMBOL}/` |
| Collection date | 2026-08-30 to 2026-09-30 (estimated) |
| Date range | 2024-08-30 to 2026-08-30 (730 days) |
| Schema | timestamp, price, quantity, is_buyer_maker |
| Timezone | UTC |
| Raw-data hashing | SHA-256 of each downloaded ZIP file |
| Dataset manifest | JSON file listing all files, hashes, download timestamps |

### 10.3 Minimum Viable Sample

For initial hypothesis testing, a **90-day sample** is sufficient:
- 90 days × 10 coins × 1440 min/day = ~1.3M bars
- If 90-day test passes, extend to 730 days for robustness

### 10.4 Required Fields

| Field | Type | Description |
|-------|------|-------------|
| timestamp | int64 | UTC milliseconds of trade |
| price | float | Trade price in USDT |
| quantity | float | Trade quantity in base asset |
| is_buyer_maker | bool | True if buyer is maker |

---

## 11. REPRODUCIBILITY

### 11.1 Code and Environment

| Item | Specification |
|------|---------------|
| Code version | Git commit hash recorded at time of analysis |
| Python version | 3.10+ |
| Key dependencies | pandas, numpy, scikit-learn, statsmodels |
| Random seeds | 42 (for all stochastic procedures) |
| Model initialization | Default scikit-learn initialization |

### 11.2 Preprocessing

| Step | Specification |
|------|---------------|
| Raw → Minute bars | Aggregate trades into 1-minute OHLCV bars (UTC) |
| Return computation | Log returns: ln(close[t]/close[t-1]) |
| Standardization | Z-score using training-window mean/std (computed per fold) |
| Missing data | Invalid bars (no trades) excluded; no forward fill |

### 11.3 Output Artifacts

1. Raw data manifest (JSON)
2. Processed minute bars (Parquet)
3. Model coefficients per fold (JSON)
4. OOS performance metrics (JSON)
5. Robustness test results (JSON)
6. Final report (Markdown)

---

## 12. FEASIBILITY ASSESSMENT

### 12.1 Strengths

1. **Strong literature support:** Guo et al. (2024) demonstrates 2.16% daily after VIP0 costs using exactly this mechanism.
2. **Different mechanism:** Cross-asset predictability is fundamentally different from V5–V8's single-asset order flow approach.
3. **Favorable signal-to-cost ratio:** At minute horizons, signal (3.55 bps/min) may exceed cost floor.
4. **Data obtainable:** Binance publishes minute-level aggTrades for all major altcoins.
5. **Existing infrastructure:** The project already has data pipelines, calibration frameworks, and walk-forward infrastructure that can be adapted.

### 12.2 Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Data acquisition takes weeks | Medium | Start with 90-day minimum viable sample |
| Cross-asset predictability has decayed since 2024 | Medium | Test on most recent 90 days first |
| Execution at minute frequency may have higher slippage | Medium | Use conservative liquidity multiplier |
| Strategy requires simultaneous multi-coin execution | Low | Start with paper trading |
| Current fees (10 bps) higher than literature's 4 bps | High | Acknowledge explicitly; test both scenarios |
| Regime changes may eliminate predictability | Medium | Test across bull/bear/sideways regimes |

### 12.3 Go/No-Go Decision Points

| Stage | Go Criteria | No-Go Action |
|-------|-------------|--------------|
| Data acquisition | ≥ 3 altcoins with 90 days minute data acquired | Reformulate with fewer coins |
| Exploratory analysis | In-sample predictability confirmed (R² > 0.01, t-stat > 3) | Falsify H1; document failure |
| Walk-forward OOS | Net return > 0 after costs at ≥ 1 frequency | Falsify H1; document failure |
| Robustness | Results hold across ≥ 2 regimes | Downgrade to "inconclusive" |

---

## 13. WHAT THIS SPECIFICATION DOES NOT DO

1. **Does not authorize implementation code.** This is a research specification only.
2. **Does not guarantee profitability.** The literature supports the hypothesis, but market conditions may have changed.
3. **Does not rescue V5–V8.** This is a genuinely new hypothesis with a different economic mechanism.
4. **Does not permit parameter fishing.** All parameters are pre-registered.
5. **Does not permit horizon/frequency selection after seeing results.** All horizons and frequencies are pre-registered.
6. **Does not permit post-hoc cost model alteration.** The cost model is frozen at 10 bps round-trip.

---

## 14. EXPECTED OUTCOMES

### 14.1 If V9 Succeeds

- A new deployable strategy based on cross-asset predictability
- Different risk profile from V5–V8 (minute-horizon, multi-asset, long-short)
- Foundation for further research (more altcoins, longer horizons, cross-exchange)

### 14.2 If V9 Fails

- Documented negative evidence for cross-asset lead-lag on current data
- Preservation as negative control alongside V5–V8
- Clear signal that the information set (even cross-asset) does not contain deployable edge on Binance

### 14.3 Either Outcome Is Valuable

The purpose is not to make V9 pass. The purpose is to determine whether the hypothesis survives rigorous testing.

---

*Specification pre-registered: 2026-08-30*
*Version: 2.0 (post-audit corrected)*
*Authority: MASTER_GOVERNANCE_PROTOCOL.md*
*V5–V8 status: Preserved as negative evidence. Do not modify.*
*Implementation authorization: NOT GRANTED — pending re-audit.*
