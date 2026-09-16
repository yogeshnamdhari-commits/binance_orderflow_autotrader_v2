from decimal import Decimal

from app.mm.order_constraints import SymbolConstraints, find_symbol


def constraints():
    return SymbolConstraints(
        symbol="BTCUSDT",
        tick_size=Decimal("0.1"),
        min_price=Decimal("100"),
        max_price=Decimal("1000000"),
        step_size=Decimal("0.001"),
        min_qty=Decimal("0.001"),
        max_qty=Decimal("100"),
        min_notional=Decimal("5"),
    )


def test_valid_order_passes():
    ok, reasons = constraints().validate(100000.0, 0.001)
    assert ok
    assert reasons == ()


def test_tick_and_step_are_enforced():
    ok, reasons = constraints().validate(100000.05, 0.0015)
    assert not ok
    assert "price_tick_violation" in reasons
    assert "qty_step_violation" in reasons


def test_exchange_info_symbol_lookup():
    c = find_symbol({"symbols": [{
        "symbol": "BTCUSDT", "status": "TRADING",
        "filters": [
            {"filterType": "PRICE_FILTER", "minPrice": "1", "maxPrice": "2", "tickSize": "0.1"},
            {"filterType": "LOT_SIZE", "minQty": "0.001", "maxQty": "10", "stepSize": "0.001"},
        ]
    }]}, "BTCUSDT")
    assert c.tick_size == Decimal("0.1")
