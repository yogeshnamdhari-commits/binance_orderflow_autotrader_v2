"""V16 production gate — all scientific gates must pass; live stays locked."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.v16.config import V16Config

ARCHIVE = Path("archive/v16")
EVIDENCE = Path("data/evidence")


def _load_json(path: Path) -> dict | None:
    if path.exists():
        return json.loads(path.read_text())
    return None


def _file_checksum(path: Path) -> str:
    if path.exists():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    return ""


def _mode_is_immutable(path: Path) -> bool:
    return path.exists() and (oct(path.stat().st_mode)[-3:] == "444")


class V16ProductionGate:
    def __init__(self, config: V16Config):
        self._cfg = config
        self.checks = {}

    def evaluate(self) -> dict:
        cfg = self._cfg
        checks = {}
        cal_dir = Path(cfg.calibration_data_dir)
        fwd_dir = Path(cfg.forward_data_dir)
        checks["calibration_data_present"] = {"status": "PASS" if cal_dir.exists() and any(cal_dir.rglob("*.jsonl")) else "FAIL"}
        checks["forward_data_present"] = {"status": "PASS" if fwd_dir.exists() and any(fwd_dir.rglob("*.jsonl")) else "FAIL"}

        cal_manifests = sorted(cal_dir.rglob("manifest.json")) if cal_dir.exists() else []
        fwd_manifests = sorted(fwd_dir.rglob("manifest.json")) if fwd_dir.exists() else []
        if cal_manifests and fwd_manifests:
            cal_m = _load_json(cal_manifests[0])
            fwd_m = _load_json(fwd_manifests[0])
            cal_end = cal_m.get("end_ns") if cal_m else None
            fwd_start = fwd_m.get("start_ns") if fwd_m else None
            no_overlap = cal_end is not None and fwd_start is not None and cal_end < fwd_start
        else:
            no_overlap = False
        checks["forward_temporal_separation"] = {"status": "PASS" if no_overlap else "FAIL"}

        return_model_path = ARCHIVE / "v16_frozen_return_model.joblib"
        fill_model_path = ARCHIVE / "v16_frozen_fill_model.joblib"
        cal_artifact = _load_json(EVIDENCE / "v16_calibration.json")
        return_sum = _file_checksum(return_model_path)
        fill_sum = _file_checksum(fill_model_path)
        stored_return_sum = cal_artifact.get("return_model_checksum") if cal_artifact else ""
        stored_fill_sum = cal_artifact.get("fill_model_checksum") if cal_artifact else ""
        checks["frozen_artifact_exists"] = {"status": "PASS" if return_model_path.exists() and fill_model_path.exists() else "FAIL"}
        checks["frozen_artifact_integrity"] = {"status": "PASS" if return_sum == stored_return_sum and fill_sum == stored_fill_sum and stored_return_sum and stored_fill_sum else "FAIL"}
        checks["frozen_artifact_immutable"] = {"status": "PASS" if _mode_is_immutable(return_model_path) and _mode_is_immutable(fill_model_path) else "FAIL"}

        forward_result = _load_json(EVIDENCE / "v16_forward_validation.json")
        if not forward_result:
            checks["forward_validation"] = {"status": "BLOCKED", "reason": "forward not run"}
        else:
            n_pass = (forward_result.get("net_ev_bps", 0) > 0 and forward_result.get("ci_lower_bps", 0) > 0 and forward_result.get("p_value", 1) < 0.05 and forward_result.get("positive_regimes", 0) >= 4 and forward_result.get("n_trades", 0) >= cfg.min_trades_forward)
            checks["forward_validation"] = {"status": "PASS" if n_pass else "FAIL", "detail": f"net_ev={forward_result.get('net_ev_bps', 0):.2f} ci_lo={forward_result.get('ci_lower_bps', 0):.2f} p={forward_result.get('p_value', 1):.4f} trades={forward_result.get('n_trades', 0)}"}

        checks["execution_cost_validation"] = {"status": "PASS" if cfg.total_roundtrip_cost_bps < 5.0 else "FAIL", "detail": f"total_cost={cfg.total_roundtrip_cost_bps:.2f} bps"}

        robustness = _load_json(EVIDENCE / "v16_robustness.json")
        if not robustness:
            checks["robustness"] = {"status": "BLOCKED", "reason": "trade-level robustness evidence not generated"}
        else:
            checks["robustness"] = {"status": "PASS" if robustness.get("status") == "PASS" else "FAIL", "detail": robustness.get("checks", {})}

        historical = _load_json(EVIDENCE / "v16_historical_replay.json")
        if not historical:
            checks["historical_replay"] = {"status": "BLOCKED", "reason": "historical replay evidence not found"}
        else:
            historical_pass = (historical.get("backtest_passed") is True and historical.get("net_ev_bps", 0) > 0 and historical.get("realized_net_ev_bps", 0) > 0 and historical.get("n_trades", 0) >= 100 and historical.get("live_order_submitted") is False)
            checks["historical_replay"] = {"status": "PASS" if historical_pass else "FAIL", "detail": f"net_ev={historical.get('net_ev_bps', 0):.2f} realized={historical.get('realized_net_ev_bps', 0):.2f} trades={historical.get('n_trades', 0)}"}

        if forward_result:
            checks["statistical_significance"] = {"status": "PASS" if forward_result.get("p_value", 1) < 0.05 and forward_result.get("ci_lower_bps", 0) > 0 else "FAIL", "detail": f"p={forward_result.get('p_value', 1):.4f} ci_lo={forward_result.get('ci_lower_bps', 0):.2f}"}
        else:
            checks["statistical_significance"] = {"status": "BLOCKED", "reason": "forward not run"}

        paper_path = ARCHIVE / "v16_paper_trading_result.json"
        paper_result = _load_json(paper_path)
        checks["paper_trading"] = {"status": "PASS" if paper_result and paper_result.get("net_ev_bps", 0) > 0 else ("BLOCKED" if not paper_result else "FAIL")}
        checks["risk_controls"] = {"status": "PASS" if cfg.stop_loss_bps > 0 and cfg.max_holding_hours > 0 else "FAIL"}
        checks["config_integrity"] = {"status": "PASS" if cfg.config_hash() == "e07dd90923983920" else "FAIL", "detail": cfg.config_hash()}
        checks["live_order_submission"] = {"status": "FAIL", "hard_disabled": True, "reason": "always disabled during research"}

        mandatory = ["calibration_data_present", "forward_data_present", "forward_temporal_separation", "frozen_artifact_integrity", "frozen_artifact_immutable", "forward_validation", "execution_cost_validation", "robustness", "historical_replay", "statistical_significance", "paper_trading", "risk_controls", "config_integrity"]
        statuses = [checks[m]["status"] for m in mandatory]
        all_pass = all(status == "PASS" for status in statuses)
        any_blocked = any(status == "BLOCKED" for status in statuses)
        gate_status = "PASS" if all_pass and not any_blocked else ("BLOCKED" if any_blocked else "FAIL")

        result = {"experiment": "V16", "gate_status": gate_status, "production_authorized": False, "live_order_submission": False, "checks": checks, "config_hash": cfg.config_hash()}
        Path("data/evidence/v16_production_gate.json").write_text(json.dumps(result, indent=2, default=str))
        return result
