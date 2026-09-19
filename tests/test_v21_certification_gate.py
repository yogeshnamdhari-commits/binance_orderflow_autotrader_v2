import json
from pathlib import Path

from scripts.v21_certification_gate import evaluate


def _write(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _learned(tmp_path: Path, live: bool = False) -> Path:
    return _write(tmp_path / "learned.json", {"config": {"live_order_submission": live}})


def _sweep(tmp_path: Path, folds: dict) -> Path:
    return _write(tmp_path / "sweep.json", {"folds": folds})


def _fold(net: float, improvement: float, fills: int) -> dict:
    return {
        "outer_test": {
            "net_pnl_usd": net,
            "baseline_net_pnl_usd": net - improvement,
            "improvement_vs_fixed_baseline_usd": improvement,
            "fills": fills,
            "final_inventory": 0.0,
        }
    }


def test_certification_requires_every_outer_fold_to_be_profitable(tmp_path):
    report = evaluate(
        _learned(tmp_path),
        _sweep(tmp_path, {"B": _fold(2.0, 1.0, 10), "C": _fold(-1.0, 2.0, 10)}),
    )
    assert report["status"] == "NOT_CERTIFIED"
    assert report["checks"]["every_outer_fold_profitable"] is False


def test_certification_requires_every_outer_fold_to_beat_baseline(tmp_path):
    report = evaluate(
        _learned(tmp_path),
        _sweep(tmp_path, {"B": _fold(2.0, 1.0, 10), "C": _fold(2.0, -1.0, 10)}),
    )
    assert report["status"] == "NOT_CERTIFIED"
    assert report["checks"]["every_outer_fold_beats_fixed_baseline"] is False


def test_certification_requires_minimum_fills_per_fold(tmp_path):
    report = evaluate(
        _learned(tmp_path),
        _sweep(tmp_path, {"B": _fold(2.0, 1.0, 10), "C": _fold(2.0, 1.0, 9)}),
    )
    assert report["status"] == "NOT_CERTIFIED"
    assert report["checks"]["every_outer_fold_has_minimum_fills"] is False


def test_certification_passes_only_when_all_outer_folds_clear_gates(tmp_path):
    report = evaluate(
        _learned(tmp_path),
        _sweep(tmp_path, {"B": _fold(2.0, 1.0, 10), "C": _fold(3.0, 1.5, 12)}),
    )
    assert report["status"] == "CERTIFIED"
    assert report["checks"]["minimum_outer_oos_folds"] is True
    assert report["checks"]["every_outer_fold_profitable"] is True
    assert report["checks"]["every_outer_fold_beats_fixed_baseline"] is True
    assert report["checks"]["every_outer_fold_has_minimum_fills"] is True


def test_certification_never_passes_when_live_submission_is_enabled(tmp_path):
    report = evaluate(
        _learned(tmp_path, live=True),
        _sweep(tmp_path, {"B": _fold(2.0, 1.0, 10), "C": _fold(3.0, 1.5, 12)}),
    )
    assert report["status"] == "NOT_CERTIFIED"
    assert report["checks"]["live_submission_disabled"] is False
