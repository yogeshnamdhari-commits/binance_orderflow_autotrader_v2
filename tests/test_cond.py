import numpy as np
import pandas as pd
import pytest

from app.hist.cond import (_forward_ptr, _sliding_max_min, build_day,
                           condition_mask, condition_trades, decile_expectancy,
                           event_stats, exhaustion_expectancy, exhaustion_mask,
                           thin_indices, excursion_bps)


def _write_aggr(tmp_path):
    rng = np.random.default_rng(7)
    n = 40_000
    t = np.cumsum(rng.integers(5, 120, n)).astype(np.int64)
    p = 100.0 + rng.normal(0, 0.05, n).cumsum()
    q = rng.uniform(0.001, 2.0, n)
    maker = rng.random(n) < 0.5
    df = pd.DataFrame({"transact_time": t, "price": p,
                       "quantity": q, "is_buyer_maker": maker})
    path = tmp_path / "day.parquet"
    df.to_parquet(path)
    return path


def test_forward_ptr():
    t = np.array([0, 10, 11, 20, 25, 26, 40, 500])
    fp = _forward_ptr(t, 15)
    assert fp.tolist() == [3, 4, 5, 6, 6, 7, 7, -1]
    fp5 = _forward_ptr(t, 5)
    assert fp5.tolist() == [1, 3, 3, 4, 6, 6, 7, -1]


def test_sliding_max_min_matches_brute():
    rng = np.random.default_rng(3)
    for _ in range(5):
        p = rng.random(200)
        start = sorted(rng.integers(0, 100, 200))
        right = np.array(start) + rng.integers(0, 101, 200)
        right = np.minimum(np.maximum.accumulate(right), len(p))
        mx, mn = _sliding_max_min(p, right)
        for i in range(200):
            seg = p[i:right[i]]
            if len(seg):
                assert mx[i] == pytest.approx(seg.max())
                assert mn[i] == pytest.approx(seg.min())
            else:
                assert mx[i] == p[i]
                assert mn[i] == p[i]


def test_build_day_shapes(tmp_path):
    bd = build_day(_write_aggr(tmp_path))
    n = len(bd["t"])
    for k in ("delta_1s", "delta_5s", "buyshare_5s", "intensity_5s", "accel", "mfe15", "mae15"):
        arr = bd[k]
        assert arr.shape == (n,)
        assert np.isfinite(arr).mean() > 0.5
    for h in (5_000, 15_000, 60_000):
        assert bd["r"][h].shape == (n,)
        assert np.isfinite(bd["r"][h]).mean() > 0.5


def test_decile_predictive(tmp_path):
    bd = build_day(_write_aggr(tmp_path))
    rows = decile_expectancy(bd, "buyshare_5s")
    assert len(rows) > 0
    dec = {r["decile"]: r["net_mean_bps"] for r in rows}
    assert dec[10] > dec[1]


def test_thin_indices_non_overlapping():
    t = np.arange(0, 1000, 1, dtype=np.int64)
    mask = np.ones(1000, dtype=bool)
    picked = thin_indices(t, mask, 15)
    gaps = np.diff(t[picked])
    assert np.all(gaps >= 15)
    assert len(picked) == 67  # first at 0, then >=15 apart


def test_condition_mask_matches_decile_expectancy(tmp_path):
    bd = build_day(_write_aggr(tmp_path))
    mask = condition_mask(bd, "buyshare_5s", 10)
    assert mask is not None
    rows = decile_expectancy(bd, "buyshare_5s")
    dec10 = next(r for r in rows if r["decile"] == 10)
    assert int(np.sum(mask & np.isfinite(bd["r"][15_000]))) == dec10["n"]


def test_condition_trades_thinned(tmp_path):
    bd = build_day(_write_aggr(tmp_path))
    rs, idx, mask = condition_trades(bd, "buyshare_5s", 10, 15_000, 1)
    assert mask is not None
    assert len(rs) > 0
    assert np.array_equal(idx, thin_indices(bd["t"], mask & np.isfinite(bd["r"][15_000]), 15_000))
    assert np.all(np.diff(bd["t"][idx]) >= 15_000)
    fav, adv = excursion_bps(bd, idx, 15_000, 1)
    assert len(fav) == len(idx)
    assert np.all(fav >= 0) and np.all(adv >= 0)


def test_event_stats():
    s = event_stats([10.0, -5.0, 3.0])
    assert s["n"] == 3
    assert s["hit_rate"] == pytest.approx(66.7, abs=0.1)
    assert s["profit_factor"] == pytest.approx(13.0 / 5.0)
    assert event_stats([]) is None


def test_exhaustion_mask_shapes(tmp_path):
    # deterministic day: strong one-sided buying then a decelerating second
    t = []
    for s in range(0, 12):                # 12 seconds
        t.extend([s * 1000 + i * 20 for i in range(50)])
    t = np.array(t, dtype=np.int64)
    n = len(t)
    p = np.full(n, 100.0)
    q = np.full(n, 0.1)
    maker = np.zeros(n, dtype=bool)        # all trades are buyer aggressor until last 2s
    maker[t // 1000 >= 10] = True          # last 2s: seller aggressor (balanced flow)
    df = pd.DataFrame({"transact_time": t, "price": p,
                       "quantity": q, "is_buyer_maker": maker})
    path = tmp_path / "exh_day.parquet"
    df.to_parquet(path, index=False)
    bd = build_day(path)
    buy, sell = exhaustion_mask(bd)
    assert buy.shape == sell.shape == (len(bd["t"]),)
    assert buy.dtype == bool and sell.dtype == bool
    assert int(np.sum(buy)) > 0


def test_exhaustion_returns_schema(tmp_path):
    bd = build_day(_write_aggr(tmp_path))
    eb, es = exhaustion_expectancy(bd)
    for row in (eb, es):
        assert row is None or {"condition", "n", "net_mean_bps", "hit_rate"} <= set(row)