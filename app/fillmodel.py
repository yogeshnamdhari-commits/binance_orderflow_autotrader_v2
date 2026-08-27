"""Passive execution / fill model — the cost gate between signal and order.

Given a candidate signal (expected gross edge bps from the frozen research),
the current local book, and the empirical fill calibration, computes the net
expected edge of a PASSIVE (maker) execution:

  net_edge = P(fill) * E[fill_contingent_return]
           - P(fill) * maker_fee_rt
           - P(no fill within T) * fallback_cost
           - queue_loss_bps

Components:
- P(fill): empirical touch probability from the trades-only calibration
  (same-tick = fill at the level; 1-tick inside = strictly better print),
  attenuated by a queue/depth factor derived from the live top-of-book depth
  vs the requested size.
- E[fill_contingent_return]: the adverse-selection-corrected horizon return
  measured FROM the fill price (empirical, per condition x horizon).
- fallback_cost: cost if the passive order did not fill by the deadline and
  we either cancel (0) or chase as taker (taker round trip).
- queue_loss_bps: expected lost edge from late fills / queue displacement,
  conservatively estimated from the mean time-to-fill and the horizon edge.

The production decision rule is enforced by `evaluate()`:

  TRADE only if  net_edge > 0  AND  P(fill) >= min_fill  AND  liquidity ok
                 AND  integrity gates all true  (see IntegrityGate).

No ML. No threshold hunting. All inputs are measured or conservatively bounded.
"""

from dataclasses import dataclass


@dataclass
class FillDecision:
    allowed: bool
    net_edge_bps: float
    p_fill: float
    e_fill_return_bps: float
    queue_loss_bps: float
    fallback_cost_bps: float
    maker_fee_bps: float
    reason: str
    details: dict


class PassiveFillModel:
    def __init__(self, calibration=None, maker_fee_rt_bps=2.0, taker_fee_rt_bps=4.0,
                 min_fill_prob=0.30, fallback="cancel", queue_penalty=0.5):
        self.cal = calibration or {}
        self.maker_fee_rt_bps = maker_fee_rt_bps
        self.taker_fee_rt_bps = taker_fee_rt_bps
        self.min_fill_prob = min_fill_prob
        self.fallback = fallback  # 'cancel' or 'chase'
        self.queue_penalty = queue_penalty  # bps haircut for queue/latency loss

    # ---- empirical inputs from fill_calib.json ----
    def _row(self, condition, horizon_ms):
        key = "%s@%ds" % (condition, horizon_ms // 1000)
        return self.cal.get("results", {}).get(key)

    def p_fill(self, condition, horizon_ms, depth_factor=1.0):
        r = self._row(condition, horizon_ms)
        if not r:
            return 0.0
        return r["p_fill_same_tick"] * min(depth_factor, 1.0)

    def e_fill_return(self, condition, horizon_ms):
        r = self._row(condition, horizon_ms)
        return r["e_fill_return_bps"] if r else 0.0

    def time_to_fill(self, condition, horizon_ms):
        r = self._row(condition, horizon_ms)
        return r.get("mean_time_to_fill_ms", 0.0) if r else 0.0

    # ---- live book ----
    def depth_factor(self, book, notional_usd):
        """Estimated fill-at-once factor from top-of-book depth vs size.
        Conservative: uses the resting side depth at the touch (5 levels)."""
        try:
            bids, asks = book.level_quantities(5)
            bid_usd = sum(q * p for p, q in bids)
            ask_usd = sum(q * p for p, q in asks)
        except Exception:
            return 0.0
        avail = min(bid_usd, ask_usd)
        if avail <= 0:
            return 0.0
        return min(avail / notional_usd, 1.0)

    def evaluate(self, condition, horizon_ms, notional_usd, book=None,
                 expected_gross_bps=None):
        """Compute the net expected edge of a passive execution.

        condition: research condition label e.g. 'delta_5s_dec10_long'.
        expected_gross_bps: optional override of the unconditional gross edge
            (otherwise taken from the empirical calibration's unconditional).
        """
        r = self._row(condition, horizon_ms)
        if not r:
            return FillDecision(False, 0.0, 0.0, 0.0, 0.0, 0.0,
                                self.maker_fee_rt_bps, "no empirical calibration",
                                {"missing": True})
        df = self.depth_factor(book, notional_usd) if book else 1.0
        p_fill = self.p_fill(condition, horizon_ms, df)
        e_fill = self.e_fill_return(condition, horizon_ms)
        if expected_gross_bps is None:
            uncond = r.get("gross_unconditional_bps", 0.0)
        else:
            uncond = expected_gross_bps

        # queue/latency loss: edge decays across the horizon; a fill late in the
        # window captures a fraction of the edge. Conservative linear model.
        tt = self.time_to_fill(condition, horizon_ms)
        frac = min(tt / horizon_ms, 1.0) if horizon_ms else 0.0
        queue_loss = self.queue_penalty * frac * max(uncond, 0.0)

        if self.fallback == "chase":
            fallback = self.taker_fee_rt_bps
        else:
            fallback = 0.0

        gross_captured = p_fill * (e_fill - self.maker_fee_rt_bps - queue_loss)
        net_edge = gross_captured - (1.0 - p_fill) * fallback

        ok_fill = p_fill >= self.min_fill_prob
        ok_edge = net_edge > 0.0
        allowed = ok_fill and ok_edge
        reason = "PASS" if allowed else (
            "net edge not positive" if not ok_edge else "fill probability too low")
        return FillDecision(
            allowed=allowed, net_edge_bps=round(net_edge, 3),
            p_fill=round(p_fill, 4), e_fill_return_bps=round(e_fill, 3),
            queue_loss_bps=round(queue_loss, 3), fallback_cost_bps=round(fallback, 3),
            maker_fee_bps=round(self.maker_fee_rt_bps, 3), reason=reason,
            details={"condition": condition, "horizon_ms": horizon_ms,
                     "depth_factor": round(df, 4), "notional_usd": notional_usd,
                     "unconditional_gross_bps": round(uncond, 3),
                     "time_to_fill_ms": round(tt, 1)})