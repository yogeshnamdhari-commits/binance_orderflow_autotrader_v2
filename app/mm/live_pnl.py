from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Fill:
    trade_id: str
    side: str
    qty: float
    price: float
    fee_usd: float = 0.0


@dataclass(frozen=True)
class PnLSnapshot:
    position_qty: float
    avg_entry_price: float
    realized_pnl_usd: float
    fees_usd: float
    mark_price: float
    inventory_mtm_usd: float
    net_pnl_usd: float


@dataclass
class LivePnL:
    """Idempotent exchange-fill P&L accumulator for one symbol/account mode.

    Realized P&L is generated only when fills reduce/reverse inventory. Open
    inventory is marked independently. Duplicate exchange trade IDs are ignored.
    """

    position_qty: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl_usd: float = 0.0
    fees_usd: float = 0.0
    _seen_trade_ids: set[str] = field(default_factory=set)

    def apply_fill(self, fill: Fill) -> bool:
        if fill.trade_id in self._seen_trade_ids:
            return False
        if fill.qty <= 0 or fill.price <= 0 or fill.side not in {"BUY", "SELL"}:
            raise ValueError("invalid fill")

        signed = fill.qty if fill.side == "BUY" else -fill.qty
        old_qty = self.position_qty
        old_avg = self.avg_entry_price

        if old_qty == 0 or (old_qty > 0 and signed > 0) or (old_qty < 0 and signed < 0):
            new_qty = old_qty + signed
            gross_abs = abs(old_qty) * old_avg + abs(signed) * fill.price
            self.position_qty = new_qty
            self.avg_entry_price = gross_abs / abs(new_qty) if new_qty else 0.0
        else:
            closing_qty = min(abs(old_qty), abs(signed))
            if old_qty > 0:
                self.realized_pnl_usd += closing_qty * (fill.price - old_avg)
            else:
                self.realized_pnl_usd += closing_qty * (old_avg - fill.price)

            new_qty = old_qty + signed
            self.position_qty = new_qty
            if new_qty == 0:
                self.avg_entry_price = 0.0
            elif (old_qty > 0 and new_qty > 0) or (old_qty < 0 and new_qty < 0):
                self.avg_entry_price = old_avg
            else:
                self.avg_entry_price = fill.price

        self.fees_usd += max(0.0, fill.fee_usd)
        self._seen_trade_ids.add(fill.trade_id)
        return True

    def snapshot(self, mark_price: float) -> PnLSnapshot:
        if mark_price < 0:
            raise ValueError("invalid mark price")
        if self.position_qty > 0:
            mtm = self.position_qty * (mark_price - self.avg_entry_price)
        elif self.position_qty < 0:
            mtm = abs(self.position_qty) * (self.avg_entry_price - mark_price)
        else:
            mtm = 0.0
        net = self.realized_pnl_usd + mtm - self.fees_usd
        return PnLSnapshot(
            position_qty=self.position_qty,
            avg_entry_price=self.avg_entry_price,
            realized_pnl_usd=self.realized_pnl_usd,
            fees_usd=self.fees_usd,
            mark_price=mark_price,
            inventory_mtm_usd=mtm,
            net_pnl_usd=net,
        )
