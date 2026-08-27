# V4 Maker Execution Report — Frozen V3 Signal Through the Fill Chain

## Verdict: FAIL

- net maker expectancy -0.6095 bps <= 0 after realistic maker costs

## Binding economic component

FILL RARITY IS THE BINDING COMPONENT: only 2.5% of posted touch-quotes fill within 5 s (median time-to-fill 4.2 s, deep queue ahead); adverse selection is NOT the driver (measured fills-conditional drag is negative). The ~97.5% of attempts that never fill each incur the predeclared cancel/reprice+latency drag.
| per-posted realized_move_bps (bps) | -0.002175 |
| per-posted executed_maker_taker_fees_bps (bps) | 0.06871 |
| per-posted nonfill_cancel_reprice_latency_drag_bps (bps) | 0.538584 |
| per-posted net_bps (bps) | -0.609468 |
| decision state counts | {'NO_TRADE': 946} |
| filled sub-sample | {'n': 24, 'net_mean_bps': -2.894049, 'move_mean_bps': -0.085716} |

## OOS maker economics (untouched slice, fills measured from the L2 stream)

| samples | 946 |
| posted_signals | 946 |
| entries_filled | 24 |
| fill_probability | 0.02537 |
| full_fill_probability | 1.0 |
| partial_fill_probability | 0.0 |
| median_time_to_fill_ms | 4214.5 |
| p95_time_to_fill_ms | 4998.0 |
| net_expectancy_bps | -0.609468 |
| profit_factor | 0.0 |
| sharpe | -48.105977480796156 |
| max_drawdown_bps | -576.0071844357874 |
| adverse_selection_mean_bps | 0.106989 |
| adverse_selection_median_bps | 0.0 |
| adverse_selection_p95_bps | 0.443942 |
| fill_conditional_drag_bps | -0.130199 |
| unconditional_gross_bps | 0.02321 |
| oos_periods | 12 |
| largest_session_net_share | 0.3145158966851944 |

## Verdict criteria

| net_expectancy_bps | -0.609468 |
| oos_periods | 12 |
| posted_signals | 946 |
| officials_ok | True |
| fill_supported | False |
| single_session_share | 0.3145158966851944 |
| dominance_ok | True |
| positive_session_fraction | 0.0 |
| robust | False |
| adverse_consumes_edge | False |

## Integrity

- frozen model: data/research/v3_model.json
- replay/feature/pred integrity failures: []
