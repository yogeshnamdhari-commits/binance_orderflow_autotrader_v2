from __future__ import annotations

from decimal import Decimal
import json
from pathlib import Path
import tempfile

import pytest

from app.mm.production_execution import (
    ProductionExecutionGuard,
    ProductionSafetyError,
    SymbolRules,
)


class FakeREST:
    def __init__(self):
        self.rules = SymbolRules(
            symbol="BTCUSDT",
            tick_size=Decimal("0.10"),
            min_price=Decimal("0"),
            max_price=Decimal("0"),
            step_size=Decimal("0.001"),
            min_qty=Decimal("0.001"),
            max_qty=Decimal("100"),
            min_notional=Decimal("5"),
        )

    def exchange_info(self, symbol):
        return self.rules

    def sync_clock(self):
        return 0

    def position_risk(self, symbol):
        return [{"symbol": symbol, "positionAmt": "0", "markPrice": "83000"}]

    def open_orders(self, symbol):
        return []

    def cancel_all(self, symbol):
        return {}

    def cancel_order(self, symbol, client_order_id):
        return {"clientOrderId": client_order_id, "status": "CANCELED"}


def write_manifest(path: Path, sha: str):
    path.write_text(json.dumps({
        "authorized": True,
        "candidate_config_sha256": sha,
        "required_research_commit": "a06e8f590634777bbd5ade86ef3b2563194ca2ed",
        "forward_certification_status": "PASS",
        "production_identity_status": "PASS",
        "execution_authorization": "AUTHORIZED",
    }))


def make_guard(fake, manifest_path):
    guard = ProductionExecutionGuard(
        rest=fake,
        symbol="BTCUSDT",
        max_position_notional_usd=5000,
        candidate_config_sha256="abc",
        research_reference_commit="a06e8f590634777bbd5ade86ef3b2563194ca2ed",
        manifest_path=manifest_path,
    )
    guard.rules = fake.rules
    guard.state.authorized = True
    guard.state.book_synchronized = True
    guard.state.user_stream_healthy = True
    guard.state.trade_stream_healthy = True
    guard.state.reconciliation_ok = True
    now_ms = 1_000_000
    guard.state.last_market_event_ms = now_ms
    guard.state.last_user_event_ms = now_ms
    guard.state.last_trade_event_ms = now_ms
    return guard


def test_price_and_quantity_normalization():
    fake = FakeREST()
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "manifest.json"
        write_manifest(mp, "abc")
        guard = make_guard(fake, mp)
        price, qty = guard.validate_quote(
            side="BUY",
            price=82999.97,
            qty=0.0027,
            best_bid=82999.80,
            best_ask=83000.10,
        )
        assert price == Decimal("82999.90")
        assert qty == Decimal("0.002")


def test_crossing_is_blocked():
    fake = FakeREST()
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "manifest.json"
        write_manifest(mp, "abc")
        guard = make_guard(fake, mp)
        with pytest.raises(ProductionSafetyError):
            guard.validate_quote(
                side="BUY",
                price=83000.20,
                qty=0.01,
                best_bid=82999.80,
                best_ask=83000.10,
            )


def test_position_limit_is_blocked():
    fake = FakeREST()
    with tempfile.TemporaryDirectory() as td:
        mp = Path(td) / "manifest.json"
        write_manifest(mp, "abc")
        guard = make_guard(fake, mp)
        guard.state.position_qty = 0.06
        with pytest.raises(ProductionSafetyError):
            guard.validate_quote(
                side="BUY",
                price=82999.90,
                qty=0.001,
                best_bid=82999.80,
                best_ask=83000.10,
            )


def test_candidate_parameters_remain_frozen():
    root = Path(__file__).resolve().parents[1]
    data = json.loads(
        (root / "app" / "mm" / "config_v21_active_flow_hedge_01bps.json").read_text()
    )
    assert data["live_order_submission"] is False
    assert data["flow_quote_bias_bps"] == 1.0
    assert data["hedge_threshold_notional"] == 1000.0
    assert data["hedge_ratio"] == 0.5
    assert data["inventory_penalty_base_bps"] == 1.0
    assert data["inventory_penalty_slope"] == 0.5
    assert data["quote_size_reduction_after_breach"] == 0.5
    assert data["max_position_notional_usd"] == 5000.0


def test_quote_requires_explicit_authorization():
    fake = FakeREST()
    with tempfile.TemporaryDirectory() as td:
        guard = make_guard(fake, Path(td) / "manifest.json")
        guard.state.authorized = False
        with pytest.raises(ProductionSafetyError, match="execution authorization"):
            guard.validate_quote(
                side="BUY",
                price=82999.90,
                qty=0.001,
                best_bid=82999.80,
                best_ask=83000.10,
            )


def test_user_stream_failure_revokes_authorization():
    fake = FakeREST()
    with tempfile.TemporaryDirectory() as td:
        guard = make_guard(fake, Path(td) / "manifest.json")
        guard.update_user_stream_health(
            False, event_ms=83000000, reason="test user stream failure"
        )
        assert guard.state.authorized is False
        assert guard.state.kill_switch is True


def test_live_runner_bootstraps_feeds_before_authorization():
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "active_flow_hedge_live.py").read_text()
    start_user = source.index("        self.user_stream.start()")
    start_market = source.index("        self.market_thread.start()")
    start_auth = source.index("        self.guard.authorize()")
    assert start_user < start_auth
    assert start_market < start_auth


def test_private_user_stream_uses_routed_endpoint():
    root = Path(__file__).resolve().parents[1]
    source = (root / "app" / "mm" / "production_execution.py").read_text()
    assert "wss://fstream.binance.com/private/ws/{listen_key}" in source


def test_trade_stream_failure_revokes_authorization():
    fake = FakeREST()
    with tempfile.TemporaryDirectory() as td:
        guard = make_guard(fake, Path(td) / "manifest.json")
        guard.state.trade_stream_healthy = False
        guard.state.last_trade_event_ms = 0
        with pytest.raises(ProductionSafetyError, match="trade stream stale"):
            guard.validate_quote(
                side="BUY",
                price=82999.90,
                qty=0.001,
                best_bid=82999.80,
                best_ask=83000.10,
            )
        assert guard.state.authorized is False
        assert guard.state.kill_switch is True


def test_live_runner_uses_current_routed_usdm_websockets():
    root = Path(__file__).resolve().parents[1]
    source = (root / "scripts" / "active_flow_hedge_live.py").read_text()
    assert "wss://fstream.binance.com/public/ws/" in source
    assert "wss://fstream.binance.com/market/stream?streams=" in source
    assert "wss://fstream.binance.com/private/ws/{listen_key}" in source
