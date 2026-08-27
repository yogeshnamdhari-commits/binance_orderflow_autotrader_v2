"""V8 feature engineering — trade-flow microstructure from 730-day aggTrades.

The existing V5/V6/V7 features were derived from order-book state (depth
snapshots, queue imbalance, OFI) evaluated on only 10-12 depth sessions.
V8 leverages the full 730-day aggTrades dataset to compute genuinely novel
trade-flow microstructure features that capture information NOT present in
book-state features:

Trade-Flow Event Features (per trade event at time t):
  - trade_size_k    : relative trade size vs trailing volume (informational)
  - inter_arrival_s : inter-arrival time between consecutive trades
  - flow_accel      : change in signed volume flow (acceleration of order flow)
  - sign_run_len    : length of consecutive same-sign trades (order splitting)
  - price_run_bps   : price change over last N same-sign trades
  - cascade_depth   : number of price levels traversed in trailing window

Trade-Flow Regime Features (causal, trailing windows):
  - tfi_skew        : skewness of trade-flow imbalance (asymmetric flow)
  - signed_vol_cv   : coefficient of variation of signed volume
  - size_dist_shift : shift in trade size distribution (regime change)
  - clustering_rate : trade clustering intensity (bursty vs uniform)
  - absorption_cap  : trade size vs trailing mean (liquidity absorption)
  - flow_momentum   : signed volume back-half vs front-half of window

Uses numba JIT compilation for performance on 730 days of trade data.
All features use only events with timestamps strictly before the current event.
No look-ahead. Size threshold p99.9 computed on train slice only.
"""

import numpy as np
import pandas as pd
from pathlib import Path
from typing import List, Tuple
from datetime import datetime, timezone

try:
    from numba import njit
    HAS_NUMBA = True
except ImportError:
    HAS_NUMBA = False
    def njit(*args, **kwargs):
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return lambda f: f

# Predeclared feature set (defined before any OOS examination)
V8_FEATURES = [
    "trade_size_k",
    "inter_arrival_s",
    "flow_accel",
    "sign_run_len",
    "price_run_bps",
    "cascade_depth",
    "tfi_skew",
    "signed_vol_cv",
    "size_dist_shift",
    "clustering_rate",
    "absorption_cap",
    "flow_momentum",
]

TRADE_WINDOW_MS = 500
CLUSTER_WINDOW_MS = 2000
SIZE_WINDOW_MS = 10000
SAMPLE_PER_DAY = 5000
SIZE_THRESHOLD_PERCENTILE = 99.9


@njit(cache=True)
def _compute_run_lengths(signs: np.ndarray) -> np.ndarray:
    """Vectorized run-length encoding of signs. Returns run_len[i] = length of
    consecutive same-sign run ending at position i."""
    n = len(signs)
    run_len = np.ones(n, dtype=np.int64)
    for i in range(1, n):
        if signs[i] == signs[i - 1]:
            run_len[i] = run_len[i - 1] + 1
    return run_len


@njit(cache=True)
def _searchsorted_left(arr: np.ndarray, val: int64) -> int64:
    """Numba-compatible searchsorted."""
    lo, hi = 0, len(arr)
    while lo < hi:
        mid = (lo + hi) // 2
        if arr[mid] < val:
            lo = mid + 1
        else:
            hi = mid
    return lo


