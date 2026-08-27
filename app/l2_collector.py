"""Phase 1 — authentic Binance USD-M event-level L2 + trade collector (V2).

Collects event-linked market data for BTCUSDT USD-M perpetual:
  - depth diff stream  (@depth@100ms)   -> applied to a local book
  - aggregate trades    (@aggTrade)     -> per-event trades
  - book ticker         (@bookTicker)   -> best bid/ask reference

The collector does NOT reduce data to 1 snapshot/sec. Every depth update and
every trade is recorded with exchange event time (E/T), exchange sequence ids
(U,u for depth; a for trades), local receive time (recv_ms), the reconstructed
book state at that event (bid/ask L1..L5, depth sums) and event-level features
(OFI net, depth-normalized OFI, queue imbalance QI, trade-flow imbalance TFI).

Local book synchronization follows the documented Binance procedure:
REST snapshot -> buffer incremental updates -> apply continuing update ids;
on any gap the book is discarded and rebuilt. A gap is NEVER silently merged
into the dataset.

Output per run (data/live/v2/<session>/):
  session.json   metadata (symbol, window, config)
  raw.jsonl      EVERY raw event verbatim (snapshot/depth/trade/bookTicker)
  derived.jsonl  per-event reconstructed book + features (event-linked)

The raw log is immutable and sufficient to deterministically rebuild the book
offline (app/l2_replay.py), so nothing is lost to 1 Hz downsampling.

Usage:  python -m app.l2_collector --minutes 30 [--symbol btcusdt] [--out data/live/v2]
"""

import argparse
import json
import signal
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
import websocket

from .config import Config
from .models import DepthEvent, TradeEvent
from .orderbook import LocalOrderBook

DEPTH_LIMIT = 1000


