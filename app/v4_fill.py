"""V4 deterministic maker fill simulator — queue position + fill from the L2 stream.

Execution-model layer (NOT a signal layer; V3 frozen model is untouched):
  - a passive maker order is posted at the touch (buy at best_bid / sell at best_ask)
    AT THE BACK of the queue (ahead = full displayed size at that price level)
  - the simulator walks the replayed V4 event stream and reconstructs queue
    consumption price-level by price-level:
        depth deltas that shrink our price level count as queue consumed (fills
        or cancels ahead of us, both reduce time-to-fill);
        aggressive trades AT our price consume queue FIFO;
        a market sweep that removes our whole level (best price moves through
        ours) fills us at our limit price ("swept") — the classic maker adverse
        selection event measured conditionally on fills;
  - if neither full nor partial fill occurs within max_wait_ms the remainder is
    cancelled (cost applied by the caller).

Everything is a pure function of the immutable V4 derived rows (same raw logs
as V3). No randomness: is_fill, fill time, fill ratio and price are all
deterministic per (order, stream).
"""

import json
from pathlib import Path

import numpy as np

MAX_WAIT_MS = 5000          # predeclared: cancel after 5 s unfilled
LEG_REASON_SWEPT = "swept"
LEG_REASON_TRADE = "trade"
LEG_REASON_NONE = "none"


class SessionStream:
    """Arrays of one session's V4 derived rows for fast, index-accurate sim."""

    def __init__(self, rows):
        n = len(rows)
        self.ts = np.array([r["ts_ms"] for r in rows], dtype=np.int64)
        self.kind = np.array([1 if r["kind"] == "trade" else 0 for r in rows],
                             dtype=np.int8)
        self.bid = np.array([(r.get("best_bid") or 0.0) for r in rows], dtype=float)
        self.ask = np.array([(r.get("best_ask") or 0.0) for r in rows], dtype=float)
        self.mid = np.array([(r.get("mid") or 0.0) for r in rows], dtype=float)
        L = 0
        for r in rows:
            L = max(L, len(r.get("levels_bid", [])))
        rows_L = []
        rows_A = []
        for r in rows:
            lb = r.get("levels_bid", [])
            la = r.get("levels_ask", [])
            bp = np.full(L, -1.0); bq = np.zeros(L); ap = np.full(L, -1.0); aq = np.zeros(L)
            for k, (p, q) in enumerate(lb):
                if k >= L:
                    break
                bp[k] = p; bq[k] = q
            for k, (p, q) in enumerate(la):
                if k >= L:
                    break
                ap[k] = p; aq[k] = q
            rows_L.append(bp); rows_A.append(ap)
            # store qty aligned with price for per-price lookup
        self.bid_p = np.stack(rows_L) if rows_L else np.zeros((n, 1))
        self.ask_p = np.stack(rows_A) if rows_A else np.zeros((n, 1))
        self._bid_q = np.zeros((n, self.bid_p.shape[1]))
        self._ask_q = np.zeros((n, self.ask_p.shape[1]))
        for j, r in enumerate(rows):
            lb = r.get("levels_bid", [])
            for k, (p, q) in enumerate(lb):
                if k < self._bid_q.shape[1]:
                    self._bid_q[j, k] = q
            la = r.get("levels_ask", [])
            for k, (p, q) in enumerate(la):
                if k < self._ask_q.shape[1]:
                    self._ask_q[j, k] = q
        self.tprice = np.array([r.get("trade_price") for r in rows], dtype=float)
        self.tqty = np.array([r.get("trade_qty") for r in rows], dtype=float)
        self.tmaker = np.array([bool(r.get("trade_maker")) for r in rows],
                               dtype=bool)

    def __len__(self):
        return len(self.ts)

    def qty_at(self, i, side, price):
        """side: 0=buy queue (bids), 1=sell queue (asks). 0.0 if absent."""
        prices = self.bid_p[i] if side == 0 else self.ask_p[i]
        quals = self._bid_q[i] if side == 0 else self._ask_q[i]
        for k in range(len(prices)):
            if prices[k] == price:
                return float(quals[k])
        return 0.0

    def best(self, i, side):
        return self.bid[i] if side == 0 else self.ask[i]


def load_stream(path):
    rows = [json.loads(line) for line in Path(path).open() if line.strip()]
    return SessionStream(rows)


def sim_maker_leg(ss, i0, dir_sign, qty, max_wait_ms=MAX_WAIT_MS):
    """Post qty at the touch. dir_sign=+1 posts a BUY (best_bid); -1 a SELL
    (best_ask). Returns fills measured from the L2 event stream (deterministic).

    Returns dict with filled_ratio, fill_time_ms (None if no fill), fill_price,
    reason (swept / trade / none) and queue detail.
    """
    out = {"placed": False, "price": None, "ahead0": 0.0, "ours": float(qty),
           "consumed": 0.0, "filled_ratio": 0.0, "filled_qty": 0.0,
           "fill_time_ms": None, "fill_price": None, "reason": LEG_REASON_NONE,
           "max_wait_ms": int(max_wait_ms)}
    if i0 >= len(ss) or i0 < 0:
        return out
    side = 0 if dir_sign > 0 else 1                 # 0=bid queue, 1=ask queue
    P = ss.best(i0, side)
    if not P or P <= 0:
        return out
    out["placed"] = True
    out["price"] = P
    ours = float(qty)
    ahead0 = ss.qty_at(i0, side, P)
    out["ahead0"] = ahead0
    consumed = 0.0
    t0 = ss.ts[i0]
    i = i0 + 1
    prev_qP = ahead0
    while i < len(ss) and ss.ts[i] - t0 <= max_wait_ms:
        qP = ss.qty_at(i, side, P)
        if ss.kind[i] == 1 and ss.tprice[i] == P:
            aggressor = ss.tmaker[i]
            if (dir_sign > 0 and aggressor) or (dir_sign < 0 and not aggressor):
                consumed += float(ss.tqty[i])
                out["reason"] = LEG_REASON_TRADE
        else:
            best_px = ss.best(i, side)
            swept = (best_px < P) if dir_sign > 0 else (best_px > P)
            if swept:
                consumed = ahead0 + ours
                out["reason"] = LEG_REASON_SWEPT
            elif qP < prev_qP:
                consumed += prev_qP - qP
        filled = max(0.0, min(ours, consumed - ahead0))
        if filled >= ours - 1e-9:
            out["filled_qty"] = ours
            out["filled_ratio"] = 1.0
            out["fill_time_ms"] = int(ss.ts[i])
            out["fill_price"] = P
            return out
        prev_qP = qP
        i += 1
    if consumed - ahead0 > 1e-12:
        filled = min(ours, consumed - ahead0)
        out["filled_qty"] = filled
        out["filled_ratio"] = round(filled / ours, 9)
        out["fill_time_ms"] = int(ss.ts[i - 1])
        out["fill_price"] = P
    return out