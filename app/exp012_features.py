"""EXP-012: Aggressive Flow × Absorption Capacity × Liquidity Fragility features.

Research basis:
  - Cont, Kukanov & Stoikov (2013): Price impact linear in OFI, slope ~ 1/depth
  - Gould & Bonart (2016): Queue imbalance predicts next price move, with
    conditional regime structure
  - Binance microstructure research (2025): Spread attenuates predictability,
    depth regeneration speed determines resilience, high cancellation indicates
    fragility

New architecture: conditional market-state detection rather than raw OFI→trade.
Computes:
  AGGRESSIVE FLOW: taker buy/sell volume hitting the book
  ABSORPTION CAPACITY: depth available at the touch
  LIQUIDITY FRAGILITY: cancellation velocity, depth regeneration, spread dynamics
  STATE VARIABLES: flow/depth ratio, fragility score — the conditional gate

All features are computed causally from event streams with strict timestamp
ordering. No future information is used.
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from typing import List, Dict, Tuple, Optional


BPS = 1e4


def _price_bps(price: float, ref: float) -> float:
    """Convert price difference to bps relative to reference."""
    return (price - ref) / ref * BPS if ref and ref > 0 else 0.0


class EventBuffer:
    """Circular buffer for tracking recent trades and depth events."""

    def __init__(self, max_window_ms: int = 2000):
        self.max_window_ms = max_window_ms
        self.trades: List[Tuple[int, float, str, float]] = []  # (ts, qty, side, price)
        self.depth_events: List[Tuple[int, float, float, float, float]] = []  # (ts, mid, bid_cancel, ask_cancel, depth1)
        self.book_states: List[Dict] = []  # (ts, bid_depth_3, ask_depth_3, spread_bps)

    def prune(self, now_ts: int):
        cutoff = now_ts - self.max_window_ms
        self.trades = [t for t in self.trades if t[0] >= cutoff]
        self.depth_events = [d for d in self.depth_events if d[0] >= cutoff]
        self.book_states = [b for b in self.book_states if b[0] >= cutoff]

    def add_trade(self, ts: int, qty: float, side: str, price: float):
        self.trades.append((ts, qty, side, price))

    def add_depth(self, ts: int, mid: float, bid_cancel: float, ask_cancel: float, depth1: float):
        self.depth_events.append((ts, mid, bid_cancel, ask_cancel, depth1))

    def add_book_state(self, ts: int, bid_depth_3: float, ask_depth_3: float, spread_bps: float):
        self.book_states.append((ts, bid_depth_3, ask_depth_3, spread_bps))

    def agg_flow(self, ts: int, window_ms: int = 500) -> Dict[str, float]:
        """Compute aggregate flow within the window ending at ts."""
        cutoff = ts - window_ms
        window = [t for t in self.trades if t[0] >= cutoff and t[0] <= ts]
        vbuy = sum(t[1] for t in window if t[2] == "BUY")
        vsell = sum(t[1] for t in window if t[2] == "SELL")
        return {
            "aggressive_buy_flow": vbuy,
            "aggressive_sell_flow": vsell,
            "total_flow": vbuy + vsell,
            "flow_imbalance": (vbuy - vsell) / (vbuy + vsell + 1e-12),
            "trade_count": len(window),
        }

    def fragility_metrics(self, ts: int, window_ms: int = 1000) -> Dict[str, float]:
        """Compute liquidity fragility metrics from recent depth events."""
        cutoff = ts - window_ms
        window = [d for d in self.depth_events if d[0] >= cutoff and d[0] <= ts]
        if not window:
            return {
                "cancellation_velocity": 0.0,
                "avg_spread_bps": 0.0,
                "depth_volatility": 0.0,
                "half_life_events": 0,
            }

        total_cancel = sum(d[2] + d[3] for d in window)
        total_depth = sum(d[4] for d in window)
        avg_depth = np.mean([d[4] for d in window])
        cancel_rate = total_cancel / (total_depth + 1e-12)

        # Spread dynamics
        book_states = [b for b in self.book_states if b[0] >= cutoff and b[0] <= ts]
        avg_spread = np.mean([b[3] for b in book_states]) if book_states else 0.0
        spread_vol = np.std([b[3] for b in book_states]) if len(book_states) > 1 else 0.0

        # Depth volatility (top of book depth stability)
        depths = [b[1] + b[2] for b in book_states]
        depth_vol = np.std(depths) if len(depths) > 1 else 0.0

        return {
            "cancellation_velocity": cancel_rate,
            "avg_spread_bps": avg_spread,
            "spread_volatility": spread_vol,
            "depth_volatility": depth_vol,
            "half_life_events": len(window),
        }


def compute_event_features(raw_path: Path, session_id: str) -> List[Dict]:
    """Compute EXP-012 features from a raw event log.

    Events must be in chronological order. For each depth/trade event, we compute
    the conditional state features based on the event stream preceding it.

    Returns a list of feature dicts, one per event with ts_ms.
    """
    events = []
    with open(raw_path) as f:
        for line in f:
            line = line.strip()
            if line:
                events.append(json.loads(line))

    if not events:
        return []

    book = {}
    book['bids'] = {}
    book['asks'] = {}
    prev_levels_bid = []
    prev_levels_ask = []

    buffer = EventBuffer(max_window_ms=3000)
    rows = []

    for i, evt in enumerate(events):
        kind = evt.get('kind', '')

        if kind == 'snapshot':
            book['bids'] = {float(p): float(q) for p, q in evt.get('bids', [])}
            book['asks'] = {float(p): float(q) for p, q in evt.get('asks', [])}
            continue

        if kind == 'bookTicker':
            continue

        if not book['bids'] or not book['asks']:
            continue

        ts = evt.get('E', evt.get('T', 0))

        if kind == 'depth':
            U, u = evt.get('U', 0), evt.get('u', 0)
            bids = evt.get('bids', [])
            asks = evt.get('asks', [])

            # Apply updates to book
            for p, q in bids:
                p = float(p)
                q = float(q)
                if q == 0:
                    book['bids'].pop(p, None)
                else:
                    book['bids'][p] = q

            for p, q in asks:
                p = float(p)
                q = float(q)
                if q == 0:
                    book['asks'].pop(p, None)
                else:
                    book['asks'][p] = q

            # Compute book stats
            best_bid = max(book['bids'].keys()) if book['bids'] else 0
            best_ask = min(book['asks'].keys()) if book['asks'] else 0

            if best_bid >= best_ask:
                continue

            mid = (best_bid + best_ask) / 2
            spread_bps = (best_ask - best_bid) / mid * BPS

            bq1 = book['bids'].get(best_bid, 0.0)
            aq1 = book['asks'].get(best_ask, 0.0)
            depth1 = bq1 + aq1

            # Depth at 3 levels each side (absorption capacity)
            bid_prices = sorted(book['bids'].keys(), reverse=True)
            ask_prices = sorted(book['asks'].keys())
            bid_depth_3 = sum(book['bids'][p] for p in bid_prices[:3]) if bid_prices else 0
            ask_depth_3 = sum(book['asks'][p] for p in ask_prices[:3]) if ask_prices else 0

            # Compute cancellation from prev levels
            bid_cancel = 0.0
            ask_cancel = 0.0
            curr_levels_bid = [(p, q) for p, q in zip(bid_prices[:10], [book['bids'][p] for p in bid_prices[:10]])]
            curr_levels_ask = [(p, q) for p, q in zip(ask_prices[:10], [book['asks'][p] for p in ask_prices[:10]])]

            if prev_levels_bid and prev_levels_ask:
                prev_bid_dict = {p: q for p, q in prev_levels_bid}
                prev_ask_dict = {p: q for p, q in prev_levels_ask}
                for p, q in curr_levels_bid:
                    prev_q = prev_bid_dict.get(p, 0.0)
                    if q < prev_q:
                        bid_cancel += prev_q - q
                for p, q in curr_levels_ask:
                    prev_q = prev_ask_dict.get(p, 0.0)
                    if q < prev_q:
                        ask_cancel += prev_q - q

            prev_levels_bid = curr_levels_bid
            prev_levels_ask = curr_levels_ask

            buffer.add_depth(ts, mid, bid_cancel, ask_cancel, depth1)
            buffer.add_book_state(ts, bid_depth_3, ask_depth_3, spread_bps)

            flow = buffer.agg_flow(ts)
            frag = buffer.fragility_metrics(ts)

            # Key conditional state variables
            total_aggressive_flow = flow["aggressive_buy_flow"] + flow["aggressive_sell_flow"]
            absorption_capacity = depth1  # Can also use bid_depth_3 + ask_depth_3

            flow_to_depth = total_aggressive_flow / (absorption_capacity + 1e-12)

            # Direction of flow (buy/sell)
            flow_direction = 1.0 if flow["aggressive_buy_flow"] > flow["aggressive_sell_flow"] else -1.0

            # Directional absorption capacity
            if flow_direction > 0:
                directional_capacity = ask_depth_3
            else:
                directional_capacity = bid_depth_3

            directional_flow_to_depth = total_aggressive_flow / (directional_capacity + 1e-12)

            row = {
                "session": session_id,
                "ts_ms": ts,
                "kind": "depth",
                "seq": f"{U}-{u}",
                "best_bid": best_bid,
                "best_ask": best_ask,
                "mid": mid,
                "spread_bps": spread_bps,
                "depth1": depth1,
                # Aggressive flow metrics
                "aggressive_buy_flow": flow["aggressive_buy_flow"],
                "aggressive_sell_flow": flow["aggressive_sell_flow"],
                "total_aggressive_flow": total_aggressive_flow,
                "flow_imbalance": flow["flow_imbalance"],
                "trade_count_500": flow["trade_count"],
                # Absorption capacity
                "bid_depth_3": bid_depth_3,
                "ask_depth_3": ask_depth_3,
                "absorption_capacity": absorption_capacity,
                "directional_capacity": directional_capacity,
                # Conditional state (key hypothesis variables)
                "flow_to_depth_ratio": flow_to_depth,
                "directional_flow_depth_ratio": directional_flow_to_depth,
                "flow_direction": flow_direction,
                # Liquidity fragility
                "cancellation_velocity": frag["cancellation_velocity"],
                "avg_spread_bps": frag["avg_spread_bps"],
                "spread_volatility": frag["spread_volatility"],
                "depth_volatility": frag["depth_volatility"],
                # Queue imbalance (Gould-Bonart)
                "qi_l1": (bq1 - aq1) / (bq1 + aq1 + 1e-12) if (bq1 + aq1) > 0 else 0.0,
                # Microprice displacement
                "microb_price": (best_ask * bq1 + best_bid * aq1) / (bq1 + aq1) if (bq1 + aq1) > 0 else mid,
                "mpd_bps": _price_bps((best_ask * bq1 + best_bid * aq1) / (bq1 + aq1) if (bq1 + aq1) > 0 else mid, mid),
            }
            rows.append(row)

        elif kind == 'trade':
            taker_side = "SELL" if evt.get('m', False) else "BUY"
            price = float(evt.get('p', 0))
            qty = float(evt.get('q', 0))

            buffer.add_trade(ts, qty, taker_side, price)
            # No row for trade events — we compute features at depth events

    return rows


def build_exp012_features(session_dirs: List[Path], out_path: str | Path) -> Path:
    """Build EXP-012 features for all sessions.

    Only depth events receive feature rows (one row per book update), since
    the conditional state is evaluated at book states. Aggressive flow is
    accumulated from trade events in the preceding window.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    all_rows = []

    for sd in sorted(session_dirs):
        raw = sd / "raw.jsonl"
        if not raw.exists():
            continue

        session_id = sd.name
        rows = compute_event_features(raw, session_id)
        all_rows.extend(rows)
        print(f"  {session_id}: {len(rows)} event-level feature rows")

    if not all_rows:
        raise ValueError("No rows processed")

    df = pd.DataFrame(all_rows)
    df["seq"] = df["seq"].astype(str)
    df = df.sort_values(["session", "ts_ms"]).reset_index(drop=True)
    df.to_parquet(out_path, index=False)

    print(f"\nBuilt EXP-012 features: {out_path}")
    print(f"  Shape: {df.shape}")
    print(f"  Sessions: {df['session'].nunique()}")
    print(f"  Date range: {df['ts_ms'].min()} to {df['ts_ms'].max()}")

    return out_path


