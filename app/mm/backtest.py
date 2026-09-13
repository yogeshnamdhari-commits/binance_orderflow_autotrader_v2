from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence
import numpy as np

from app.v19.features import L2Event, compute_orderflow_features
from app.mm.quoting import QuoteEngine, QuoteState
from app.mm.inventory import InventoryManager, InventoryState
from app.mm.fill_sim import FillSimulator, FillResult


@dataclass(frozen=True)
class MMTrade:
    side: str
    price: float
    qty: float
    timestamp_ns: int
    realized_pnl_bps: float
    adverse_selection_bps: float
    queue_position: int


@dataclass(frozen=True)
class MMResult:
    total_pnl_bps: float
    realized_spread_bps: float
    adverse_selection_bps: float
    maker_fees_bps: float
    fill_count: int
    cancel_count: int
    inventory_max: float
    inventory_final: float
    regime_profitability: dict[int, float]
    trades: tuple[MMTrade, ...]


class MarketMakingBacktest:
    def __init__(
        self,
        base_half_spread_bps: float = 0.75,
        max_half_spread_bps: float = 2.50,
        inventory_penalty_bps: float = 0.50,
        inventory_target: float = 0.0,
        max_position_notional_usd: float = 5000.0,
        adverse_selection_threshold_bps: float = 0.75,
        cancel_on_adverse_selection: bool = True,
        maker_fee_bps: float = 0.0,
        taker_fee_bps: float = 3.0,
    ):
        self.quote_engine = QuoteEngine(
            base_half_spread_bps=base_half_spread_bps,
            max_half_spread_bps=max_half_spread_bps,
            inventory_penalty_bps=inventory_penalty_bps,
            inventory_target=inventory_target,
            adverse_selection_threshold_bps=adverse_selection_threshold_bps,
            cancel_on_adverse_selection=cancel_on_adverse_selection,
        )
        self.inventory_manager = InventoryManager(
            inventory_target=inventory_target,
            inventory_penalty_bps=inventory_penalty_bps,
            max_position_notional_usd=max_position_notional_usd,
        )
        self.fill_sim = FillSimulator(
            maker_fee_bps=maker_fee_bps,
            taker_fee_bps=taker_fee_bps,
        )

    def run(
        self,
        events: Sequence[L2Event],
        config: dict,
    ) -> MMResult:
        trades: list[MMTrade] = []
        cancels = 0
        total_pnl = 0.0
        realized_spread = 0.0
        adverse_selection_total = 0.0
        maker_fees_total = 0.0
        max_inventory = 0.0
        position = 0.0
        regime_pnl: dict[int, float] = {}

        current_price = self._get_mid_price(events)
        if current_price <= 0:
            return MMResult(
                total_pnl_bps=0.0,
                realized_spread_bps=0.0,
                adverse_selection_bps=0.0,
                maker_fees_bps=0.0,
                fill_count=0,
                cancel_count=0,
                inventory_max=0.0,
                inventory_final=0.0,
                regime_profitability={},
                trades=(),
            )

        for event in events:
            features = compute_orderflow_features(events[:events.index(event) + 1], event.timestamp_ns)
            now_ns = event.timestamp_ns

            inventory_state = self.inventory_manager.update(
                position, current_price, "", 0.0
            )
            max_inventory = max(max_inventory, abs(inventory_state.position))

            quote_state = self.quote_engine.generate_quotes(
                events, now_ns, current_price, inventory_state.position, config.get("max_position_notional_usd", 5000.0)
            )

            adverse_selection = features["spread_bps"] * 0.5
            should_cancel, cancel_reason = self.quote_engine.should_cancel(
                quote_state, features, adverse_selection
            )
            if should_cancel:
                cancels += 1
                continue

            fill_result = self.fill_sim.simulate_fill(
                quote_side="BUY",
                quote_price=quote_state.bid_price,
                quote_qty=quote_state.bid_qty,
                best_bid=quote_state.bid_price,
                best_ask=quote_state.ask_price,
                trade_price=current_price,
                trade_qty=0.001,
                trade_side="SELL",
                queue_depth=1,
            )

            if fill_result.filled:
                trade = MMTrade(
                    side=fill_result.side,
                    price=fill_result.price,
                    qty=fill_result.qty,
                    timestamp_ns=now_ns,
                    realized_pnl_bps=fill_result.realized_pnl_bps,
                    adverse_selection_bps=fill_result.adverse_selection_bps,
                    queue_position=fill_result.queue_position,
                )
                trades.append(trade)
                total_pnl += fill_result.realized_pnl_bps
                realized_spread += fill_result.realized_pnl_bps + fill_result.adverse_selection_bps
                adverse_selection_total += fill_result.adverse_selection_bps
                maker_fees_total += self.fill_sim.maker_fee_bps

                if fill_result.side == "BUY":
                    position += fill_result.qty
                else:
                    position -= fill_result.qty

                regime = int(features["volatility_regime"])
                regime_pnl[regime] = regime_pnl.get(regime, 0.0) + fill_result.realized_pnl_bps

        return MMResult(
            total_pnl_bps=float(total_pnl),
            realized_spread_bps=float(realized_spread),
            adverse_selection_bps=float(adverse_selection_total),
            maker_fees_bps=float(maker_fees_total),
            fill_count=len(trades),
            cancel_count=cancels,
            inventory_max=float(max_inventory),
            inventory_final=float(position),
            regime_profitability={int(k): float(v) for k, v in regime_pnl.items()},
            trades=tuple(trades),
        )

    def _get_mid_price(self, events: Sequence[L2Event]) -> float:
        if not events:
            return 0.0
        last = events[-1]
        return float((last.bid_px + last.ask_px) / 2.0)
