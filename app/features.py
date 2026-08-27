"""Order-flow feature engine (production pipeline).

Single source of truth for microstructure features used by the live, paper,
backtest and replay paths. All features are computed causally (from data
already observed at event time) and are purely descriptive numbers -- no trade
thresholds live here. Thresholds/decisions belong in the decision engine.

Definitions are microstructurally motivated (Cont, Kukanov & Stoikov; Silantyev;
Alexander, Heck, Kaeck & Riordan; Sandås; Moallemi & Yuan; Kyle):
  - ofi_l1 / ofi_norm_l1   : CKS OFI and depth-normalized OFI (impact/depth)
  - qi_l1                  : queue imbalance at the touch (B-A)/(B+A)
  - di_l5 / di_l10         : distance-weighted multi-level depth imbalance
  - mpd_bps                : microprice offset from mid (bps)
  - spread_bps             : (ask-bid)/mid * 1e4
  - bid_cancel_bps/ask_add_bps : cancel/add pressure in bps
  - cancel_pressure        : (bid_cancels + ask_cancels) / depth1
  - tfi_500                : trade-flow imbalance over trailing 500ms
  - liq_depletion          : near-touch depth consumed by recent aggressors / depth5
  - log_depth1/log_depth5  : log liquidity
  - log_event_rate         : event activity
  - depth_slope_bps        : log-depth decay (liquidity shape)
  - vol_500                : trailing realized vol of mid log-returns (bps)

NO technical indicators, no RSI/EMA/VWAP, no forward references.
"""

from collections import deque
from dataclasses import dataclass, field
import time

import numpy as np


# Classification cutoffs (heuristic STATE labels only, not trade thresholds).
THIN_DEPTH_USD = 50_000.0      # top-5 notional below this => THIN liquidity
STRESS_SPREAD_BPS = 5.0        # spread above this => STRESSED
HIGH_VPIN = 0.60
ELEVATED_VPIN = 0.40
HIGH_CANCEL = 0.50
ELEVATED_CANCEL = 0.30


# V5_FEATURES as defined in v5_features.py (must match exactly for model compatibility)
V5_FEATURES = ["ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
               "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
               "cancel_pressure", "tfi_500", "liq_depletion",
               "log_depth1", "log_depth5", "log_event_rate",
               "depth_slope_bps", "vol_500"]


@dataclass
class FlowFeatures:
    # --- V5 model features (exact names and definitions matching v3_replay/v5_features) ---
    ofi_l1: float = 0.0
    ofi_norm_l1: float = 0.0
    qi_l1: float = 0.0
    di_l5: float = 0.0
    di_l10: float = 0.0
    mpd_bps: float = 0.0
    spread_bps: float = 0.0
    bid_cancel_bps: float = 0.0
    ask_add_bps: float = 0.0
    cancel_pressure: float = 0.0
    tfi_500: float = 0.0
    liq_depletion: float = 0.0
    log_depth1: float = 0.0
    log_depth5: float = 0.0
    log_event_rate: float = 0.0
    depth_slope_bps: float = 0.0
    vol_500: float = 0.0
    
    # --- backward-compatible core fields (used by main.py / replay.py) ---
    delta: float = 0.0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    cvd: float = 0.0
    trade_rate: float = 0.0
    ofi: float = 0.0
    mlofi: float = 0.0
    imbalance_1: float = 0.0
    imbalance_5: float = 0.0
    imbalance_20: float = 0.0
    spread_bps: float = 0.0
    mid: float = 0.0
    # --- extended order-flow features ---
    imbalance_10: float = 0.0
    microprice: float = 0.0
    microprice_dev_bps: float = 0.0
    depth_weighted_pressure: float = 0.0
    queue_imbalance: float = 0.0
    aggressive_buy_volume: float = 0.0
    aggressive_sell_volume: float = 0.0
    aggressive_buy_ratio: float = 0.0
    trade_imbalance: float = 0.0
    ofi_norm: float = 0.0
    cvd_slope: float = 0.0
    vol_bps: float = 0.0
    vpin: float = 0.0
    kyle_lambda: float = 0.0
    cancel_pressure: float = 0.0
    bid_cancel_bps: float = 0.0
    ask_add_bps: float = 0.0
    liquidity_depletion: float = 0.0
    replenishment: float = 0.0
    sweep_intensity: float = 0.0
    absorption_proxy: float = 0.0
    toxicity_state: str = "UNKNOWN"
    liquidity_state: str = "UNKNOWN"
    book_state: str = "BOOK_STARTING"
    n_trades: int = 0


