from app.production_gate import Evidence, authorize_live


def evidence_all(value=True):
    return Evidence(*(value for _ in range(8)))


def test_any_failed_evidence_blocks_live():
    e = evidence_all()
    e = Evidence(True, True, True, True, True, False, True, True)
    ok, failed = authorize_live(e, explicit_authorization=True)
    assert not ok
    assert "statistical_significance" in failed


def test_explicit_authorization_is_required():
    ok, failed = authorize_live(evidence_all(), explicit_authorization=False)
    assert not ok
    assert "explicit_authorization" in failed


def test_all_gates_plus_authorization_passes():
    ok, failed = authorize_live(evidence_all(), explicit_authorization=True)
    assert ok
    assert failed == []
