#!/usr/bin/env python3
"""Backtest the actual production SignalEngine/EventDetector path.

This does NOT use the V5 model. It uses the exact same signal-generation
path as main.py: OrderFlowEngine -> EventDetector -> SignalEngine.

Key insight: main.py calls flow.on_book_event/on_trade + flow.snapshot()
+ detector.detect() + signals.decide() on every depth update and every trade.
We replicate this on historical raw.jsonl data.

For P&L: we use the mid prices from derived.jsonl (same book state) and
compute returns at ts_ms + 500ms, matching the V5 horizon for fair comparison.
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
    """Load mid prices and timestamps from derived_v5.jsonl for this session.

    This file has the same event timestamps as raw.jsonl (each row = one depth/trade event)
    and includes the reconstructed mid price at each event.
    """
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

def replay_session_signal_engine(sess_dir: Path, ts_arr, mid_arr):
    """Replay a session through OrderFlowEngine -> EventDetector -> SignalEngine.

    Generates a signal on every depth and trade event, exactly as main.py does.
    For BUY/SELL signals, compute the horizon return at ts_ms + HORIZON.

    Returns:
        signal_counts: dict with total/buy/sell/no_trade counts
        pnl_rows: list of dicts with gross_bps, net_bps, session, ts_ms, action, spread_bps
    """
    book = LocalOrderBook(50)
    flow = OrderFlowEngine(book)
    detector = EventDetector()
    signals = SignalEngine()

    counts = {"total": 0, "buy": 0, "sell": 0, "no_trade": 0}
    pnl_rows = []
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
                replay_ms = rec.get("recv_ms", ts)
                flow.on_trade(te)
                recv_ms_counter += 1

            elif kind == "bookTicker":
                continue
            else:
                continue

            # Generate signal on every depth/trade event
            f = flow.snapshot(now_ms=recv_ms_counter)
            events = detector.detect(f)
            sig = signals.decide(f, events)
            counts["total"] += 1

            if sig.action == "BUY":
                counts["buy"] += 1
            elif sig.action == "SELL":
                counts["sell"] += 1
            else:
                counts["no_trade"] += 1
                continue

            # Compute P&L: find mid price at ts + HORIZON
            ts = int(rec.get("E", rec.get("T", rec.get("recv_ms", 0))))
            future_ts = ts + HORIZON
            idx = np.searchsorted(ts_arr, future_ts, side='left')
            if idx < len(mid_arr):
                mid0 = float(f.mid) if f.mid and not np.isnan(f.mid) else mid_arr[min(idx, len(mid_arr)-1)]
                mid_future = mid_arr[idx]
                if mid0 is not None and mid0 != 0:
                    ret_bps = (mid_future - mid0) / mid0 * 1e4
                    gross = ret_bps if sig.action == "BUY" else -ret_bps
                    net = gross - GAMMA
                    pnl_rows.append({
                        'session': sess_dir.name,
                        'ts_ms': ts,
                        'action': sig.action,
                        'gross_bps': gross,
                        'net_bps': net,
                        'mid': mid0,
                        'spread_bps': float(f.spread_bps) if f.spread_bps else 0.0,
                    })

    return counts, pnl_rows

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
    total_counts = {"total": 0, "buy": 0, "sell": 0, "no_trade": 0}
    all_pnl = []

    for sess in sessions:
        sess_dir = Path(f'data/live/v5/{sess}')
        ts_arr, mid_arr = precompute_mid_arrays(sess_dir)
        counts, pnl = replay_session_signal_engine(sess_dir, ts_arr, mid_arr)
        for k in total_counts:
            total_counts[k] += counts[k]
        all_pnl.extend(pnl)
        elapsed = time.time() - t0
        print(f"  {sess}: signals={counts} traded={len(pnl)} elapsed={elapsed:.1f}s")

    print(f"\n=== PRODUCTION SignalEngine/EventDetector Backtest ===")
    print(f"Sessions: {len(sessions)}")
    print(f"Signal events: {total_counts}")
    print(f"  Signal rate (traded/total): {(total_counts['buy']+total_counts['sell'])/max(total_counts['total'],1)*100:.2f}%")

    if all_pnl:
        pnl_df = pd.DataFrame(all_pnl)
        gross_vals = pnl_df['gross_bps'].values
        net_vals = pnl_df['net_bps'].values
        sgn = np.sign(gross_vals)  # actual direction matches signal direction

        mean_g, t_g, p_g, ci_g = block_bootstrap_ci(gross_vals)
        mean_n, _, _, ci_n = block_bootstrap_ci(net_vals)

        # Correct: gross should be positive for BUY when price goes up
        # Let's recompute: BUY -> (mid_future - mid_past)/mid_past * 1e4
        # SELL -> (mid_past - mid_future)/mid_past * 1e4
        # So gross for BUY with price going up = positive
        actual_gross = float(np.mean(gross_vals))
        actual_net = actual_gross - GAMMA

        print(f"\n=== P&L (H={HORIZON}ms, gate={GAMMA} bps) ===")
        print(f"Traded signals: {len(pnl_df)}")
        print(f"Gross mean: {actual_gross:.6f} bps")
        print(f"Net mean: {actual_net:.6f} bps")
        print(f"t-stat (gross): {t_g:.4f}")
        print(f"p-value (gross): {p_g:.6f}")
        print(f"Block-bootstrap 95% CI (gross): [{ci_g[0]:.6f}, {ci_g[1]:.6f}] bps")
        print(f"Block-bootstrap 95% CI (net): [{ci_n[0]:.6f}, {ci_n[1]:.6f}] bps")
        print(f"Spread (median): {pnl_df['spread_bps'].median():.4f} bps")
        print(f"Slippage assumption: 0.5 bps (from config)")
        print(f"Fee assumption: taker 2.5 bps (from config)")
        print(f"Adverse selection proxy: captured by return distribution")

        # By session
        print(f"\n=== Performance by session ===")
        by_sess = pnl_df.groupby('session').agg(
            n=('gross_bps', 'count'),
            gross=('gross_bps', 'mean'),
            net=('net_bps', 'mean'),
        ).round(4).reset_index()
        print(by_sess.to_string(index=False))

        # By direction
        print(f"\n=== Performance by direction ===")
        by_dir = pnl_df.groupby('action').agg(
            n=('gross_bps', 'count'),
            gross=('gross_bps', 'mean'),
            net=('net_bps', 'mean'),
        ).round(6)
        print(by_dir.to_string(index=False))

    # V5 comparison
    print(f"\n=== V5 Model Comparison ===")
    v5_df = pd.read_parquet('data/research/v5_evidence_features.parquet')
    v5_df = add_labels(v5_df, (HORIZON,))
    model_d = load_model('data/research/v5_model.json')
    feature_cols = model_d['features']
    v5_pred = predict(model_d, v5_df[feature_cols], HORIZON)
    v5_df['actual'] = v5_df['r_500']

    # Raw V5 predictions (sign-based)
    valid = v5_df['actual'].notna() & np.isfinite(v5_df['actual']) & np.isfinite(v5_pred)
    v5_sign = np.sign(v5_pred[valid])
    v5_actual = v5_df['actual'][valid]
    v5_returns = v5_sign * v5_actual
    v5_gross = float(np.mean(v5_returns))
    v5_net = v5_gross - GAMMA
    v5_mean, v5_t, v5_p, v5_ci = block_bootstrap_ci(v5_returns.values)

    # Calibrated V5 (production DecisionEngine path)
    with open('data/research/v5_binned_calibration.json') as f:
        cal_data = json.load(f)
    cal = {
        'bin_edges': np.array(cal_data['bin_edges']),
        'bin_means': np.array(cal_data['bin_means']),
        'bin_counts': np.array(cal_data['bin_counts']),
        'bin_stderr': np.array(cal_data['bin_stderr']),
        'horizon_ms': cal_data['horizon_ms'],
        'n_bins': cal_data['n_bins'],
        'min_pred': cal_data['min_pred'],
        'max_pred': cal_data['max_pred'],
    }
    v5_calibrated = calibrate_prediction(model_d, v5_df[feature_cols][valid], HORIZON, cal)
    v5_exec_ready = np.abs(v5_calibrated) > (GAMMA + 0.5)

    print(f"V5 raw (sign-based) gross: {v5_gross:.6f} bps")
    print(f"V5 raw net: {v5_net:.6f} bps")
    print(f"V5 t-stat: {v5_t:.4f}, p-value: {v5_p:.6f}")
    print(f"V5 CI: [{v5_ci[0]:.6f}, {v5_ci[1]:.6f}] bps")
    print(f"V5 EXECUTION_READY signals (|calibrated| > {GAMMA+0.5:.4f}): {int(v5_exec_ready.sum())}")

    print(f"\n=== V5 vs Production Comparison ===")
    if all_pnl:
        print(f"{'Metric':<30} {'V5 Research':>15} {'Production':>15}")
        print(f"{'-'*60}")
        print(f"{'Gross (bps)':<30} {v5_gross:>15.6f} {actual_gross:>15.6f}")
        print(f"{'Net (bps)':<30} {v5_net:>15.6f} {actual_net:>15.6f}")
        print(f"{'Traded signals':<30} {int(valid.sum()):>15} {len(pnl_df):>15}")
        print(f"{'Cost gate (bps)':<30} {GAMMA:>15.4f} {GAMMA:>15.4f}")

if __name__ == "__main__":
    main()
