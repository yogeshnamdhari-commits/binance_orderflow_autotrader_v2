"""Fail-closed production readiness checks for the frozen V16 system."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any
ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "FINAL_STATUS.json"
PAPER = ROOT / "data/evidence/v16_paper_trading.json"
PAPER_RESULT = ROOT / "archive/v16/v16_paper_trading_result.json"
REQUIRED = (ROOT / "archive/v16/v16_frozen_return_model.joblib", ROOT / "archive/v16/v16_frozen_fill_model.joblib", PAPER, PAPER_RESULT)

def _load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))

def run_preflight() -> dict[str, Any]:
    result: dict[str, Any] = {"system":"binance_orderflow_autotrader_v2","model_version":"V16","live_order_submission":False,"production_authorized":False,"checks":{},"status":"FAIL"}
    result["checks"]["required_artifacts"] = all(p.is_file() and p.stat().st_size > 0 for p in REQUIRED)
    if not result["checks"]["required_artifacts"]:
        return result
    paper, status, realized = _load(PAPER), _load(STATUS), _load(PAPER_RESULT)
    result["checks"]["paper_complete"] = (paper.get("status") == "COMPLETE" and paper.get("paper_trading_passed") is True and int(paper.get("n_trades", 0)) > 0 and paper.get("live_order_submitted") is False)
    result["checks"]["realized_paper_evidence"] = (realized.get("status") == "COMPLETE" and realized.get("performance_basis") == "realized_closed_trade_pnl" and int(realized.get("realized_trade_count", 0)) > 0 and realized.get("live_order_submitted") is False and isinstance(realized.get("closed_positions"), list) and len(realized["closed_positions"]) == int(realized.get("realized_trade_count", 0)))
    result["checks"]["paper_status_consistent"] = (status.get("live_order_submission") is False and paper.get("live_order_submitted") is False and realized.get("live_order_submitted") is False)
    result["checks"]["paper_result_reconciles"] = (paper.get("n_trades") == realized.get("realized_trade_count") and abs(float(paper.get("net_ev_bps", 0.0)) - float(realized.get("net_ev_bps", 0.0))) < 1e-9)
    result["paper_net_ev_bps"], result["paper_trades"] = paper.get("net_ev_bps"), paper.get("n_trades")
    result["checks"]["live_safety_lock"] = (status.get("production_authorized") is False and status.get("live_order_submission") is False)
    if all(result["checks"].values()):
        result["status"] = "READY_LOCKED"
    return result

if __name__ == "__main__":
    outcome = run_preflight()
    print(json.dumps(outcome, indent=2, sort_keys=True))
    raise SystemExit(0 if outcome["status"] == "READY_LOCKED" else 1)
