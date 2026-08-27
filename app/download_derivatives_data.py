"""Download historical Binance futures data: funding rates, open interest, long/short ratio."""
import requests
import pandas as pd
import numpy as np
from pathlib import Path
import time
import json

DATA_DIR = Path("data/hist/derivatives")
DATA_DIR.mkdir(parents=True, exist_ok=True)

BASE_URL = "https://fapi.binance.com/fapi/v1"

def fetch_funding_rates(start_ts: int, end_ts: int, limit: int = 1000):
    """Fetch historical funding rates for BTCUSDT perpetual."""
    url = f"{BASE_URL}/fundingRate"
    params = {
        "symbol": "BTCUSDT",
        "startTime": start_ts,
        "endTime": end_ts,
        "limit": limit,
    }
    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        return None
    data = r.json()
    return pd.DataFrame(data)

def fetch_open_interest_history(start_ts: int, end_ts: int, period: str = "1h", limit: int = 1000):
    """Fetch historical open interest."""
    url = f"{BASE_URL}/openInterest"
    # Binance API doesn't support history for OI via REST spot - use different endpoint
    # Actually, there's no direct endpoint for historical OI. Use the /fapi/v1/openInterest for current.
    # For historical, we need the data file downloads.
    return None

def fetch_long_short_ratio(start_ts: int, end_ts: int, limit: int = 1000):
    """Fetch long/short ratio data."""
    url = f"{BASE_URL}/longShortRatio"
    params = {
        "symbol": "BTCUSDT",
        "startDate": start_ts,
        "endDate": end_ts,
        "limit": limit,
    }
    r = requests.get(url, timeout=30)
    if r.status_code != 200:
        return None
    data = r.json()
    return pd.DataFrame(data.get("data", data)) if isinstance(data, dict) else pd.DataFrame(data)

def fetch_btcusdt_price_history(start_date: str, end_date: str):
    """Fetch BTCUSDT perpetual price history for basis calculation."""
    url = f"{BASE_URL}/klines"
    params = {
        "symbol": "BTCUSDT",
        "interval": "1h",
        "startTime": start_date,
        "endTime": end_date,
        "limit": 1500,
    }
    r = requests.get(url, params=params, timeout=30)
    if r.status_code != 200:
        return None
    data = r.json()
    df = pd.DataFrame(data, columns=[
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base_asset_volume", "taker_buy_quote_asset_volume", "ignore"
    ])
    df['ts'] = df['open_time'].astype(np.int64)
    return df

def main():
    """Download 30 days of funding rates and long/short ratio."""
    start_date = "2024-08-16"
    end_date = "2024-09-15"
    start_ts = int(pd.Timestamp(start_date).timestamp() * 1000)
    end_ts = int(pd.Timestamp(end_date).timestamp() * 1000)
    
    output_dir = DATA_DIR / "BTCUSDT"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"Downloading BTCUSDT perpetual data: {start_date} to {end_date}")
    
    # Funding rates
    print("Downloading funding rates...")
    funding_df = fetch_funding_rates(start_ts, end_ts)
    if funding_df is not None and len(funding_df) > 0:
        funding_path = output_dir / "funding_rates.parquet"
        funding_df.to_parquet(funding_path)
        print(f"  Saved {len(funding_df)} funding rate records to {funding_path}")
        print(f"  Funding rate range: {funding_df['fundingRate'].astype(float).min():.6f} to {funding_df['fundingRate'].astype(float).max():.6f}")
    else:
        print("  Failed to download funding rates")
    
    # Long/short ratio
    print("Downloading long/short ratio...")
    ls_df = fetch_long_short_ratio(start_ts, end_ts)
    if ls_df is not None and len(ls_df) > 0:
        ls_path = output_dir / "long_short_ratio.parquet"
        ls_df.to_parquet(ls_path)
        print(f"  Saved {len(ls_df)} long/short ratio records to {ls_path}")
    else:
        print("  Failed to download long/short ratio")
    
    # Price history for basis
    print("Downloading hourly price history...")
    price_df = fetch_btcusdt_price_history(start_ts, end_ts)
    if price_df is not None and len(price_df) > 0:
        price_path = output_dir / "hourly_price.parquet"
        price_df.to_parquet(price_path)
        print(f"  Saved {len(price_df)} hourly price records to {price_path}")
    else:
        print("  Failed to download price history")
    
    # Save manifest
    manifest = {
        "source": "https://fapi.binance.com/fapi/v1",
        "symbol": "BTCUSDT",
        "data_type": "derivatives_context",
        "start_date": start_date,
        "end_date": end_date,
        "files": {
            "funding_rates": "BTCUSDT/funding_rates.parquet" if funding_df is not None else "MISSING",
            "long_short_ratio": "BTCUSDT/long_short_ratio.parquet" if ls_df is not None else "MISSING",
            "hourly_price": "BTCUSDT/hourly_price.parquet" if price_df is not None else "MISSING",
        }
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\nManifest saved to {output_dir / 'manifest.json'}")

if __name__ == "__main__":
    main()
