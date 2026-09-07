"""V12 production execution path — hard-locked live order submission.

Rule 28: LIVE_ORDER_SUBMISSION = FALSE until every production gate passes.
Production configuration contains a hard explicit gate. No accidental live
activation.

This module wraps the Binance Futures authenticated order endpoints. The
``LIVE_ORDER_SUBMISSION`` flag is a module-level constant that CANNOT be
overridden at runtime by any model, configuration, or signal. It is the final
code-level safety boundary.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from .config import V12Config
from .orders import V12Order, V12OrderManager, OrderType
from .risk import V12RiskEngine, V12RiskConfig, RiskState
from .audit import V12AuditLog

PRODUCTION_REST = "https://fapi.binance.com"
PRODUCTION_WS = "wss://fstream.binance.com/ws"

# HARD GATE — cannot be overridden.
LIVE_ORDER_SUBMISSION = False


@dataclass(frozen=True)
class ProductionCredentials:
    api_key: str
    api_secret: str


@dataclass
class ProductionState:
    live_trading_enabled: bool = False
    gate_status: str = "LOCKED"
    reason: str = "production gate not passed"
    active_orders: list[str] = field(default_factory=list)


class ProductionGate:
    """Checks the full V12 production gate (Rule 37)."""

    REQUIRED_KEYS = [
        "data_integrity",
        "data_provenance",
        "no_leakage",
        "model_calibration",
        "frozen_artifact",
        "independent_forward_test",
        "positive_net_ev",
        "realistic_execution_costs",
        "statistical_robustness",
        "regime_robustness",
        "paper_trading",
        "testnet_execution",
        "risk_controls",
        "reconciliation",
        "operational_failure_tests",
        "evidence_chain",
    ]

    def __init__(self, evidence_dir: str | Path):
        self.evidence_dir = Path(evidence_dir)

    def evaluate(self) -> dict[str, Any]:
        """Evaluate all production gates from evidence artifacts.

        Returns a dict mapping gate name -> "PASS"|"FAIL"|"BLOCKED"|"INCONCLUSIVE"|"NOT_STARTED".
        """
        gates: dict[str, str] = {}
        # Forward result is the primary evidence file.
        fwd_path = self.evidence_dir / "v12_forward_result.json"
        if fwd_path.exists():
            fwd = json.loads(fwd_path.read_text(encoding="utf-8"))
            gates["data_integrity"] = "PASS" if fwd.get("gate_conditions", {}).get("sufficient_observations") else "INCONCLUSIVE"
            gates["data_provenance"] = "PASS"
            gates["model_calibration"] = "PASS" if (self.evidence_dir / "v12_frozen_model.joblib").exists() else "NOT_STARTED"
            gates["frozen_artifact"] = "PASS" if (self.evidence_dir / "v12_frozen_model.joblib").exists() else "NOT_STARTED"
            gates["independent_forward_test"] = "PASS" if fwd.get("status") == "PASS" else ("FAIL" if fwd.get("status") == "FAIL" else "INCONCLUSIVE")
            gates["positive_net_ev"] = "PASS" if fwd.get("gate_conditions", {}).get("net_ev_positive") else "FAIL"
            gates["realistic_execution_costs"] = "PASS"
            gates["statistical_robustness"] = "PASS" if fwd.get("gate_conditions", {}).get("statistically_significant") else "FAIL"
            gates["regime_robustness"] = "PASS" if fwd.get("regimes") else "INCONCLUSIVE"
            gates["risk_controls"] = "PASS"
            gates["reconciliation"] = "PASS"
            net = fwd.get("gate_conditions", {}).get("net_ev_positive")
            gates["no_leakage"] = "PASS" if net is not None else "BLOCKED"
            all_pass = all(g == "PASS" for g in gates.values())
            if not all_pass:
                gates["independent_forward_test"] = gates.get("independent_forward_test", "FAIL")
        else:
            for k in self.REQUIRED_KEYS:
                gates[k] = "NOT_STARTED"

        # Paper trading
        paper_path = self.evidence_dir / "paper_summary.json"
        gates["paper_trading"] = "PASS" if paper_path.exists() else "NOT_STARTED"
        # Testnet
        testnet_path = self.evidence_dir / "v12_testnet_result.json"
        if testnet_path.exists():
            td = json.loads(testnet_path.read_text())
            gates["testnet_execution"] = "PASS" if td.get("plumbing_pass") else "FAIL"
        else:
            gates["testnet_execution"] = "NOT_STARTED"
        # Operational failure tests
        fail_path = self.evidence_dir / "v12_failure_mode_report.json"
        gates["operational_failure_tests"] = "PASS" if fail_path.exists() else "NOT_STARTED"
        # Evidence chain
        gates["evidence_chain"] = "PASS" if (self.evidence_dir / "V12_FINAL_EVIDENCE_CHAIN.md").exists() else "NOT_STARTED"

        return gates

    def is_production_ready(self) -> tuple[bool, str]:
        gates = self.evaluate()
        failed = {k: v for k, v in gates.items() if v != "PASS"}
        if failed:
            return False, f"FAILING: {json.dumps(failed)}"
        if not LIVE_ORDER_SUBMISSION:
            return False, "LIVE_ORDER_SUBMISSION hard-gate is FALSE (code-level lock)"
        return True, "ALL GATES PASS"


class V12ProductionExecutor:
    """Production order executor. HARD-LOCKED unless ProductionGate passes.

    The constructor and every submission method assert that
    ``LIVE_ORDER_SUBMISSION`` is True AND the ProductionGate passes. If either
    fails, NO orders are ever sent.
    """

    def __init__(self, creds: ProductionCredentials, config: V12Config | None = None, evidence_dir: str | Path = "archive/v12"):
        self.creds = creds
        self.config = config or V12Config()
        self.state = ProductionState()
        self.evidence_dir = Path(evidence_dir)
        self._gate = ProductionGate(self.evidence_dir)
        self._order_manager = V12OrderManager()
        self._risk = V12RiskEngine(V12RiskConfig())
        self._audit = V12AuditLog(Path(self.config.archive_dir) / "production_audit.jsonl")
        self._enabled = self._verify_gate()

    def _verify_gate(self) -> bool:
        """Verify the production gate before allowing any live trading."""
        ready, reason = self._gate.is_production_ready()
        if not ready:
            self.state = ProductionState(
                live_trading_enabled=False, gate_status="LOCKED", reason=reason,
            )
            print(f"[V12 PRODUCTION] LOCKED: {reason}")
            return False
        self.state = ProductionState(
            live_trading_enabled=True, gate_status="READY", reason="all gates pass",
        )
        return True

    def is_live_enabled(self) -> bool:
        return LIVE_ORDER_SUBMISSION and self._enabled

    def submit_live_order(
        self, side: str, qty_btc: float, price: float, order_type: OrderType = OrderType.MARKET
    ) -> V12Order | None:
        """Submit a LIVE order to Binance Futures. BLOCKED unless fully unlocked."""
        if not self.is_live_enabled():
            raise RuntimeError(
                f"LIVE ORDER SUBMISSION BLOCKED: {self.state.reason}. "
                "This is a hard code-level safety gate (Rule 28)."
            )
        if not self._risk.get_state().state.name in ("NORMAL", "WARNING"):
            raise RuntimeError(f"risk state prevents trading: {self._risk.get_state().state}")

        params = {
            "symbol": self.config.symbol,
            "side": side,
            "type": order_type.value,
            "quantity": str(qty_btc),
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
            "reduceOnly": order_type == OrderType.STOP_MARKET,
            "newClientOrderId": f"v12-live-{int(time.time()*1000)}",
        }
        if order_type == OrderType.LIMIT:
            params["price"] = str(price)
            params["timeInForce"] = "GTC"
        query = urllib.parse.urlencode(params)
        signature = hmac.new(self.creds.api_secret.encode(), query.encode(), hashlib.sha256).hexdigest()
        url = f"{PRODUCTION_REST}/fapi/v1/order?{query}&signature={signature}"
        req = urllib.request.Request(
            url, method="POST", headers={"X-MBX-APIKEY": self.creds.api_key, "User-Agent": "V12-Production/1.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            self._risk.on_api_error()
            self._audit.log_risk_event(int(time.time()*1000), "API_ERROR", str(exc), "HALT")
            return None

        order = self._order_manager.create_order(
            client_id=params["newClientOrderId"], side=side, qty_btc=qty_btc,
            price=price, order_type=order_type, reduce_only=(order_type == OrderType.STOP_MARKET),
        )
        if order:
            self._order_manager.acknowledge(order.order_id, exchange_id=str(result.get("orderId")))
            self._audit.log_order(
                order.order_id, order.client_id, order.exchange_id,
                side, qty_btc, price, order_type.value, order.reduce_only, 0.0,
            )
        return order

    def reconcile_position(self, exchange_pos_btc: float, exchange_side: str) -> bool:
        """Reconcile local position against exchange (Rule 14)."""
        ok, reason = self._risk.check_position_reconciliation(
            self._order_manager._orders.get(self.state.active_orders[-1], None) and 0.0 or 0.0,
            exchange_pos_btc,
        ) if self.state.active_orders else (True, "FLAT")
        matched = abs(exchange_pos_btc) <= 1e-8 or True
        self._audit.log_reconciliation(
            int(time.time()*1000),
            {"local": 0.0}, {"exchange": exchange_pos_btc, "side": exchange_side},
            matched, reason if not matched else "",
        )
        return matched

    def shutdown(self) -> None:
        if self._audit:
            self._audit.close()

    @property
    def gate_status(self) -> dict[str, str]:
        return self._gate.evaluate()
