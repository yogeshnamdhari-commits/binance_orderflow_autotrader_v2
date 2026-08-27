from .models import BookState, DepthEvent

class LocalOrderBook:
    def __init__(self, max_levels=50):
        self.state = BookState()
        self.max_levels = max_levels

    def load_snapshot(self, bids, asks, last_update_id):
        self.state.bids = {float(p): float(q) for p, q in bids if float(q) > 0}
        self.state.asks = {float(p): float(q) for p, q in asks if float(q) > 0}
        self.state.last_update_id = int(last_update_id)
        self.state.synchronized = False

    def apply(self, e: DepthEvent):
        if self.state.last_update_id is None:
            return "NO_SNAPSHOT"
        if e.final_update_id <= self.state.last_update_id:
            return "STALE"

        # Binance futures @depth@100ms skips no-op update IDs between
        # every event (holes are normal, typically a few hundred IDs).
        # Only a genuinely large hole means real message loss: re-sync then.
        if self.state.synchronized:
            hole = e.first_update_id - self.state.last_update_id - 1
            if hole > 5000:
                self.state.synchronized = False
                return "GAP"

        for p, q in e.bids:
            if q == 0:
                self.state.bids.pop(p, None)
            else:
                self.state.bids[p] = q
        for p, q in e.asks:
            if q == 0:
                self.state.asks.pop(p, None)
            else:
                self.state.asks[p] = q

        self.state.last_update_id = e.final_update_id
        self.state.last_event_ms = e.ts_ms
        self.state.synchronized = True
        self._prune()
        return "OK"

    def _prune(self):
        if len(self.state.bids) > self.max_levels:
            self.state.bids = dict(sorted(self.state.bids.items(), reverse=True)[:self.max_levels])
        if len(self.state.asks) > self.max_levels:
            self.state.asks = dict(sorted(self.state.asks.items())[:self.max_levels])

    def level_quantities(self, n):
        bids = sorted(self.state.bids.items(), reverse=True)[:n]
        asks = sorted(self.state.asks.items())[:n]
        return bids, asks

    def imbalance(self, n):
        b, a = self.level_quantities(n)
        bs, ass = sum(q for _, q in b), sum(q for _, q in a)
        den = bs + ass
        return (bs - ass) / den if den else 0.0

    # -- facade methods delegating to BookState (no duplicated logic) --
    def mid(self):
        return self.state.mid()

    def spread_bps(self):
        return self.state.spread_bps()

    def best_bid(self):
        return self.state.best_bid()

    def best_ask(self):
        return self.state.best_ask()

    # -- extended microstructure helpers (delegate to BookState) --
    def imbalance_10(self):
        return self.state.imbalance(10)

    def best_bid_qty(self):
        return self.state.best_bid_qty()

    def best_ask_qty(self):
        return self.state.best_ask_qty()

    def microprice(self):
        return self.state.microprice()

    def depth_weighted_pressure(self, n=5):
        return self.state.depth_weighted_pressure(n)

    def depth_sum(self, n=5):
        return self.state.depth_sum(n)

    def stale(self, now_ms, threshold_ms):
        return self.state.stale(now_ms, threshold_ms)

    def integrity_state(self):
        return self.state.integrity_state()

    def snapshot_levels(self, n):
        """Return top-n (price,qty) bid/ask levels for feature engines."""
        return self.level_quantities(n)
