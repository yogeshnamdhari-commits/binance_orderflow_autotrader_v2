from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN
from typing import Any


@dataclass(frozen=True)
class SymbolConstraints:
    symbol: str
    tick_size: Decimal
    min_price: Decimal
    max_price: Decimal
    step_size: Decimal
    min_qty: Decimal
    max_qty: Decimal
    min_notional: Decimal = Decimal("0")

    @staticmethod
    def _d(value: Any) -> Decimal:
        return Decimal(str(value or "0"))

    @classmethod
    def from_exchange_info(cls, symbol_info: dict[str, Any]) -> "SymbolConstraints":
        filters = {f["filterType"]: f for f in symbol_info.get("filters", [])}
        price = filters.get("PRICE_FILTER", {})
        lot = filters.get("LOT_SIZE", {})
        notion = filters.get("MIN_NOTIONAL", {})
        return cls(
            symbol=str(symbol_info["symbol"]),
            tick_size=cls._d(price.get("tickSize")),
            min_price=cls._d(price.get("minPrice")),
            max_price=cls._d(price.get("maxPrice")),
            step_size=cls._d(lot.get("stepSize")),
            min_qty=cls._d(lot.get("minQty")),
            max_qty=cls._d(lot.get("maxQty")),
            min_notional=cls._d(notion.get("notional", notion.get("minNotional"))),
        )

    def normalize_price(self, price: float) -> float:
        value = self._d(price)
        if self.tick_size <= 0:
            return float(value)
        steps = (value - self.min_price) / self.tick_size
        normalized = self.min_price + steps.to_integral_value(rounding=ROUND_DOWN) * self.tick_size
        return float(normalized)

    def normalize_qty(self, qty: float) -> float:
        value = self._d(qty)
        if self.step_size <= 0:
            return float(value)
        steps = (value - self.min_qty) / self.step_size
        normalized = self.min_qty + steps.to_integral_value(rounding=ROUND_DOWN) * self.step_size
        return float(normalized)

    def validate(self, price: float, qty: float) -> tuple[bool, tuple[str, ...]]:
        p = self._d(price)
        q = self._d(qty)
        reasons: list[str] = []
        if p <= 0 or q <= 0:
            reasons.append("non_positive_price_or_qty")
        if self.min_price > 0 and p < self.min_price:
            reasons.append("price_below_min")
        if self.max_price > 0 and p > self.max_price:
            reasons.append("price_above_max")
        if self.tick_size > 0:
            steps = (p - self.min_price) / self.tick_size
            if steps != steps.to_integral_value():
                reasons.append("price_tick_violation")
        if q < self.min_qty:
            reasons.append("qty_below_min")
        if self.max_qty > 0 and q > self.max_qty:
            reasons.append("qty_above_max")
        if self.step_size > 0:
            steps = (q - self.min_qty) / self.step_size
            if steps != steps.to_integral_value():
                reasons.append("qty_step_violation")
        if self.min_notional > 0 and p * q < self.min_notional:
            reasons.append("min_notional_violation")
        return len(reasons) == 0, tuple(reasons)


def find_symbol(exchange_info: dict[str, Any], symbol: str) -> SymbolConstraints:
    target = symbol.upper()
    for info in exchange_info.get("symbols", []):
        if str(info.get("symbol", "")).upper() == target:
            if str(info.get("status", "TRADING")) != "TRADING":
                raise RuntimeError(f"symbol_not_trading:{target}")
            return SymbolConstraints.from_exchange_info(info)
    raise RuntimeError(f"symbol_not_found:{target}")
