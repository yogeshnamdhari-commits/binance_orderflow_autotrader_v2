# CROSS-MARKET DATA AUDIT

**Date:** 2026-08-26
**Objective:** Audit availability of cross-market price discovery data

---

## DATA AVAILABILITY

| Source | Available | Resolution | Time Range | Causal? |
|---|---|---|---|---|
| Binance BTCUSDT spot | YES | 100ms depth | 2026-08-18 | YES |
| Binance BTCUSDT perpetual | YES | 100ms depth | 2026-08-18 | YES |
| Binance BTCUSD perpetual | NO | — | — | — |
| Coinbase BTC spot | NO | — | — | — |
| Kraken BTC spot | NO | — | — | — |
| OKX BTC perpetual | NO | — | — | — |
| Bybit BTC perpetual | NO | — | — | — |
| CME BTC futures | NO | — | — | — |

---

## RESEARCH BASIS

### Price Discovery in Crypto Markets
- **Brandvoll, L (2021)** "Price Discovery and Efficiency in Bitcoin Markets" — leads/lag between spot and perp
- **Karkkainen (2022)** "Predicting Bitcoin Returns: Lead-Lag Relationships" — cross-market lead-lag
- **Kroeger, Sarkar (2017)** "The Law of One Price in Bitcoin" — cross-exchange price convergence

### Mechanism
Leading markets (e.g., spot) may predict perpetual returns due to:
1. Information arrival first in spot
2. Arbitrageurs transmit information to perp
3. Lead-lag of 100ms-5s expected

---

## DATA QUALITY GATE

**FAIL:** No cross-venue data available at high frequency.
- Binance is the only source with historical depth data
- Other exchanges require paid APIs for historical data
- Clock synchronization across venues is unreliable

---

## CLASSIFICATION

**D = DATA UNAVAILABLE / UNTESTABLE**

Cross-market price discovery cannot be tested with available data.

---

**END OF CROSS-MARKET DATA AUDIT**
