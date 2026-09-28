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
    guard.state.book_synchronized = True
    guard.state.user_stream_healthy = True
    guard.state.reconciliation_ok = True
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
        (root / "mm" / "config_v21_active_flow_hedge_01bps.json").read_text()
    )
    assert data["live_order_submission"] is False
    assert data["flow_quote_bias_bps"] == 1.0
    assert data["hedge_threshold_notional"] == 1000.0
    assert data["hedge_ratio"] == 0.5
    assert data["inventory_penalty_base_bps"] == 1.0
    assert data["inventory_penalty_slope"] == 0.5
    assert data["quote_size_reduction_after_breach"] == 0.5
    assert data["max_position_notional_usd"] == 5000.0
