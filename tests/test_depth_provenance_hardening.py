from __future__ import annotations

import pytest

from app.mm.book import L2Snapshot, L2Update, OrderBook
from app.v10_market_data import DepthSequenceValidator


def test_order_book_requires_snapshot_plus_one_bridge():
    book = OrderBook.from_snapshot(
        L2Snapshot(
            timestamp_ns=1,
            last_update_id=100,
            bids=[(99.0, 1.0)],
            asks=[(101.0, 1.0)],
        )
    )
    with pytest.raises(ValueError, match="initial depth bridge invalid"):
        book.apply_update(
            L2Update(2, 100, 100, None, [(99.0, 2.0)], [])
        )

    book.apply_update(
        L2Update(3, 101, 102, 100, [(99.0, 2.0)], [])
    )
    assert book.last_update_id == 102


def test_order_book_requires_pu_after_bridge():
    book = OrderBook.from_snapshot(
        L2Snapshot(
            timestamp_ns=1,
            last_update_id=100,
            bids=[(99.0, 1.0)],
            asks=[(101.0, 1.0)],
        )
    )
    book.apply_update(L2Update(2, 101, 102, 100, [(99.0, 2.0)], []))

    with pytest.raises(ValueError, match="missing pu"):
        book.apply_update(L2Update(3, 103, 104, None, [], [(101.0, 2.0)]))


def test_depth_validator_bootstrap_and_pu():
    validator = DepthSequenceValidator()
    validator.bootstrap(100)

    bridged = validator.observe({"U": 101, "u": 102, "pu": 99})
    assert bridged.state == "BRIDGED"

    contiguous = validator.observe({"U": 103, "u": 104, "pu": 102})
    assert contiguous.state == "CONTIGUOUS"

    missing_pu = validator.observe({"U": 105, "u": 106})
    assert missing_pu.state == "GAP"
    assert missing_pu.reason == "MISSING_PU_AFTER_BOOTSTRAP"


def test_depth_validator_rejects_pu_mismatch():
    validator = DepthSequenceValidator()
    validator.bootstrap(100)
    assert validator.observe({"U": 101, "u": 102, "pu": 100}).state == "BRIDGED"

    status = validator.observe({"U": 103, "u": 104, "pu": 101})
    assert status.state == "GAP"
    assert status.reason == "PU_MISMATCH"
