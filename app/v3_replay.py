"""V3 deterministic replay — rebuild book from immutable raw log -> rich V3 rows.

Reads a session's raw.jsonl and reproduces the EXACT book the collector had,
then computes the V3 execution-aware feature row per event. This mirrors the
data that the live collector would produce, so derived.jsonl is a pure
function of the immutable raw log (recv_ms excluded from comparison).

Feature rationale (predeclared, all microstructure-driven, NO indicator stacks):
  ofi_l1 / ofi_l5     CKS order-flow imbalance (sum of signed qty deltas by
                      side across changed price levels in the depth event)
  ofi_norm_l1         ofi / depth1  (Cont-Kukanov-Stoikov: impact per unit depth)
  qi_l1               B-A / B+A at best (queue imbalance)
  di_l5, di_l10       distance-weighted multi-level depth imbalance
  mpd_bps             microprice offset from mid (microprice = qty-weighted mid)
  spread_bps          (best_ask - best_bid) / mid
  depth_slope_bps     log-depth decay across levels 1..10 (liquidity shape)
  bid/ask add/cancel  bps-normalized qty added vs cancelled per side per event
  cancel_pressure     (bid_cancels + ask_cancels) / depth1
  tfi_500 / signed_vol_500 / trade_rate   aggressive bought/sold flow, 500 ms
  liq_depletion       near-touch depth consumed by recent aggressors / depth5
  regime              descriptive liquidity state (thin_book / high_impact / normal)

The regime label is a predeclared rule-based diagnostic, not a tradable
parameter. Nothing here is fitted to OOS.
"""

import argparse
import json
from pathlib import Path

import numpy as np

from .l2_replay import DepthEventReplay
from .orderbook import LocalOrderBook

THIN_BOOK_BTC = 5.0
HIGH_IMPACT_OFI_NORM = 1.0
WINDOW_MS = 500


class BookStats:
    """Book-derived microstructure stats (shareable per event)."""

    def __init__(self, book, microb_prev=None):
        self.book = book
        self.b = book.state.best_bid()
        self.a = book.state.best_ask()
        self.mid = book.state.mid()
        self.spread_bps = book.state.spread_bps() or 0.0
        self.bq = book.state.bids.get(self.b, 0.0) if self.b else 0.0
        self.aq = book.state.asks.get(self.a, 0.0) if self.a else 0.0
        self.microb = self._microprice()
        self.mpd_bps = (self.microb - self.mid) / self.mid * 1e4 if self.mid else 0.0

    def _microprice(self):
        b, a = self.b, self.a
        if b is None or a is None or (self.bq + self.aq) <= 0:
            return self.mid
        return (a * self.bq + b * self.aq) / (self.bq + self.aq)

    def qi_l1(self):
        den = self.bq + self.aq
        return (self.bq - self.aq) / den if den else 0.0

    def _levels(self, n):
        return self.book.level_quantities(n)

    def multi_di(self, n):
        wb = sum((n - i + 1) * q for i, (_, q) in enumerate(self._levels(n)[0][:n]))
        wa = sum((n - i + 1) * q for i, (_, q) in enumerate(self._levels(n)[1][:n]))
        return (wb - wa) / (wb + wa) if (wb + wa) else 0.0

    def depth_slope_bps(self):
        bq = [q for _, q in self._levels(10)[0]]
        aq = [q for _, q in self._levels(10)[1]]
        if not bq or not aq:
            return 0.0
        logq = np.log1p(np.array(bq + aq))
        return float(np.polyfit(np.arange(len(logq)), logq, 1)[0])


