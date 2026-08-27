import json

from app.orderbook import LocalOrderBook
from app.features import OrderFlowEngine
from app.events import EventDetector
from app.signal import SignalEngine
from app.journal import Journal
from app.replay import EventReplay
from app.hist.quality import normalize_aggTrades


def test_replay_aggtrades_counts_and_cvd(tmp_path):
    csv = tmp_path / "a.csv"
    csv.write_text(
        "agg_trade_id,price,quantity,first_trade_id,last_trade_id,transact_time,is_buyer_maker\n"
        "1,100.0,1.0,1,1,1782864000000,false\n"   # buyer_is_maker=false -> BUY (+1)
        "2,100.0,2.0,2,2,1782864001000,true\n"    # maker=true -> SELL (-2)
        "3,100.1,3.0,3,3,1782864002000,false\n"   # BUY (+3)
        "4,100.2,4.0,4,4,1782864003000,true\n"    # SELL (-4)
    )
    p, _ = normalize_aggTrades(csv, str(tmp_path / "norm"), "BTCUSDT", "2026-07-01")
    book = LocalOrderBook(10)
    flow = OrderFlowEngine(book)
    j = Journal(str(tmp_path / "journal.jsonl"))
    replay = EventReplay(book, flow, EventDetector(), SignalEngine(), j)
    stats = replay.run_aggTrades_parquet(p, "test")
    assert stats["trades"] == 4
    assert stats["buys"] == 2 and stats["sells"] == 2
    assert stats["cvd_end"] == (1 - 2 + 3 - 4)  # -2
    rows = j.path.read_text().splitlines()
    assert any(json.loads(r)["type"] == "trade_flow_day" for r in rows)
    assert not replay.book.state.synchronized  # L2 not synthesized -> no book features