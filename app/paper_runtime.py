"""Paper trading runtime — complete paper trading engine with position tracking,
PnL, fees, journals, and system health.

This module provides a self-contained paper trading engine that can run
deterministically from market data through signal → risk → execution →
position management → journaling, with full audit trail.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional
import json
import time

from .config import Config
from .execution import OrderStateManager, PaperExecution, ExecutionResult, OrderState
from .fillmodel import PassiveFillModel
from .journal import Journal
from .models import TradeEvent
from .reconciliation import ReconcileResult, reconcile_orders, reconcile_positions


class PaperOrderSide(Enum):
    BUY = "BUY"
    SELL = "SELL"


class PaperOrderStatus(Enum):
    NEW = "NEW"
    ACCEPTED = "ACCEPTED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


@dataclass
class PaperPosition:
    """Track paper trading position with PnL."""
    symbol: str
    qty: float = 0.0
    entry_price: float = 0.0
    avg_price: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    fees_paid: float = 0.0
    last_update_ms: int = 0

    @property
    def notional(self) -> float:
        return abs(self.qty) * self.avg_price if self.avg_price > 0 else 0.0

    def update_unrealized(self, mark_price: float):
        if self.qty != 0 and mark_price > 0:
            self.unrealized_pnl = (mark_price - self.avg_price) * self.qty
            if self.avg_price == 0:
                self.unrealized_pnl = 0.0
        else:
            self.unrealized_pnl = 0.0

    def total_pnl(self) -> float:
        return self.realized_pnl + self.unrealized_pnl - self.fees_paid


@dataclass
class PaperTrade:
    """Record of a paper trade execution."""
    trade_id: str
    order_id: str
    client_id: str
    symbol: str
    side: str
    qty: float
    price: float
    fee: float
    fee_asset: str
    timestamp_ms: int
    timestamp_iso: str
    realized_pnl: float = 0.0  # only for closing trades


@dataclass
class PaperSignal:
    """Record of a signal decision."""
    signal_id: str
    symbol: str
    action: str  # BUY, SELL, NO_TRADE
    side: str | None  # BUY, SELL
    gross_bps: float
    cost_bps: float
    net_bps: float
    probability: float
    reason: str
    book_state: str
    liquidity_state: str
    toxicity_state: str
    gates: dict
    timestamp_ms: int
    timestamp_iso: str


@dataclass
class RiskRejection:
    """Record of a risk rejection."""
    rejection_id: str
    symbol: str
    side: str | None
    qty: float
    reason: str
    details: dict
    timestamp_ms: int
    timestamp_iso: str


@dataclass
class ExecutionRejection:
    """Record of an execution rejection."""
    rejection_id: str
    order_id: str | None
    client_id: str
    symbol: str
    side: str
    qty: float
    price: float
    status: str
    reason: str
    timestamp_ms: int
    timestamp_iso: str


@dataclass
class SystemHealth:
    """System health/status snapshot."""
    timestamp_ms: int
    timestamp_iso: str
    feed_connected: bool
    feed_ready: bool
    book_synchronized: bool
    last_event_ms: int
    orders_open: int
    positions: dict
    equity: float
    daily_pnl: float
    drawdown_bps: float
    emergency_active: bool
    rejection_cooldown_active: bool
    feed_status: str = ""
    last_error: str = ""


class PaperTradingEngine:
    """Complete paper trading engine with full lifecycle management."""

    def __init__(
        self,
        config: Optional[Config] = None,
        starting_equity: float = 100_000.0,
        data_dir: str = "data/paper",
        journal_dir: str = "data/journals",
        fill_model: Optional[Any] = None,
    ):
        self.config = config or Config()
        self.starting_equity = starting_equity
        self.equity = starting_equity
        self.peak_equity = starting_equity
        self.data_dir = Path(data_dir)
        self.journal_dir = Path(journal_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.journal_dir.mkdir(parents=True, exist_ok=True)

        # Core components
        self.order_manager = OrderStateManager()
        self.execution = PaperExecution(self.order_manager)
        self.fill_model = fill_model
        self.risk_engine = None  # Set via set_risk_engine

        # State
        self.positions: dict[str, PaperPosition] = {}
        self.trades: list[PaperTrade] = []
        self.signals: list[PaperSignal] = []
        self.risk_rejections: list[RiskRejection] = []
        self.execution_rejections: list[ExecutionRejection] = []
        self.orders: dict[str, OrderState] = {}  # local order tracking
        self._trade_seq = 0
        self._signal_seq = 0
        self._rejection_seq = 0

        # Journals
        self.order_journal = Journal(self.journal_dir / "orders.jsonl")
        self.trade_journal = Journal(self.journal_dir / "trades.jsonl")
        self.signal_journal = Journal(self.journal_dir / "signals.jsonl")
        self.risk_rejection_journal = Journal(self.journal_dir / "risk_rejections.jsonl")
        self.execution_rejection_journal = Journal(self.journal_dir / "execution_rejections.jsonl")
        self.system_journal = Journal(self.journal_dir / "system.jsonl")

        # Feed state (set externally)
        self.feed = None
        self.book = None
        self.flow = None
        self.detector = None
        self.signal_engine = None
        self.decision_engine = None

        # Cost model params (from validated config)
        self.maker_fee_bps = 1.0
        self.taker_fee_bps = 2.0
        self.slippage_bps = 0.1
        self.impact_bps = 0.1
        self.margin_bps = 0.5

    def set_risk_engine(self, risk_engine):
        """Set the risk engine for pre-trade checks."""
        self.risk_engine = risk_engine

    def set_decision_engine(self, decision_engine):
        """Set the decision engine for signal evaluation."""
        self.decision_engine = decision_engine

    def set_market_data_components(self, book, flow, detector, signal_engine):
        """Set market data components."""
        self.book = book
        self.flow = flow
        self.detector = detector
        self.signal_engine = signal_engine

    def set_feed(self, feed):
        """Set the market data feed for health monitoring."""
        self.feed = feed

    # ------------------------------------------------------------------
    # Cost model helpers
    # ------------------------------------------------------------------
    def _calc_fee(self, notional: float, is_maker: bool) -> float:
        """Calculate fee for a trade."""
        fee_bps = self.maker_fee_bps if is_maker else self.taker_fee_bps
        return notional * fee_bps / 10000.0

    def _calc_slippage(self, notional: float) -> float:
        """Estimate slippage cost."""
        return notional * self.slippage_bps / 10000.0

    def _calc_impact(self, notional: float) -> float:
        """Estimate market impact cost."""
        return notional * self.impact_bps / 10000.0

    def _total_cost_bps(self, is_maker: bool) -> float:
        """Total round-trip cost in bps for a trade."""
        fee = self.maker_fee_bps if is_maker else self.taker_fee_bps
        return 2 * (fee + self.slippage_bps) + self.impact_bps + self.margin_bps

    # ------------------------------------------------------------------
    # Signal processing
    # ------------------------------------------------------------------
    def process_signal(self, features, book_state: str = "BOOK_VALID") -> dict:
        """Process features through signal -> decision -> risk -> execution pipeline.

        Returns dict with keys: action, signal, decision, risk, execution, journal_entry
        """
        now_ms = int(time.time() * 1000)
        self._signal_seq += 1

        # 1. Signal decision
        if self.decision_engine:
            decision = self.decision_engine.evaluate(features, book_state_str=book_state, book=self.book)
            signal = PaperSignal(
                signal_id=f"SIG-{self._signal_seq:06d}",
                symbol=features.get("symbol", "BTCUSDT"),
                action=decision.state.value,
                side=decision.side,
                gross_bps=decision.gross_bps,
                cost_bps=decision.cost_bps,
                net_bps=decision.net_bps,
                probability=decision.probability,
                reason=decision.reason,
                book_state=decision.book_state,
                liquidity_state=decision.liquidity_state,
                toxicity_state=decision.toxicity_state,
                gates=decision.gates,
                timestamp_ms=int(time.time() * 1000),
                timestamp_iso=datetime.now(timezone.utc).isoformat(),
            )
            self.signals.append(signal)
            self.signal_journal.write(signal.__dict__)
        else:
            # Fallback to simple signal engine
            from .signal import SignalEngine
            from .events import EventDetector
            sig_engine = SignalEngine()
            det = EventDetector()
            sig = sig_engine.decide(features, det.detect(features))
            decision = None

        # 2. Risk check
        risk_ok = False
        risk_reason = "NO_RISK_ENGINE"
        risk_qty = 0.0
        if self.risk_engine and decision and decision.side:
            entry = features.get("mid", 100.0)
            stop = entry * 0.995
            spread_bps = features.get("spread_bps", 1.0)
            rd = self.risk_engine.pre_trade(
                equity=self.equity,
                entry=entry,
                stop=stop,
                spread_bps=spread_bps,
                last_event_ms=self.book.state.last_event_ms if self.book else 0,
                now_ms=int(time.time() * 1000),
                connected=self.feed is not None and self.feed.ready if self.feed else False,
                open_orders=len(self.order_manager.open_orders),
            )
            risk_ok = rd.allowed
            risk_reason = rd.reason
            risk_qty = rd.qty if rd.allowed else 0.0

            if not rd.allowed:
                self._rejection_seq += 1
                rr = RiskRejection(
                    rejection_id=f"RR-{self._rejection_seq:06d}",
                    symbol=features.get("symbol", "BTCUSDT"),
                    side=decision.side,
                    qty=rd.qty,
                    reason=rd.reason,
                    details=rd.details,
                    timestamp_ms=int(time.time() * 1000),
                    timestamp_iso=datetime.now(timezone.utc).isoformat(),
                )
                self.risk_rejections.append(rr)
                self.risk_rejection_journal.write(rr.__dict__)

        # 3. Execution
        execution_result = None
        trade = None
        if risk_ok and decision and decision.side in ("BUY", "SELL"):
            side = decision.side
            qty = risk_qty
            price = features.get("mid", 100.0)
            client_id = f"auto-{int(time.time() * 1000)}"

            exec_result = self.execution.submit(
                symbol=features.get("symbol", "BTCUSDT"),
                side=side,
                qty=qty,
                price=price,
                client_id=client_id,
                book=self.book,
            )
            execution_result = exec_result

            if exec_result.status == "PAPER_FILLED":
                # Create trade record
                self._trade_seq += 1
                notional = qty * price
                is_maker = False  # paper fills at touch = taker
                fee = self._calc_fee(notional, is_maker)
                fee_asset = "USDT"

                trade = PaperTrade(
                    trade_id=f"TRD-{self._trade_seq:06d}",
                    order_id=exec_result.order_id,
                    client_id=client_id,
                    symbol=features.get("symbol", "BTCUSDT"),
                    side=side,
                    qty=qty,
                    price=price,
                    fee=fee,
                    fee_asset=fee_asset,
                    timestamp_ms=int(time.time() * 1000),
                    timestamp_iso=datetime.now(timezone.utc).isoformat(),
                )
                self.trades.append(trade)
                self.trade_journal.write(trade.__dict__)

                # Update position
                pos = self.positions.setdefault(trade.symbol, PaperPosition(symbol=trade.symbol))
                if (side == "BUY" and pos.qty >= 0) or (side == "SELL" and pos.qty <= 0):
                    # Adding to position
                    new_qty = pos.qty + (qty if side == "BUY" else -qty)
                    pos.avg_price = (pos.avg_price * pos.qty + price * qty) / new_qty if new_qty != 0 else price
                    pos.qty = new_qty
                else:
                    # Reducing/flipping position
                    if abs(qty) >= abs(pos.qty):
                        # Flipping or closing
                        realized = (price - pos.avg_price) * pos.qty if pos.qty != 0 else 0.0
                        pos.realized_pnl += realized - self._calc_fee(abs(pos.qty) * pos.avg_price, False)
                        pos.qty = (qty if side == "BUY" else -qty) - (-pos.qty if pos.qty < 0 else pos.qty)
                        pos.avg_price = price if pos.qty != 0 else 0.0
                    else:
                        # Partial close
                        realized = (price - pos.avg_price) * (qty if side == "SELL" else -qty)
                        pos.realized_pnl += realized - self._calc_fee(qty * price, False)
                        pos.qty += qty if side == "BUY" else -qty

                pos.fees_paid += fee
                pos.last_update_ms = int(time.time() * 1000)

            elif exec_result.status.startswith("REJECTED") or exec_result.status in ("TIMEOUT", "CANCELLED"):
                self._rejection_seq += 1
                er = ExecutionRejection(
                    rejection_id=f"ER-{self._rejection_seq:06d}",
                    order_id=exec_result.order_id,
                    client_id=client_id,
                    symbol=features.get("symbol", "BTCUSDT"),
                    side=side,
                    qty=qty,
                    price=price,
                    status=exec_result.status,
                    reason=exec_result.message,
                    timestamp_ms=int(time.time() * 1000),
                    timestamp_iso=datetime.now(timezone.utc).isoformat(),
                )
                self.execution_rejections.append(er)
                self.execution_rejection_journal.write(er.__dict__)

        # 4. Journal decision
        decision_entry = {
            "type": "decision",
            "timestamp_ms": int(time.time() * 1000),
            "timestamp_iso": datetime.now(timezone.utc).isoformat(),
            "symbol": features.get("symbol", "BTCUSDT"),
            "action": decision.side if decision else "NO_TRADE",
            "reason": decision.reason if decision else "no decision engine",
            "gross_bps": decision.gross_bps if decision else 0,
            "cost_bps": decision.cost_bps if decision else 0,
            "net_bps": decision.net_bps if decision else 0,
            "risk_ok": risk_ok,
            "risk_reason": risk_reason,
            "risk_qty": risk_qty,
            "execution_status": execution_result.status if execution_result else "N/A",
            "order_id": execution_result.order_id if execution_result else None,
            "trade_id": trade.trade_id if trade else None,
        }
        self.order_journal.write(decision_entry)

        return {
            "action": decision.side if decision else "NO_TRADE",
            "signal": self.signals[-1] if self.signals else None,
            "decision": decision,
            "risk": {"allowed": risk_ok, "reason": risk_reason, "qty": risk_qty},
            "execution": execution_result,
            "trade": trade,
            "journal_entry": decision_entry,
        }

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------
    def update_mark_prices(self, mark_prices: dict[str, float]):
        """Update mark prices for unrealized PnL calculation."""
        for symbol, price in mark_prices.items():
            if symbol in self.positions:
                self.positions[symbol].update_unrealized(price)

    def get_total_equity(self) -> float:
        """Calculate total equity (cash + unrealized PnL - fees)."""
        total = self.equity
        for pos in self.positions.values():
            total += pos.total_pnl()
        return total

    def get_positions_summary(self) -> dict:
        """Get summary of all positions."""
        return {
            symbol: {
                "qty": pos.qty,
                "entry_price": pos.entry_price,
                "avg_price": pos.avg_price,
                "mark_price": pos.avg_price + (pos.unrealized_pnl / pos.qty) if pos.qty != 0 else 0,
                "realized_pnl": pos.realized_pnl,
                "unrealized_pnl": pos.unrealized_pnl,
                "fees_paid": pos.fees_paid,
                "total_pnl": pos.total_pnl(),
            }
            for symbol, pos in self.positions.items()
        }

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------
    def reconcile_orders(self, exchange_orders: list, now_ms: int | None = None) -> ReconcileResult:
        """Reconcile local orders against exchange orders."""
        local_open = self.order_manager.open_orders
        return reconcile_orders(local_open, exchange_orders, now_ms, stale_ms=5000)

    def reconcile_positions(self, exchange_positions: dict[str, float]) -> dict:
        """Reconcile local positions against exchange positions."""
        results = {}
        all_symbols = set(self.positions.keys()) | set(exchange_positions.keys())
        for sym in all_symbols:
            local = self.positions.get(sym)
            local_qty = local.qty if local else 0.0
            ex_qty = exchange_positions.get(sym, 0.0)
            results[sym] = reconcile_positions(local_qty, ex_qty)
        return results

    # ------------------------------------------------------------------
    # System health / status
    # ------------------------------------------------------------------
    def get_health(self) -> SystemHealth:
        """Get current system health snapshot."""
        now_ms = int(time.time() * 1000)
        feed_ready = self.feed.ready if self.feed else False
        feed_connected = self.feed is not None and hasattr(self.feed, 'ready')
        book_sync = self.book.state.synchronized if self.book else False
        last_event = self.book.state.last_event_ms if self.book else 0

        total_unrealized = sum(p.unrealized_pnl for p in self.positions.values())
        total_realized = sum(p.realized_pnl for p in self.positions.values())
        total_fees = sum(p.fees_paid for p in self.positions.values())
        equity = self.starting_equity + total_realized + total_unrealized - total_fees

        return SystemHealth(
            timestamp_ms=now_ms,
            timestamp_iso=datetime.now(timezone.utc).isoformat(),
            feed_connected=feed_connected,
            feed_ready=feed_ready,
            book_synchronized=book_sync,
            last_event_ms=last_event,
            orders_open=len(self.order_manager.open_orders),
            positions=self.get_positions_summary(),
            equity=equity,
            daily_pnl=equity - self.starting_equity,
            drawdown_bps=0.0 if self.peak_equity == 0 else max(0.0, (self.peak_equity - equity) / self.peak_equity * 10000),
            emergency_active=self.risk_engine.emergency if self.risk_engine else False,
            rejection_cooldown_active=self.risk_engine.rejection_cooldown_active(now_ms / 1000.0) if self.risk_engine else False,
            feed_status=getattr(self.feed, 'status', ''),
            last_error="",
        )

    def log_health(self):
        """Log system health to journal."""
        health = self.get_health()
        self.system_journal.write(health.__dict__)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def save_state(self, path: str | Path):
        """Save complete paper trading state."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "equity": self.equity,
            "peak_equity": self.peak_equity,
            "starting_equity": self.starting_equity,
            "positions": {s: p.__dict__ for s, p in self.positions.items()},
            "orders": self.order_manager.summary(),
            "trades": [t.__dict__ for t in self.trades],
            "signals": [s.__dict__ for s in self.signals],
            "risk_rejections": [r.__dict__ for r in self.risk_rejections],
            "execution_rejections": [e.__dict__ for e in self.execution_rejections],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        Path(path).write_text(json.dumps(state, indent=2))
        return path

    def load_state(self, path: str | Path):
        """Load paper trading state."""
        path = Path(path)
        if not path.exists():
            return False
        try:
            state = json.loads(path.read_text())
        except (json.JSONDecodeError, ValueError):
            return False

        self.equity = state.get("equity", self.starting_equity)
        self.peak_equity = state.get("peak_equity", self.starting_equity)

        for sym, pos_data in state.get("positions", {}).items():
            pos = PaperPosition(**pos_data)
            self.positions[sym] = pos

        self.order_manager.load(state.get("orders_file", ""))

        return True


