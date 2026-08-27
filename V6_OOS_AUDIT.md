# V6 OOS AUDIT

**Date:** 2026-08-26
**Objective:** Document out-of-sample validation results for V6 features

---

## VALIDATION PROTOCOL

- **Split:** Chronological 60% train / 40% OOS
- **OOS sessions:** 9 sessions (212451-232919)
- **OOS events:** 21,881
- **Horizon:** 500ms
- **Correction:** Bonferroni (α = 0.05/7 = 0.00714)

---

## OOS RESULTS

| Feature | N | Gross (bps) | t-stat | p-value | 95% CI | Net Maker (bps) | Sessions + |
|---|---|---|---|---|---|---|---|
| absorption_ratio | 21,875 | 0.002 | 0.44 | 0.662 | [-0.053, 0.055] | -2.556 | 4/9 |
| vamp_deviation | 21,875 | 0.120 | 27.39 | <0.0001 | [0.072, 0.166] | -2.438 | 8/9 |
| resiliency | 21,830 | 0.003 | 1.71 | 0.087 | [-0.003, 0.010] | -2.555 | 4/9 |
| convexity | 21,875 | 0.001 | 0.19 | 0.848 | [-0.055, 0.055] | -2.557 | 4/9 |
| flow_persistence | 21,390 | -0.005 | -1.35 | 0.176 | [-0.043, 0.036] | -2.563 | 5/9 |
| spread_regime | 20,975 | 0.001 | 0.29 | 0.771 | [-0.058, 0.058] | -2.557 | 4/9 |
| flow_pressure | 21,875 | 0.002 | 0.44 | 0.662 | [-0.053, 0.055] | -2.556 | 4/9 |

---

## WALK-FORWARD VALIDATION (vamp_deviation)

| Split | Train Sessions | Test Sessions | N | Gross (bps) | Net Maker (bps) |
|---|---|---|---|---|---|
| 1 | 1-5 | 6-8 | 9,168 | 0.054 | -1.946 |
| 2 | 1-7 | 8-10 | 9,429 | 0.095 | -1.905 |
| 3 | 1-9 | 10-12 | 8,161 | 0.043 | -1.957 |
| 4 | 1-11 | 12-14 | 10,893 | 0.159 | -1.841 |

**All walk-forward splits have negative net edge.**

---

## PERMUTATION CONTROL

| Feature | Actual Gross | Permutation Mean | Incremental |
|---|---|---|---|
| vamp_deviation | 0.120 | -0.005 | +0.125 |
| absorption_ratio | 0.002 | 0.003 | -0.001 |
| resiliency | 0.003 | 0.000 | +0.003 |
| convexity | 0.001 | 0.001 | +0.000 |
| flow_persistence | -0.005 | 0.001 | -0.006 |
| spread_regime | 0.001 | 0.001 | +0.000 |
| flow_pressure | 0.002 | 0.003 | -0.001 |

Only vamp_deviation shows meaningful incremental information over permutation.

---

## SESSION-LEVEL STABILITY (vamp_deviation)

| Session | N | Gross (bps) | Net Maker (bps) |
|---|---|---|---|
| 212451 | 222 | 0.350 | -1.650 |
| 212752 | 955 | 0.000 | -2.000 |
| 213053 | 261 | 0.502 | -1.498 |
| 213354 | 783 | 0.043 | -1.957 |
| 213655 | 1472 | 0.160 | -1.840 |
| 213956 | 953 | 0.056 | -1.944 |
| 214257 | 1864 | 0.143 | -1.857 |
| 214558 | 1867 | 0.370 | -1.630 |
| 214859 | 579 | 0.464 | -1.536 |

**8/9 sessions have positive gross, but ALL have negative net.**

---

## STATISTICAL SIGNIFICANCE vs ECONOMIC SIGNIFICANCE

| Feature | Statistically Significant? | Economically Significant? |
|---|---|---|
| vamp_deviation | YES (p<0.0001) | NO (net = -2.438 bps) |
| absorption_ratio | NO | NO |
| resiliency | NO | NO |
| convexity | NO | NO |
| flow_persistence | NO | NO |
| spread_regime | NO | NO |
| flow_pressure | NO | NO |

**Key insight:** Statistical significance ≠ economic significance. vamp_deviation is statistically significant but economically meaningless.

---

## CONCLUSION

No V6 feature passes the economic gate. The best feature (vamp_deviation) has:
- Gross: 0.120 bps
- Net (maker): -2.438 bps
- Gap to break-even: 2.158 bps

The information gap cannot be closed by further feature engineering on existing BTCUSDT data.

---

**END OF V6 OOS AUDIT**
