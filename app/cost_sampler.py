import json, signal, threading, time
from datetime import datetime, timezone
import requests, websocket

from .config import Config
from .models import DepthEvent
from .orderbook import LocalOrderBook


def walk_slippage_bps(levels_sorted, mid, notional_usd):
    target = notional_usd / mid
    filled, cost = 0.0, 0.0
    for price, qty in levels_sorted:
        if filled >= target:
            break
        take = min(qty, target - filled)
        filled += take
        cost += take * price
    if filled < target - 1e-12:
        return None
    avg = cost / filled
    return (avg - mid) / mid * 1e4


class CostSampler:
    def __init__(self, cfg=None, symbol="btcusdt", out_dir=None, cadence_s=1.0,
                 notional_bands=(1000, 5000, 10000, 25000, 50000), max_levels=20, log=print):
        self.cfg = cfg or Config()
        self.symbol = symbol.lower()
        self.sym = symbol.upper()
        self.book = LocalOrderBook(max_levels=max_levels)
        self.cadence_s = cadence_s
        self.bands = notional_bands
        self.log = log
        self.out_dir = out_dir
        self.stop_flag = threading.Event()
        self.ready = False
        self.buffer = []
        self.lock = threading.RLock()
        self.bt = None  # latest bookTicker dict
        self.rows = 0
        self._dh = None
        self.t0 = time.time()
        if out_dir:
            self._dh = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            self.path = self.out_dir / f"cost_sampler_{self._dh}.jsonl"
            self.path.parent.mkdir(parents=True, exist_ok=True)

    def snapshot(self):
        r = requests.get(self.cfg.rest + "/fapi/v1/depth",
                         params={"symbol": self.sym, "limit": 1000}, timeout=5)
        r.raise_for_status()
        return r.json()

    def synchronize(self):
        snap = self.snapshot()
        sid = int(snap["lastUpdateId"])
        with self.lock:
            # Drop events already covered by the snapshot (u <= sid), keep the rest.
            pending = [x for x in self.buffer if x.final_update_id > sid]
            if not pending:
                return False
            first = pending[0]
            if not (first.first_update_id <= sid + 1 <= first.final_update_id):
                return False
            self.book.load_snapshot(snap["bids"], snap["asks"], sid)
            for e in pending:
                if self.book.apply(e) == "GAP":
                    self.book.state.synchronized = False
                    return False
            self.ready = self.book.state.synchronized
            self.buffer.clear()
            return self.ready

    def on_open(self, ws):
        self.log("ws connected")

        def worker():
            while not self.stop_flag.is_set():
                if not self.ready:
                    try:
                        if self.synchronize():
                            self.log("book synchronized")
                    except Exception as e:
                        self.log("snapshot error: %r" % (e,))
                time.sleep(0.1)
        threading.Thread(target=worker, daemon=True).start()

    def on_message(self, ws, raw):
        try:
            m = json.loads(raw).get("data", {})
            ev = m.get("e")
            if ev == "depthUpdate":
                e = DepthEvent(int(m["E"]), int(m["U"]), int(m["u"]),
                               [(float(p), float(q)) for p, q in m["b"]],
                               [(float(p), float(q)) for p, q in m["a"]])
                with self.lock:
                    if not self.ready:
                        self.buffer.append(e)
                    else:
                        if self.book.apply(e) == "GAP":
                            self.ready = False
                            self.log("book gap, re-syncing")
                if self.ready:
                    self.sample()
            elif ev == "bookTicker":
                self.bt = {"b": float(m["b"]), "B": float(m["B"]),
                           "a": float(m["a"]), "A": float(m["A"]),
                           "E": int(m.get("E", 0))}
                if self.ready:
                    self.sample()
        except Exception as e:
            self.log("parse error: %r" % (e,))

    def on_error(self, ws, err):
        self.log("ws error: %r" % (err,))

    def on_close(self, ws, *args):
        self.ready = False
        self.log("ws closed")

    def _next_sample_at(self):
        return self._last_sample + self.cadence_s

    def sample(self, force=False):
        now = time.time()
        if not force and hasattr(self, "_last_sample") and now < self._next_sample_at():
            return
        state = self.book.state
        mid = state.mid()
        try:
            b, a = state.best_bid(), state.best_ask()
        except ValueError:
            return
        if mid is None:
            return
        bt = self.bt
        bid = bt["b"] if bt else b
        ask = bt["a"] if bt else a
        spread_bps = (ask - bid) / mid * 1e4
        bids5, asks5 = self.book.level_quantities(5)
        imb5 = self.book.imbalance(5)
        row = {
            "ts_ms": int(now * 1000),
            "bid": round(bid, 2), "ask": round(ask, 2), "mid": round(mid, 2),
            "spread_bps": round(spread_bps, 4),
            "bb_qty": bt["B"] if bt else (bids5[0][1] if bids5 else 0.0),
            "ba_qty": bt["A"] if bt else (asks5[0][1] if asks5 else 0.0),
            "bid_depth5": round(sum(q for _, q in bids5), 7),
            "ask_depth5": round(sum(q for _, q in asks5), 7),
            "imb5": round(imb5, 6),
        }
        for n in self.bands:
            bs = walk_slippage_bps(bids5, mid, n)
            as_ = walk_slippage_bps(asks5, mid, n)
            row[f"slip_buy{n}"] = round(as_, 4) if as_ is not None else None
            row[f"slip_sell{n}"] = round(bs, 4) if bs is not None else None
        self._last_sample = time.time()
        self.rows += 1
        if self._dh:
            with open(self.path, "a") as f:
                f.write(json.dumps(row) + "\n")
            if self.rows % 60 == 0:
                self.log("samples=%d spread=%.2fbps dur=%.0fs" % (self.rows, spread_bps, time.time() - self.t0))

    def run(self, minutes=None, force_sample=False, report_every_min=None):
        url = self.cfg.ws + f"?streams={self.symbol}@bookTicker/{self.symbol}@depth@100ms"
        stop_triggered = [False]
        def handler(signum, frame):
            self.log("signal received, shutting down")
            self.stop_flag.set()
            stop_triggered[0] = True
        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

        def run_once():
            app = websocket.WebSocketApp(
                url, on_open=self.on_open, on_message=self.on_message,
                on_error=self.on_error, on_close=self.on_close)
            try:
                app.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                self.log("run error: %r" % (e,))

        t = threading.Thread(target=run_once, daemon=True)
        t.start()
        deadline = time.time() + minutes * 60 if minutes else None
        next_calib = None
        if report_every_min:
            from .cost_calibrate import summarize
            next_calib = time.time() + report_every_min * 60
        while not self.stop_flag.is_set():
            if deadline and time.time() >= deadline:
                self.log("sample window elapsed (%d min)" % minutes)
                break
            if next_calib and time.time() >= next_calib and self.path:
                try:
                    from .cost_calibrate import summarize
                    summarize(self.path, out_dir=self.path.parent)
                    self.log("calibration refreshed")
                except Exception as e:
                    self.log("calibration error: %r" % (e,))
                next_calib = time.time() + report_every_min * 60
            time.sleep(1)
        self.stop_flag.set()
        time.sleep(0.5)
        self.sample_best_final = getattr(self, "_last_sample", None)
        if force_sample:
            self.sample(force=True)
        self.log("done: rows=%d path=%s dur=%.0fs" % (self.rows, self.path, time.time() - self.t0))
        if self.path:
            from .cost_calibrate import summarize
            try:
                summarize(self.path, out_dir=self.path.parent)
                self.log("final calibration written")
            except Exception as e:
                self.log("final calibration error: %r" % (e,))
        return self.path


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    ap = argparse.ArgumentParser(description="Continuous BTCUSDT cost sampler")
    ap.add_argument("--minutes", type=float, default=90.0, help="sample window in minutes")
    ap.add_argument("--cadence", type=float, default=1.0, help="min seconds between samples")
    ap.add_argument("--out", type=str, default="data/live", help="output directory")
    ap.add_argument("--report-every", type=float, default=15.0,
                    help="regenerate calibration report every N minutes (0=off)")
    args = ap.parse_args()
    from .config import Config
    cs = CostSampler(cfg=Config(), out_dir=Path(args.out), cadence_s=args.cadence)
    cs.run(minutes=args.minutes, report_every_min=args.report_every or None)