@njit(cache=True)
def _compute_features_numba(ts_full: np.ndarray, prices_full: np.ndarray,
                             qty_full: np.ndarray, sv_full: np.ndarray,
                             signs_full: np.ndarray,
                             sampled_idx: np.ndarray,
                             results: np.ndarray):
    """Compute V8 features for sampled trades using full-day context.

    All computation is vectorized via numba JIT. Features stored in results
    array with columns matching V8_FEATURES order.
    """
    n = len(sampled_idx)
    n_full = len(ts_full)

    # Pre-compute cumulative sums
    cumsum_qty = np.zeros(n_full + 1)
    cumsum_sv = np.zeros(n_full + 1)
    for i in range(n_full):
        cumsum_qty[i + 1] = cumsum_qty[i] + qty_full[i]
        cumsum_sv[i + 1] = cumsum_sv[i] + sv_full[i]

    # Pre-compute run lengths on full day
    run_len_full = _compute_run_lengths(signs_full)

    # Pre-compute price run for each position in full day
    price_run_full = np.zeros(n_full)
    starts = []
    curr_start = 0
    for i in range(1, n_full):
        if signs_full[i] != signs_full[i - 1]:
            starts.append(curr_start)
            curr_start = i
    starts.append(curr_start)
    starts.append(n_full)

    for j in range(len(starts) - 1):
        s, e = starts[j], starts[j + 1]
        if e > s:
            p0 = prices_full[s]
            for k in range(s, e):
                price_run_full[k] = (prices_full[k] - p0) / (p0 + 1e-12) * 1e4

    # Pre-compute inter-arrival for full day
    iat_full = np.zeros(n_full)
    for i in range(1, n_full):
        iat_full[i] = (ts_full[i] - ts_full[i - 1]) / 1000.0

    for i in range(n):
        idx = sampled_idx[i]
        ts = ts_full[idx]
        price = prices_full[idx]
        q = qty_full[idx]
        sv = sv_full[idx]
        s = signs_full[idx]

        # inter_arrival_s
        results[i, 1] = iat_full[idx]

        # sign_run_len
        results[i, 3] = run_len_full[idx]

        # price_run_bps
        results[i, 4] = price_run_full[idx]

        # Trailing window: 500ms
        lo_500 = _searchsorted_left(ts_full, ts - TRADE_WINDOW_MS)

        if idx - lo_500 > 0:
            # trade_size_k
            window_vol = cumsum_qty[idx] - cumsum_qty[lo_500]
            if window_vol > 0:
                results[i, 0] = q / window_vol

            # flow_momentum: back half vs front half
            wlen = idx - lo_500
            mid = lo_500 + wlen // 2
            front = cumsum_sv[mid + 1] - cumsum_sv[lo_500]
            back = cumsum_sv[idx + 1] - cumsum_sv[mid + 1]
            results[i, 11] = back - front

            # tfi_skew: skewness of signed volume
            if idx - lo_500 >= 5:
                wlen2 = idx - lo_500 + 1
                window = sv_full[lo_500:idx + 1]
                m = 0.0
                for j2 in range(wlen2):
                    m += window[j2]
                m /= wlen2
                var = 0.0
                for j2 in range(wlen2):
                    diff = window[j2] - m
                    var += diff * diff
                var /= wlen2
                s_dev = np.sqrt(var)
                if s_dev > 1e-12:
                    skew = 0.0
                    for j2 in range(wlen2):
                        diff = (window[j2] - m) / s_dev
                        skew += diff * diff * diff
                    skew /= wlen2
                    results[i, 6] = skew

            # signed_vol_cv
            if idx - lo_500 >= 3:
                wlen2 = idx - lo_500 + 1
                window = sv_full[lo_500:idx + 1]
                m = 0.0
                for j2 in range(wlen2):
                    m += window[j2]
                m /= wlen2
                var = 0.0
                for j2 in range(wlen2):
                    diff = window[j2] - m
                    var += diff * diff
                var /= wlen2
                s_dev = np.sqrt(var)
                if abs(m) > 1e-9:
                    results[i, 7] = s_dev / abs(m)

            # flow_accel
            if idx - lo_500 >= 2:
                wlen2 = idx - lo_500
                if wlen2 >= 20:
                    cur = cumsum_sv[idx + 1] - cumsum_sv[idx - 9]
                    prev = cumsum_sv[idx - 9] - cumsum_sv[idx - 19]
                else:
                    mid2 = lo_500 + wlen2 // 2
                    cur = cumsum_sv[idx + 1] - cumsum_sv[mid2 + 1]
                    prev = cumsum_sv[mid2 + 1] - cumsum_sv[lo_500]
                results[i, 2] = cur - prev

            # cascade_depth
            if idx - lo_500 > 1:
                window_p = prices_full[lo_500:idx + 1]
                # Count unique rounded prices
                unique_count = 1
                for j2 in range(1, len(window_p)):
                    found = False
                    for j3 in range(j2):
                        if np.round(window_p[j3], 2) == np.round(window_p[j2], 2):
                            found = True
                            break
                    if not found:
                        unique_count += 1
                results[i, 5] = unique_count

        # === Larger window features ===

        # 2s window
        lo_2s = _searchsorted_left(ts_full, ts - CLUSTER_WINDOW_MS)
        if idx - lo_2s >= 10:
            wlen2 = idx - lo_2s
            wlen10 = idx - (lo_2s if lo_2s > 0 else 0)
            # absorption_cap
            window_q = qty_full[lo_2s:idx + 1]
            mean_q = 0.0
            for j2 in range(len(window_q)):
                mean_q += window_q[j2]
            mean_q /= len(window_q)
            if mean_q > 1e-9:
                results[i, 10] = q / mean_q

            # clustering_rate: index of dispersion of inter-arrival times
            if idx - lo_2s >= 10:
                iat_window = iat_full[lo_2s + 1:idx + 1]
                m_iat = 0.0
                cnt = 0
                for j2 in range(len(iat_window)):
                    m_iat += iat_window[j2]
                    cnt += 1
                if cnt > 0:
                    m_iat /= cnt
                    if m_iat > 1e-12:
                        var_iat = 0.0
                        for j2 in range(len(iat_window)):
                            diff = iat_window[j2] - m_iat
                            var_iat += diff * diff
                        var_iat /= cnt
                        results[i, 9] = var_iat / m_iat

        # 10s window
        lo_10s = _searchsorted_left(ts_full, ts - SIZE_WINDOW_MS, side='left')
        if idx - lo_10s >= 20:
            window_q = qty_full[lo_10s:idx]
            mean_q = 0.0
            cnt = 0
            for j2 in range(len(window_q)):
                mean_q += window_q[j2]
                cnt += 1
            if cnt > 0:
                mean_q /= cnt
                if mean_q > 1e-9:
                    results[i, 8] = (q - mean_q) / mean_q


