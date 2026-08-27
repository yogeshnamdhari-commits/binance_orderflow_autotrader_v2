from datetime import date, timedelta
import pandas as pd

from app.hist import sources
from app.hist.quality import audit_aggTrades, normalize_aggTrades
from app.hist.report import coverage_gaps


def test_archive_url_and_checksum_layout():
    u = sources.archive_url("btcusdt", "aggTrades", "2026-07-01")
    assert u == ("https://data.binance.vision/data/futures/um/daily/"
                 "aggTrades/BTCUSDT/BTCUSDT-aggTrades-2026-07-01.zip")
    assert sources.checksum_url("btcusdt", "aggTrades", "2026-07-01") == u + ".CHECKSUM"


def test_parse_checksum():
    hexv, name = sources.parse_checksum("abc123  BTCUSDT-aggTrades-2026-07-01.zip")
    assert hexv == "abc123" and name.endswith(".zip")


def test_audit_aggtrades_detects_gap_and_duplicate(tmp_path):
    csv = tmp_path / "agg.csv"
    csv.write_text(
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
        "10,100.0,1.0,100,100,1782864000000,true\n"
        "11,100.1,1.0,101,101,1782864001000,false\n"
        "13,100.2,1.0,102,102,1782864002000,false\n"  # id 12 skipped -> gap
        "13,100.3,1.0,103,103,1782864002500,false\n"  # duplicate id 13
        "14,100.4,1.0,104,104,1782864003000,true\n"
    )
    q = audit_aggTrades(csv)
    assert q["rows"] == 5
    assert q["id_gaps"] == 1 and q["id_gap_rows"] == 1
    assert q["duplicate_or_desc_ids"] == 1


def test_normalize_produces_parquet(tmp_path):
    csv = tmp_path / "a.csv"
    csv.write_text(
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
        "2,100.5,0.5,20,20,1782864001000,false\n"
        "1,100.0,1.5,10,10,1782864000000,true\n"
    )
    out, n = normalize_aggTrades(csv, str(tmp_path / "norm"), "BTCUSDT", "2026-07-01")
    df = pd.read_parquet(out)
    assert n == 2 and list(df["agg_trade_id"]) == [1, 2]
    assert df.dtypes["is_buyer_maker"] == bool


def test_coverage_gaps_reports_interior_missing():
    payload = {"start": "2026-01-01", "end": "2026-01-10"}
    present = {("2026-01-%02d" % d) for d in range(1, 11)}
    present.discard("2026-01-05")
    gaps = coverage_gaps(present, payload)
    assert gaps == ["2026-01-05"]