def add_labels(df: pd.DataFrame, horizons_ms: tuple = (1000, 3000, 5000, 10000)) -> pd.DataFrame:
    """Add forward return labels at predeclared horizons.

    Uses first subsequent mid-price change at or after t+h as the reference
    price. Strictly future — no look-ahead.
    """
    df = df.sort_values("ts_ms").reset_index(drop=True)
    ts = df["ts_ms"].to_numpy(dtype=np.int64)
    mid = df["mid"].to_numpy(dtype=float)
    n = len(df)

    for h in horizons_ms:
        ptr = np.searchsorted(ts, ts + h, side="left")
        valid = ptr < n
        r = np.full(n, np.nan)
        r[valid] = (mid[ptr[valid]] - mid[valid]) / mid[valid] * BPS
        df[f"r_{h}"] = r

    return df


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Build EXP-012 features")
    ap.add_argument("--v4-dir", type=Path,
                    default=Path("data/live/v4"),
                    help="Directory containing v4 session subdirectories")
    ap.add_argument("--out", type=Path,
                    default=Path("data/research/exp012/exp012_features.parquet"))
    a = ap.parse_args()

    session_dirs = sorted([d for d in a.v4_dir.glob("2026*") if d.is_dir()])
    print(f"Processing {len(session_dirs)} sessions...")
    p = build_exp012_features(session_dirs, a.out)
    df = pd.read_parquet(p)
    print(f"\nColumns ({len(df.columns)}): {df.columns.tolist()}")
