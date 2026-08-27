from pathlib import Path

root = Path(__file__).resolve().parent
orderbook = root / "app" / "orderbook.py"
feed = root / "app" / "binance_feed.py"

if not orderbook.exists() or not feed.exists():
    raise SystemExit("Run this script from inside binance_orderflow_autotrader_v2.")

orderbook.write_text('from .models import BookState, DepthEvent\n\nclass LocalOrderBook:\n    def __init__(self, max_levels=50):\n        self.state = BookState()\n        self.max_levels = max_levels\n\n    def load_snapshot(self, bids, asks, last_update_id):\n        self.state.bids = {float(p): float(q) for p, q in bids if float(q) > 0}\n        self.state.asks = {float(p): float(q) for p, q in asks if float(q) > 0}\n        self.state.last_update_id = int(last_update_id)\n        self.state.synchronized = False\n\n    def apply(self, e: DepthEvent):\n        if self.state.last_update_id is None:\n            return "NO_SNAPSHOT"\n        if e.final_update_id <= self.state.last_update_id:\n            return "STALE"\n\n        # Binance diff-depth continuity: U <= previous_u + 1 <= u.\n        # U does NOT have to equal previous_u + 1.\n        if self.state.synchronized:\n            expected = self.state.last_update_id + 1\n            if not (e.first_update_id <= expected <= e.final_update_id):\n                self.state.synchronized = False\n                return "GAP"\n\n        for p, q in e.bids:\n            if q == 0:\n                self.state.bids.pop(p, None)\n            else:\n                self.state.bids[p] = q\n        for p, q in e.asks:\n            if q == 0:\n                self.state.asks.pop(p, None)\n            else:\n                self.state.asks[p] = q\n\n        self.state.last_update_id = e.final_update_id\n        self.state.last_event_ms = e.ts_ms\n        self.state.synchronized = True\n        self._prune()\n        return "OK"\n\n    def _prune(self):\n        if len(self.state.bids) > self.max_levels:\n            self.state.bids = dict(sorted(self.state.bids.items(), reverse=True)[:self.max_levels])\n        if len(self.state.asks) > self.max_levels:\n            self.state.asks = dict(sorted(self.state.asks.items())[:self.max_levels])\n\n    def level_quantities(self, n):\n        bids = sorted(self.state.bids.items(), reverse=True)[:n]\n        asks = sorted(self.state.asks.items())[:n]\n        return bids, asks\n\n    def imbalance(self, n):\n        b, a = self.level_quantities(n)\n        bs, ass = sum(q for _, q in b), sum(q for _, q in a)\n        den = bs + ass\n        return (bs - ass) / den if den else 0.0\n', encoding="utf-8")

text = feed.read_text(encoding="utf-8")
start = text.index("    def synchronize(self):")
end = text.index("\n    def run(self):", start)
sync = '    def synchronize(self):\n        # Binance synchronization:\n        # buffer depth events -> REST snapshot -> discard u <= snapshot ID\n        # -> first retained event must satisfy U <= snapshot+1 <= u.\n        snap = self.snapshot()\n        sid = int(snap["lastUpdateId"])\n\n        with self.lock:\n            pending = [x for x in self.buffer if x.final_update_id > sid]\n            if not pending:\n                return False\n\n            first = pending[0]\n            if not (first.first_update_id <= sid + 1 <= first.final_update_id):\n                return False\n\n            self.book.load_snapshot(snap["bids"], snap["asks"], sid)\n\n            for e in pending:\n                status = self.book.apply(e)\n                if status == "GAP":\n                    self.book.state.synchronized = False\n                    return False\n\n            self.ready = self.book.state.synchronized\n            self.buffer.clear()\n            return self.ready\n'
feed.write_text(text[:start] + sync + text[end:], encoding="utf-8")

print("FIX APPLIED")
print("Binance diff-depth range-continuity bug corrected.")
print("Now run: python -m app.main --symbol BTCUSDT")
