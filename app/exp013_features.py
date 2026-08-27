"""EXP-013: Two-Stage Event + Direction Prediction (5min Horizon)

Hypothesis: Predict (1) event occurrence (|future_60s_return| > cost) 
and (2) direction of that return, from pre-event book state features.

Architecture:
  Stage A: Event probability from trade features (730-day aggTrades)
  Stage B: Direction probability from book features (V4 sessions)

Trade only when:
  P(event) * P(direction) * E[|ret| | event] > all_in_cost + safety_margin

Cost model: 4.0146 bps taker, 2.0 bps maker (from data/live/cost_calibration.json)
"""

import numpy as np
import pandas as pd
import json
from pathlib import Path
from typing import Tuple, Dict, Any
from dataclasses import dataclass

COST_TAKER = 4.0146
COST_MAKER = 2.0


@dataclass
class StageAEventPrediction:
    """Stage A: Predict event occurrence from trade features."""
    horizon_ms: int = 60000
    cost_bps: float = COST_TAKER
    features: list = None
    model: Any = None
    
    def __post_init__(self):
        if self.features is None:
            self.features = [
                'trade_qty',
                'recent_ret_50',     # momentum over 50 trades
                'recent_vi_50',      # volume imbalance over 50 trades
                'recent_vol_50',     # volatility over 50 trades
                'buy_sign',          # trade direction
            ]


@dataclass
class StageBDirectionPrediction:
    """Stage B: Predict direction from book features."""
    horizon_ms: int = 60000
    cost_bps: float = COST_TAKER
    features: list = None
    model: Any = None
    
    def __post_init__(self):
        if self.features is None:
            self.features = [
                'qi_l1', 'mpd_bps', 'spread_bps', 'depth_slope_bps',
                'ofi_l1', 'ofi_norm_l1', 'bid_add_bps', 'bid_cancel_bps',
                'ask_add_bps', 'ask_cancel_bps', 'cancel_pressure',
                'log_depth1', 'log_depth5', 'tfi_500', 'signed_vol_500',
                'trade_rate', 'liq_depletion',
            ]


def compute_trade_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute trade-level features for Stage A.
    
    Features are computed using only past information (no look-ahead).
    """
    df = df.sort_values('transact_time').reset_index(drop=True)
    n = len(df)
    
    ts = df['transact_time'].values
    prices = df['price'].values
    log_p = np.log(prices)
    qty = df['quantity'].values
    is_bm = df['is_buyer_maker'].values
    buy_sign = np.where(is_bm, -1.0, 1.0)
    
    window = 50
    
    # Recent return (momentum)
    diff_log = np.zeros(n)
    diff_log[1:] = (log_p[1:] - log_p[:-1]) * 1e4
    recent_ret = np.zeros(n)
    for i in range(window, n):
        recent_ret[i] = (log_p[i] - log_p[i - window]) * 1e4
    
    # Recent volume imbalance
    signed_vol = buy_sign * qty
    recent_vi = np.zeros(n)
    for i in range(window, n):
        recent_vi[i] = signed_vol[i-window:i].sum()
    
    # Recent volatility
    recent_vol = np.zeros(n)
    abs_diff = np.abs(diff_log)
    for i in range(window, n):
        recent_vol[i] = abs_diff[i-window:i].std() if abs_diff[i-window:i].std() > 0 else 0
    
    df['recent_ret_50'] = recent_ret
    df['recent_vi_50'] = recent_vi
    df['recent_vol_50'] = recent_vol
    df['buy_sign'] = buy_sign
    
    return df


def compute_60s_forward_return(df: pd.DataFrame, horizon_ms: int = 60000) -> np.ndarray:
    """Compute forward return at horizon using vectorized search."""
    ts = df['transact_time'].values
    prices = df['price'].values
    n = len(df)
    
    ptr = np.searchsorted(ts, ts + horizon_ms, side='left')
    valid = ptr < n
    r = np.full(n, np.nan)
    r[valid] = (prices[ptr[valid]] - prices[valid]) / prices[valid] * 1e4
    
    return r


def extract_v4_features(rows: list, horizon_ms: int = 60000) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Extract book features from V4 session data.
    
    For each trade, finds the preceding depth event and computes
    forward return at horizon.
    
    Returns:
        X: Book feature matrix (preceding depth state)
        R: Forward returns (bps)
        S: Direction labels (+1/-1)
    """
    trades = sorted([r for r in rows if r.get('kind') == 'trade'], key=lambda r: r['ts_ms'])
    depths = sorted([r for r in rows if r.get('kind') == 'depth'], key=lambda r: r['ts_ms'])
    
    depth_ts = np.array([d['ts_ms'] for d in depths])
    trade_ts = np.array([t['ts_ms'] for t in trades])
    trade_mids = np.array([t['mid'] for t in trades])
    
    feat_names = StageBDirectionPrediction().features
    
    X, R, S = [], [], []
    for t in trades:
        t_ts = t['ts_ms']
        ptr = np.searchsorted(depth_ts, t_ts, side='right') - 1
        if ptr < 0:
            continue
        d = depths[ptr]
        
        future_idx = np.searchsorted(trade_ts, t_ts + horizon_ms, side='right')
        if future_idx < len(trades):
            ret = (trade_mids[future_idx] - t['mid']) / t['mid'] * 1e4
            if abs(ret) < 500:  # filter extreme outliers
                features = [float(d.get(f, 0.0)) if d.get(f) is not None else 0.0 for f in feat_names]
                X.append(features)
                R.append(ret)
                S.append(1 if ret > 0 else -1)
    
    return np.array(X), np.array(R), np.array(S)


def economic_gate(p_event: float, p_direction_correct: float, 
                  expected_return: float, cost_bps: float,
                  safety_margin: float = 0.5) -> Tuple[bool, float]:
    """Two-stage economic gate.
    
    Compute expected net return from two-stage prediction.
    
    Args:
        p_event: Probability of large move occurring
        p_direction_correct: Probability of correct direction prediction
        expected_return: Expected absolute return when event occurs
        cost_bps: Round-trip execution cost
        safety_margin: Additional bps safety margin
    
    Returns:
        (pass_gate, net_bps)
    """
    # EV = P(event) * [P(correct) * E[ret] + (1-P(correct)) * E[-ret] - cost]
    #    = P(event) * [(2*P(correct) - 1) * E[|ret| | event] - cost]
    
    # But cost is paid on ALL trades (not just events)
    # So net per trade = P(event) * [(2*p_correct - 1) * E[|ret| | event]] - cost
    # (assuming we only trade when event predicted, and position is 1)
    
    # For variable position:
    # EV = P(predict_event) * [P(correct | predict) * E[ret | predict, correct] 
    #                            - cost]
    
    # Simplified: if we trade when P(event) > threshold,
    # net = P(event) * (2*p_dir - 1) * E[|ret| | event] - P(trade) * cost
    
    dir_edge = (2 * p_direction_correct - 1) * expected_return
    net = p_event * dir_edge - cost_bps
    net = net - safety_margin
    
    return net > 0, net
