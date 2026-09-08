from pathlib import Path

from app.v16.production_preflight import ProductionPreflight, PreflightResult


def test_preflight_fails_closed_when_live_submission_is_not_explicitly_authorized(tmp_path: Path):
    result = ProductionPreflight(
        root=tmp_path,
        live_order_submission=False,
        production_authorized=False,
    ).evaluate()

    assert isinstance(result, PreflightResult)
    assert result.ready is False
    assert result.live_order_submission is False
    assert result.checks["explicit_authorization"] == "FAIL"


def test_preflight_requires_paper_trading_pass(tmp_path: Path):
    (tmp_path / "archive/v16").mkdir(parents=True)
    (tmp_path / "archive/v16/v16_paper_trading_result.json").write_text(
        '{"paper_trading_passed": false, "net_ev_bps": -0.1}'
    )

    result = ProductionPreflight(
        root=tmp_path,
        live_order_submission=False,
        production_authorized=True,
    ).evaluate()

    assert result.ready is False
    assert result.checks["paper_trading"] == "FAIL"


def test_preflight_never_reports_ready_with_live_submission_disabled(tmp_path: Path):
    (tmp_path / "archive/v16").mkdir(parents=True)
    (tmp_path / "archive/v16/v16_paper_trading_result.json").write_text(
        '{"paper_trading_passed": true, "net_ev_bps": 2.34, "n_trades": 397}'
    )

    result = ProductionPreflight(
        root=tmp_path,
        live_order_submission=False,
        production_authorized=True,
    ).evaluate()

    assert result.ready is False
    assert result.live_order_submission is False
    assert result.checks["live_order_submission"] == "FAIL"
