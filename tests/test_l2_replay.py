import json

from app.l2_replay import DepthEventReplay, Replay, replay_session
from app.l2_collector import EventReader
from app.orderbook import LocalOrderBook
from app.models import DepthEvent


def _depth_record(ts, ufirst, ulast, bids, asks):
    return {"kind": "depth", "E": ts, "U": ufirst, "u": ulast, "recv_ms": 1,
            "bids": bids, "asks": asks}


def _book_field_block(bids, asks, mid):
    b1 = bids[0][1] if bids else 0.0
    a1 = asks[0][1] if asks else 0.0
    b5 = sum(q for _, q in bids[:5])
    a5 = sum(q for _, q in asks[:5])
    b10 = sum(q for _, q in bids)
    a10 = sum(q for _, q in asks)

    def qi(bb, aa):
        den = bb + aa
        return round((bb - aa) / den, 6) if den else 0.0

    pb, qb = bids[0]
    pa, qa = asks[0]
    microb = (qb * pa + qa * pb) / (qb + qa)
    mpd = round((microb - mid) / mid * 1e4, 4)
    return {
        "microb_price": microb, "mpd_bps": mpd,
        "bid_l1_5": [[round(p, 2), round(q, 8)] for p, q in bids[:5]],
        "ask_l1_5": [[round(p, 2), round(q, 8)] for p, q in asks[:5]],
        "bid_l1_10": [[round(p, 2), round(q, 8)] for p, q in bids],
        "ask_l1_10": [[round(p, 2), round(q, 8)] for p, q in asks],
        "bid_depth1": round(b1, 8), "ask_depth1": round(a1, 8),
        "bid_depth5": round(b5, 8), "ask_depth5": round(a5, 8),
        "bid_depth10": round(b10, 8), "ask_depth10": round(a10, 8),
        "qi1": qi(b1, a1), "qi5": qi(b5, a5), "qi10": qi(b10, a10),
    }


MID = 100.25
BOOK_A = ([(100.0, 3.0), (99.5, 1.0)], [(100.5, 2.0), (101.0, 1.0)])  # after depth1
BOOK_B = ([(100.0, 2.0), (99.5, 1.0)], [(100.5, 3.0), (101.0, 1.0)])  # after depth2


def _baseline_derived_rows():
    return [
        {  # depth @ 000
            "ts_ms": 1782864000000, "recv_ms": 1, "kind": "depth",
            "seq": "11-11", "best_bid": 100.0, "best_ask": 100.5, "mid": MID,
            "spread_bps": round(0.5 / MID * 1e4, 4),
            ** _book_field_block(*BOOK_A, MID),
            "bid_delta": 1.0, "ask_delta": 0.0, "adds": 0.0, "cancels": 0.0,
            "ofi_net": 1.0, "ofi_l1": 1.0, "ofi_l5": 1.0, "ofi_l10": 1.0,
            "ofi_depth": round(1.0 / 7, 8),
            "buy_vol": 0.0, "sell_vol": 0.0, "tfi": 0.0,
        },
        {  # trade 1001 BUY 1.5 @100.5
            "ts_ms": 1782864000500, "recv_ms": 2, "kind": "trade", "seq": 1001,
            "best_bid": 100.0, "best_ask": 100.5, "mid": MID,
            "spread_bps": round(0.5 / MID * 1e4, 4),
            ** _book_field_block(*BOOK_A, MID),
            "buy_vol": 1.5, "sell_vol": 0.0, "tfi": 1.0,
        },
        {  # trade 1002 SELL 0.5 @100.0
            "ts_ms": 1782864001000, "recv_ms": 3, "kind": "trade", "seq": 1002,
            "best_bid": 100.0, "best_ask": 100.5, "mid": MID,
            "spread_bps": round(0.5 / MID * 1e4, 4),
            ** _book_field_block(*BOOK_A, MID),
            "buy_vol": 1.5, "sell_vol": 0.5, "tfi": 0.5,
        },
        {  # depth @ 2000 (trade1 aged out of the 1s window)
            "ts_ms": 1782864002000, "recv_ms": 4, "kind": "depth",
            "seq": "12-12", "best_bid": 100.0, "best_ask": 100.5, "mid": MID,
            "spread_bps": round(0.5 / MID * 1e4, 4),
            ** _book_field_block(*BOOK_B, MID),
            "bid_delta": -1.0, "ask_delta": 1.0, "adds": 0.0, "cancels": 0.0,
            "ofi_net": -2.0, "ofi_l1": -2.0, "ofi_l5": -2.0, "ofi_l10": -2.0,
            "ofi_depth": round(-2.0 / 7, 8),
            "buy_vol": 0.0, "sell_vol": 0.5, "tfi": -1.0,
        },
    ]