# Convenience function for quick paper trading setup
def create_paper_engine(
    symbol: str = "BTCUSDT",
    starting_equity: float = 100_000.0,
    data_dir: str = "data/paper",
    journal_dir: str = "data/journals",
) -> PaperTradingEngine:
    """Create a configured paper trading engine with default components."""
    from .orderbook import LocalOrderBook
    from .features import OrderFlowEngine
    from .events import EventDetector
    from .signal import SignalEngine
    from .decision import DecisionEngine
    from .risk import RiskEngine
    from .fillmodel import PassiveFillModel
    from .config import Config

    cfg = Config()
    book = LocalOrderBook(cfg.levels)
    flow = OrderFlowEngine(book)
    detector = EventDetector()
    signal_engine = SignalEngine()
    decision_engine = DecisionEngine()
    risk_engine = RiskEngine()

    engine = PaperTradingEngine(
        config=cfg,
        starting_equity=starting_equity,
        data_dir=data_dir,
        journal_dir=journal_dir,
    )

    engine.set_risk_engine(risk_engine)
    engine.set_decision_engine(decision_engine)
    engine.set_market_data_components(book, flow, detector, signal_engine)

    return engine


__all__ = [
    "PaperTradingEngine",
    "PaperPosition",
    "PaperTrade",
    "PaperSignal",
    "RiskRejection",
    "ExecutionRejection",
    "SystemHealth",
    "PaperOrderSide",
    "PaperOrderStatus",
    "create_paper_engine",
]