class EventReader:
    """Deterministic per-event feature/derived computation (shared with replay)."""

    def __init__(self, window_ms=1000):
        self.window_ms = window_ms
        self.prev_bids = {}
        self.prev_asks = {}

    def load_snapshot(self, bids, asks):
        self.prev_bids = {float(p): float(q) for p, q in bids}
        self.prev_asks = {float(p): float(q) for p, q in asks}

    def reset(self):
        self.prev_bids = {}
        self.prev_asks = {}

    def advance(self, book):
        state = book.state
        self.prev_bids = dict(state.bids)
        self.prev_asks = dict(state.asks)

    def trade_window(self, trades):
        buy = sum(t["q"] for t in trades if t["side"] == "BUY")
        sell = sum(t["q"] for t in trades if t["side"] == "SELL")
        tot = buy + sell
        return {"buy_vol": round(buy, 8), "sell_vol": round(sell, 8),
                "tfi": round((buy - sell) / tot, 6) if tot else 0.0}

    def ofi_event(self, depth_event, book=None):
        d = {"adds": 0.0, "cancels": 0.0, "bid": 0.0, "ask": 0.0, "net": 0.0,
             "bid_l1": 0.0, "bid_l5": 0.0, "bid_l10": 0.0,
             "ask_l1": 0.0, "ask_l5": 0.0, "ask_l10": 0.0,
             "ofi_l1": 0.0, "ofi_l5": 0.0, "ofi_l10": 0.0}
        bid_thr = {n: None for n in (1, 5, 10)}
        ask_thr = {n: None for n in (1, 5, 10)}
        if book is not None:
            top_b, top_a = book.level_quantities(10)
            bid_prices = [p for p, _ in top_b]
            ask_prices = [p for p, _ in top_a]
            for n in (1, 5, 10):
                if bid_prices:
                    bid_thr[n] = min(bid_prices[:n])
                if ask_prices:
                    ask_thr[n] = max(ask_prices[:n])
        for p, q in depth_event.bids:
            old = self.prev_bids.get(p, 0.0)
            delta = q - old
            if q > 0 and old == 0:
                d["adds"] += q
            elif q == 0 and old > 0:
                d["cancels"] += old
            d["bid"] += delta
            d["net"] += delta
            for n, key in ((1, "bid_l1"), (5, "bid_l5"), (10, "bid_l10")):
                if bid_thr[n] is None or p >= bid_thr[n]:
                    d[key] += delta
        for p, q in depth_event.asks:
            old = self.prev_asks.get(p, 0.0)
            delta = q - old
            if q > 0 and old == 0:
                d["adds"] += q
            elif q == 0 and old > 0:
                d["cancels"] += old
            d["ask"] += delta
            d["net"] -= delta
            for n, key in ((1, "ask_l1"), (5, "ask_l5"), (10, "ask_l10")):
                if ask_thr[n] is None or p <= ask_thr[n]:
                    d[key] += delta
        d["ofi_l1"] = d["bid_l1"] - d["ask_l1"]
        d["ofi_l5"] = d["bid_l5"] - d["ask_l5"]
        d["ofi_l10"] = d["bid_l10"] - d["ask_l10"]
        return d

    def derived_from_book(self, book, ts_ms, recv_ms, kind, seq=None,
                          depth_deltas=None, flow=None):
        bids10, asks10 = book.level_quantities(10)
        bids5, asks5 = bids10[:5], asks10[:5]
        bids1, asks1 = bids10[:1], asks10[:1]
        def depth_sums(bb, aa):
            return (sum(q for _, q in bb), sum(q for _, q in aa))
        b1, a1 = depth_sums(bids1, asks1)
        b5, a5 = depth_sums(bids5, asks5)
        b10, a10 = depth_sums(bids10, asks10)
        def qi(bb, aa):
            den = bb + aa
            return round((bb - aa) / den, 6) if den else 0.0
        best_bid = book.state.best_bid()
        best_ask = book.state.best_ask()
        mid = (best_bid + best_ask) / 2.0 if (best_bid is not None and best_ask is not None) else None
        microb = None
        mpd = None
        if bids1 and asks1:
            pb, qb = bids1[0]
            pa, qa = asks1[0]
            den = qb + qa
            if den:
                microb = (qb * pa + qa * pb) / den
                if mid:
                    mpd = round((microb - mid) / mid * 1e4, 4)
        row = {
            "ts_ms": int(ts_ms), "recv_ms": int(recv_ms), "kind": kind, "seq": seq,
            "best_bid": best_bid, "best_ask": best_ask, "mid": mid,
            "microb_price": microb, "mpd_bps": mpd,
            "spread_bps": round((best_ask - best_bid) / mid * 1e4, 4) if mid else None,
            "bid_l1_5": [[round(p, 2), round(q, 8)] for p, q in bids5],
            "ask_l1_5": [[round(p, 2), round(q, 8)] for p, q in asks5],
            "bid_l1_10": [[round(p, 2), round(q, 8)] for p, q in bids10],
            "ask_l1_10": [[round(p, 2), round(q, 8)] for p, q in asks10],
            "bid_depth1": round(b1, 8), "ask_depth1": round(a1, 8),
            "bid_depth5": round(b5, 8), "ask_depth5": round(a5, 8),
            "bid_depth10": round(b10, 8), "ask_depth10": round(a10, 8),
            "qi1": qi(b1, a1), "qi5": qi(b5, a5), "qi10": qi(b10, a10),
        }
        if depth_deltas is not None:
            row["bid_delta"] = round(depth_deltas["bid"], 8)
            row["ask_delta"] = round(depth_deltas["ask"], 8)
            row["adds"] = round(depth_deltas["adds"], 8)
            row["cancels"] = round(depth_deltas["cancels"], 8)
            row["ofi_net"] = round(depth_deltas["net"], 8)
            row["ofi_l1"] = round(depth_deltas["ofi_l1"], 8)
            row["ofi_l5"] = round(depth_deltas["ofi_l5"], 8)
            row["ofi_l10"] = round(depth_deltas["ofi_l10"], 8)
            row["ofi_depth"] = round(depth_deltas["net"] / (b10 + a10), 8) if (b10 + a10) else 0.0
        if flow is not None:
            row["buy_vol"] = flow["buy_vol"]
            row["sell_vol"] = flow["sell_vol"]
            row["tfi"] = flow["tfi"]
        return row


