#!/usr/bin/env python3
"""Horizon Control Experiments — Determine if horizon effect is genuine or artifact.

Controls:
1. Unconditional market return (drift)
2. Signed random entry
3. Time-matched control
4. Signal-direction permutation
"""
import json, sys, warnings, time
from pathlib import Path
from collections import defaultdict
import numpy as np
import pandas as pd
from scipy import stats as scs

warnings.filterwarnings('ignore')
sys.path.insert(0, '.')

from app.orderbook import LocalOrderBook
from app.features import OrderFlowEngine
from app.events import EventDetector
from app.signal import SignalEngine

HORIZONS_MS = [100, 250, 500, 1000, 2000, 5000, 10000, 30000, 60000]
TAKER_COST = 4.0158
MAKER_COST = 2.0

class DepthEvent:
    __slots__ = ('ts_ms','first_update_id','final_update_id','bids','asks')
    def __init__(self, ts, u, final, bids, asks):
        self.ts_ms = ts
        self.first_update_id = u
        self.final_update_id = final
        self.bids = bids
        self.asks = asks

class TradeEvent:
    __slots__ = ('ts_ms','id','price','qty','aggressor_side')
    def __init__(self, ts, tid, price, qty, side):
        self.ts_ms = ts
        self.id = tid
        self.price = price
        self.qty = qty
        self.aggressor_side = side

def load_session_data(sess_dir):
    rows = []
    with open(sess_dir / 'derived_v5.jsonl') as f:
        for line in f:
            rows.append(json.loads(line))
    return rows

def get_target_mid(rows, signal_idx, horizon_ms):
    signal_ts = rows[signal_idx]['ts_ms']
    target_ts = signal_ts + horizon_ms
    for i in range(signal_idx + 1, len(rows)):
        if rows[i]['ts_ms'] >= target_ts:
            return rows[i]['mid'], rows[i]['ts_ms']
    return None, None

def run_control_unconditional(sess_dir, derived_rows):
    """Control 1: Unconditional market return (drift)."""
    results = defaultdict(list)
    for h_ms in HORIZONS_MS:
        for i, row in enumerate(derived_rows):
            mid0 = row['mid']
            if mid0 is None or mid0 <= 0:
                continue
            target_mid, _ = get_target_mid(derived_rows, i, h_ms)
            if target_mid is None:
                continue
            ret_bps = (target_mid - mid0) / mid0 * 1e4
            results[h_ms].append({
                'session': sess_dir.name,
                'ts_ms': row['ts_ms'],
                'gross_bps': ret_bps,
            })
    return results

def run_control_random_entry(sess_dir, derived_rows, seed=42):
    """Control 2: Signed random entry."""
    rng = np.random.RandomState(seed)
    results = defaultdict(list)
    for h_ms in HORIZONS_MS:
        for i, row in enumerate(derived_rows):
            mid0 = row['mid']
            if mid0 is None or mid0 <= 0:
                continue
            target_mid, _ = get_target_mid(derived_rows, i, h_ms)
            if target_mid is None:
                continue
            ret_bps = (target_mid - mid0) / mid0 * 1e4
            # Random direction
            side = 'BUY' if rng.random() > 0.5 else 'SELL'
            gross = ret_bps if side == 'BUY' else -ret_bps
            results[h_ms].append({
                'session': sess_dir.name,
                'ts_ms': row['ts_ms'],
                'gross_bps': gross,
            })
    return results

def run_control_time_matched(sess_dir, derived_rows, signal_times, seed=42):
    """Control 3: Time-matched control (random times matching signal times)."""
    rng = np.random.RandomState(seed + 1)
    results = defaultdict(list)

    # Get all valid event indices
    valid_indices = [i for i, r in enumerate(derived_rows) if r['mid'] is not None and r['mid'] > 0]

    for h_ms in HORIZONS_MS:
        # Sample random times matching the number of signals
        n_signals = len(signal_times.get(h_ms, []))
        if n_signals == 0:
            continue
        # Sample from valid indices
        if len(valid_indices) < n_signals:
            continue
        sampled_indices = rng.choice(valid_indices, size=n_signals, replace=False)
        for idx in sampled_indices:
            row = derived_rows[idx]
            mid0 = row['mid']
            target_mid, _ = get_target_mid(derived_rows, idx, h_ms)
            if target_mid is None:
                continue
            ret_bps = (target_mid - mid0) / mid0 * 1e4
            # Use actual signal direction from signal_times
            side = signal_times[h_ms][min(len(signal_times[h_ms])-1, list(sampled_indices).index(idx))]['action'] if h_ms in signal_times else 'BUY'
            gross = ret_bps if side == 'BUY' else -ret_bps
            results[h_ms].append({
                'session': sess_dir.name,
                'ts_ms': row['ts_ms'],
                'gross_bps': gross,
            })
    return results

