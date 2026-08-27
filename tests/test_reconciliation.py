"""Tests for the reconciliation utility (app.reconciliation)."""
import pytest
from app.reconciliation import (
    ReconcileResult,
    reconcile_orders,
    reconcile_positions,
    categorize_order_lifecycle,
    is_terminal_status,
    can_transition,
)


class TestReconcileOrders:
    def test_matched_orders(self):
        local = [{
            "order_id": "ORD-1",
            "client_id": "c1",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "qty": 1.0,
            "filled_qty": 1.0,
            "status": "FILLED",
        }]
        exchange = [{
            "orderId": "ORD-1",
            "clientOrderId": "c1",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "origQty": "1.0",
            "executedQty": "1.0",
            "status": "FILLED",
        }]
        res = reconcile_orders(local, exchange)
        assert "ORD-1" in res.matched
        assert not res.local_only
        assert not res.exchange_only

    def test_local_only_order(self):
        local = [{
            "order_id": "ORD-1",
            "client_id": "c1",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "qty": 1.0,
            "filled_qty": 0.0,
            "status": "OPEN",
        }]
        exchange = []
        res = reconcile_orders(local, exchange)
        assert "ORD-1" in res.local_only

    def test_exchange_only_order(self):
        local = []
        exchange = [{
            "orderId": "EX-1",
            "clientOrderId": "c1",
            "symbol": "BTCUSDT",
            "side": "SELL",
            "origQty": "1.0",
            "executedQty": "0.5",
            "status": "PARTIALLY_FILLED",
        }]
        res = reconcile_orders(local, exchange)
        assert "EX-1" in res.exchange_only

    def test_partial_fill_mismatch(self):
        local = [{
            "order_id": "ORD-1",
            "client_id": "c1",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "qty": 1.0,
            "filled_qty": 0.3,
            "status": "PARTIAL",
        }]
        exchange = [{
            "orderId": "ORD-1",
            "clientOrderId": "c1",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "origQty": "1.0",
            "executedQty": "0.8",
            "status": "PARTIALLY_FILLED",
        }]
        res = reconcile_orders(local, exchange)
        assert len(res.partial_mismatch) == 1
        assert res.partial_mismatch[0]["local_filled"] == 0.3
        assert res.partial_mismatch[0]["exchange_filled"] == 0.8
        assert "ORD-1" in res.matched

    def test_duplicate_client_ids(self):
        local = [
            {"order_id": "ORD-1", "client_id": "c1", "symbol": "BTCUSDT", "side": "BUY", "qty": 1.0, "filled_qty": 0, "status": "OPEN"},
            {"order_id": "ORD-2", "client_id": "c1", "symbol": "BTCUSDT", "side": "BUY", "qty": 1.0, "filled_qty": 0, "status": "OPEN"},
        ]
        exchange = []
        res = reconcile_orders(local, exchange)
        assert "ORD-2" in res.duplicate_client_ids

    def test_stale_local_detection(self):
        local = [{
            "order_id": "ORD-1",
            "client_id": "c1",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "qty": 1.0,
            "filled_qty": 0,
            "status": "OPEN",
            "updated_at": "2024-01-01T00:00:00+00:00",
        }]
        exchange = [{
            "orderId": "ORD-1",
            "clientOrderId": "c1",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "origQty": "1.0",
            "executedQty": "0",
            "status": "NEW",
        }]
        now_ms = 1_704_070_800_000  # 2024-01-01T01:00:00 (1 hour later) in ms
        stale_ms = 300_000  # 5 minutes
        res = reconcile_orders(local, exchange, now_ms=now_ms, stale_ms=stale_ms)
        assert "ORD-1" in res.stale_local


class TestReconcilePositions:
    def test_positions_match(self):
        res = reconcile_positions(1.5, 1.5)
        assert res["diff"] == 0.0
        assert not res["mismatch"]

    def test_positions_mismatch(self):
        res = reconcile_positions(1.5, 1.0)
        assert res["diff"] == -0.5
        assert res["mismatch"]


class TestOrderLifecycle:
    def test_categorize_lifecycle(self):
        assert categorize_order_lifecycle("OPEN") == "active"
        assert categorize_order_lifecycle("PARTIAL") == "active"
        assert categorize_order_lifecycle("FILLED") == "terminal_filled"
        assert categorize_order_lifecycle("CANCELLED") == "terminal_other"
        assert categorize_order_lifecycle("REJECTED") == "terminal_other"
        assert categorize_order_lifecycle("TIMEOUT") == "terminal_other"
        assert categorize_order_lifecycle("UNKNOWN") == "unknown"

    def test_is_terminal(self):
        assert is_terminal_status("FILLED")
        assert is_terminal_status("CANCELLED")
        assert is_terminal_status("REJECTED")
        assert is_terminal_status("TIMEOUT")
        assert not is_terminal_status("OPEN")
        assert not is_terminal_status("PARTIAL")

    def test_can_transition(self):
        assert can_transition("OPEN", "PARTIAL")
        assert can_transition("OPEN", "FILLED")
        assert can_transition("OPEN", "CANCELLED")
        assert can_transition("OPEN", "REJECTED")
        assert can_transition("OPEN", "TIMEOUT")
        assert can_transition("PARTIAL", "FILLED")
        assert can_transition("PARTIAL", "CANCELLED")
        assert not can_transition("FILLED", "OPEN")
        assert not can_transition("CANCELLED", "OPEN")
        assert not can_transition("TIMEOUT", "PARTIAL")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])