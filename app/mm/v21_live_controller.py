"""Fail-closed V21 live quote controller.

The controller is an execution adapter around the already-tested V21 causal
features and frozen model bundle. It does not train models, does not submit
crossing orders, and defaults to deployment-disabled. A caller must pass a
deployment authorization result before any exchange submission is attempted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

import numpy as np

from app.models import BookState, DepthEvent, TradeEvent
from app.research.v21_orderflow_core import BookTop, CausalOrderFlowState
from app.research.v21_production_model import V21ModelBundle, V21Prediction
from .execution_gateway import ExecutionGateway, Submission
from .live_risk import LiveRiskGate


@dataclass(frozen=True)
class LiveQuote:
    side: str
    price: float
    qty: float


@dataclass(frozen=True)
class V21QuotePlan:
    timestamp_ms: int
    bid: Optional[LiveQuote]
    ask: Optional[LiveQuote]
    bid_edge_bps: float
    ask_edge_bps: float
    prediction: V21Prediction
    reason: str
    live_allowed: bool


class V21LiveController:
    """V21 causal inference + passive quoting controller.

    Feed synchronization remains owned by the exchange market-data layer.
    This controller requires a synchronized BookState and derives all model
    inputs from the current book plus prior causal event history.
    """

    def __init__(
        self,
        *,
        gateway: ExecutionGateway,
        risk: LiveRiskGate,
        model: V21ModelBundle,
        symbol: str,
        tick_size: float,
        maker_fee_bps: float,
        half_spread_bps: float = 2.5,
        min_edge_bps: float = 0.10,
        toxicity_multiplier: float = 1.0,
        inventory_penalty_bps: float = 2.0,
        max_position_notional_usd: float = 5000.0,
        quote_size_usd: float = 100.0,
        quote_interval_ms: int = 100,
        live_authorized: bool = False,
    ) -> None:
        if tick_size <= 0:
            raise ValueError("tick_size must be positive")
        if maker_fee_bps < 0:
            raise ValueError("maker_fee_bps must be non-negative")
        if half_spread_bps <= 0:
            raise ValueError("half_spread_bps must be positive")
        if min_edge_bps < 0 or toxicity_multiplier < 0:
            raise ValueError("economic thresholds must be non-negative")
        if max_position_notional_usd <= 0 or quote_size_usd <= 0:
            raise ValueError("position and quote notional limits must be positive")
        if quote_interval_ms <= 0:
            raise ValueError("quote_interval_ms must be positive")

        self.gateway = gateway
        self.risk = risk
        self.model = model
        self.symbol = symbol.upper()
        self.tick_size = float(tick_size)
        self.maker_fee_bps = float(maker_fee_bps)
        self.half_spread_bps = float(half_spread_bps)
        self.min_edge_bps = float(min_edge_bps)
        self.toxicity_multiplier = float(toxicity_multiplier)
        self.inventory_penalty_bps = float(inventory_penalty_bps)
        self.max_position_notional_usd = float(max_position_notional_usd)
        self.quote_size_usd = float(quote_size_usd)
        self.quote_interval_ms = int(quote_interval_ms)
        self.live_authorized = bool(live_authorized)

        self.flow = CausalOrderFlowState()
        self._last_rebalance_ms: int | None = None
        self._active: dict[str, str] = {}  # side -> exchange order id
        self._active_price: dict[str, float] = {}
        self._client_seq = 0

    def set_live_authorization(self, authorized: bool) -> None:
        self.live_authorized = bool(authorized)

    def _top_and_features(self, book: BookState, timestamp_ms: int) -> tuple[BookTop, np.ndarray]:
        if not book.synchronized:
            raise RuntimeError("book_not_synchronized")
        bids = book.top_bids(5)
        asks = book.top_asks(5)
        if not bids or not asks:
            raise RuntimeError("missing_top_of_book")
        top = BookTop(
            bid_price=float(bids[0][0]),
            bid_qty=float(bids[0][1]),
            ask_price=float(asks[0][0]),
            ask_qty=float(asks[0][1]),
        )
        if not top.valid:
            raise RuntimeError("invalid_top_of_book")
        features = self.flow.snapshot(timestamp_ms)
        bid5 = sum(float(q) for _, q in bids)
        ask5 = sum(float(q) for _, q in asks)
        depth5 = (bid5 - ask5) / (bid5 + ask5) if bid5 + ask5 > 0 else 0.0
        x = np.asarray(
            [
                features.queue_imbalance,
                features.microprice_edge_bps,
                features.ofi_100ms,
                features.ofi_500ms,
                features.ofi_1000ms,
                features.trade_imbalance_100ms,
                features.trade_imbalance_500ms,
                features.trade_imbalance_1000ms,
                features.trade_intensity_notional_s,
                features.spread_bps,
                features.mid_return_100ms_bps,
                features.mid_return_500ms_bps,
                depth5,
            ],
            dtype=float,
        )
        return top, x

    def _floor_tick(self, price: float) -> float:
        return np.floor(price / self.tick_size) * self.tick_size

    def _ceil_tick(self, price: float) -> float:
        return np.ceil(price / self.tick_size) * self.tick_size

    def _quote_decision(
        self,
        top: BookTop,
        prediction: V21Prediction,
        inventory_units: float,
    ) -> V21QuotePlan:
        inventory_notional = float(inventory_units) * top.mid
        inventory_fraction = max(
            -1.0,
            min(1.0, inventory_notional / self.max_position_notional_usd),
        )
        inventory_shift = -inventory_fraction * self.inventory_penalty_bps
        reservation_shift = prediction.expected_signed_move_bps + inventory_shift
        reservation = top.mid * (1.0 + reservation_shift / 10_000.0)

        half = self.half_spread_bps / 10_000.0
        raw_bid = reservation * (1.0 - half)
        raw_ask = reservation * (1.0 + half)

        bid = self._floor_tick(raw_bid)
        ask = self._ceil_tick(raw_ask)

        bid_cross = bid >= top.ask_price
        ask_cross = ask <= top.bid_price
        if bid_cross:
            bid = None
        if ask_cross:
            ask = None
        if bid is not None and ask is not None and bid >= ask:
            bid = None
            ask = None
            bid_cross = True
            ask_cross = True

        bid_edge = (
            ((top.mid - bid) * 10_000.0 / top.mid if bid else 0.0)
            + prediction.expected_signed_move_bps
            - self.maker_fee_bps
            - self.toxicity_multiplier * prediction.toxicity_buy_bps
        )
        ask_edge = (
            ((ask - top.mid) * 10_000.0 / top.mid if ask else 0.0)
            - prediction.expected_signed_move_bps
            - self.maker_fee_bps
            - self.toxicity_multiplier * prediction.toxicity_sell_bps
        )

        bid_enabled = bid is not None and bid_edge >= self.min_edge_bps
        ask_enabled = ask is not None and ask_edge >= self.min_edge_bps

        if inventory_notional >= self.max_position_notional_usd:
            bid_enabled = False
        if inventory_notional <= -self.max_position_notional_usd:
            ask_enabled = False

        reasons: list[str] = []
        if bid_cross:
            reasons.append("bid_crossing_suppressed")
        if ask_cross:
            reasons.append("ask_crossing_suppressed")
        if not bid_enabled and not bid_cross:
            reasons.append("bid_edge_below_threshold")
        if not ask_enabled and not ask_cross:
            reasons.append("ask_edge_below_threshold")
        if not reasons:
            reasons.append("quote_eligible")

        bid_quote = (
            LiveQuote("BUY", float(bid), self.quote_size_usd / float(bid))
            if bid_enabled and bid and bid > 0
            else None
        )
        ask_quote = (
            LiveQuote("SELL", float(ask), self.quote_size_usd / float(ask))
            if ask_enabled and ask and ask > 0
            else None
        )
        return V21QuotePlan(
            timestamp_ms=0,
            bid=bid_quote,
            ask=ask_quote,
            bid_edge_bps=float(bid_edge),
            ask_edge_bps=float(ask_edge),
            prediction=prediction,
            reason=";".join(reasons),
            live_allowed=False,
        )

    def on_order_update(self, order_id: str, side: str, status: str) -> None:
        """Release local quote ownership when the exchange reaches a terminal state."""
        side = side.upper()
        if self._active.get(side) != str(order_id):
            return
        if status.upper() in {"FILLED", "CANCELED", "CANCELLED", "REJECTED", "EXPIRED", "EXPIRED_IN_MATCH"}:
            self._active.pop(side, None)
            self._active_price.pop(side, None)

    def on_trade(self, event: TradeEvent) -> None:
        signed = float(event.qty) if event.aggressor_side == "BUY" else -float(event.qty)
        self.flow.update_trade(int(event.ts_ms), signed, float(event.qty) * float(event.price))

    def on_depth(self, event: DepthEvent, book: BookState, inventory_units: float) -> V21QuotePlan:
        now_ms = int(event.ts_ms)
        self.flow.update_book(now_ms, BookTop(
            float(book.best_bid()),
            float(book.best_bid_qty() or 0.0),
            float(book.best_ask()),
            float(book.best_ask_qty() or 0.0),
        ))
        top, x = self._top_and_features(book, now_ms)
        prediction = self.model.predict(x)
        plan = self._quote_decision(top, prediction, inventory_units)
        # The plan is computed from the current event-time book, so its quote
        # timestamp is fresh. This prevents the initial fail-closed sentinel
        # quote age from blocking the first evaluated quote.
        self.risk.update_quote_age(0)
        allowed, reasons = self.risk.can_quote()
        live_allowed = self.live_authorized and self.gateway.live_enabled and allowed
        reason = plan.reason
        if not allowed:
            reason = ";".join([reason, *reasons])
        return V21QuotePlan(
            timestamp_ms=now_ms,
            bid=plan.bid,
            ask=plan.ask,
            bid_edge_bps=plan.bid_edge_bps,
            ask_edge_bps=plan.ask_edge_bps,
            prediction=plan.prediction,
            reason=reason,
            live_allowed=live_allowed,
        )

    def apply_plan(self, plan: V21QuotePlan) -> dict[str, object]:
        """Apply one already-computed plan.

        Live order submission is impossible unless both the external deployment
        gate and ExecutionGateway.live_enabled are true. Otherwise this method
        returns a dry-run decision and performs no exchange call.
        """
        now = int(plan.timestamp_ms)

        # Safety takes precedence over quote throttling. If an already-live
        # controller loses authorization or risk health, cancel active quotes
        # immediately rather than waiting for the next quote interval.
        if not plan.live_allowed:
            if self._active and self.gateway.live_enabled:
                cancelled = self.cancel_all()
                return {"status": "LIVE_DISABLED_CANCELLED", "actions": cancelled["actions"], "plan": plan}
            self._last_rebalance_ms = now
            return {"status": "DRY_RUN_BLOCKED", "actions": [], "plan": plan}

        if self._last_rebalance_ms is not None and now - self._last_rebalance_ms < self.quote_interval_ms:
            return {"status": "THROTTLED", "plan": plan}

        desired = {
            "BUY": plan.bid,
            "SELL": plan.ask,
        }
        actions: list[dict[str, object]] = []

        for side in ("BUY", "SELL"):
            active_id = self._active.get(side)
            desired_quote = desired[side]
            if active_id and (
                desired_quote is None
                or abs(float(self._active_price.get(side, 0.0)) - (desired_quote.price if desired_quote else 0.0))
                > max(self.tick_size * 0.5, 1e-12)
            ):
                result = self.gateway.cancel(active_id)
                actions.append({"action": "cancel", "side": side, "result": result.status})
                if result.status in {"CANCEL_UNKNOWN", "REJECTED_UNKNOWN_ORDER"}:
                    return {"status": "BLOCKED_AFTER_CANCEL", "actions": actions, "plan": plan}
                self._active.pop(side, None)
                self._active_price.pop(side, None)

        if not plan.live_allowed:
            self._last_rebalance_ms = now
            return {
                "status": "DRY_RUN_BLOCKED",
                "actions": actions,
                "plan": plan,
            }

        self.risk.update_orders(len(self.gateway.manager.open_orders))
        for side in ("BUY", "SELL"):
            quote = desired[side]
            if quote is None or side in self._active:
                continue
            self._client_seq += 1
            client_id = f"V21-{side[0]}-{now}-{self._client_seq:08d}"
            result = self.gateway.submit(
                Submission(
                    self.symbol,
                    quote.side,
                    quote.qty,
                    quote.price,
                    client_id,
                )
            )
            actions.append({"action": "submit", "side": side, "result": result.status})
            if result.order_id:
                self._active[side] = str(result.order_id)
                self._active_price[side] = quote.price
            if result.status == "UNKNOWN_SUBMISSION":
                self.risk.emergency_stop()
                return {"status": "EMERGENCY_STOP", "actions": actions, "plan": plan}

        self.risk.update_orders(len(self.gateway.manager.open_orders))
        self.risk.update_quote_age(0)
        self._last_rebalance_ms = now
        return {"status": "LIVE_APPLIED", "actions": actions, "plan": plan}

    def cancel_all(self) -> dict[str, object]:
        # Exchange-wide symbol cancellation is the authoritative safety
        # action; local cleanup follows the exchange response. This prevents
        # orphaned quotes when local state has lost an order binding.
        actions: list[dict[str, object]] = []
        bulk = self.gateway.cancel_all(self.symbol)
        actions.append({"action": "cancel_all_exchange", "result": bulk.status})
        if bulk.status in {
            "CANCEL_ALL_UNKNOWN",
            "CANCEL_ALL_UNSUPPORTED",
            "BLOCKED_LIVE_DISABLED",
        }:
            self.risk.emergency_stop()
            return {"status": "CANCEL_ALL_BLOCKED", "actions": actions}

        for side, order_id in list(self._active.items()):
            actions.append({"action": "clear_local", "side": side, "order_id": order_id})
            self._active.pop(side, None)
            self._active_price.pop(side, None)

        self.risk.update_orders(len(self.gateway.manager.open_orders))
        return {"status": "CANCELLED_ALL", "actions": actions}