def run_control_permutation(sess_dir, derived_rows, signal_data, seed=42):
    """Control 4: Signal-direction permutation within sessions."""
    rng = np.random.RandomState(seed + 2)
    results = defaultdict(list)

    for h_ms in HORIZONS_MS:
        signals = signal_data.get(h_ms, [])
        if not signals:
            continue

        # Group by session
        by_session = defaultdict(list)
        for s in signals:
            by_session[s['session']].append(s)

        for sess_name, sess_signals in by_session.items():
            # Permute directions within session
            directions = [s['action'] for s in sess_signals]
            rng.shuffle(directions)

            for s, d in zip(sess_signals, directions):
                gross = s['gross_bps']
                # Flip direction if permuted
                if d != s['action']:
                    gross = -gross
                results[h_ms].append({
                    'session': sess_name,
                    'ts_ms': s['ts_ms'],
                    'gross_bps': gross,
                })
    return results

def replay_get_signals(sess_dir, derived_rows):
    """Replay session and get signals with their indices."""
    book = LocalOrderBook(50)
    flow = OrderFlowEngine(book)
    detector = EventDetector()
    signals = SignalEngine()

    ts_to_idx = {}
    for i, row in enumerate(derived_rows):
        ts_to_idx[row['ts_ms']] = i

    signal_data = defaultdict(list)
    signal_times = defaultdict(list)
    recv_ms_counter = 0

    with open(sess_dir / "raw.jsonl") as f:
        for line in f:
            rec = json.loads(line)
            kind = rec.get("kind", "unknown")

            if kind == "snapshot":
                b = [(float(p), float(q)) for p, q in rec.get("bids", [])]
                a = [(float(p), float(q)) for p, q in rec.get("asks", [])]
                book.load_snapshot(b, a, rec.get("last_update_id", rec.get("E", 0)))
                flow.prev_full_bids = dict(book.state.bids)
                flow.prev_full_asks = dict(book.state.asks)
                continue
            elif kind == "depth":
                ts = int(rec.get("E", rec.get("recv_ms", 0)))
                u = int(rec.get("U", 0))
                final = int(rec.get("u", 0))
                b = [(float(p), float(q)) for p, q in rec.get("bids", [])]
                a = [(float(p), float(q)) for p, q in rec.get("asks", [])]
                e = DepthEvent(ts, u, final, b, a)
                if book.apply(e) != "OK":
                    continue
                recv_ms_counter += 1
                flow.on_book_event(e)
            elif kind == "trade":
                t = int(rec.get("T", rec.get("ts_ms", 0)))
                price = float(rec.get("p", 0))
                qty = float(rec.get("q", 0))
                is_sell = bool(rec.get("m", False))
                side = "SELL" if is_sell else "BUY"
                te = TradeEvent(t, int(rec.get("a", rec.get("t", 0))), price, qty, side)
                flow.on_trade(te)
                recv_ms_counter += 1
            else:
                continue

            f = flow.snapshot(now_ms=recv_ms_counter)
            events = detector.detect(f)
            sig = signals.decide(f, events)

            if sig.action not in ('BUY', 'SELL'):
                continue

            ts = int(rec.get("E", rec.get("T", rec.get("recv_ms", 0))))
            signal_idx = ts_to_idx.get(ts)
            if signal_idx is None:
                continue

            mid0 = derived_rows[signal_idx]['mid']
            if mid0 is None or mid0 <= 0:
                continue

            for h_ms in HORIZONS_MS:
                target_mid, _ = get_target_mid(derived_rows, signal_idx, h_ms)
                if target_mid is None:
                    continue
                ret_bps = (target_mid - mid0) / mid0 * 1e4
                gross = ret_bps if sig.action == 'BUY' else -ret_bps

                signal_data[h_ms].append({
                    'session': sess_dir.name,
                    'ts_ms': ts,
                    'action': sig.action,
                    'gross_bps': gross,
                })
                signal_times[h_ms].append({
                    'session': sess_dir.name,
                    'ts_ms': ts,
                    'action': sig.action,
                })

    return signal_data, signal_times