def _write_session(path, recs, expected=None):
    path.mkdir(parents=True)
    raw = [{"kind": "snapshot", "last_update_id": 10, "ts_ms": 1782864000000,
            "recv_ms": 0,
            "bids": [["100.0", "2"], ["99.5", "1"]],
            "asks": [["100.5", "2"], ["101.0", "1"]]}]
    raw += recs
    if expected is None:
        expected = _baseline_derived_rows()
    (path / "raw.jsonl").write_text("\n".join(json.dumps(r) for r in raw) + "\n")
    (path / "derived.jsonl").write_text(
        "\n".join(json.dumps(r) for r in expected) + "\n")


def test_replay_reconstructs_book_and_features_bitwise(tmp_path):
    recs = [
        _depth_record(1782864000000, 11, 11, [[100.0, 3.0]], []),
        {"kind": "trade", "T": 1782864000500, "a": 1001, "p": 100.5,
         "q": 1.5, "m": False, "recv_ms": 2},
        {"kind": "trade", "T": 1782864001000, "a": 1002, "p": 100.0,
         "q": 0.5, "m": True, "recv_ms": 3},
        _depth_record(1782864002000, 12, 12, [[100.0, 2.0]], [[100.5, 3.0]]),
        {"kind": "bookTicker", "E": 1782864002100, "recv_ms": 5,
         "b": 100.0, "B": 2.0, "a": 100.5, "A": 3.0},
    ]
    _write_session(tmp_path / "sess", recs)

    replay, mismatches = replay_session(tmp_path / "sess")
    assert mismatches == [], "mismatches: %s" % (mismatches,)
    assert replay.events == {"snapshot": 1, "depth": 2, "trade": 2, "bookTicker": 1}
    assert len(replay.rows) == 4

    expected = _baseline_derived_rows()
    for row, exp in zip(replay.rows, expected):
        assert row["mid"] == exp["mid"]
        assert row["qi5"] == exp["qi5"]
        assert row["qi1"] == exp["qi1"]
        assert row["qi10"] == exp["qi10"]
        assert row["mpd_bps"] == exp["mpd_bps"]
        assert row["bid_depth10"] == exp["bid_depth10"]
        assert row["ask_depth10"] == exp["ask_depth10"]
        assert row["tfi"] == exp["tfi"]
        assert row["bid_depth5"] == exp["bid_depth5"]
        assert row["ask_depth5"] == exp["ask_depth5"]
        if "ofi_net" in exp:
            assert row["ofi_net"] == exp["ofi_net"]
            assert row["ofi_l1"] == exp["ofi_l1"]
            assert row["ofi_l10"] == exp["ofi_l10"]
    assert replay.rows[0]["mpd_bps"] == round((100.3 - MID) / MID * 1e4, 4)
    assert replay.rows[3]["tfi"] == -1.0  # trade1 aged out of the 1s window


def test_stack_missing_after_snapshot_drops_rows(tmp_path):
    recs = [_depth_record(1782864000000, 11, 11, [[100.0, 3.0]], []),
            {"kind": "trade", "T": 1782864000500, "a": 1001, "p": 100.5,
             "q": 1.5, "m": False, "recv_ms": 2}]
    _write_session(tmp_path / "sess", recs, _baseline_derived_rows()[:2])
    replay, mismatches = replay_session(tmp_path / "sess")
    assert mismatches == []


def test_ofi_on_add_and_cancel_levels():
    reader = EventReader()
    reader.load_snapshot([["100", "2"], ["99.5", "1"]],
                         [["100.5", "2"], ["101", "1"]])
    book = LocalOrderBook(10)
    book.load_snapshot([["100", "2"], ["99.5", "1"]],
                       [["100.5", "2"], ["101", "1"]], 10)
    add = reader.ofi_event(DepthEvent(1, 11, 11, [], [(103.0, 1.5)]), book)
    assert add["adds"] == 1.5 and add["cancels"] == 0.0 and add["net"] == -1.5
    assert add["ofi_l1"] == 0.0 and add["ofi_l5"] == 0.0 and add["ofi_l10"] == 0.0  # 103 beyond top-10
    cancel = reader.ofi_event(DepthEvent(1, 12, 12, [(100.0, 0.0)], []), book)
    assert cancel["cancels"] == 2.0 and cancel["net"] == -2.0
    assert cancel["ofi_l1"] == -2.0


def test_replay_single_depth_event_shape(tmp_path):
    _write_session(tmp_path / "sess",
                   [_depth_record(1782864000000, 11, 11, [[100.0, 3.0]], [])],
                   [_baseline_derived_rows()[0]])
    replay, mismatches = replay_session(tmp_path / "sess")
    assert mismatches == []
    assert replay.rows[0]["best_bid"] == 100.0
    assert replay.rows[0]["seq"] == "11-11"