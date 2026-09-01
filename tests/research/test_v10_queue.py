from app.v10_queue import QueueEstimator


def test_initial_queue_is_visible_size_at_quote():
    q = QueueEstimator()
    assert q.initial_ahead("bid", displayed_size=3.5) == 3.5


def test_queue_depletes_on_executed_volume_and_never_below_zero():
    q = QueueEstimator()
    q.start("bid", 5.0)
    assert q.apply_execution("bid", 2.0) == 3.0
    assert q.apply_execution("bid", 10.0) == 0.0


def test_replenishment_is_not_assumed_to_be_queue_progress():
    q = QueueEstimator()
    q.start("ask", 2.0)
    q.apply_cancel("ask", 1.0)
    assert q.ahead("ask") == 1.0
    q.apply_replenishment("ask", 4.0)
    assert q.ahead("ask") == 1.0