WINDOW_TFI = 500

class OrderFlowEngine:
    def __init__(self, book, window_ms=5000, max_trades=20000):
        self.book = book
        self.window_ms = window_ms
        self.trades = deque(maxlen=max_trades)
        self.cvd = 0.0
        self.prev_depth = {}
        self.prev_full_bids = dict(book.state.bids)
        self.prev_full_asks = dict(book.state.asks)
        self.ofi = 0.0
        self.mlofi = 0.0
        self.last_was_depth = False
        self.last_cancel_bid = 0.0
        self.last_cancel_ask = 0.0
        self.last_add_bid = 0.0
        self.last_add_ask = 0.0
        self.book_events = deque(maxlen=20000)
        self.depth_hist = deque(maxlen=5000)
        self.cvd_hist = deque(maxlen=5000)
        self.mid_hist = deque(maxlen=5000)
        self._prev_mid = None
        self._prev_mid_ts = 0
        self.mid_hist = deque(maxlen=5000)

    # ------------------------------------------------------------------
    # ingest
    # ------------------------------------------------------------------
    def on_trade(self, t):
        side = t.aggressor_side
        self.cvd += t.qty if side == 'BUY' else -t.qty
        mid = self.book.mid()
        self.trades.append({'ts_ms': t.ts_ms, 'qty': t.qty, 'price': t.price,
                            'side': side, 'signed': t.qty if side == 'BUY' else -t.qty,
                            'mid': mid})
        self.cvd_hist.append((t.ts_ms, self.cvd))
        self.last_was_depth = False

    def on_book_event(self, e):
        cur_bids = {p: q for p, q in e.bids}
        cur_asks = {p: q for p, q in e.asks}

        x = 0.0
        cancel_bid = cancel_ask = add_bid = add_ask = 0.0

        for p, q in cur_bids.items():
            old = self.prev_full_bids.get(p, 0.0)
            d = q - old
            if d < 0:
                cancel_bid += -d
            elif d > 0:
                add_bid += d
            x += d

        for p, q in cur_asks.items():
            old = self.prev_full_asks.get(p, 0.0)
            d = q - old
            if d < 0:
                cancel_ask += -d
            elif d > 0:
                add_ask += d
            x -= d

        self.prev_full_bids = dict(self.book.state.bids)
        self.prev_full_asks = dict(self.book.state.asks)

        self.ofi = x
        self.last_was_depth = True
        self.last_cancel_bid = cancel_bid
        self.last_cancel_ask = cancel_ask
        self.last_add_bid = add_bid
        self.last_add_ask = add_ask
        self.book_events.append(
            (e.ts_ms, cancel_bid, cancel_ask, add_bid, add_ask))
        return x

    # ------------------------------------------------------------------
    # windowed helpers
    # ------------------------------------------------------------------
    def _window_trades(self, now_ms, window_ms):
        return [t for t in self.trades if now_ms - t['ts_ms'] <= window_ms]

    def _vpin(self, trades, n_buckets=50):
        if len(trades) < 2:
            return 0.0
        total = sum(t['qty'] for t in trades)
        if total <= 0:
            return 0.0
        size = max(total / n_buckets, 1e-9)
        bb = bs = 0.0
        buckets = []
        for t in trades:
            if t['side'] == 'BUY':
                bb += t['qty']
            else:
                bs += t['qty']
            if bb + bs >= size:
                vol = bb + bs
                buckets.append(abs(bb - bs) / vol if vol > 0 else 0.0)
                bb = bs = 0.0
        return sum(buckets) / len(buckets) if buckets else 0.0

    def _kyle_lambda(self, trades):
        mids = [t['mid'] for t in trades if t['mid'] is not None]
        if len(mids) < 3:
            return 0.0
        dmid = np.diff(mids)
        sv = np.array([t['signed'] for t in trades[1:]], dtype=float)
        if len(dmid) != len(sv) or len(sv) < 3:
            return 0.0
        var = float(np.var(sv))
        if var <= 0:
            return 0.0
        return float(np.cov(dmid, sv, ddof=0)[0, 1] / var)

    def _flow(self, now_ms):
        r = self._window_trades(now_ms, WINDOW_TFI)
        vbuy = sum(t['qty'] for t in r if t['side'] == 'BUY')
        vsell = sum(t['qty'] for t in r if t['side'] == 'SELL')
        den = vbuy + vsell
        st = self.book.state
        d5 = (sum(q for _, q in self.book.level_quantities(5)[0]) +
              sum(q for _, q in self.book.level_quantities(5)[1]))
        if den <= 0:
            return {"tfi_500": 0.0, "signed_vol_500": 0.0, "trade_rate": 0.0,
                    "liq_depletion": 0.0}
        return {"tfi_500": (vbuy - vsell) / den, "signed_vol_500": vbuy - vsell,
                "trade_rate": len(r), "liq_depletion": den / d5 if d5 else 0.0}

    def _flush_old_trades(self, now_ms):
        cutoff = now_ms - self.window_ms
        while self.trades and self.trades[0]['ts_ms'] < cutoff:
            self.trades.popleft()

    # ------------------------------------------------------------------
    # snapshots
    # ------------------------------------------------------------------
    def snapshot(self, window_ms=None, now_ms=None):
        window_ms = window_ms or self.window_ms
        if now_ms is None:
            ev = self.book.state.last_event_ms
            now = ev if ev > 0 else int(time.time() * 1000)
        else:
            now = int(now_ms)
        book = self.book
        mid = book.mid()
        spread = book.spread_bps()
        f = FlowFeatures(mid=mid or 0.0, spread_bps=spread or 0.0)

        b = book.state.best_bid()
        a = book.state.best_ask()
        bq = book.state.bids.get(b, 0.0) if b else 0.0
        aq = book.state.asks.get(a, 0.0) if a else 0.0
        d1 = bq + aq

        f.qi_l1 = round((bq - aq) / d1, 6) if d1 > 0 else 0.0
        f.di_l5 = round(self._multi_di(5), 6)
        f.di_l10 = round(self._multi_di(10), 6)

        microb = self._microprice()
        f.mpd_bps = round(((microb - mid) / mid * 1e4) if (mid and microb) else 0.0, 6)
        f.spread_bps = round(spread or 0.0, 6)
        f.depth_slope_bps = round(self._depth_slope_bps(), 6)

        ofi_val = self.ofi if self.last_was_depth else 0.0
        f.ofi_l1 = round(ofi_val, 6)
        f.ofi_norm_l1 = round(ofi_val / d1, 6) if d1 > 0 else 0.0

        to_bps = lambda q: q / mid * 1e4 if mid else 0.0
        if self.last_was_depth:
            f.bid_cancel_bps = round(to_bps(self.last_cancel_bid), 6)
            f.ask_add_bps = round(to_bps(self.last_add_ask), 6)
            f.cancel_pressure = round((self.last_cancel_bid + self.last_cancel_ask) / (d1 + 1e-9), 6)
        else:
            f.bid_cancel_bps = 0.0
            f.ask_add_bps = 0.0
            f.cancel_pressure = 0.0

        f.log_depth1 = np.log1p(d1)
        d5sum = sum(q for _, q in book.level_quantities(5)[0]) + sum(q for _, q in book.level_quantities(5)[1])
        f.log_depth5 = np.log1p(d5sum)
        f.log_event_rate = np.log1p(len(self._window_trades(now, WINDOW_TFI)))

        flow = self._flow(now)
        f.tfi_500 = round(flow["tfi_500"], 6)
        f.liq_depletion = round(flow["liq_depletion"], 6)

        f.vol_500 = self._trailing_vol(now, mid, WINDOW_TFI)

        f.spread_bps = round(spread or 0.0, 6)
        f.mid = mid or 0.0

        f.delta = self._compute_delta(now)
        f.buy_volume = 0.0
        f.sell_volume = 0.0
        f.cvd = self.cvd
        f.trade_rate = len(self._window_trades(now, self.window_ms)) / (self.window_ms / 1000.0) if self.window_ms > 0 else 0.0
        f.ofi = ofi_val
        f.mlofi = self.mlofi
        f.imbalance_1 = book.imbalance(1)
        f.imbalance_5 = book.imbalance(5)
        f.imbalance_20 = book.imbalance(20)
        f.spread_bps = round(spread or 0.0, 6)
        f.mid = mid or 0.0

        f.imbalance_10 = book.imbalance(10)
        f.microprice = self._microprice() or 0.0
        f.microprice_dev_bps = round(((self._microprice() - mid) / mid * 1e4) if (mid and self._microprice()) else 0.0, 6)
        f.depth_weighted_pressure = book.depth_weighted_pressure(5)
        f.queue_imbalance = book.imbalance(1)

        r = self._window_trades(now, self.window_ms)
        buy = sum(t['qty'] for t in r if t['side'] == 'BUY')
        sell = sum(t['qty'] for t in r if t['side'] == 'SELL')
        total = buy + sell
        f.buy_volume = buy
        f.sell_volume = sell
        f.aggressive_buy_volume = buy
        f.aggressive_sell_volume = sell
        f.delta = buy - sell
        f.cvd = self.cvd
        f.trade_rate = len(r) / (self.window_ms / 1000.0) if self.window_ms > 0 else 0.0
        f.aggressive_buy_ratio = (buy / total) if total > 0 else 0.0
        f.trade_imbalance = ((buy - sell) / total) if total > 0 else 0.0
        f.n_trades = len(r)

        f.ofi = ofi_val
        mlofi = 0.0
        for level_idx, (price, qty) in enumerate(self.book.state.top_bids(10), 1):
            old_qty = self.prev_full_bids.get(price, 0.0)
            d = qty - old_qty
            mlofi += d / level_idx
        for level_idx, (price, qty) in enumerate(self.book.state.top_asks(10), 1):
            old_qty = self.prev_full_asks.get(price, 0.0)
            d = qty - old_qty
            mlofi -= d / level_idx
        self.mlofi = mlofi
        f.mlofi = mlofi
        f.ofi = ofi_val
        f.ofi_norm = self.ofi / (abs(self.ofi) + 1.0)

        prices = np.array([t['price'] for t in r], dtype=float)
        if len(prices) >= 2:
            rets = np.diff(np.log(prices))
            f.vol_bps = float(np.std(rets) * 1e4)
        else:
            f.vol_bps = 0.0

        f.vpin = self._vpin(r)
        f.kyle_lambda = self._kyle_lambda(r)

        if len(self.cvd_hist) >= 2:
            t0, c0 = self.cvd_hist[0]
            f.cvd_slope = (self.cvd - c0) / max(1.0, (now - t0) / 1000.0)
        else:
            f.cvd_slope = 0.0

        bid_depth, ask_depth = book.depth_sum(5)
        depth5 = (bid_depth + ask_depth) * (mid or 0.0)

        self.depth_hist.append((now, depth5))
        recent = [d for ts, d in self.depth_hist if now - ts <= self.window_ms]
        if len(recent) >= 2:
            half = max(1, len(recent) // 2)
            earlier = recent[:half]
            mean_earlier = sum(earlier) / len(earlier)
            cur_depth = recent[-1]
            min_depth = min(recent)
            f.liquidity_depletion = max(0.0, (mean_earlier - cur_depth) / (mean_earlier + 1e-9))
            f.replenishment = max(0.0, (cur_depth - min_depth) / (mean_earlier + 1e-9))
        else:
            f.liquidity_depletion = 0.0
            f.replenishment = 0.0

        side_depth = (bid_depth if f.delta >= 0 else ask_depth) * (mid or 0.0)
        if total > 0 and side_depth > 0:
            f.sweep_intensity = min(1.0, total / (side_depth + 1e-9) - 1.0) if total > side_depth else 0.0
        else:
            f.sweep_intensity = 0.0

        f.absorption_proxy = max(-1.0, min(1.0, f.replenishment - f.liquidity_depletion))

        f.book_state = book.integrity_state()
        if depth5 < THIN_DEPTH_USD:
            f.liquidity_state = "THIN"
        elif (spread or 0.0) > STRESS_SPREAD_BPS:
            f.liquidity_state = "STRESSED"
        else:
            f.liquidity_state = "NORMAL"
        if f.vpin > HIGH_VPIN or f.cancel_pressure > HIGH_CANCEL:
            f.toxicity_state = "HIGH_TOXICITY"
        elif f.vpin > ELEVATED_VPIN or f.cancel_pressure > ELEVATED_CANCEL:
            f.toxicity_state = "ELEVATED_TOXICITY"
        else:
            f.toxicity_state = "LOW_TOXICITY"
        return f
    
    # Helper methods matching v3_replay.BookStats
    def _microprice(self):
        """Volume-weighted mid: (ask*bid_qty + bid*ask_qty) / (bid_qty + ask_qty)."""
        b = self.book.state.best_bid()
        a = self.book.state.best_ask()
        if b is None or a is None:
            return None
        qb = self.book.state.bids.get(b, 0.0)
        qa = self.book.state.asks.get(a, 0.0)
        tot = qb + qa
        return (a * qb + b * qa) / tot if tot > 0 else None
    
    def _multi_di(self, n):
        """Distance-weighted multi-level depth imbalance (matching v3_replay.BookStats.multi_di)."""
        bids = self.book.state.top_bids(n)
        asks = self.book.state.top_asks(n)
        wb = sum((n - i + 1) * q for i, (_, q) in enumerate(bids[:n]))
        wa = sum((n - i + 1) * q for i, (_, q) in enumerate(asks[:n]))
        return (wb - wa) / (wb + wa) if (wb + wa) else 0.0
    
    def _depth_slope_bps(self):
        bq = [q for _, q in self.book.level_quantities(10)[0]]
        aq = [q for _, q in self.book.level_quantities(10)[1]]
        if not bq or not aq:
            return 0.0
        logq = np.log1p(np.array(bq + aq))
        return float(np.polyfit(np.arange(len(logq)), logq, 1)[0])

    def _trailing_vol(self, now_ms, mid, window_ms):
        if mid is None or mid <= 0 or now_ms == 0:
            return 0.0
        if self._prev_mid is not None and self._prev_mid > 0 and now_ms > self._prev_mid_ts:
            lr = float(np.log(mid / self._prev_mid))
        else:
            lr = 0.0
        self.mid_hist.append((now_ms, mid, lr))
        self._prev_mid = mid
        self._prev_mid_ts = now_ms
        hist_list = list(self.mid_hist)
        j = 0
        for k in range(len(hist_list)):
            if hist_list[k][0] >= now_ms - window_ms:
                j = k
                break
        seg = [hist_list[k][2] for k in range(j, len(hist_list) - 1)]
        if len(seg) >= 3:
            return float(np.sqrt(np.sum(np.array(seg) ** 2)) * 1e4)
        return 0.0
    
    def _compute_delta(self, now_ms):
        """Compute delta (buy - sell volume) over the window."""
        r = self._window_trades(now_ms, self.window_ms)
        buy = sum(t['qty'] for t in r if t['side'] == 'BUY')
        sell = sum(t['qty'] for t in r if t['side'] == 'SELL')
        return buy - sell

    def snapshot_events(self, n=500, now_ms=None):
        """Event-time aggregation: features over the last N trade events.

        Used where wall-clock time is uninformative (e.g. illiquid sessions);
        book structure still reflects the live snapshot."""
        now = int(time.time() * 1000) if now_ms is None else int(now_ms)
        f = self.snapshot(window_ms=self.window_ms, now_ms=now)
        r = list(self.trades)[-n:] if n > 0 else list(self.trades)
        buy = sum(t['qty'] for t in r if t['side'] == 'BUY')
        sell = sum(t['qty'] for t in r if t['side'] == 'SELL')
        total = buy + sell
        f.buy_volume = buy
        f.sell_volume = sell
        f.delta = buy - sell
        f.aggressive_buy_volume = buy
        f.aggressive_sell_volume = sell
        f.trade_rate = float(len(r))
        f.aggressive_buy_ratio = (buy / total) if total > 0 else 0.0
        f.trade_imbalance = ((buy - sell) / total) if total > 0 else 0.0
        f.n_trades = len(r)
        f.vpin = self._vpin(r)
        f.kyle_lambda = self._kyle_lambda(r)
        prices = np.array([t['price'] for t in r], dtype=float)
        if len(prices) >= 2:
            f.vol_bps = float(np.std(np.diff(np.log(prices))) * 1e4)
        return f