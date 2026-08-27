from app.hist.research import day_metrics
from app.hist.quality import normalize_aggTrades


def test_day_metrics_aggregates(tmp_path):
    csv = tmp_path / "a.csv"
    csv.write_text(
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
        "1,100.0,1.0,1,1,1782864000000,false\n"   # buy +1
        "2,100.0,2.0,2,2,1782864001000,true\n"    # sell -2
        "3,100.1,3.0,3,3,1782864002000,false\n"   # buy +3
        "4,100.2,1.0,4,4,1782864003000,false\n"   # buy +1
    )
    p, _ = normalize_aggTrades(csv, str(tmp_path / "norm"), "BTCUSDT", "2026-07-01")
    m = day_metrics(p)
    assert m["trades"] == 4
    assert m["buy_volume_btc"] == 5.0 and m["sell_volume_btc"] == 2.0
    assert m["delta_btc"] == 3.0
    assert abs(m["buy_volume_share"] - 5 / 7) < 1e-5
    assert m["cvd_sign"] == "buyer"
    assert m["trade_rate_per_sec"] > 0