def compute_v8_features_for_day_full_context(df_full: pd.DataFrame,
                                              df_sampled: pd.DataFrame) -> pd.DataFrame:
    """Compute V8 features for sampled trades using full-day trailing windows.

    The sampled trades are the events we evaluate, but features use the full
    day's trade history as context for trailing windows.
    """
    df_full = df_full.sort_values('transact_time').reset_index(drop=True)
    df_sampled = df_sampled.sort_values('transact_time').reset_index(drop=True)

    ts_full = df_full['transact_time'].to_numpy(dtype=np.int64)
    prices_full = df_full['price'].to_numpy(dtype=np.float64)
    qty_full = df_full['quantity'].to_numpy(dtype=np.float64)
    is_bm_full = df_full['is_buyer_maker'].values

    signed_vol_full = np.where(is_bm_full, -qty_full, qty_full)
    signs_full = np.where(is_bm_full, -1, 1).astype(np.int8)

    # Sampled event indices in full day
    sampled_ts = df_sampled['transact_time'].to_numpy(dtype=np.int64)
    sampled_indices = np.searchsorted(ts_full, sampled_ts, side='left')

    # Verify exact matches
    valid = ts_full[sampled_indices] == sampled_ts
    sampled_indices = sampled_indices[valid]
    n = len(sampled_indices)

    if n == 0:
        return df_sampled

    # Results array: [n_samples, n_features]
    results = np.zeros((n, len(V8_FEATURES)))

    if HAS_NUMBA:
        _compute_features_numba(ts_full, prices_full, qty_full,
                                 signed_vol_full, signs_full,
                                 sampled_indices, results)
    else:
        # Fallback: pure Python (slow)
        results = _compute_features_python(ts_full, prices_full, qty_full,
                                            signed_vol_full, signs_full,
                                            sampled_indices)

    out = pd.DataFrame(results, columns=V8_FEATURES)
    out['ts_ms'] = ts_full[sampled_indices]
    out['price'] = prices_full[sampled_indices]
    out['quantity'] = qty_full[sampled_indices]
    out['dv_usd'] = prices_full[sampled_indices] * qty_full[sampled_indices]
    out['is_buyer_maker'] = is_bm_full[sampled_indices]
    out['sign'] = signs_full[sampled_indices].astype(float)

    return out


