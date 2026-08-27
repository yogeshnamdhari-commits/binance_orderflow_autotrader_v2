# LIQUIDATION DATA AUDIT

**Date:** 2026-08-26
**Objective:** Audit availability of liquidation flow data

---

## DATA AVAILABILITY

| Source | Available | Resolution | Time Range | Causal? |
|---|---|---|---|---|
| Binance liquidations | NO | — | — | — |
| Binance auto-deleverage | NO | — | — | — |
| Third-party (CoinGlass) | NO | — | — | — |
| Third-party (Laevitas) | NO | — | — | — |

---

## RESEARCH BASIS

### Liquidation Flow and Price Impact
- **Brunnermeier, Pedersen (2005)** "Predatory Trading" — liquidation cascades
- **Antoniou, Tarashev, Tsomidis (2023)** "Large Crypto Trades and Liquidations" — liquidation impact
- **Fishe, Robe (2023)** "Forced Liquidation in Crypto Markets" — liquidation clustering

### Mechanism
Liquidations create forced buying/selling that:
1. Moves price in direction of liquidation
2. Can trigger cascading liquidations
3. Creates short-term price dislocations that revert

---

## DATA QUALITY GATE

**FAIL:** No reliable historical liquidation data available.
- Binance does not provide historical liquidation data via free API
- Third-party providers require paid subscriptions
- Timestamp reliability is questionable
- Survivorship bias (only reported liquidations)

---

## CLASSIFICATION

**D = DATA UNAVAILABLE / UNTESTABLE**

Liquidation flow cannot be tested with available data.

---

**END OF LIQUIDATION DATA AUDIT**
