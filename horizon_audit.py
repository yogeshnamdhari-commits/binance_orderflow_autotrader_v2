#!/usr/bin/env python3
"""Horizon Economic Audit — Measure information decay curve of existing signal.

Pre-registered horizons: 100ms, 250ms, 500ms, 1s, 2s, 5s, 10s, 30s, 60s
Uses frozen SignalEngine and frozen V5 DecisionEngine.
Causal correctness: targets use only post-signal information.
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
from app.v5_cost import measured_gate
from app.v5_model import load_model, predict, V5_FEATURES
from app.v5_calibration import calibrate_prediction

# === Configuration ===
HORIZONS_MS = [100, 250, 500, 1000, 2000, 5000, 10000, 30000, 60000]
TAKER_COST = 4.0158
MAKER_COST = 2.0
SLIPPAGE_BPS = 0.0079
ALPHA = 0.05 / 9  # Bonferroni correction

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
    """Load derived_v5.jsonl with level data."""
    rows = []
    with open(sess_dir / 'derived_v5.jsonl') as f:
        for line in f:
            rows.append(json.loads(line))
    return rows

def get_target_mid(rows, signal_idx, horizon_ms):
    """Get mid price at signal_time + horizon. Causal: only uses post-signal data."""
    signal_ts = rows[signal_idx]['ts_ms']
    target_ts = signal_ts + horizon_ms

    # Find first event at or after target_ts
    for i in range(signal_idx + 1, len(rows)):
        if rows[i]['ts_ms'] >= target_ts:
            return rows[i]['mid'], rows[i]['ts_ms']
    return None, None

def get_target_book(rows, signal_idx, horizon_ms):
    """Get book state at signal_time + horizon. Causal: only uses post-signal data."""
    signal_ts = rows[signal_idx]['ts_ms']
    target_ts = signal_ts + horizon_ms

    for i in range(signal_idx + 1, len(rows)):
        if rows[i]['ts_ms'] >= target_ts:
            return rows[i]
    return None

def compute_excursion(rows, signal_idx, horizon_ms, side):
    """Compute maximum adverse and favorable excursion."""
    signal_ts = rows[signal_idx]['ts_ms']
    signal_mid = rows[signal_idx]['mid']
    target_ts = signal_ts + horizon_ms

    max_favorable = 0.0
    max_adverse = 0.0
    time_to_peak = 0
    time_to_adverse = 0

    for i in range(signal_idx + 1, len(rows)):
        if rows[i]['ts_ms'] > target_ts:
            break
        mid = rows[i]['mid']
        if mid is None:
            continue
        change = (mid - signal_mid) / signal_mid * 1e4
        if side == 'SELL':
            change = -change

        if change > max_favorable:
            max_favorable = change
            time_to_peak = rows[i]['ts_ms'] - signal_ts
        if change < max_adverse:
            max_adverse = change
            time_to_adverse = rows[i]['ts_ms'] - signal_ts

    return max_favorable, max_adverse, time_to_peak, time_to_adverse

def replay_and_evaluate_horizons(sess_dir, derived_rows, model_d, calibration):
    """Replay session and evaluate all horizons."""
    book = LocalOrderBook(50)
    flow = OrderFlowEngine(book)
    detector = EventDetector()
    signals = SignalEngine()

    # Index derived rows by ts_ms
    ts_to_idx = {}
    for i, row in enumerate(derived_rows):
        ts_to_idx[row['ts_ms']] = i

    results = defaultdict(list)
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
                status = book.apply(e)
                if status != "OK":
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

            elif kind == "bookTicker":
                continue
            else:
                continue

            # Generate signal
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

            spread_bps = derived_rows[signal_idx].get('spread_bps', 0)
            qi_l1 = derived_rows[signal_idx].get('qi_l1', 0)

            # Evaluate each horizon
            for h_ms in HORIZONS_MS:
                target_mid, target_ts = get_target_mid(derived_rows, signal_idx, h_ms)
                if target_mid is None:
                    continue

                # Raw directional gross return
                ret_bps = (target_mid - mid0) / mid0 * 1e4
                gross = ret_bps if sig.action == 'BUY' else -ret_bps

                # Executable returns
                target_book = get_target_book(derived_rows, signal_idx, h_ms)
                if target_book:
                    best_bid = target_book.get('best_bid')
                    best_ask = target_book.get('best_ask')
                    if best_bid and best_ask and sig.action == 'BUY':
                        exec_price = best_ask * (1 + SLIPPAGE_BPS / 1e4)
                        exec_ret = (target_mid - exec_price) / exec_price * 1e4
                    elif best_bid and best_ask and sig.action == 'SELL':
                        exec_price = best_bid * (1 - SLIPPAGE_BPS / 1e4)
                        exec_ret = (exec_price - target_mid) / exec_price * 1e4
                    else:
                        exec_ret = gross
                else:
                    exec_ret = gross

                # Net returns
                net_taker = gross - TAKER_COST
                net_maker = gross - MAKER_COST

                # Excursion
                max_fav, max_adv, t_peak, t_adv = compute_excursion(
                    derived_rows, signal_idx, h_ms, sig.action
                )

                results[h_ms].append({
                    'session': sess_dir.name,
                    'ts_ms': ts,
                    'action': sig.action,
                    'score': sig.score,
                    'gross_bps': gross,
                    'exec_ret_bps': exec_ret,
                    'net_taker_bps': net_taker,
                    'net_maker_bps': net_maker,
                    'mid0': mid0,
                    'mid_target': target_mid,
                    'spread_bps': spread_bps,
                    'qi_l1': qi_l1,
                    'max_favorable_bps': max_fav,
                    'max_adverse_bps': max_adv,
                    'time_to_peak_ms': t_peak,
                    'time_to_adverse_ms': t_adv,
                })

    return results

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
    print(f"Horizons: {HORIZONS_MS}")
    print(f"Bonferroni-corrected α = {ALPHA:.5f}")

    # Load V5 model and calibration
    model_d = load_model('data/research/v5_model.json')
    with open('data/research/v5_binned_calibration.json') as f:
        cal_data = json.load(f)
    calibration = {
        'bin_edges': np.array(cal_data['bin_edges']),
        'bin_means': np.array(cal_data['bin_means']),
        'bin_counts': np.array(cal_data['bin_counts']),
        'bin_stderr': np.array(cal_data['bin_stderr']),
        'horizon_ms': cal_data['horizon_ms'],
        'n_bins': cal_data['n_bins'],
        'min_pred': cal_data['min_pred'],
        'max_pred': cal_data['max_pred'],
    }

    t0 = time.time()
    all_results = defaultdict(list)

    for sess in sessions:
        sess_dir = Path(f'data/live/v5/{sess}')
        derived_rows = load_session_data(sess_dir)
        results = replay_and_evaluate_horizons(sess_dir, derived_rows, model_d, calibration)
        for h, v in results.items():
            all_results[h].extend(v)
        elapsed = time.time() - t0
        print(f"  {sess}: signals={sum(len(v) for v in results.values())} elapsed={elapsed:.1f}s")

    # Convert to DataFrames
    dfs = {}
    for h, v in all_results.items():
        dfs[h] = pd.DataFrame(v) if v else pd.DataFrame()

    print(f"\n{'='*70}")
    print(f"HORIZON ECONOMIC AUDIT RESULTS")
    print(f"{'='*70}")

    summary = []

    for h_ms in HORIZONS_MS:
        df = dfs.get(h_ms, pd.DataFrame())
        if len(df) == 0:
            print(f"\n{h_ms} ms: No signals")
            continue

        gross_vals = df['gross_bps'].values
        net_taker_vals = df['net_taker_bps'].values
        net_maker_vals = df['net_maker_bps'].values

        mean_g, t_g, p_g, ci_g = block_bootstrap_ci(gross_vals)
        mean_nt, t_nt, p_nt, ci_nt = block_bootstrap_ci(net_taker_vals)
        mean_nm, t_nm, p_nm, ci_nm = block_bootstrap_ci(net_maker_vals)

        frac_pos = (gross_vals > 0).mean()
        median_g = np.median(gross_vals)
        std_g = np.std(gross_vals)

        # Per-session
        by_sess = df.groupby('session').agg(
            n=('gross_bps', 'count'),
            gross=('gross_bps', 'mean'),
        ).reset_index()

        # Excursion
        max_fav = df['max_favorable_bps'].mean()
        max_adv = df['max_adverse_bps'].mean()
        t_peak = df['time_to_peak_ms'].mean()
        t_adv = df['time_to_adverse_ms'].mean()

        # Break-even cost
        break_even = mean_g

        summary.append({
            'horizon_ms': h_ms,
            'n': len(df),
            'gross_bps': mean_g,
            'median_bps': median_g,
            'std_bps': std_g,
            'frac_positive': frac_pos,
            't_stat': t_g,
            'p_value': p_g,
            'ci_low': ci_g[0],
            'ci_high': ci_g[1],
            'net_taker_bps': mean_nt,
            'net_maker_bps': mean_nm,
            'break_even_cost': break_even,
            'max_favorable': max_fav,
            'max_adverse': max_adv,
            'time_to_peak_ms': t_peak,
            'time_to_adverse_ms': t_adv,
            'sessions_positive': (by_sess['gross'] > 0).sum(),
            'total_sessions': len(by_sess),
        })

        print(f"\n{'='*70}")
        print(f"Horizon: {h_ms} ms ({h_ms/1000:.1f} s)")
        print(f"{'='*70}")
        print(f"Signals: {len(df)}")
        print(f"  BUY: {(df['action'] == 'BUY').sum()}")
        print(f"  SELL: {(df['action'] == 'SELL').sum()}")
        print(f"Gross mean: {mean_g:.6f} bps")
        print(f"Gross median: {median_g:.6f} bps")
        print(f"Gross std: {std_g:.6f} bps")
        print(f"Fraction positive: {frac_pos:.4f}")
        print(f"t-stat: {t_g:.4f}, p-value: {p_g:.6f}")
        print(f"95% CI: [{ci_g[0]:.6f}, {ci_g[1]:.6f}] bps")
        print(f"Net (taker): {mean_nt:.6f} bps")
        print(f"Net (maker): {mean_nm:.6f} bps")
        print(f"Break-even cost: {break_even:.6f} bps")
        print(f"Max favorable: {max_fav:.4f} bps")
        print(f"Max adverse: {max_adv:.4f} bps")
        print(f"Time to peak: {t_peak:.0f} ms")
        print(f"Time to adverse: {t_adv:.0f} ms")
        print(f"Sessions positive: {(by_sess['gross'] > 0).sum()}/{len(by_sess)}")

    # Summary table
    print(f"\n{'='*70}")
    print(f"SUMMARY TABLE")
    print(f"{'='*70}")
    print(f"{'Horizon':>10} {'N':>6} {'Gross':>8} {'Median':>8} {'Std':>8} {'Frac+':>8} {'t-stat':>8} {'p-val':>8} {'Net(T)':>8} {'Net(M)':>8} {'BE Cost':>8}")
    print(f"{'-'*90}")
    for s in summary:
        print(f"{s['horizon_ms']:>10} {s['n']:>6} {s['gross_bps']:>8.4f} {s['median_bps']:>8.4f} {s['std_bps']:>8.4f} {s['frac_positive']:>8.4f} {s['t_stat']:>8.4f} {s['p_value']:>8.4f} {s['net_taker_bps']:>8.4f} {s['net_maker_bps']:>8.4f} {s['break_even_cost']:>8.4f}")

    # Save results
    for h_ms, df in dfs.items():
        if len(df) > 0:
            df.to_csv(f'data/research/horizon_audit_{h_ms}ms.csv', index=False)
    print(f"\nSaved results to data/research/horizon_audit_*.csv")

if __name__ == "__main__":
    main()
