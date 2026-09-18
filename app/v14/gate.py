"""V14 production gate — hard lock. All gates must pass or LIVE stays disabled."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.v14.config import V14Config

ARCHIVE = Path("archive/v14")
EVIDENCE = Path("data/evidence")


def _load_json(path: Path) -> dict | None:
    if path.exists():
        return json.loads(path.read_text())
    return None


def _file_checksum(path: Path) -> str:
    if path.exists():
        return hashlib.sha256(path.read_bytes()).hexdigest()
    return ""


class V14ProductionGate:
    def __init__(self, config: V14Config):
        self._cfg = config
        self.checks = {}

    def evaluate(self) -> dict:
        cfg = self._cfg
        checks = {}

        # 1. Data provenance
        cal_dir = Path(cfg.calibration_data_dir)
        fwd_dir = Path(cfg.forward_data_dir)
        checks["calibration_data_present"] = {"status": "PASS" if cal_dir.exists() and any(cal_dir.rglob("*.jsonl")) else "FAIL"}
        checks["forward_data_present"] = {"status": "PASS" if fwd_dir.exists() and any(fwd_dir.rglob("*.jsonl")) else "FAIL"}

        # 2. Temporal separation (no overlap)
        cal_manifests = sorted(Path(cfg.calibration_data_dir).rglob("manifest.json")) if cal_dir.exists() else []
        fwd_manifests = sorted(Path(cfg.forward_data_dir).rglob("manifest.json")) if fwd_dir.exists() else []
        if cal_manifests and fwd_manifests:
            cal_manifest = _load_json(cal_manifests[0])
            fwd_manifest = _load_json(fwd_manifests[0])
            cal_end = cal_manifest.get("end_ns")
            fwd_start = fwd_manifest.get("start_ns")
            no_overlap = cal_end is not None and fwd_start is not None and cal_end < fwd_start
        else:
            cal_manifest = None
            fwd_manifest = None
            no_overlap = False
        checks["forward_temporal_separation"] = {"status": "PASS" if no_overlap else "FAIL", "detail": f"cal_end={cal_manifest.get('end_ns') if cal_manifest else None} < fwd_start={fwd_manifest.get('start_ns') if fwd_manifest else None}"}

        # 3. Frozen artifact integrity
        model_path = ARCHIVE / "v14_frozen_model.joblib"
        frozen_artifact = _load_json(EVIDENCE / "v14_calibration.json")
        model_sum = _file_checksum(model_path) if model_path.exists() else ""
        stored_sum = frozen_artifact.get("model_checksum") if frozen_artifact else ""
        checks["frozen_artifact_exists"] = {"status": "PASS" if model_path.exists() else "FAIL"}
        checks["frozen_artifact_integrity"] = {"status": "PASS" if model_sum == stored_sum and stored_sum else "FAIL", "detail": f"model={model_sum[:16]}... stored={stored_sum}"}
        checks["frozen_artifact_immutable"] = {"status": "PASS" if model_path.exists() and (oct(model_path.stat().st_mode)[-3:] == "444") else "BLOCKED"}

        # 4. Forward validation
        forward_result = _load_json(EVIDENCE / "v14_forward_validation.json")
        if not forward_result:
            checks["forward_validation"] = {"status": "BLOCKED", "reason": "forward not run"}
        else:
            n_pass = (
                forward_result.get("net_ev_bps", 0) > 0
                and forward_result.get("ci_lower_bps", 0) > 0
                and forward_result.get("p_value", 1) < 0.05
                and forward_result.get("positive_regimes", 0) >= 4
            )
            checks["forward_validation"] = {
                "status": "PASS" if n_pass else "FAIL",
                "detail": f"net_ev={forward_result.get('net_ev_bps', 0):.2f} ci_lo={forward_result.get('ci_lower_bps', 0):.2f} p={forward_result.get('p_value', 1):.4f} regimes={forward_result.get('positive_regimes', 0)}/6",
            }

        # 5. Execution cost validation
        checks["execution_cost_validation"] = {
            "status": "PASS" if cfg.total_roundtrip_cost_bps < 5.0 else "FAIL",
            "detail": f"total_cost={cfg.total_roundtrip_cost_bps:.2f} bps (< 5.0 required)",
        }

        # 6. Robustness (not yet run for V14, mark BLOCKED)
        checks["robustness"] = {"status": "BLOCKED", "reason": "not implemented for V14"}

        # 7. Statistical significance
        if forward_result:
            checks["statistical_significance"] = {
                "status": "PASS" if forward_result.get("p_value", 1) < 0.05 and forward_result.get("ci_lower_bps", 0) > 0 else "FAIL",
                "detail": f"p={forward_result.get('p_value', 1):.4f} ci_lo={forward_result.get('ci_lower_bps', 0):.2f}",
            }
        else:
            checks["statistical_significance"] = {"status": "BLOCKED", "reason": "forward not run"}

        # 8. Paper trading (only after all above PASS)
        paper_path = Path("archive/v14/v14_paper_trading_result.json")
        paper_result = _load_json(paper_path)
        checks["paper_trading"] = {
            "status": "PASS" if paper_result and paper_result.get("net_ev_bps", 0) > 0 else ("BLOCKED" if not paper_result else "FAIL"),
        }

        # 9. Risk controls present
        checks["risk_controls"] = {"status": "PASS" if cfg.stop_loss_bps > 0 and cfg.max_holding_hours > 0 else "FAIL"}

        # 10. Config integrity
        checks["config_integrity"] = {"status": "PASS" if cfg.config_hash() == "12e0e1775ee6b46d" else "FAIL", "detail": cfg.config_hash()}

        # 11. LIVE_ORDER_SUBMISSION
        checks["live_order_submission"] = {"status": "FAIL", "hard_disabled": True, "reason": "always disabled during research/paper validation"}

        # Final determination
        mandatory = ["calibration_data_present", "forward_data_present", "forward_temporal_separation",
                     "frozen_artifact_integrity", "forward_validation", "execution_cost_validation",
                     "statistical_significance", "risk_controls", "config_integrity"]
        all_pass = all(checks[m]["status"] == "PASS" for m in mandatory if m in checks)
        any_blocked = any(checks[m]["status"] == "BLOCKED" for m in mandatory if m in checks)

        if all_pass and not any_blocked:
            live_eligible = False  # Paper trading must confirm first
            checks["live_order_submission"] = {"status": "BLOCKED", "hard_disabled": True, "reason": "paper trading gate pending"}
            gate_status = "PASS"
            production_authorized = False  # requires explicit authorization
        elif any_blocked:
            gate_status = "BLOCKED"
            production_authorized = False
        else:
            gate_status = "FAIL"
            production_authorized = False

        result = {
            "experiment": "V14",
            "gate_status": gate_status,
            "production_authorized": production_authorized,
            "live_order_submission": False,
            "checks": checks,
            "config_hash": cfg.config_hash(),
        }
        Path("data/evidence/v14_production_gate.json").write_text(json.dumps(result, indent=2, default=str))
        return result
