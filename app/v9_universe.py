"""Deterministic, pre-asof V9 follower-universe selection."""
import pandas as pd


def select_v9_universe(liquidity_frame: pd.DataFrame, asof: pd.Timestamp, n: int = 10) -> list[str]:
    required = {"symbol", "timestamp", "volume_usd"}
    missing = required.difference(liquidity_frame.columns)
    if missing:
        raise ValueError(f"missing columns: {sorted(missing)}")
    frame = liquidity_frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    asof = pd.Timestamp(asof)
    if asof.tzinfo is None:
        asof = asof.tz_localize("UTC")
    else:
        asof = asof.tz_convert("UTC")
    if not (frame["timestamp"] < asof).all():
        raise ValueError("liquidity observations must be before asof")
    frame = frame[frame["symbol"].ne("BTCUSDT")].copy()
    if frame.empty:
        raise ValueError("no eligible follower symbols")
    ranked = (frame.groupby("symbol", as_index=False)["volume_usd"].median()
              .sort_values(["volume_usd", "symbol"], ascending=[False, True]))
    if len(ranked) < n:
        raise ValueError(f"fewer than {n} eligible follower symbols")
    return ranked.head(n)["symbol"].tolist()