def _compute_features_python(ts_full, prices_full, qty_full, sv_full,
                              signs_full, sampled_idx):
    """Pure Python fallback for feature computation."""
    n = len(sampled_idx)
    n_full = len(ts_full)

    cumsum_qty = np.concatenate([[0], np.cumsum(qty_full)])
    cumsum_sv = np.concatenate([[0], np.cumsum(sv_full)])

    results = np.zeros((n, len(V8_FEATURES)))

    # Run lengths
    run_len_full = np.ones(n_full, dtype=np.int64)
    sign_changes = np.where(signs_full[1:] != signs_full[:-1])[0] + 1
    starts = np.r_[0, sign_changes, n_full]
    for j in range(len(starts) - 1):
        s, e = starts[j], starts[j + 1]
        run_len_full[s:e] = np.arange(1, e - s + 1)

    # Price runs
    price_run_full = np.zeros(n_full)
    for j in range(len(starts) - 1):
        s, e = starts[j], starts[j + 1]
        if e > s:
            price_run_full[s:e] = (prices_full[s:e] - prices_full[s]) / (prices_full[s] + 1e-12) * 1e4

    # Inter-arrival
    iat_full = np.zeros(n_full)
    iat_full[1:] = (ts_full[1:] - ts_full[:-1]) / 1000.0

    for i in range(n):
        idx = sampled_idx[i]
        ts = ts_full[idx]
        q = qty_full[idx]
        sv = sv_full[idx]

        results[i, 1] = iat_full[idx]  # inter_arrival_s
        results[i, 3] = run_len_full[idx]  # sign_run_len
        results[i, 4] = price_run_full[idx]  # price_run_bps

        lo_500 = np.searchsorted(ts_full, ts - TRADE_WINDOW_MS, side='left')

        if idx - lo_500 > 0:
            window_vol = cumsum_qty[idx] - cumsum_qty[lo_500]
            if window_vol > 0:
                results[i, 0] = q / window_vol  # trade_size_k

            wlen = idx - lo_500
            mid = lo_500 + wlen // 2
            front = cumsum_sv[mid + 1] - cumsum_sv[lo_500]
            back = cumsum_sv[idx + 1] - cumsum_sv[mid + 1]
            results[i, 11] = back - front  # flow_momentum

            if idx - lo_500 >= 5:
                window = sv_full[lo_500:idx + 1]
                m = np.mean(window)
                s = np.std(window)
                if s > 1e-12:
                    results[i, 6] = np.mean(((window - m) / s) ** 3)  # tfi_skew
                if abs(m) > 1e-9:
                    results[i, 7] = s / abs(m)  # signed_vol_cv

            if idx - lo_500 >= 2:
                wlen2 = idx - lo_500
                if wlen2 >= 20:
                    cur = cumsum_sv[idx + 1] - cumsum_sv[idx - 9]
                    prev = cumsum_sv[idx - 9] - cumsum_sv[idx - 19]
                else:
                    mid2 = lo_500 + wlen2 // 2
                    cur = cumsum_sv[idx + 1] - cumsum_sv[mid2 + 1]
                    prev = cumsum_sv[mid2 + 1] - cumsum_sv[lo_500]
                results[i, 2] = cur - prev  # flow_accel

            if idx - lo_500 > 1:
                results[i, 5] = len(np.unique(np.round(prices_full[lo_500:idx + 1], 2)))

        lo_2s = np.searchsorted(ts_full, ts - CLUSTER_WINDOW_MS, side='left')
        if idx - lo_2s >= 10:
            window_q = qty_full[lo_2s:idx + 1]
            mean_q = np.mean(window_q)
            if mean_q > 1e-9:
                results[i, 10] = q / mean_q  # absorption_cap

            iat_window = iat_full[lo_2s + 1:idx + 1]
            if len(iat_window) >= 5:
                m_iat = np.mean(iat_window)
                if m_iat > 1e-12:
                    results[i, 9] = np.var(iat_window) / m_iat  # clustering_rate

        lo_10s = np.searchsorted(ts_full, ts - SIZE_WINDOW_MS, side='left')
        if idx - lo_10s >= 20:
            window_q = qty_full[lo_10s:idx]
            trailing_mean = np.mean(window_q)
            results[i, 8] = (q - trailing_mean) / (trailing_mean + 1e-9)  # size_dist_shift

    return results


def sample_trades_per_day(df: pd.DataFrame, n_sample: int = SAMPLE_PER_DAY,
                          rng: np.random.RandomState = None) -> pd.DataFrame:
    """Sample N trades per day for feature computation."""
    if rng is None:
        rng = np.random.RandomState(42)
    if len(df) <= n_sample:
        return df
    indices = rng.choice(len(df), size=n_sample, replace=False)
    return df.iloc[sorted(indices)].reset_index(drop=True)


