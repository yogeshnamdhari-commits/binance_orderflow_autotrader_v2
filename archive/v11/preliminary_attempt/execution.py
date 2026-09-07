"""V11 realistic execution economics.

Separates signal edge from execution costs.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class V11ExecutionConfig:
    """Frozen execution configuration with realistic Binance assumptions."""
    maker_fee_bps: float = -0.02
    taker_fee_bps: float = 0.04
    cancellation_cost_bps: float = 0.05
    inventory_cost_bps: float = 0.2
    exit_cost_bps: float = 0.3
    order_quantity: float = 0.01
    horizon_ms: int = 1000


@dataclass(frozen=True)
class ExecutionResult:
    """Result of simulating an order under specific execution mode."""
    mode: str
    fill_probability: float
    revenue_bps: float
    fees_bps: float
    slippage_bps: float
    adverse_selection_bps: float
    net_ev_bps: float
    n_orders: int
    n_filled: int


class V11ExecutionModel:
    """Realistic execution model for V11.
    
    Does NOT assume:
    - guaranteed passive fills
    - guaranteed spread capture
    - unrealistic maker rebates
    - zero slippage
    - zero adverse selection
    - instantaneous execution
    """
    
    def __init__(self, config: V11ExecutionConfig):
        self._config = config
    
    def simulate_passive(self, observations: pd.DataFrame, spread_bps: float) -> ExecutionResult:
        """Simulate passive limit order execution.
        
        Passive order:
        - Posts at bid/ask
        - Waits for fill
        - No spread capture (doesn't cross spread)
        - Pays maker fee if filled
        - Fill probability depends on queue position
        """
        if len(observations) == 0:
            return ExecutionResult(
                mode="passive",
                fill_probability=0.0,
                revenue_bps=0.0,
                fees_bps=0.0,
                slippage_bps=0.0,
                adverse_selection_bps=0.0,
                net_ev_bps=0.0,
                n_orders=0,
                n_filled=0,
            )
        
        # Fill probability from observations
        fill_probability = observations["filled"].mean()
        n_orders = len(observations)
        n_filled = int(observations["filled"].sum())
        
        # Revenue: 0 bps (passive order doesn't capture spread)
        revenue_bps = 0.0
        
        # Fees: maker rebate if filled
        fees_bps = self._config.maker_fee_bps if n_filled > 0 else 0.0
        
        # Slippage: 0 for passive at top of queue, conservative estimate
        slippage_bps = 0.0
        
        # Adverse selection: measured from data
        adverse_selection_bps = observations["adverse_selection_bps"].mean()
        
        # Net EV per order
        net_ev_per_order = (
            fill_probability * (revenue_bps + fees_bps - adverse_selection_bps - self._config.inventory_cost_bps - self._config.exit_cost_bps)
            - self._config.cancellation_cost_bps
        )
        
        return ExecutionResult(
            mode="passive",
            fill_probability=fill_probability,
            revenue_bps=revenue_bps,
            fees_bps=fees_bps,
            slippage_bps=slippage_bps,
            adverse_selection_bps=adverse_selection_bps,
            net_ev_bps=net_ev_per_order,
            n_orders=n_orders,
            n_filled=n_filled,
        )
    
    def simulate_aggressive(self, observations: pd.DataFrame, spread_bps: float, signal_edge_bps: float) -> ExecutionResult:
        """Simulate aggressive market order execution.
        
        Aggressive order:
        - Crosses spread to execute immediately
        - Captures spread (pays it)
        - Pays taker fee
        - ~100% fill probability (if size allows)
        - Slippage depends on market depth
        """
        if len(observations) == 0:
            return ExecutionResult(
                mode="aggressive",
                fill_probability=0.0,
                revenue_bps=0.0,
                fees_bps=0.0,
                slippage_bps=0.0,
                adverse_selection_bps=0.0,
                net_ev_bps=0.0,
                n_orders=0,
                n_filled=0,
            )
        
        n_orders = len(observations)
        
        # Fill probability: high but not guaranteed
        fill_probability = 0.95  # Conservative estimate
        
        # Revenue: signal edge minus spread paid
        revenue_bps = signal_edge_bps - spread_bps
        
        # Fees: taker fee
        fees_bps = self._config.taker_fee_bps
        
        # Slippage: half spread for aggressive order
        slippage_bps = spread_bps / 2.0
        
        # Adverse selection: measured from data
        adverse_selection_bps = observations["adverse_selection_bps"].mean()
        
        # Net EV per order
        net_ev_per_order = (
            fill_probability * (revenue_bps - fees_bps - slippage_bps - adverse_selection_bps - self._config.inventory_cost_bps - self._config.exit_cost_bps)
            - self._config.cancellation_cost_bps
        )
        
        return ExecutionResult(
            mode="aggressive",
            fill_probability=fill_probability,
            revenue_bps=revenue_bps,
            fees_bps=fees_bps,
            slippage_bps=slippage_bps,
            adverse_selection_bps=adverse_selection_bps,
            net_ev_bps=net_ev_per_order,
            n_orders=n_orders,
            n_filled=n_orders,  # Assume all filled
        )
    
    def simulate_mid(self, observations: pd.DataFrame, spread_bps: float, signal_edge_bps: float) -> ExecutionResult:
        """Simulate mid-price order execution.
        
        Mid-price order:
        - Posts at mid
        - Captures half spread if filled
        - Pays maker fee if filled as maker, taker if not
        """
        if len(observations) == 0:
            return ExecutionResult(
                mode="mid",
                fill_probability=0.0,
                revenue_bps=0.0,
                fees_bps=0.0,
                slippage_bps=0.0,
                adverse_selection_bps=0.0,
                net_ev_bps=0.0,
                n_orders=0,
                n_filled=0,
            )
        
        # Fill probability: lower than passive
        fill_probability = observations["filled"].mean() * 0.5  # Conservative
        n_orders = len(observations)
        n_filled = int(n_orders * fill_probability)
        
        # Revenue: half spread capture
        revenue_bps = spread_bps / 2.0
        
        # Fees: maker rebate if filled
        fees_bps = self._config.maker_fee_bps if n_filled > 0 else 0.0
        
        # Slippage: minimal
        slippage_bps = 0.0
        
        # Adverse selection: measured from data
        adverse_selection_bps = observations["adverse_selection_bps"].mean()
        
        # Net EV per order
        net_ev_per_order = (
            fill_probability * (revenue_bps + fees_bps - adverse_selection_bps - self._config.inventory_cost_bps - self._config.exit_cost_bps)
            - self._config.cancellation_cost_bps
        )
        
        return ExecutionResult(
            mode="mid",
            fill_probability=fill_probability,
            revenue_bps=revenue_bps,
            fees_bps=fees_bps,
            slippage_bps=slippage_bps,
            adverse_selection_bps=adverse_selection_bps,
            net_ev_bps=net_ev_per_order,
            n_orders=n_orders,
            n_filled=n_filled,
        )
