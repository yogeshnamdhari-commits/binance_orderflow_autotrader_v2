# Literature Review

## Category 1: Price Impact & Order Flow Imbalance

### Cont, Kukanov & Stoikov (2013) — "The Price Impact of Order Book Events"
- **Journal**: Journal of Financial Econometrics, Vol. 12(1), pp. 47-88
- **Key finding**: Price changes driven by order flow imbalance (OFI) with slope inversely proportional to depth: `ΔP = β × OFI, β = c/D`
- **Relevance**: Explains why raw OFI fails — signal is too small relative to cost
- **Limitation**: Static depth assumption; doesn't account for dynamic liquidity withdrawal

### Bouchaud et al. (2009) — "Fluctuations and Response of Financial Markets"
- **Key finding**: Order flow has complicated auto/cross-correlation structures that vanish after ~10s
- **Relevance**: Suggests longer horizons may capture more signal, but our data shows IC doesn't increase

## Category 2: Queue Imbalance & Price Prediction

### Gould & Bonart (2016) — "Queue Imbalance as a One-Tick-Ahead Price Predictor"
- **Journal**: Quantitative Finance
- **Key finding**: Queue imbalance (bid/ask depth ratio) predicts next mid-price movement; 50-60% improvement for large-tick stocks
- **Relevance**: Our implementation (EXP-012) used qi_l1 as predictor; IC=0.08, too weak
- **Limitation**: Focuses on large-tick stocks; crypto has different price dynamics

### Cao, O'Hara & Wang (2009) — "The Impact of Payment for Order Flow"
- **Key finding**: Queue imbalance at depth influences 5-min returns
- **Relevance**: Multi-level analysis showed no improvement

## Category 3: Crypto-Specific Microstructure

### Explainable Patterns in Cryptocurrency Microstructure (2025) — arXiv:2602.00776
- **Data**: Binance Futures BTC/ETH perps, 2022-2025
- **Key finding**: OFI, spread, and VWAP-to-mid dominate SHAP importance; wider spreads attenuate predictability
- **Relevance**: Confirmed spread-attenuation mechanism; tested in EXP-012
- **Limitation**: Uses 1s aggregation; we found similar results at 10s-30s

### High-frequency dynamics of Bitcoin futures (2025) — Journal of Banking & Finance
- **Key finding**: MDH over ITIH; volatility driven by information arrival
- **Relevance**: Suggests trade-sign signal is real (information-driven) but weak

### Crypto Liquidity Analysis (Kalena, 2026)
- **Key finding**: Order book half-life: seconds to minutes; depth regeneration speed critical; 82% of displayed depth replaced within 60s
- **Relevance**: Justified EXP-012 fragility features; liquidity is ephemeral on Binance
- **Limitation**: Fragility signal doesn't amplify the weak directional signal

## Category 4: Execution & Market Impact

### Almgren & Chriss (2001) — "Optimal Execution Trajectories"
- **Key finding**: Square-root law for market impact; optimal execution splits orders
- **Relevance**: Confirms 4.0 bps taker cost is binding

### Gatheral (2018) — "The Square Root Law and the Impact of Order Flow"
- **Key finding**: Impact ~ sqrt(volume/market_volume)
- **Relevance**: Larger trades have diminishing impact per unit

## Summary

The literature consistently identifies the **price impact / cost trade-off** as the binding constraint in HFT:

1. **Signal strength** (IC 0.05-0.15) is real but weak
2. **Execution cost** (4.0 bps taker) is fixed and large
3. **Maximum return** (3.54-4.60 bps) barely exceeds cost at best horizons
4. **No literature finding** suggests the cost-to-signal gap can be closed without:
   - Fee rebates (VIP tier)
   - L3 data (queue position)
   - Cross-exchange arbitrage
   - Funding rate capture
   - Different instruments (less liquid = higher impact)
