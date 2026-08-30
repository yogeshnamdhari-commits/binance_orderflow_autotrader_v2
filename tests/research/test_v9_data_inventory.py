from pathlib import Path
from research.v9_data_inventory import inspect_file


def test_inventory_rejects_missing_timestamp_and_price(tmp_path: Path):
    p = tmp_path / "bad.csv"
    p.write_text("symbol,close\nETHUSDT,100\n", encoding="utf-8")
    result = inspect_file(p)
    assert result["valid"] is False
    assert "timestamp" in result["missing_required"]


def test_inventory_accepts_minimal_ohlcv(tmp_path: Path):
    p = tmp_path / "good.csv"
    p.write_text("timestamp,symbol,open,high,low,close,volume\n2026-01-01T00:00:00Z,ETHUSDT,1,2,0.5,1.5,10\n", encoding="utf-8")
    result = inspect_file(p)
    assert result["valid"] is True
    assert result["rows"] == 1
