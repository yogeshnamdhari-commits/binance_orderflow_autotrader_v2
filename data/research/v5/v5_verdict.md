# V5 verdict

- measured gate (1000 notional): 4.6658 bps
- verdict: **CONDITIONAL PASS**

## OOS scoreboard (h=500ms)
| metric | value |
|---|---|
| oos_rows | 3889 |
| gross_dir_n | 3889 |
| executed_rows | 0 |
| no_trade_rows | 3889 |
| gross_expectancy_bps | 0.06407983716249906 |
| gated_expectancy_bps | 0.0 |
| pf | 0.0 |
| sharpe | 0.0 |
| max_drawdown_bps | 0.0 |
| net_trail_n | 0 |
| largest_session_share | 0.0 |
| LONG n | 0 |
| LONG net_bps | 0.0000 |
| SHORT n | 0 |
| SHORT net_bps | 0.0000 |

## Robustness cells
| cell | n | executed | net_bps | gross_bps |
| half:first | 1944 | 0 | 0.0000 | -0.0062 |
| half:second | 1945 | 0 | 0.0000 | 0.1346 |
| regime:high_impact | 1383 | 0 | 0.0000 | 0.0020 |
| regime:normal | 2506 | 0 | 0.0000 | 0.0983 |
| vol_tercile:hi | 140 | 0 | 0.0000 | 0.0467 |
| vol_tercile:lo | 3746 | 0 | 0.0000 | 0.0645 |
| vol_tercile:nan | 3 | 0 | 0.0000 | 0.3094 |

## Cost sensitivity (bps)
| gate | exp net bps | executed |
| gate_minus_1 | 0.0000 | 0 |
| gate_minus_half | 0.0000 | 0 |
| gate | 0.0000 | 0 |
| gate_plus_half | 0.0000 | 0 |
| gate_plus_1 | 0.0000 | 0 |
