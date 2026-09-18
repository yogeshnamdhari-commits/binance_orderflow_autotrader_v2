"""V13 research experiment — order-flow persistence at a 2-second horizon.

Hypothesis (pre-registered):
  Order-flow signed trade imbalance and order-book imbalance have predictive
  power for BTCUSDT returns at a 2-second horizon, where microstructure
  persistence effects (Cont & de Prado 2016; Bianchi et al. 2022) peak.
  V12 failed at 500 ms because the horizon was shorter than the persistence
  window; 2 s captures the carry-through of aggressive flow.

This is a CLEAN experiment: new config hash, new features, new frozen model.
V12 forward data is NOT reused for V13 calibration (Rule: no information flow
backwards).
"""
from __future__ import annotations
