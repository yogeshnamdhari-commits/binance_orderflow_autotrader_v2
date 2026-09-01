# V10 execution model — queue, fill, adverse selection, economics

## Status

Research-only. This document does **not** authorize live trading.

## Model chain

1. **Queue position:** observable displayed depth is treated as queue-ahead information, not exact order-level FIFO rank.
2. **Fill probability:** estimate both empirical queue-conditioned fill rates and censored fill-time probabilities.
3. **Adverse selection:** measure the signed post-fill mid-price markout conditional on an actual fill.
4. **Passive-order economics:** combine calibrated fill probability with spread capture, fee/rebate, adverse selection, inventory, exit and cancellation costs.
5. **Walk-forward OOS:** fit calibration only on chronological training data; evaluate on later data separated by an embargo.
6. **Deployment gate:** no implementation/live trading unless the complete OOS economic result survives the predefined statistical and cost gates.

## Why survival analysis is included

Orders that do not fill before the evaluation horizon are right-censored observations. Treating every censored order as a binary zero-time outcome discards information about the time-to-fill process. `app/v10_fill_survival.py` therefore provides a Kaplan–Meier estimator of the fill-time distribution. This is deliberately a transparent non-parametric baseline before considering higher-capacity models.

The literature supports modelling limit-order execution as a queueing/survival problem rather than assuming a deterministic fill from displayed depth. Huang, Lehalle and Rosenbaum's queue-reactive model treats order-book dynamics as state-dependent queues; Cont, Stoikov and Talreja derive execution probabilities from a stochastic order-book model; Arroyo et al. formulate fill-time prediction explicitly as survival analysis. The implementation here is intentionally simpler and must be validated on the captured Binance event stream before it is used for decisions.

## Queue-position limitation

Binance market-by-price depth does not expose individual order identities. Consequently, exact FIFO rank cannot be reconstructed from aggregate depth alone. The implementation must therefore report uncertainty/bounds rather than manufacture exact queue rank. Anonymous cancellations are especially important because they can change the amount of queue ahead without revealing whose order was cancelled.

## Minimum empirical evidence before strategy use

- real Binance depth + trade + book-ticker capture;
- deterministic event ordering and gap checks;
- enough independent chronological periods to support walk-forward testing;
- train-only fill calibration;
- out-of-sample Brier/calibration assessment;
- conditional adverse-selection distribution, not only its mean;
- net economics after measured fees/rebates and realistic exit/cancellation costs;
- robustness to cost assumptions and market regimes;
- no parameter changes after inspecting the final OOS result.

## References

- Cont, R., Stoikov, S., Talreja, R. (2010), *A Stochastic Model for Order Book Dynamics*, Operations Research 58(3), 549–563.
- Huang, W., Lehalle, C.-A., Rosenbaum, M. (2015), *Simulating and Analyzing Order Book Data: The Queue-Reactive Model*, Journal of the American Statistical Association 110(509), 107–122.
- Arroyo, A., Cartea, A., Moreno-Pino, F., Zohren, S. (2023), *Deep Attentive Survival Analysis in Limit Order Books: Estimating Fill Probabilities with Convolutional-Transformers*.
- Maglaras, C., Moallemi, C. C., Wang, M. (2021), *A Deep Learning Approach to Estimating Fill Probabilities in a Limit Order Book*.
- Fabre, T., Ragel, V. (2023), *Tackling the Problem of State Dependent Execution Probability: Empirical Evidence and Order Placement*.
