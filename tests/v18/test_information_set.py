from app.v18.information_set import MarketObservation, asof_join, assemble_information_set


def test_asof_join_never_uses_future_observation():
    observations = [
        MarketObservation(100, "funding", {"rate": 1.0}),
        MarketObservation(300, "funding", {"rate": 3.0}),
    ]
    result = asof_join([200], observations, max_age_ns=500)
    assert result[0]["rate"] == 1.0
    assert result[0]["age_ns"] == 100


def test_asof_join_marks_stale_data_missing():
    observations = [MarketObservation(100, "spot", {"return": 0.1})]
    result = asof_join([1000], observations, max_age_ns=100)
    assert result == [{"timestamp_ns": 1000, "age_ns": None, "source": None}]


def test_assemble_preserves_source_age():
    result = assemble_information_set(
        200,
        200,
        [MarketObservation(150, "funding", {"funding_rate": 0.001})],
    )
    assert result["funding_rate"] == 0.001
    assert result["funding__age_ns"] == 50
