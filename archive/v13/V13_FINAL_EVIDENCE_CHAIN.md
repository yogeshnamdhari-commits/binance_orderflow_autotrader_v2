# V13 Final Evidence Chain

**Version:** V13-orderflow-persistence-2s  
**Symbol:** BTCUSDT (Binance USDT-M Perpetual)  
**Config hash:** `14dfaab9e88f47bf`  
**Status:** FAIL — production remains LOCKED (Rule 28)

---

## 1. Objective

Test whether a longer 2-second prediction horizon with order-flow-persistence features (signed trade imbalance, OFI persistence, book imbalance) produces **economically valuable** predictions — where V12 at 500 ms showed no statistical signal.

**Pre-registered hypothesis** (data/evidence/v13_hypothesis.json):
> Order-flow signed trade imbalance and order-book imbalance predict BTCUSDT 2s-ahead returns, where V12 showed no signal at 500ms.

---

## 2. Data Provenance (PASS)

| Phase | Session | Start (ns) | End (ns) | Events | Streams |
|-------|---------|-----------|----------|--------|---------|
| Calibration | `9484a12...` | 1788781920066176000 | 1788782160765070000 | 41,060 | depth@100ms + trade + bookTicker |
| Forward | `6270a46...` | 1788782253990306000 | 1788782494858190000 | 45,466 | depth@100ms + trade + bookTicker |

**Temporal separation verified:** Forward session starts AFTER calibration session ends. No data overlap. V12 forward data (f717fc...) is explicitly excluded.

All data captured directly from Binance public WebSocket + REST with SHA-256 checksums.

---

## 3. Model Calibration

**Frozen model:** `archive/v13/v13_frozen_model.joblib`  
**Checksum:** see `data/research/v13_proposal.json`

| Metric | V12 | V13 |
|--------|-----|-----|
| Val AUC | 0.5014 | **0.7202** |
| Test AUC | 0.2619 | **0.6362** |
| Train AUC | 0.7677 | 0.7150 |
| Calibration obs | 325 | 2,326 |

V13 achieves materially better statistical discrimination (AUC 0.72 vs 0.50). Train ≈ Val (no overfitting).

---

## 4. Independent Forward Test (FAIL)

**Result artifact:** `archive/v13/v13_forward_result.json`

| Metric | Value |
|--------|-------|
| Forward observations | 2,327 |
| Mean net EV | **-5.92 bps** |
| Gross EV | **-0.16 bps** |
| Total cost | 14.52 bps |
| 95% CI | [-6.01, -5.83] |
| p-value | 1.0 |

### Economic decomposition

```
signal_edge_bps = -0.14    (predicted return magnitude ~0)
gross_ev_bps = -0.16       (signal + funding, ≈ 0)
total_cost_bps = 14.52
net_ev_bps   = -5.92       (gross - costs, × confidence)
```

### Gate conditions

| Gate | Result |
|------|--------|
| sufficient_observations | PASS |
| net_ev_positive | **FAIL** (-5.92) |
| statistically_significant | **FAIL** |
| ci_excludes_zero | **FAIL** |
| effect_size_sufficient | PASS (|d|=2.69) |
| permutation_significant | **FAIL** |

---

## 5. Key Finding: Statistical ≠ Economic

V13 demonstrates a **critical distinction**:

- The model achieves Val AUC 0.72 — it **ranks** trades correctly (it can tell favorable from unfavorable setups).
- But the **magnitude** of expected returns is ~0 bps. The binned return calibration assigns near-zero returns to all probability bins.
- With 14.52 bps in execution costs (market taker orders on a 2s holding period), zero gross EV → deeply negative net EV.

**Root cause:** A 2-second holding period does not give order-flow persistence enough time to generate price movement that exceeds Binance's taker fees + slippage. The signal exists statistically but not economically.

This is NOT overfitting (train=AUC 0.72, val=0.72). It is NOT leakage. It is a genuine economic barrier: the cost of execution exceeds the informational value at this horizon.

---

## 6. Execution Costs (PASS — realistic)

| Component | Value (bps) |
|-----------|-------------|
| Taker fee | 5.0 |
| Slippage | 0.5 |
| Adverse selection | 0.5 |
| Latency | 0.1 |
| Exit (round-trip) | 5.0 |
| Spread | ~2.42 (measured) |
| **Total** | **14.52** |

---

## 7. Regime Robustness (FAIL)

| Regime | n | Mean net EV | Positive rate |
|--------|---|-------------|---------------|
| High spread | 1,238 | -6.71 bps | 0.24% |
| Low spread | 1,089 | -5.03 bps | 0.09% |
| High vol | 1,164 | -5.58 bps | 0.09% |
| Low vol | 1,163 | -6.26 bps | 0.26% |
| Early | 776 | -5.81 bps | 0.39% |
| Mid | 775 | -5.84 bps | 0.00% |
| Late | 776 | -6.11 bps | 0.13% |

0/6 regimes show positive net EV. Positive rate ≈ 0.1–0.4% across all regimes.

---

## 8. Statistical Robustness (FAIL)

- t = -129.9, p = 1.0
- Permutation test (10,000 reps): p = 1.0
- 95% CI [-6.01, -5.83] entirely below zero.

---

## 9. Funding

Real 8-hour Binance funding rates fetched via `/fapi/v1/fundingRate`. Mean rate: -1.64e-06 bps (negligible, correctly signed for shorts receiving negative-rate funding).

---

## 10. Summary

| Gate | Verdict |
|------|---------|
| Data provenance | PASS |
| Data integrity | PASS |
| No leakage | PASS |
| Model calibration | PASS (AUC improved) |
| Frozen artifact | PASS |
| Independent forward test | **FAIL** |
| Positive net EV | **FAIL** |
| Realistic execution costs | PASS |
| Statistical robustness | **FAIL** |
| Regime robustness | **FAIL** |
| Paper trading | BLOCKED |
| Testnet | NOT_STARTED |

**Overall: FAIL — Production remains LOCKED.**

The V13 hypothesis was partially validated (signal exists at 2s) but the economic value is structurally negative due to execution costs. The next experiment (V14) should target **cost reduction via passive maker/taker execution** to bring total costs below the signal's gross EV.
