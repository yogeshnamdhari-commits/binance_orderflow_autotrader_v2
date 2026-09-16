"""V12 audit log — complete, reproducible record of every signal and order.

Rule 32: Every signal and order must be reproducible.

Logs:
- timestamp
- market state
- features
- model version
- model output
- expected gross return
- estimated costs
- expected net return
- decision
- risk state
- order state
- fill state
- realized P&L

Audit records are append-only JSON-lines and immutable per session.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class V12AuditLog:
    """Append-only audit journal for full reproducibility."""

    def __init__(self, path: str | Path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = open(self._path, "a", encoding="utf-8")
        self._records: list[dict[str, Any]] = []

    @staticmethod
    def _now_ms() -> int:
        return int(datetime.now(timezone.utc).timestamp() * 1000)

    def log_signal(
        self,
        ts_ms: int,
        market_state: dict[str, Any],
        features: dict[str, float],
        model_version: str,
        model_output: dict[str, Any],
        expected_gross_bps: float,
        estimated_costs_bps: float,
        expected_net_bps: float,
    ) -> None:
        rec = {
            "type": "SIGNAL",
            "ts_ms": ts_ms,
            "log_ts_ms": self._now_ms(),
            "market_state": market_state,
            "features": features,
            "model_version": model_version,
            "model_output": model_output,
            "expected_gross_bps": expected_gross_bps,
            "estimated_costs_bps": estimated_costs_bps,
            "expected_net_bps": expected_net_bps,
        }
        self._write(rec)

    def log_decision(
        self,
        ts_ms: int,
        signal_id: str,
        decision: str,
        reason: str,
        risk_state: dict[str, Any],
        expected_net_bps: float,
        funding_rate_8h: float,
    ) -> None:
        rec = {
            "type": "DECISION",
            "ts_ms": ts_ms,
            "log_ts_ms": self._now_ms(),
            "signal_id": signal_id,
            "decision": decision,
            "reason": reason,
            "risk_state": risk_state,
            "expected_net_bps": expected_net_bps,
            "funding_rate_8h": funding_rate_8h,
        }
        self._write(rec)

    def log_order(
        self,
        order_id: str,
        client_id: str,
        exchange_id: str | None,
        side: str,
        qty_btc: float,
        price: float,
        order_type: str,
        reduce_only: bool,
        expected_edge_bps: float,
    ) -> None:
        rec = {
            "type": "ORDER",
            "log_ts_ms": self._now_ms(),
            "order_id": order_id,
            "client_id": client_id,
            "exchange_id": exchange_id,
            "side": side,
            "qty_btc": qty_btc,
            "price": price,
            "order_type": order_type,
            "reduce_only": reduce_only,
            "expected_edge_bps": expected_edge_bps,
        }
        self._write(rec)

    def log_fill(
        self,
        ts_ms: int,
        order_id: str,
        fill_price: float,
        fill_qty: float,
        fees_bps: float,
        slippage_bps: float,
        latency_ms: int,
        funding_rate_8h: float,
        funding_income_bps: float,
    ) -> None:
        rec = {
            "type": "FILL",
            "ts_ms": ts_ms,
            "log_ts_ms": self._now_ms(),
            "order_id": order_id,
            "fill_price": fill_price,
            "fill_qty": fill_qty,
            "fees_bps": fees_bps,
            "slippage_bps": slippage_bps,
            "latency_ms": latency_ms,
            "funding_rate_8h": funding_rate_8h,
            "funding_income_bps": funding_income_bps,
        }
        self._write(rec)

    def log_exit(
        self,
        ts_ms: int,
        order_id: str,
        exit_price: float,
        exit_qty: float,
        exit_reason: str,
        urgency: str,
        realized_pnl_bps: float,
        funding_accrued_bps: float,
    ) -> None:
        rec = {
            "type": "EXIT",
            "ts_ms": ts_ms,
            "log_ts_ms": self._now_ms(),
            "order_id": order_id,
            "exit_price": exit_price,
            "exit_qty": exit_qty,
            "exit_reason": exit_reason,
            "urgency": urgency,
            "realized_pnl_bps": realized_pnl_bps,
            "funding_accrued_bps": funding_accrued_bps,
        }
        self._write(rec)

    def log_risk_event(self, ts_ms: int, event: str, details: str, state: str) -> None:
        rec = {
            "type": "RISK",
            "ts_ms": ts_ms,
            "log_ts_ms": self._now_ms(),
            "event": event,
            "details": details,
            "state": state,
        }
        self._write(rec)

    def log_reconciliation(self, ts_ms: int, local: dict, exchange: dict, matched: bool, discrepancy: str) -> None:
        rec = {
            "type": "RECONCILE",
            "ts_ms": ts_ms,
            "log_ts_ms": self._now_ms(),
            "local": local,
            "exchange": exchange,
            "matched": matched,
            "discrepancy": discrepancy,
        }
        self._write(rec)

    def _write(self, rec: dict[str, Any]) -> None:
        rec_hash = hashlib.sha256(json.dumps(rec, sort_keys=True, default=str).encode()).hexdigest()[:16]
        rec["record_hash"] = rec_hash
        line = json.dumps(rec, sort_keys=True, default=str)
        self._fh.write(line + "\n")
        self._fh.flush()
        self._records.append(rec)

    def close(self) -> None:
        if self._fh and not self._fh.closed:
            self._fh.close()

    def records(self) -> list[dict[str, Any]]:
        return list(self._records)

    def verify_integrity(self) -> dict[str, Any]:
        """Verify audit log integrity (recompute hashes)."""
        recomputed = 0
        mismatches = 0
        for rec in self._records:
            stored = rec.get("record_hash")
            check = {k: v for k, v in rec.items() if k != "record_hash"}
            recomputed_hash = hashlib.sha256(
                json.dumps(check, sort_keys=True, default=str).encode()
            ).hexdigest()[:16]
            if recomputed_hash != stored:
                mismatches += 1
            recomputed += 1
        return {
            "total_records": recomputed,
            "hash_mismatches": mismatches,
            "integrity_pass": mismatches == 0,
        }

    @staticmethod
    def from_file(path: str | Path) -> "V12AuditLog":
        log = V12AuditLog(path)
        log._records = []
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                rec = json.loads(line)
                log._records.append(rec)
        log._fh.close()
        log._fh = open(log._path, "a", encoding="utf-8")
        return log