class SessionWriter:
    """Immutable append-only writers (raw + derived) + session metadata."""

    def __init__(self, out_dir):
        self.dir = Path(out_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.session = self.dir / stamp
        self.session.mkdir(parents=True, exist_ok=True)
        self.raw = open(self.session / "raw.jsonl", "a")
        self.derived = open(self.session / "derived.jsonl", "a")
        self.n_raw = 0
        self.n_derived = 0

    def write_raw(self, record):
        self.raw.write(json.dumps(record) + "\n")
        self.raw.flush()
        self.n_raw += 1

    def write_derived(self, row):
        self.derived.write(json.dumps(row) + "\n")
        self.derived.flush()
        self.n_derived += 1

    def close(self, meta=None):
        self.raw.flush()
        self.derived.flush()
        meta = meta or {}
        meta.update({"raw_rows": self.n_raw, "derived_rows": self.n_derived,
                     "session": self.session.name})
        (self.session / "session.json").write_text(json.dumps(meta, indent=1))
        self.raw.close()
        self.derived.close()
        return self.session


class V2Collector:
    def __init__(self, cfg=None, symbol="btcusdt", out_dir=Path("data/live/v2"),
                 max_book_levels=50, log=print):
        self.cfg = cfg or Config()
        self.symbol = symbol.lower()
        self.sym = symbol.upper()
        self.out_dir = Path(out_dir)
        self.book = LocalOrderBook(max_levels=max_book_levels)
        self.reader = EventReader()
        self.log = log
        self.stop_flag = threading.Event()
        self.ready = False
        self.buffer = []
        self.lock = threading.RLock()
        self.writer = None
        self.trades_buffer = []
        self._t0 = time.time()

    def snapshot(self):
        r = requests.get(self.cfg.rest + "/fapi/v1/depth",
                         params={"symbol": self.sym, "limit": DEPTH_LIMIT}, timeout=5)
        r.raise_for_status()
        return r.json()

    def synchronize(self):
        snap = self.snapshot()
        sid = int(snap["lastUpdateId"])
        now_ms = int(time.time() * 1000)
        with self.lock:
            pending = [x for x in self.buffer if x.final_update_id > sid]
            self.buffer = [x for x in self.buffer if x.final_update_id > sid]
            if not pending:
                return False
            first = pending[0]
            if not (first.first_update_id <= sid + 1 <= first.final_update_id):
                self.log("snapshot/stream overlap mismatch; retry")
                return False
            self.book.load_snapshot(snap["bids"], snap["asks"], sid)
            if self.writer:
                self.writer.write_raw({"kind": "snapshot", "last_update_id": sid,
                                       "ts_ms": now_ms, "recv_ms": now_ms,
                                       "bids": snap["bids"], "asks": snap["asks"]})
            self.reader.load_snapshot(snap["bids"], snap["asks"])
            for e in pending:
                if self._process_depth(e, now_ms) != "OK":
                    self.book.state.synchronized = False
                    return False
            self.ready = self.book.state.synchronized
            if self.ready:
                self.buffer.clear()
                return True
            return False

    def _process_depth(self, e, now_ms):
        status = self.book.apply(e)
        if status != "OK":
            return status
        if self.writer:
            self.writer.write_raw({"kind": "depth",
                                   "E": e.ts_ms,
                                   "U": e.first_update_id,
                                   "u": e.final_update_id,
                                   "recv_ms": now_ms,
                                   "bids": e.bids, "asks": e.asks})
        deltas = self.reader.ofi_event(e, self.book)
        self._flush_trades(e.ts_ms)
        flow = self.reader.trade_window(self.trades_buffer)
        row = self.reader.derived_from_book(
            self.book, e.ts_ms, now_ms, "depth",
            seq="%s-%s" % (e.first_update_id, e.final_update_id),
            depth_deltas=deltas, flow=flow)
        if self.writer:
            self.writer.write_derived(row)
        self.reader.advance(self.book)
        return status

    def on_open(self, ws):
        self.log("ws connected; synchronizing book")

        def worker():
            while not self.stop_flag.is_set():
                if not self.ready:
                    try:
                        if self.synchronize():
                            self.log("book synchronized @ update id %d"
                                     % self.book.state.last_update_id)
                    except Exception as e:
                        self.log("synchronize error: %r" % (e,))
                time.sleep(0.1)
        threading.Thread(target=worker, daemon=True).start()

    def _flush_trades(self, now_ms):
        self.trades_buffer = [t for t in self.trades_buffer
                              if now_ms - t["ts_ms"] <= self.reader.window_ms]

    def on_message(self, ws, raw):
        try:
            m = json.loads(raw).get("data", {})
            ev = m.get("e")
            now_ms = int(time.time() * 1000)
            if ev == "depthUpdate":
                e = DepthEvent(int(m["E"]), int(m["U"]), int(m["u"]),
                               [(float(p), float(q)) for p, q in m["b"]],
                               [(float(p), float(q)) for p, q in m["a"]])
                with self.lock:
                    if not self.ready:
                        self.buffer.append(e)
                        return
                    status = self._process_depth(e, now_ms)
                    if status == "GAP":
                        self.ready = False
                        self.log("BOOK GAP @%d-%d; discarding and rebuilding"
                                 % (e.first_update_id, e.final_update_id))
            elif ev == "aggTrade":
                t = TradeEvent(int(m["T"]), int(m["a"]),
                               float(m["p"]), float(m["q"]), bool(m["m"]))
                with self.lock:
                    if not self.ready:
                        return
                    if self.writer:
                        self.writer.write_raw({"kind": "trade", "T": t.ts_ms,
                                               "a": t.trade_id, "p": t.price,
                                               "q": t.qty, "m": t.buyer_is_maker,
                                               "recv_ms": now_ms})
                    side = "SELL" if t.buyer_is_maker else "BUY"
                    self.trades_buffer.append({"ts_ms": t.ts_ms, "q": t.qty, "side": side})
                    self._flush_trades(t.ts_ms)
                    flow = self.reader.trade_window(self.trades_buffer)
                    row = self.reader.derived_from_book(self.book, t.ts_ms, now_ms, "trade",
                                                        seq=t.trade_id, flow=flow)
                    if self.writer:
                        self.writer.write_derived(row)
            elif ev == "bookTicker":
                if self.writer and self.ready:
                    self.writer.write_raw({"kind": "bookTicker",
                                           "E": int(m.get("E", 0)),
                                           "recv_ms": now_ms, "b": float(m["b"]),
                                           "B": float(m["B"]), "a": float(m["a"]),
                                           "A": float(m["A"])})
        except Exception as e:
            self.log("parse error: %r" % (e,))

    def on_error(self, ws, err):
        self.log("ws error: %r" % (err,))

    def on_close(self, ws, *args):
        self.ready = False
        self.log("ws closed")

    def run(self, minutes=None):
        public_streams = "%s@depth@100ms/%s@bookTicker" % (self.symbol, self.symbol)
        market_streams = "%s@aggTrade" % self.symbol
        self.writer = SessionWriter(self.out_dir)
        self.log("collecting -> %s" % self.writer.session)

        def handler(signum, frame):
            self.log("signal received, closing")
            self.stop_flag.set()
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

        apps = []
        for base, streams in ((self.cfg.ws_public, public_streams),
                              (self.cfg.ws_market, market_streams)):
            url = base + "/stream?streams=" + streams
            app = websocket.WebSocketApp(
                url, on_open=self.on_open, on_message=self.on_message,
                on_error=self.on_error, on_close=self.on_close)
            t = threading.Thread(target=lambda: app.run_forever(
                ping_interval=20, ping_timeout=10))
            t.daemon = True
            apps.append((app, t))
            t.start()
        deadline = time.time() + minutes * 60 if minutes else None
        while not self.stop_flag.is_set():
            if deadline and time.time() >= deadline:
                self.log("window elapsed")
                break
            time.sleep(1.0)
        self.stop_flag.set()
        for app, t in apps:
            app.close()
            t.join(timeout=5)
        meta = {"symbol": self.symbol, "window_seconds": round(time.time() - self._t0, 1),
                "book_levels": self.book.max_levels}
        session = self.writer.close(meta)
        self.log("done: raw=%d derived=%d -> %s"
                 % (self.writer.n_raw, self.writer.n_derived, session))
        return session


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=30.0)
    ap.add_argument("--symbol", default="btcusdt")
    ap.add_argument("--out", type=Path, default=Path("data/live/v2"))
    args = ap.parse_args(argv)
    c = V2Collector(cfg=Config(), symbol=args.symbol, out_dir=args.out)
    session = c.run(minutes=args.minutes)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())