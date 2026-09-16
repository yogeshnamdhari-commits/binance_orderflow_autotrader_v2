from app.v10_fill_model import QueueState, consume_queue, passive_fill_fraction


def test_queue_consumption_never_makes_remaining_negative():
    state = consume_queue(QueueState(10.0), 15.0)
    assert state.remaining_ahead == 0.0


def test_passive_fill_requires_volume_to_clear_queue():
    state = QueueState(10.0)
    assert passive_fill_fraction(state, 2.0, 9.0) == 0.0
    assert passive_fill_fraction(state, 2.0, 11.0) == 0.5
    assert passive_fill_fraction(state, 2.0, 20.0) == 1.0