class ReplayV3:
    def __init__(self, book=None, log=print):
        self.book = book or LocalOrderBook(50)
        self.log = log
        self.rows = []
        self.ready = False
        self.skips = 0
        self.trades = []
        self.prev_bids = {}
        self.prev_asks = {}
        self.prev_stats = None

    def feed_line(self, line):
        rec = json.loads(line)
        kind = rec["kind"]
        now_ms = int(rec.get("recv_ms", 0))
        if kind == "snapshot":
            self.book.load_snapshot(rec["bids"], rec["asks"], rec["last_update_id"])
            self.prev_bids = dict(self.book.state.bids)
            self.prev_asks = dict(self.book.state.asks)
            self.ready = True
            return
        if kind == "bookTicker":
            return
        if not self.ready:
            self.skips += 1
            return

        if kind == "depth":
            e = DepthEventReplay(rec)
            status = self.book.apply(e)
            if status != "OK":
                self.ready = False
                self.skips += 1
                return
            flow = self._flow(rec["E"])
            ofi = self._ofi(rec)
            cancel = self._cancel(rec)
            row = self._row(rec["E"], now_ms, "depth",
                            seq="%s-%s" % (e.first_update_id, e.final_update_id),
                            ofi=ofi, cancel=cancel, flow=flow)
            self.rows.append(row)
            self.prev_bids = dict(self.book.state.bids)
            self.prev_asks = dict(self.book.state.asks)
        elif kind == "trade":
            side = "SELL" if rec["m"] else "BUY"
            self.trades.append((rec["T"], float(rec["q"]), side))
            flow = self._flow(rec["T"])
            row = self._row(rec["T"], now_ms, "trade", seq=rec["a"],
                            ofi=None, cancel=None, flow=flow)
            self.rows.append(row)
        else:
            raise ValueError("unknown raw kind: %r" % kind)

    def _flow(self, ts_ms):
        window = [t for t in self.trades if ts_ms - t[0] <= WINDOW_MS]
        vbuy = sum(t[1] for t in window if t[2] == "BUY")
        vsell = sum(t[1] for t in window if t[2] == "SELL")
        den = vbuy + vsell
        st = self.book.state
        d5 = (sum(q for _, q in self.book.level_quantities(5)[0]) +
              sum(q for _, q in self.book.level_quantities(5)[1]))
        if den <= 0:
            return {"tfi_500": 0.0, "signed_vol_500": 0.0, "trade_rate": 0.0,
                    "liq_depletion": 0.0}
        return {"tfi_500": (vbuy - vsell) / den, "signed_vol_500": vbuy - vsell,
                "trade_rate": len(window), "liq_depletion": den / d5 if d5 else 0.0}

    def _ofi(self, rec):
        """CKS OFI: sum of signed qty deltas per side over changed levels."""
        ob, oa = 0.0, 0.0
        for p, q in rec["bids"]:
            p, q = float(p), float(q)
            prev = self.prev_bids.get(p, 0.0)
            ob += q - prev
        for p, q in rec["asks"]:
            p, q = float(p), float(q)
            prev = self.prev_asks.get(p, 0.0)
            oa += q - prev
        return {"ofi_bid": ob, "ofi_ask": oa, "ofi": ob - oa}

    def _cancel(self, rec):
        """Quantities added vs cancelled at touched price levels."""
        ba = ca = aadd = caa = 0.0
        for p, q in rec["bids"]:
            p, q = float(p), float(q)
            d = q - self.prev_bids.get(p, 0.0)
            if d >= 0:
                ba += d
            else:
                ca += -d
        for p, q in rec["asks"]:
            p, q = float(p), float(q)
            d = q - self.prev_asks.get(p, 0.0)
            if d >= 0:
                aadd += d
            else:
                caa += -d
        return {"bid_add": ba, "bid_cancel": ca, "ask_add": aadd,
                "ask_cancel": caa, "of_cancel": ca + caa, "of_add": ba + aadd}

    def _row(self, ts_ms, recv_ms, kind, seq, ofi, cancel, flow):
        cancel = cancel or {}
        ofi = ofi or {}
        bs = BookStats(self.book)
        st = self.book.state
        d1 = bs.bq + bs.aq
        d5sum = (sum(q for _, q in self.book.level_quantities(5)[0]) +
                 sum(q for _, q in self.book.level_quantities(5)[1]))
        ofi_norm = (ofi["ofi"] / d1 if (ofi and d1 > 0) else 0.0)
        fdiv = d1 if d1 > 0 else np.finfo(float).eps
        regime = ("thin_book" if d1 < THIN_BOOK_BTC
                  else ("high_impact" if abs(ofi_norm) > HIGH_IMPACT_OFI_NORM
                        else "normal"))
        mid = bs.mid or 0.0
        to_bps = lambda q: q / mid * 1e4 if mid else 0.0
        row = {
            "ts_ms": ts_ms, "recv_ms": recv_ms, "kind": kind, "seq": seq,
            "best_bid": bs.b, "best_ask": bs.a, "mid": mid,
            "spread_bps": round(bs.spread_bps, 6),
            "microb_price": bs.microb, "mpd_bps": round(bs.mpd_bps, 6),
            "qi_l1": round(bs.qi_l1(), 6),
            "di_l5": round(bs.multi_di(5), 6),
            "di_l10": round(bs.multi_di(10), 6),
            "depth_slope_bps": round(bs.depth_slope_bps(), 6),
            "ofi_l1": round(ofi["ofi"], 6) if ofi else 0.0,
            "ofi_norm_l1": round(ofi_norm, 6),
            "bid_add_bps": round(to_bps(cancel.get("bid_add", 0.0)), 6),
            "bid_cancel_bps": round(to_bps(cancel.get("bid_cancel", 0.0)), 6),
            "ask_add_bps": round(to_bps(cancel.get("ask_add", 0.0)), 6),
            "ask_cancel_bps": round(to_bps(cancel.get("ask_cancel", 0.0)), 6),
            "cancel_pressure": round((cancel.get("bid_cancel", 0.0) + cancel.get("ask_cancel", 0.0))
                                     / fdiv, 6),
            "log_depth1": np.log1p(d1),
            "log_depth5": np.log1p(d5sum),
            "log_event_rate": np.log1p(flow["trade_rate"]),
            "tfi_500": round(flow["tfi_500"], 6),
            "signed_vol_500": round(flow["signed_vol_500"], 6),
            "trade_rate": int(flow["trade_rate"]),
            "liq_depletion": round(flow["liq_depletion"], 6),
            "regime": regime,
        }
        return row


def replay_session(session_dir, write=True, log=print):
    session_dir = Path(session_dir)
    raw = session_dir / "raw.jsonl"
    if not raw.exists():
        raise FileNotFoundError("no raw.jsonl in %s" % session_dir)
    rp = ReplayV3(log=log)
    with open(raw) as f:
        for line in f:
            line = line.strip()
            if line:
                rp.feed_line(line)
    if write:
        out = session_dir / "derived.jsonl"
        with open(out, "w") as f:
            for row in rp.rows:
                f.write(json.dumps(row) + "\n")
        log("v3 replay %s: %d rows, %d skips" % (session_dir.name,
                                                 len(rp.rows), rp.skips))
    return rp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("session_dirs", nargs="+", type=Path)
    a = ap.parse_args()
    total = 0
    for sd in a.session_dirs:
        rp = replay_session(sd, write=True)
        total += len(rp.rows)
    print("total v3 rows:", total)


if __name__ == "__main__":
    main()