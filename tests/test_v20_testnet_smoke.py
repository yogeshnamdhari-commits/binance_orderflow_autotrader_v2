from decimal import Decimal

import pytest

from scripts.v20_testnet_smoke import ALLOWED_DEMO_HOSTS, valid_passive_order


def test_smoke_allows_only_binance_demo_hosts():
    assert "demo-fapi.binance.com" in ALLOWED_DEMO_HOSTS
    assert "testnet.binancefuture.com" in ALLOWED_DEMO_HOSTS
    assert "fapi.binance.com" not in ALLOWED_DEMO_HOSTS


def test_smoke_order_sizing_meets_filters():
    info = {
        "symbol": "BTCUSDT",
        "status": "TRADING",
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "0.10", "minPrice": "0", "maxPrice": "0"},
            {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "100"},
            {"filterType": "MIN_NOTIONAL", "notional": "100"},
        ],
    }
    price, qty = valid_passive_order(info, 100000)
    assert price < 100000
    assert (price / Decimal("0.10")).to_integral_value() == price / Decimal("0.10")
    assert (qty / Decimal("0.001")).to_integral_value() == qty / Decimal("0.001")
    assert qty >= Decimal("0.001")
    assert price * qty >= Decimal("100")


def test_smoke_rejects_qty_when_min_notional_exceeds_max_qty():
    info = {
        "symbol": "BTCUSDT",
        "status": "TRADING",
        "filters": [
            {"filterType": "PRICE_FILTER", "tickSize": "1", "minPrice": "0", "maxPrice": "0"},
            {"filterType": "LOT_SIZE", "stepSize": "0.001", "minQty": "0.001", "maxQty": "0.01"},
            {"filterType": "MIN_NOTIONAL", "notional": "5000"},
        ],
    }
    with pytest.raises(SystemExit, match="no valid BTCUSDT smoke quantity"):
        valid_passive_order(info, 100000)
