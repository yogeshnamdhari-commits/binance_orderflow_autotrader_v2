"""V11 economic decomposition.

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
class V11EconomicDecomposition:
    """Economic decomposition of V11 strategy."""
    signal_edge_bps: float
    spread_capture_bps: float
    maker_rebate_bps: float
    taker_fee_bps: float
    slippage_bps: float
    adverse_selection_bps: float
    fill_probability: float
    net_ev_bps: float
    gross_ev_bps: float
    total_cost_bps: float


def decompose_economics(
    signal_edge_bps: float,
    spread_bps: float,
    execution_mode: str,
    fill_probability: float,
    maker_fee_bps: float = -0.02,
    taker_fee_bps: float = 0.04,
    adverse_selection_bps: float = 0.0,
    cancellation_cost_bps: float = 0.05,
    inventory_cost_bps: float = 0.2,
    exit_cost_bps: float = 0.3,
) -> V11EconomicDecomposition:
    """Decompose strategy economics into signal vs execution components.
    
    Args:
        signal_edge_bps: Predictive signal edge in bps
        spread_bps: Actual market spread in bps
        execution_mode: "passive", "aggressive", or "mid"
        fill_probability: Probability of fill
        maker_fee_bps: Maker fee/rebate
        taker_fee_bps: Taker fee
        adverse_selection_bps: Adverse selection cost
        cancellation_cost_bps: Cancellation cost
        inventory_cost_bps: Inventory cost
        exit_cost_bps: Exit cost
        
    Returns:
        Economic decomposition
    """
    if execution_mode == "passive":
        spread_capture = 0.0
        fees = maker_fee_bps
        slippage = 0.0
    elif execution_mode == "aggressive":
        spread_capture = -spread_bps  # Pay the spread
        fees = taker_fee_bps
        slippage = spread_bps / 2.0
    elif execution_mode == "mid":
        spread_capture = -spread_bps / 2.0  # Pay half spread
        fees = maker_fee_bps
        slippage = 0.0
    else:
        raise ValueError(f"Unknown execution mode: {execution_mode}")
    
    # Gross EV = signal edge + spread capture + fees
    gross_ev = signal_edge_bps + spread_capture + fees
    
    # Total costs = slippage + adverse selection + inventory + exit + cancellation
    total_cost = slippage + adverse_selection_bps + inventory_cost_bps + exit_cost_bps + cancellation_cost_bps
    
    # Net EV = fill_prob * (gross - variable costs) - fixed costs
    net_ev = fill_probability * (gross_ev - adverse_selection_bps - inventory_cost_bps - exit_cost_bps) - cancellation_cost_bps
    
    return V11EconomicDecomposition(
        signal_edge_bps=signal_edge_bps,
        spread_capture_bps=spread_capture,
        maker_rebate_bps=maker_fee_bps if execution_mode != "aggressive" else 0.0,
        taker_fee_bps=taker_fee_bps if execution_mode == "aggressive" else 0.0,
        slippage_bps=slippage,
        adverse_selection_bps=adverse_selection_bps,
        fill_probability=fill_probability,
        net_ev_bps=net_ev,
        gross_ev_bps=gross_ev,
        total_cost_bps=total_cost,
    )