def block_bootstrap_ci(values, block_size=50, n_boot=2000, alpha=0.05, seed=42):
    rng = np.random.RandomState(seed)
    n = len(values)
    if n == 0:
        return 0.0, 0.0, 0.0, (0.0, 0.0)
    values = np.array(values)
    n_blocks = max(1, int(np.ceil(n / block_size)))
    boot_means = np.empty(n_boot)
    for i in range(n_boot):
        starts = rng.randint(0, n, size=n_blocks)
        sample = np.concatenate([values[s:s+block_size] for s in starts])[:n]
        boot_means[i] = np.mean(sample)
    lo = np.percentile(boot_means, alpha/2 * 100)
    hi = np.percentile(boot_means, (1 - alpha/2) * 100)
    mean = float(np.mean(values))
    if n > 1:
        t = mean / (np.std(values, ddof=1) / np.sqrt(n))
        p = 2 * min(float(scs.t.cdf(t, n-1)), 1 - float(scs.t.cdf(t, n-1)))
    else:
        t, p = 0.0, 1.0
    return mean, t, p, (float(lo), float(hi))

def main():
    sessions = sorted([d.name for d in Path('data/live/v5').glob('2026*') if (d / 'raw.jsonl').exists()])
    print(f"Sessions: {len(sessions)}")

    t0 = time.time()
    all_signal_data = defaultdict(list)
    all_signal_times = defaultdict(list)
    all_control_unconditional = defaultdict(list)
    all_control_random = defaultdict(list)
    all_control_permutation = defaultdict(list)

    for sess in sessions:
        sess_dir = Path(f'data/live/v5/{sess}')
        derived_rows = load_session_data(sess_dir)

        # Get signals
        signal_data, signal_times = replay_get_signals(sess_dir, derived_rows)
        for h, v in signal_data.items():
            all_signal_data[h].extend(v)
        for h, v in signal_times.items():
            all_signal_times[h].extend(v)

        # Control 1: Unconditional
        ctrl1 = run_control_unconditional(sess_dir, derived_rows)
        for h, v in ctrl1.items():
            all_control_unconditional[h].extend(v)

        # Control 2: Random entry
        ctrl2 = run_control_random_entry(sess_dir, derived_rows, seed=42)
        for h, v in ctrl2.items():
            all_control_random[h].extend(v)

        # Control 4: Permutation
        ctrl4 = run_control_permutation(sess_dir, derived_rows, signal_data, seed=42)
        for h, v in ctrl4.items():
            all_control_permutation[h].extend(v)

        elapsed = time.time() - t0
        print(f"  {sess}: elapsed={elapsed:.1f}s")

    # Evaluate controls
    print(f"\n{'='*70}")
    print(f"CONTROL EXPERIMENT RESULTS")
    print(f"{'='*70}")

    controls = {
        'SignalEngine (actual)': all_signal_data,
        'Unconditional (drift)': all_control_unconditional,
        'Random entry': all_control_random,
        'Permutation': all_control_permutation,
    }

    summary = []

    for ctrl_name, ctrl_data in controls.items():
        print(f"\n{'='*70}")
        print(f"Control: {ctrl_name}")
        print(f"{'='*70}")
        print(f"{'Horizon':>10} {'N':>6} {'Gross':>8} {'Std':>8} {'Frac+':>8} {'t-stat':>8} {'p-val':>8}")
        print(f"{'-'*60}")

        for h_ms in HORIZONS_MS:
            data = ctrl_data.get(h_ms, [])
            if not data:
                continue
            gross_vals = np.array([d['gross_bps'] for d in data])
            mean_g, t_g, p_g, ci_g = block_bootstrap_ci(gross_vals)
            std_g = np.std(gross_vals)
            frac_pos = (gross_vals > 0).mean()

            summary.append({
                'control': ctrl_name,
                'horizon_ms': h_ms,
                'n': len(gross_vals),
                'gross_bps': mean_g,
                'std_bps': std_g,
                'frac_positive': frac_pos,
                't_stat': t_g,
                'p_value': p_g,
            })

            print(f"{h_ms:>10} {len(gross_vals):>6} {mean_g:>8.4f} {std_g:>8.4f} {frac_pos:>8.4f} {t_g:>8.4f} {p_g:>8.4f}")

    # Save results
    for ctrl_name, ctrl_data in controls.items():
        for h_ms, data in ctrl_data.items():
            if data:
                df = pd.DataFrame(data)
                safe_name = ctrl_name.replace(' ', '_').replace('(', '').replace(')', '')
                df.to_csv(f'data/research/horizon_control_{safe_name}_{h_ms}ms.csv', index=False)

    print(f"\nSaved control results to data/research/horizon_control_*.csv")

if __name__ == "__main__":
    main()
