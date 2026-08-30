import pandas as pd
import pytest
from app.v9_universe import select_v9_universe


def test_selects_top_ten_by_pre_asof_liquidity_and_excludes_btc():
    df = pd.DataFrame({"symbol": ["BTCUSDT"] + [f"ALT{i}USDT" for i in range(12)], "timestamp": pd.Timestamp("2026-01-01", tz="UTC"), "volume_usd": [10_000_000] + list(range(12, 0, -1))})
    selected = select_v9_universe(df, pd.Timestamp("2026-01-02", tz="UTC"), n=10)
    assert len(selected) == 10
    assert "BTCUSDT" not in selected
    assert selected == [f"ALT{i}USDT" for i in range(10)]


def test_rejects_future_liquidity():
    df = pd.DataFrame({"symbol": [f"ALT{i}USDT" for i in range(10)], "timestamp": pd.Timestamp("2026-01-03", tz="UTC"), "volume_usd": 100})
    with pytest.raises(ValueError, match="before asof"):
        select_v9_universe(df, pd.Timestamp("2026-01-02", tz="UTC"), n=10)
