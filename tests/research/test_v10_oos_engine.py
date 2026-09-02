import pytest

from app.v10_oos_engine import OrderSample, evaluate_oos_folds, sample_realized_ev_bps


def test_unfilled_order_has_zero_realized_submission_ev():
    sample = OrderSample(
        timestamp=1.0,
        side="BUY",
        quote_price=99.95,
        mid_at_submit=100.0,
        horizon_ms=1000.0,
        filled=False,
        fill_time_ms=1000.0,
        mid_at_horizon=99.0,
        maker_fee_bps=1.0,
    )
    assert sample_realized_ev_bps(sample) == 0.0


def test_filled_buy_realized_ev_accounts_for_spread_and_price_move():
    sample = OrderSample(
        timestamp=1.0,
        side="BUY",
        quote_price=99.95,
        mid_at_submit=100.0,
        horizon_ms=1000.0,
        filled=True,
        fill_time_ms=100.0,
        mid_at_horizon=100.01,
        maker_fee_bps=1.0,
    )
    assert sample_realized_ev_bps(sample) == pytest.approx(5.0)


def test_oos_engine_keeps_test_period_out_of_training_estimates():
    samples = []
    for i in range(8):
        samples.append(
            OrderSample(
                timestamp=float(i),
                side="BUY",
                quote_price=99.95,
                mid_at_submit=100.0,
                horizon_ms=1000.0,
                filled=i < 2,
                fill_time_ms=100.0 if i < 2 else 1000.0,
                mid_at_horizon=100.0,
                maker_fee_bps=1.0,
            )
        )
    result = evaluate_oos_folds(samples, train_size=4, test_size=2, step=2)
    assert len(result.folds) == 2
    assert result.folds[0].train_count == 4
    assert result.folds[0].test_count == 2
    assert result.folds[0].train_fill_probability == pytest.approx(0.5)
