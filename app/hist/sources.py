"""Authentic Binance public-data sources (USD-M Futures).

References verified 2026-08-16:
- https://github.com/binance/binance-public-data  (README: layouts, columns, CHECKSUM spec)
- https://data.binance.vision                     (archive endpoint)
- USD-M: data/futures/um/daily/{type}/{SYMBOL}/{SYMBOL}-{type}-{date}.zip + .CHECKSUM (SHA256)

Public archives DO include: aggTrades, trades, metrics, bookDepth.
Public archives do NOT include: tick-by-tick L2 (T_DEPTH). Binance historical L2 is a
separate facility: <7-day request ranges, must be handled for gaps.

NOTE: the futures `bookDepth` daily file is the "depth at +/- % from mid" metric
(timestamp,percentage,depth,notional), NOT an L2 order-book diff stream. It must never be
used to reconstruct bid/ask L2 or OFI, and is absent from the replay core inputs.
"""

BASE = "https://data.binance.vision"
FUTURES_UM = "data/futures/um/daily"

# Public daily archive types, canonical ordering for the availability audit.
ARCHIVE_TYPES = ("aggTrades", "trades", "metrics", "bookDepth")

# Types the replay/order-flow engine actually consumes.
REPLAY_TYPES = ("aggTrades",)

LINEAGE = {
    "aggTrades": "https://fapi.binance.com/fapi/v1/aggTrades",
    "trades": "https://fapi.binance.com/fapi/v1/trades",
    "metrics": "https://fapi.binance.com/fapi/v1/globalLongShortAccountRatio",
    "bookDepth": "https://data.binance.vision (depth-at-percentage metric; NOT L2)",
}


def archive_url(symbol, dtype, date, base=BASE, fut=FUTURES_UM):
    return ("/".join([base, fut, dtype, symbol.upper(), "%s-%s-%s.zip" % (symbol.upper(), dtype, date)]))


def checksum_url(symbol, dtype, date, base=BASE, fut=FUTURES_UM):
    return archive_url(symbol, dtype, date, base, fut) + ".CHECKSUM"


def parse_checksum(text):
    """Parse a Binance .CHECKSUM file ('sha256hex  filename'). Returns (hex, filename)."""
    parts = text.strip().split()
    return parts[0], parts[1]