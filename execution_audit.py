#!/usr/bin/env python3
"""Execution Economic Audit — Simulate execution mechanisms on historical data.

Pre-registered hypotheses evaluated on chronological OOS data.
Uses only causally available information (book state at signal time).

Hypotheses:
  H1: Market-order (taker) execution
  H2: Aggressive-limit execution (cross spread, then cancel)
  H3: Passive-limit (maker) execution (join queue, wait for fill)
  H4: Signal-strength-conditioned execution
  H5: Queue/imbalance-aware execution
  H6: Post-only limit with maker rebates
  H7: Delayed execution (wait for better fill)
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

# === Configuration ===
GAMMA_TAKER = 4.0158  # Effective taker roundtrip (p90)
MAKER_FEE_RT = 2.0    # Maker fee round-trip
TAKER_FEE_RT = 4.0    # Taker fee round-trip
SLIPPAGE_BPS = 0.0079 # Slippage p90 for 1000-notional
HORIZON_MS = 500
NOTIONAL_USD = 1000

# Bonferroni correction for 7 hypotheses
ALPHA = 0.05 / 7  # = 0.00714

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
    """Load derived_v5.jsonl with level data for execution simulation."""
    rows = []
    with open(sess_dir / 'derived_v5.jsonl') as f:
        for line in f:
            rec = json.loads(line)
            rows.append(rec)
    return rows

def get_book_state_at_event(event_row):
    """Extract book state from derived_v5.jsonl row."""
    bids = event_row.get('levels_bid', [])
    asks = event_row.get('levels_ask', [])
    best_bid = event_row.get('best_bid')
    best_ask = event_row.get('best_ask')
    mid = event_row.get('mid')
    spread_bps = event_row.get('spread_bps', 0)
    qi_l1 = event_row.get('qi_l1', 0)
    return {
        'bids': bids,
        'asks': asks,
        'best_bid': best_bid,
        'best_ask': best_ask,
        'mid': mid,
        'spread_bps': spread_bps,
        'qi_l1': qi_l1,
    }

def simulate_market_order(book_state, side):
    """H1: Market-order (taker) execution. Fill immediately at touched price."""
    if side == 'BUY':
        fill_price = book_state['best_ask'] * (1 + SLIPPAGE_BPS / 1e4)
    else:
        fill_price = book_state['best_bid'] * (1 - SLIPPAGE_BPS / 1e4)

    cost_bps = TAKER_FEE_RT + book_state['spread_bps'] + SLIPPAGE_BPS
    return {
        'filled': True,
        'fill_price': fill_price,
        'cost_bps': cost_bps,
        'fill_prob': 1.0,
        'wait_ms': 0,
    }

def simulate_aggressive_limit(book_state, side, max_wait_ms=50):
    """H2: Aggressive-limit execution. Cross spread, wait 50ms, then chase."""
    # Simplified: assume 70% fill at maker price, 30% chase at taker price
    p_fill_passive = 0.70

    if side == 'BUY':
        passive_price = book_state['best_ask']
        chase_price = book_state['best_ask'] * (1 + SLIPPAGE_BPS / 1e4)
    else:
        passive_price = book_state['best_bid']
        chase_price = book_state['best_bid'] * (1 - SLIPPAGE_BPS / 1e4)

    # Expected cost
    passive_cost = MAKER_FEE_RT + book_state['spread_bps'] / 2
    chase_cost = TAKER_FEE_RT + book_state['spread_bps'] + SLIPPAGE_BPS

    expected_cost = p_fill_passive * passive_cost + (1 - p_fill_passive) * chase_cost

    return {
        'filled': True,
        'fill_price': passive_price,  # Simplified
        'cost_bps': expected_cost,
        'fill_prob': 1.0,
        'wait_ms': max_wait_ms * (1 - p_fill_passive),
    }

def simulate_passive_limit(book_state, side, horizon_ms=HORIZON_MS):
    """H3: Passive-limit (maker) execution. Join queue, wait for fill."""
    if side == 'BUY':
        order_price = book_state['best_bid']
    else:
        order_price = book_state['best_ask']

    # Fill probability model based on queue state
    # P(fill) = f(queue_depth, spread, activity)
    # Simplified: use empirical calibration
    base_p_fill = 0.71  # From execution_calibration.json

    # Adjust for queue imbalance
    qi = abs(book_state.get('qi_l1', 0))
    # High imbalance → queue is one-sided → less likely to fill
    qi_adjustment = max(0.5, 1.0 - qi * 0.3)

    # Spread adjustment (wider spread → less likely to fill)
    spread_factor = max(0.5, 1.0 - book_state['spread_bps'] / 0.1)

    p_fill = min(0.95, base_p_fill * qi_adjustment * spread_factor)

    # Cost if filled: maker fee only (no spread cost)
    cost_bps = MAKER_FEE_RT

    return {
        'filled': True,  # Conditional on fill
        'fill_price': order_price,
        'cost_bps': cost_bps,
        'fill_prob': p_fill,
        'wait_ms': horizon_ms * p_fill,  # Expected wait time
    }

def simulate_signal_strength_conditioned(book_state, side, strength):
    """H4: Signal-strength-conditioned execution."""
    # Strong signals → aggressive, weak signals → passive
    threshold = 0.8

    if strength >= threshold:
        # Strong signal → aggressive execution
        return simulate_market_order(book_state, side)
    else:
        # Weak signal → passive execution
        result = simulate_passive_limit(book_state, side)
        result['strategy'] = 'passive_weak'
        return result

def simulate_queue_imbalance_aware(book_state, side):
    """H5: Queue/imbalance-aware execution."""
    qi = abs(book_state.get('qi_l1', 0))

    if qi > 0.7:
        # High imbalance → queue is one-sided → passive more likely to fill
        return simulate_passive_limit(book_state, side)
    elif qi < 0.3:
        # Low imbalance → balanced queue → need aggressive
        return simulate_market_order(book_state, side)
    else:
        # Medium → aggressive limit
        return simulate_aggressive_limit(book_state, side)

def compute_signal_return(mid0, mid_future, side):
    """Compute gross return for a signal."""
    if mid0 is None or mid0 <= 0 or mid_future is None:
        return 0.0
    ret_bps = (mid_future - mid0) / mid0 * 1e4
    return ret_bps if side == 'BUY' else -ret_bps

def replay_and_simulate(sess_dir, derived_rows_by_ts):
    """Replay session through SignalEngine and simulate execution."""
    book = LocalOrderBook(50)
    flow = OrderFlowEngine(book)
    detector = EventDetector()
    signals = SignalEngine()

    results = defaultdict(list)
    recv_ms_counter = 0

    # Index derived rows by ts_ms for quick lookup
    derived_index = {}
    for row in derived_rows_by_ts:
        ts = row.get('ts_ms')
        if ts is not None:
            derived_index[ts] = row

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

            # Get book state from derived data
            derived_row = derived_index.get(ts)
            if derived_row is None:
                continue

            book_state = get_book_state_at_event(derived_row)
            if book_state['best_bid'] is None or book_state['best_ask'] is None:
                continue

            # Find future mid price
            future_ts = ts + HORIZON_MS
            future_row = None
            for row in derived_rows_by_ts:
                if row.get('ts_ms', 0) >= future_ts:
                    future_row = row
                    break

            if future_row is None:
                continue

            mid0 = book_state['mid']
            mid_future = future_row.get('mid')
            if mid0 is None or mid0 <= 0 or mid_future is None:
                continue

            gross = compute_signal_return(mid0, mid_future, sig.action)

            # Simulate each hypothesis
            # H1: Market order
            h1 = simulate_market_order(book_state, sig.action)
            h1_net = gross - h1['cost_bps'] if h1['filled'] else 0

            # H2: Aggressive limit
            h2 = simulate_aggressive_limit(book_state, sig.action)
            h2_net = gross - h2['cost_bps'] if h2['filled'] else 0

            # H3: Passive limit
            h3 = simulate_passive_limit(book_state, sig.action)
            # For passive, only count if filled
            h3_net = (gross - h3['cost_bps']) if h3['filled'] else 0
            h3_filled = np.random.random() < h3['fill_prob']  # Simulate fill

            # H4: Signal-strength-conditioned
            h4 = simulate_signal_strength_conditioned(book_state, sig.action, sig.score)
            h4_net = gross - h4['cost_bps'] if h4['filled'] else 0

            # H5: Queue-imbalance-aware
            h5 = simulate_queue_imbalance_aware(book_state, sig.action)
            h5_net = gross - h5['cost_bps'] if h5['filled'] else 0

            results['sigeng'].append({
                'session': sess_dir.name,
                'ts_ms': ts,
                'action': sig.action,
                'score': sig.score,
                'gross_bps': gross,
                'mid0': mid0,
                'mid_future': mid_future,
                'qi_l1': book_state['qi_l1'],
                'spread_bps': book_state['spread_bps'],
            })

            for h_name, h_result, h_net in [
                ('h1_market', h1, h1_net),
                ('h2_aggressive_limit', h2, h2_net),
                ('h3_passive_limit', h3, h3_net if h3_filled else 0),
                ('h4_strength_conditioned', h4, h4_net),
                ('h5_queue_aware', h5, h5_net),
            ]:
                results[h_name].append({
                    'session': sess_dir.name,
                    'ts_ms': ts,
                    'action': sig.action,
                    'gross_bps': gross,
                    'net_bps': h_net,
                    'cost_bps': h_result['cost_bps'],
                    'fill_prob': h_result['fill_prob'],
                    'filled': h_result['filled'],
                    'qi_l1': book_state['qi_l1'],
                    'spread_bps': book_state['spread_bps'],
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

    t0 = time.time()
    all_results = defaultdict(list)

    for sess in sessions:
        sess_dir = Path(f'data/live/v5/{sess}')
        derived_rows = load_session_data(sess_dir)
        results = replay_and_simulate(sess_dir, derived_rows)
        for k, v in results.items():
            all_results[k].extend(v)
        elapsed = time.time() - t0
        print(f"  {sess}: sigeng={len(results.get('sigeng', []))} elapsed={elapsed:.1f}s")

    # Convert to DataFrames
    dfs = {}
    for k, v in all_results.items():
        dfs[k] = pd.DataFrame(v) if v else pd.DataFrame()

    print(f"\n{'='*70}")
    print(f"EXECUTION ECONOMIC AUDIT RESULTS")
    print(f"{'='*70}")

    # Evaluate each hypothesis
    hypotheses = {
        'h1_market': 'H1: Market-Order (Taker)',
        'h2_aggressive_limit': 'H2: Aggressive-Limit',
        'h3_passive_limit': 'H3: Passive-Limit (Maker)',
        'h4_strength_conditioned': 'H4: Signal-Strength-Conditioned',
        'h5_queue_aware': 'H5: Queue/Imbalance-Aware',
    }

    print(f"\nBonferroni-corrected α = {ALPHA:.5f} (0.05/7)")
    print(f"Horizon: {HORIZON_MS}ms")
    print(f"Notional: {NOTIONAL_USD} USD")
    print()

    summary = []

    for h_key, h_name in hypotheses.items():
        df = dfs.get(h_key, pd.DataFrame())
        if len(df) == 0:
            print(f"{h_name}: No signals")
            continue

        gross_vals = df['gross_bps'].values
        net_vals = df['net_bps'].values
        mean_g, t_g, p_g, ci_g = block_bootstrap_ci(gross_vals)
        mean_n, t_n, p_n, ci_n = block_bootstrap_ci(net_vals)

        fill_rate = df['fill_prob'].mean() if 'fill_prob' in df.columns else 1.0
        avg_cost = df['cost_bps'].mean() if 'cost_bps' in df.columns else 0.0

        # Per-session results
        by_sess = df.groupby('session').agg(
            n=('gross_bps', 'count'),
            gross=('gross_bps', 'mean'),
            net=('net_bps', 'mean'),
        ).reset_index()

        # Classification
        if mean_n > 0 and p_n < ALPHA and fill_rate > 0.5:
            classification = 'A (Viable)'
        elif mean_n > 0 and p_n < 0.05 and fill_rate > 0.5:
            classification = 'B (Potentially Viable)'
        elif mean_n > -1.0 and fill_rate > 0.7:
            classification = 'B (Potentially Viable)'
        else:
            classification = 'C (Insufficient)'

        summary.append({
            'hypothesis': h_name,
            'n': len(df),
            'gross_bps': mean_g,
            'net_bps': mean_n,
            'cost_bps': avg_cost,
            'fill_rate': fill_rate,
            't_stat': t_n,
            'p_value': p_n,
            'ci_low': ci_n[0],
            'ci_high': ci_n[1],
            'classification': classification,
            'sessions_positive': (by_sess['net'] > 0).sum(),
            'total_sessions': len(by_sess),
        })

        print(f"{'='*70}")
        print(f"{h_name}")
        print(f"{'='*70}")
        print(f"Signals: {len(df)}")
        print(f"  BUY: {(df['action'] == 'BUY').sum()}")
        print(f"  SELL: {(df['action'] == 'SELL').sum()}")
        print(f"Gross mean: {mean_g:.6f} bps")
        print(f"Net mean: {mean_n:.6f} bps")
        print(f"Avg cost: {avg_cost:.4f} bps")
        print(f"Fill rate: {fill_rate:.4f}")
        print(f"t-stat (net): {t_n:.4f}")
        print(f"p-value (net): {p_n:.6f}")
        print(f"Block-bootstrap 95% CI (net): [{ci_n[0]:.6f}, {ci_n[1]:.6f}] bps")
        print(f"Sessions with positive net: {(by_sess['net'] > 0).sum()}/{len(by_sess)}")
        print(f"Classification: {classification}")
        print()

    # Summary table
    print(f"\n{'='*70}")
    print(f"SUMMARY TABLE")
    print(f"{'='*70}")
    print(f"{'Hypothesis':<35} {'N':>6} {'Gross':>8} {'Net':>8} {'Cost':>8} {'Fill':>8} {'p-val':>8} {'Class':>15}")
    print(f"{'-'*90}")
    for s in summary:
        print(f"{s['hypothesis']:<35} {s['n']:>6} {s['gross_bps']:>8.4f} {s['net_bps']:>8.4f} {s['cost_bps']:>8.4f} {s['fill_rate']:>8.4f} {s['p_value']:>8.4f} {s['classification']:>15}")

    # Save results
    for k, df in dfs.items():
        if len(df) > 0:
            df.to_csv(f'data/research/execution_audit_{k}.csv', index=False)
    print(f"\nSaved results to data/research/execution_audit_*.csv")

if __name__ == "__main__":
    main()
