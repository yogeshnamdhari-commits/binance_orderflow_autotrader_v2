"""Live adapter for the existing ACTIVE_FLOW_HEDGE-0.1 quote generator."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import time

from .live_quote_engine import ActiveFlowHedgeQuoteEngine
from .book import OrderBook
from .config import V20Config
from .production_execution import (
    BinanceFuturesREST,
    ProductionExecutionGuard,
    ProductionSafetyError,
)


@dataclass(frozen=True)
class ManagedQuote:
    side: str
    price: float
    qty: float
    client_order_id: str


class ActiveFlowHedgeLiveController:
    """Wrap the existing quote calculation with the production safety boundary.

    This class does not add a new alpha model. It uses the same generate_quotes()
    primitive and the same authoritative ACTIVE_FLOW_HEDGE configuration.
    """

    def __init__(
        self,
        config: V20Config,
        guard: ProductionExecutionGuard,
    ) -> None:
        self.config = config
        self.guard = guard
        self._revision = 0
        self._quote_engine = ActiveFlowHedgeQuoteEngine(config)

    @staticmethod
    def _book_imbalance(book: OrderBook) -> float:
        if not book.bids or not book.asks:
            return 0.0
        bid = max(book.bids)
        ask = min(book.asks)
        bq = max(0.0, book.bids[bid])
        aq = max(0.0, book.asks[ask])
        denom = bq + aq
        return (bq - aq) / denom if denom > 0 else 0.0

    def build_quotes(
        self,
        *,
        book: OrderBook,
        inventory: float,
        flow_imbalance: float,
        inventory_penalty_bps: float | None = None,
        quote_size_scale: float = 1.0,
    ) -> tuple[ManagedQuote, ...]:
        if not book.is_valid():
            raise ProductionSafetyError("invalid L2 book")

        best_bid = max(book.bids)
        best_ask = min(book.asks)

        pair = self._quote_engine.build(
            book=book,
            inventory=inventory,
            flow_imbalance=flow_imbalance,
            inventory_penalty_bps=inventory_penalty_bps,
            quote_size_scale=quote_size_scale,
        )

        quotes: list[ManagedQuote] = []
        self._revision += 1
        nonce = int(time.time() * 1000)
        for side, price, qty, prefix in (
            ("BUY", pair.bid_price, pair.bid_qty, "B"),
            ("SELL", pair.ask_price, pair.ask_qty, "S"),
        ):
            try:
                p, q = self.guard.validate_quote(
                    side=side,
                    price=price,
                    qty=qty,
                    best_bid=best_bid,
                    best_ask=best_ask,
                )
            except ProductionSafetyError:
                continue
            client_id = f"AFH01-{prefix}-{nonce}-{self._revision}"
            if len(client_id) > 36:
                digest = hashlib.sha1(client_id.encode()).hexdigest()[:8]
                client_id = f"AFH01-{prefix}-{digest}-{self._revision}"
            quotes.append(
                ManagedQuote(
                    side=side,
                    price=float(p),
                    qty=float(q),
                    client_order_id=client_id,
                )
            )
        return tuple(quotes)

    def submit(
        self,
        quotes: tuple[ManagedQuote, ...],
        *,
        best_bid: float,
        best_ask: float,
    ) -> list[dict]:
        results = []
        for quote in quotes:
            results.append(
                self.guard.submit_quote(
                    side=quote.side,
                    price=quote.price,
                    qty=quote.qty,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    client_order_id=quote.client_order_id,
                )
            )
        return results


def build_production_stack(
    *,
    config: V20Config,
    config_sha256: str,
    manifest_path: str = "data/live/active_flow_hedge_deployment.json",
    kill_switch_path: str = "data/live/ACTIVE_FLOW_HEDGE_KILL",
) -> tuple[BinanceFuturesREST, ProductionExecutionGuard, ActiveFlowHedgeLiveController]:
    """Construct, but do not authorize, the production stack."""
    import os

    client = BinanceFuturesREST(
        api_key=os.environ.get("BINANCE_API_KEY", ""),
        api_secret=os.environ.get("BINANCE_API_SECRET", ""),
        base_url=os.environ.get("BINANCE_REST", "https://fapi.binance.com"),
    )
    guard = ProductionExecutionGuard(
        rest=client,
        symbol=config.symbol,
        max_position_notional_usd=config.max_position_notional_usd,
        candidate_config_sha256=config_sha256,
        research_reference_commit="a06e8f590634777bbd5ade86ef3b2563194ca2ed",
        manifest_path=manifest_path,
        kill_switch_path=kill_switch_path,
    )
    controller = ActiveFlowHedgeLiveController(config, guard)
    return client, guard, controller