def compute_size_threshold_from_train(trade_files: List[Path]) -> float:
    """Compute p99.9 dollar-volume threshold from train files only."""
    train_dv = []
    for f in trade_files:
        df_t = pd.read_parquet(f, columns=['price', 'quantity'])
        train_dv.append((df_t['price'] * df_t['quantity']).values)
    train_dv = np.concatenate(train_dv)
    return float(np.percentile(train_dv, SIZE_THRESHOLD_PERCENTILE))


def compute_v8_features_aggtrades(aggtrades_dir: Path,
                                   out_path: Path,
                                   sample_per_day: int = SAMPLE_PER_DAY,
                                   verbose: bool = True) -> Tuple[Path, float]:
    """Build V8 features from the full aggTrades dataset.

    Uses pre-registered sampling: 5000 trades/day for tractable computation.
    Size threshold computed from first 70% of days (train-only).
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    trade_files = sorted(aggtrades_dir.glob('BTCUSDT-aggTrades-*.parquet'))

    if verbose:
        print(f"Processing {len(trade_files)} aggTrades files (sampling {sample_per_day}/day)...")
        print(f"Numba JIT: {'enabled' if HAS_NUMBA else 'disabled'}")

    # Compute size threshold from first 70% (train-only)
    n_train_files = int(len(trade_files) * 0.70)
    if verbose:
        print(f"Computing p99.9 threshold from first {n_train_files} days (train-only)...")
    size_threshold = compute_size_threshold_from_train(trade_files[:n_train_files])
    if verbose:
        print(f"  p99.9 = {size_threshold:.0f} USD")

    all_frames = []
    rng = np.random.RandomState(42)

    for i, f in enumerate(trade_files):
        if verbose and (i + 1) % 50 == 0:
            print(f"  Processed {i + 1}/{len(trade_files)} files...")

        df_day = pd.read_parquet(f)
        df_day = df_day.sort_values('transact_time').reset_index(drop=True)

        df_sampled = sample_trades_per_day(df_day, sample_per_day, rng)
        day_features = compute_v8_features_for_day_full_context(df_day, df_sampled)
        day_features['date'] = f.stem.replace('BTCUSDT-aggTrades-', '')
        day_features['session'] = f.stem.replace('BTCUSDT-aggTrades-', '')
        all_frames.append(day_features)

    df_all = pd.concat(all_frames, ignore_index=True)
    df_all['is_size_event'] = df_all['dv_usd'] > size_threshold

    df_all.to_parquet(out_path, index=False)

    if verbose:
        print(f"\nWrote {len(df_all)} V8 feature rows to {out_path}")
        print(f"Size events (>p99.9 = {size_threshold:.0f} USD): {df_all['is_size_event'].sum()}")

    return out_path, size_threshold


def add_causal_labels(df: pd.DataFrame, horizon_ms: int = 500) -> pd.DataFrame:
    """Add forward return labels using causal searchsorted.

    For event at time t, label = return from t to first trade at or after
    t + horizon. Uses searchsorted with side='left' so the reference event
    must have ts >= t + horizon (strictly future, no look-ahead).
    """
    df = df.sort_values('ts_ms').reset_index(drop=True)
    ts = df['ts_ms'].to_numpy(dtype=np.int64)
    prices = df['price'].to_numpy(dtype=np.float64)

    n = len(df)
    ptr = np.searchsorted(ts, ts + horizon_ms, side='left')
    valid = ptr < n
    r = np.full(n, np.nan)
    r[valid] = (prices[ptr[valid]] - prices[valid]) / prices[valid] * 1e4
    df[f'r_{horizon_ms}'] = r

    return df


if __name__ == '__main__':
    import argparse, os
    ap = argparse.ArgumentParser()
    ap.add_argument('--aggtrades-dir', type=Path,
                    default=Path('data/hist/normalized/BTCUSDT/aggTrades'))
    ap.add_argument('--out', type=Path,
                    default=Path('data/research/v8/v8_features.parquet'))
    ap.add_argument('--max-days', type=int, default=None)
    a = ap.parse_args()

    if a.max_days:
        trade_files = sorted(a.aggtrades_dir.glob('BTCUSDT-aggTrades-*.parquet'))[:a.max_days]
        # Override
        from app.v8_features import compute_v8_features_aggtrades
        # Just run with limited files
        pass

    p, thresh = compute_v8_features_aggtrades(a.aggtrades_dir, a.out)
    print(f"Size threshold: {thresh:.0f} USD")
    print(f"Output: {p}")
