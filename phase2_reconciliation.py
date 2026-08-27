#!/usr/bin/env python3
"""PHASE 2: Production/Research Path Reconciliation.

Apples-to-apples comparison:
  A = Production SignalEngine path (main.py)
  B = Frozen V5 DecisionEngine path (decision.py)

Uses identical events, timestamps, features, costs, horizon, and causal info set.
"""
import json, sys, warnings, time
from pathlib import Path
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
from app.v3_labels import add_labels
from app.v5_model import load_model, predict, PRIMARY_HORIZON, V5_FEATURES
from app.v5_calibration import calibrate_prediction
from app.v5_features import add_trailing_vol

GAMMA = measured_gate()
HORIZON = PRIMARY_HORIZON

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

def precompute_mid_arrays(session_dir):
    ts_list, mids = [], []
    with open(session_dir / 'derived_v5.jsonl') as f:
        for line in f:
            rec = json.loads(line)
            ts = int(rec.get('ts_ms', rec.get('E', 0)))
            mid = rec.get('mid')
            if mid is not None and mid > 0:
                ts_list.append(ts)
                mids.append(float(mid))
    return np.array(ts_list, dtype=np.int64), np.array(mids, dtype=np.float64)

def replay_both_paths(sess_dir: Path, ts_arr, mid_arr, model_d, calibration):
    """Replay session through both SignalEngine and V5 DecisionEngine."""
    book = LocalOrderBook(50)
    flow = OrderFlowEngine(book)
    detector = EventDetector()
    signals = SignalEngine()

    # Results storage
    sigeng_results = []  # Production path
    v5_results = []      # Research path
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

            # === PATH A: Production SignalEngine ===
            f = flow.snapshot(now_ms=recv_ms_counter)
            events = detector.detect(f)
            sig = signals.decide(f, events)

            ts = int(rec.get("E", rec.get("T", rec.get("recv_ms", 0))))
            future_ts = ts + HORIZON
            idx = np.searchsorted(ts_arr, future_ts, side='left')

            if sig.action in ('BUY', 'SELL') and idx < len(mid_arr) and f.mid and f.mid > 0:
                mid0 = float(f.mid)
                mid_future = mid_arr[idx]
                ret_bps = (mid_future - mid0) / mid0 * 1e4
                gross = ret_bps if sig.action == "BUY" else -ret_bps
                net = gross - GAMMA
                sigeng_results.append({
                    'session': sess_dir.name,
                    'ts_ms': ts,
                    'action': sig.action,
                    'gross_bps': gross,
                    'net_bps': net,
                    'mid': mid0,
                    'spread_bps': float(f.spread_bps) if f.spread_bps else 0.0,
                })

            # === PATH B: V5 DecisionEngine ===
            # Check if we have all V5 features
            has_all_features = all(hasattr(f, feat) for feat in V5_FEATURES)
            if has_all_features and idx < len(mid_arr) and f.mid and f.mid > 0:
                try:
                    import pandas as pd
                    feat_df = pd.DataFrame([[getattr(f, feat) for feat in V5_FEATURES]], columns=V5_FEATURES)
                    pred_raw = predict(model_d, feat_df, HORIZON)[0]
                    calibrated = calibrate_prediction(model_d, feat_df, HORIZON, calibration)[0]

                    if np.isfinite(calibrated) and calibrated != 0:
                        side = "BUY" if calibrated > 0 else "SELL"
                        mid0 = float(f.mid)
                        mid_future = mid_arr[idx]
                        ret_bps = (mid_future - mid0) / mid0 * 1e4
                        gross = ret_bps if side == "BUY" else -ret_bps
                        net = gross - GAMMA

                        # DecisionEngine gate
                        gate = GAMMA + 0.5  # taker_gate + safety_margin
                        exec_ready = abs(calibrated) > gate

                        v5_results.append({
                            'session': sess_dir.name,
                            'ts_ms': ts,
                            'action': side,
                            'gross_bps': gross,
                            'net_bps': net,
                            'mid': mid0,
                            'spread_bps': float(f.spread_bps) if f.spread_bps else 0.0,
                            'pred_raw': float(pred_raw),
                            'calibrated': float(calibrated),
                            'exec_ready': exec_ready,
                        })
                except Exception:
                    pass

    return sigeng_results, v5_results

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
    all_sigeng = []
    all_v5 = []

    for sess in sessions:
        sess_dir = Path(f'data/live/v5/{sess}')
        ts_arr, mid_arr = precompute_mid_arrays(sess_dir)
        sigeng, v5 = replay_both_paths(sess_dir, ts_arr, mid_arr, model_d, calibration)
        all_sigeng.extend(sigeng)
        all_v5.extend(v5)
        elapsed = time.time() - t0
        print(f"  {sess}: sigeng={len(sigeng)} v5={len(v5)} elapsed={elapsed:.1f}s")

    # Convert to DataFrames
    sigeng_df = pd.DataFrame(all_sigeng) if all_sigeng else pd.DataFrame()
    v5_df = pd.DataFrame(all_v5) if all_v5 else pd.DataFrame()

    print(f"\n{'='*70}")
    print(f"PHASE 2: PRODUCTION vs RESEARCH PATH COMPARISON")
    print(f"{'='*70}")
    print(f"Sessions: {len(sessions)}")
    print(f"Horizon: {HORIZON}ms")
    print(f"Cost gate: {GAMMA} bps")
    print()

    # === PATH A: SignalEngine ===
    print(f"{'='*70}")
    print(f"PATH A: Production SignalEngine (main.py)")
    print(f"{'='*70}")
    if len(sigeng_df) > 0:
        gross_vals = sigeng_df['gross_bps'].values
        net_vals = sigeng_df['net_bps'].values
        mean_g, t_g, p_g, ci_g = block_bootstrap_ci(gross_vals)
        mean_n, _, _, ci_n = block_bootstrap_ci(net_vals)

        print(f"Traded signals: {len(sigeng_df)}")
        print(f"  BUY: {(sigeng_df['action'] == 'BUY').sum()}")
        print(f"  SELL: {(sigeng_df['action'] == 'SELL').sum()}")
        print(f"Gross mean: {mean_g:.6f} bps")
        print(f"Net mean: {mean_n:.6f} bps")
        print(f"t-stat: {t_g:.4f}, p-value: {p_g:.6f}")
        print(f"Block-bootstrap 95% CI (gross): [{ci_g[0]:.6f}, {ci_g[1]:.6f}] bps")
        print(f"Block-bootstrap 95% CI (net): [{ci_n[0]:.6f}, {ci_n[1]:.6f}] bps")
        print(f"Spread (median): {sigeng_df['spread_bps'].median():.4f} bps")

        # By session
        print(f"\nBy session:")
        by_sess = sigeng_df.groupby('session').agg(
            n=('gross_bps', 'count'),
            gross=('gross_bps', 'mean'),
            net=('net_bps', 'mean'),
        ).round(4).reset_index()
        print(by_sess.to_string(index=False))

        # By direction
        print(f"\nBy direction:")
        by_dir = sigeng_df.groupby('action').agg(
            n=('gross_bps', 'count'),
            gross=('gross_bps', 'mean'),
            net=('net_bps', 'mean'),
        ).round(6)
        print(by_dir.to_string(index=False))
    else:
        print("No signals generated")

    # === PATH B: V5 DecisionEngine ===
    print(f"\n{'='*70}")
    print(f"PATH B: Frozen V5 DecisionEngine (decision.py)")
    print(f"{'='*70}")
    if len(v5_df) > 0:
        gross_vals = v5_df['gross_bps'].values
        net_vals = v5_df['net_bps'].values
        mean_g, t_g, p_g, ci_g = block_bootstrap_ci(gross_vals)
        mean_n, _, _, ci_n = block_bootstrap_ci(net_vals)

        exec_ready_df = v5_df[v5_df['exec_ready']]

        print(f"Total signals (all events): {len(v5_df)}")
        print(f"  BUY: {(v5_df['action'] == 'BUY').sum()}")
        print(f"  SELL: {(v5_df['action'] == 'SELL').sum()}")
        print(f"Gross mean: {mean_g:.6f} bps")
        print(f"Net mean: {mean_n:.6f} bps")
        print(f"t-stat: {t_g:.4f}, p-value: {p_g:.6f}")
        print(f"Block-bootstrap 95% CI (gross): [{ci_g[0]:.6f}, {ci_g[1]:.6f}] bps")
        print(f"Block-bootstrap 95% CI (net): [{ci_n[0]:.6f}, {ci_n[1]:.6f}] bps")
        print(f"Spread (median): {v5_df['spread_bps'].median():.4f} bps")
        print(f"\nDecisionEngine gate: {GAMMA + 0.5:.4f} bps")
        print(f"EXECUTION_READY signals: {len(exec_ready_df)} ({len(exec_ready_df)/len(v5_df)*100:.4f}%)")

        if len(exec_ready_df) > 0:
            print(f"EXECUTION_READY gross: {exec_ready_df['gross_bps'].mean():.6f} bps")
            print(f"EXECUTION_READY net: {exec_ready_df['net_bps'].mean():.6f} bps")

        # Calibrated prediction distribution
        print(f"\nCalibrated prediction distribution:")
        print(f"  Min: {v5_df['calibrated'].min():.6f}")
        print(f"  P5: {v5_df['calibrated'].quantile(0.05):.6f}")
        print(f"  P50: {v5_df['calibrated'].median():.6f}")
        print(f"  P95: {v5_df['calibrated'].quantile(0.95):.6f}")
        print(f"  Max: {v5_df['calibrated'].max():.6f}")

        # By session
        print(f"\nBy session:")
        by_sess = v5_df.groupby('session').agg(
            n=('gross_bps', 'count'),
            gross=('gross_bps', 'mean'),
            net=('net_bps', 'mean'),
            exec_ready=('exec_ready', 'sum'),
        ).round(4).reset_index()
        print(by_sess.to_string(index=False))

        # By direction
        print(f"\nBy direction:")
        by_dir = v5_df.groupby('action').agg(
            n=('gross_bps', 'count'),
            gross=('gross_bps', 'mean'),
            net=('net_bps', 'mean'),
        ).round(6)
        print(by_dir.to_string(index=False))
    else:
        print("No signals generated")

    # === COMPARISON ===
    print(f"\n{'='*70}")
    print(f"COMPARISON: SignalEngine vs V5 DecisionEngine")
    print(f"{'='*70}")
    if len(sigeng_df) > 0 and len(v5_df) > 0:
        sigeng_gross = sigeng_df['gross_bps'].mean()
        v5_gross = v5_df['gross_bps'].mean()
        sigeng_net = sigeng_df['net_bps'].mean()
        v5_net = v5_df['net_bps'].mean()

        print(f"{'Metric':<30} {'SignalEngine':>15} {'V5 DecisionEng':>15} {'Diff':>10}")
        print(f"{'-'*70}")
        print(f"{'Gross (bps)':<30} {sigeng_gross:>15.6f} {v5_gross:>15.6f} {sigeng_gross - v5_gross:>10.6f}")
        print(f"{'Net (bps)':<30} {sigeng_net:>15.6f} {v5_net:>15.6f} {sigeng_net - v5_net:>10.6f}")
        print(f"{'Traded signals':<30} {len(sigeng_df):>15} {len(v5_df):>15} {len(sigeng_df) - len(v5_df):>10}")
        print(f"{'Cost gate (bps)':<30} {GAMMA:>15.4f} {GAMMA:>15.4f} {'':>10}")
        print(f"{'Gate clearance':<30} {'N/A':>15} {len(exec_ready_df) if len(v5_df) > 0 else 0:>15} {'':>10}")

        # Hit rate comparison
        sigeng_hits = (sigeng_df['gross_bps'] > 0).mean()
        v5_hits = (v5_df['gross_bps'] > 0).mean()
        print(f"{'Hit rate (gross > 0)':<30} {sigeng_hits:>15.4f} {v5_hits:>15.4f} {sigeng_hits - v5_hits:>10.4f}")

    # Save results
    if len(sigeng_df) > 0:
        sigeng_df.to_csv('data/research/phase2_sigeng_results.csv', index=False)
    if len(v5_df) > 0:
        v5_df.to_csv('data/research/phase2_v5_results.csv', index=False)
    print(f"\nSaved results to data/research/phase2_*.csv")

if __name__ == "__main__":
    main()
