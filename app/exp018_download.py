"""EXP-018: Download full 730-day derivatives data for hypothesis testing.

Downloads:
1. BTCUSDT funding rate (8h intervals, ~2190 records for 730 days)
2. BTCUSDT perp hourly klines (730 days, 1h bars)
3. BTCUSDT spot hourly klines (for basis calculation)
4. ETHUSDT funding rate (for cross-asset analysis)

All downloads are paginated and saved to data/hist/derivatives/BTCUSDT/.
"""
import requests
import pandas as pd
import numpy as np
from pathlib import Path
import json
import time
from datetime import datetime, timedelta

DERIV_DIR = Path("data/hist/derivatives/BTCUSDT")
ETH_DIR = Path("data/hist/derivatives/BTCUSDT")  # Store ETH alongside for cross-asset

def fetch_funding_rates_full(symbol="BTCUSDT", max_records=2200):
    """Download all historical funding rates via API pagination."""
    url = "https://fqi.binance.com/fapi/v1/fundingRate"
    # Use the correct Binance Futures endpoint
    url = "https://fapi.binance.com/fapi/v1/fundingRate"
    
    # Funding occurs every 8 hours = 3 times per day
    # 730 days = 2160 funding events expected
    # Max limit per call = 1000, so need ~3 calls
    
    # Start from the earliest date in our trade data
    start_dt = datetime(2024, 8, 16)
    end_dt = datetime(2026, 8, 24)
    
    # Use startTime/endTime params
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)
    
    all_records = []
    last_ts = start_ts
    
    while last_ts < end_ts:
        url = f"https://fapi.binance.com/fapi/v1/fundingRate"
        params = {
            "symbol": symbol,
            "startTime": last_ts,
            "endTime": end_ts,
            "limit": 1000,
        }
        
        r = requests.get(url, params=params, timeout=30)
        if r.status_code != 200:
            print(f"  API error: {r.status_code} {r.text[:200]}")
            break
            
        data = r.json()
        if not data:
            break
            
        all_records.extend(data)
        
        # Move to after the last returned record
        last_ts = data[-1]["fundingTime"] + 1
        
        # Binance rate limit: 1200 weight/minute
        time.sleep(0.5)
        
        if len(data) < 1000:
            break
    
    print(f"  {symbol}: Downloaded {len(all_records)} funding rate records")
    
    df = pd.DataFrame(all_records)
    df["fundingTime"] = df["fundingTime"].astype(np.int64)
    df["fundingRate"] = df["fundingRate"].astype(float)
    df = df.sort_values("fundingTime").reset_index(drop=True)
    
    return df


def fetch_hourly_klines_full(symbol="BTCUSDT", max_calls=700, use_mark=False):
    """Download hourly klines via REST API pagination.
    
    Max 1000 records per call (hourly), 730 days = 17520 records = ~18 calls.
    """
    base_url = "https://fapi.binance.com/fapi/v1/klines" if use_mark else "https://api.binance.com/api/v3/klines"
    url = f"https://fapi.binance.com/fapi/v1/klines" if use_mark else "https://api.binance.com/api/v3/klines"
    
    start_dt = datetime(2024, 8, 16)
    end_dt = datetime(2026, 8, 24)
    
    start_ts = int(start_dt.timestamp() * 1000)
    end_ts = int(end_dt.timestamp() * 1000)
    
    all_records = []
    last_ts = start_ts
    call_count = 0
    
    while last_ts < end_ts and call_count < max_calls:
        params = {
            "symbol": symbol,
            "interval": "1h",
            "startTime": last_ts,
            "limit": 1000,
        }
        
        r = requests.get(url, params=params, timeout=30)
        if r.status_code != 200:
            print(f"  API error: {r.status_code} {r.text[:200]}")
            break
        
        data = r.json()
        if not data:
            break
        
        all_records.extend(data)
        last_ts = data[-1][0] + 1  # Close time of last candle + 1ms
        call_count += 1
        
        # Binance rate limit
        time.sleep(0.5)
        
        if len(data) < 1000:
            break
    
    print(f"  {symbol}: Downloaded {len(all_records)} hourly klines ({call_count} calls)")
    
    columns = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "num_trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ]
    df = pd.DataFrame(all_records, columns=columns)
    df["ts_ms"] = df["open_time"].astype(np.int64)
    df["close"] = df["close"].astype(float)
    df["open"] = df["open"].astype(float)
    df["high"] = df["high"].astype(float)
    df["low"] = df["low"].astype(float)
    df = df.sort_values("ts_ms").reset_index(drop=True)
    
    return df


def main():
    print("=" * 70)
    print("EXP-018: Full 730-Day Derivatives Data Download")
    print("=" * 70)
    
    DERIV_DIR.mkdir(parents=True, exist_ok=True)
    
    # 1. BTCUSDT funding rates (full 730 days)
    print("\n1. Downloading BTCUSDT funding rates (730 days)...")
    try:
        funding_df = fetch_funding_rates_full("BTCUSDT")
        if len(funding_df) > 0:
            funding_path = DERIV_DIR / "funding_rates_730d.parquet"
            funding_df.to_parquet(funding_path)
            print(f"   Saved to {funding_path}")
            print(f"   Range: {pd.to_datetime(funding_df['fundingTime'].iloc[0], unit='ms')} "
                  f"to {pd.to_datetime(funding_df['fundingTime'].iloc[-1], unit='ms')}")
            print(f"   Records: {len(funding_df)}")
        else:
            print("   WARNING: No data downloaded, keeping existing 30-day file")
            funding_df = pd.read_parquet(DERIV_DIR / "funding_rates.parquet")
    except Exception as e:
        print(f"   Error: {e}")
        print("   Keeping existing 30-day funding data")
        funding_df = pd.read_parquet(DERIV_DIR / "funding_rates.parquet")
    
    # 2. BTCUSDT perp hourly klines (full 730 days)
    print("\n2. Downloading BTCUSDT perpetual hourly klines (730 days)...")
    try:
        perp_df = fetch_hourly_klines_full("BTCUSDT", use_mark=False)
        if len(perp_df) > 0:
            perp_path = DERIV_DIR / "perp_hourly_730d.parquet"
            perp_df.to_parquet(perp_path)
            print(f"   Saved to {perp_path}")
            print(f"   Range: {pd.to_datetime(perp_df['ts_ms'].iloc[0], unit='ms')} "
                  f"to {pd.to_datetime(perp_df['ts_ms'].iloc[-1], unit='ms')}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # 3. BTC spot hourly klines (for basis)
    print("\n3. Downloading BTC spot hourly klines (730 days)...")
    try:
        spot_df = fetch_hourly_klines_full("BTCUSDT", use_mark=False)
        # Binance spot uses different endpoint
        url = "https://api.binance.com/api/v3/klines"
        start_ts = int(datetime(2024, 8, 16).timestamp() * 1000)
        end_ts = int(datetime(2026, 8, 24).timestamp() * 1000)
        
        all_spot = []
        last_ts = start_ts
        calls = 0
        while last_ts < end_ts and calls < 25:
            r = requests.get(url, params={
                "symbol": "BTCUSDT",
                "interval": "1h",
                "startTime": last_ts,
                "limit": 1000
            }, timeout=30)
            if r.status_code != 200:
                print(f"   Spot API error: {r.status_code}")
                break
            data = r.json()
            if not data:
                break
            all_spot.extend(data)
            last_ts = data[-1][0] + 1
            calls += 1
            time.sleep(0.5)
        
        print(f"   BTC spot: Downloaded {len(all_spot)} hourly klines ({calls} calls)")
        if len(all_spot) > 0:
            columns = ["open_time", "open", "high", "low", "close", "volume",
                      "close_time", "quote_asset_volume", "num_trades",
                      "taker_buy_base", "taker_buy_quote", "ignore"]
            spot_df = pd.DataFrame(all_spot, columns=columns)
            spot_df["ts_ms"] = spot_df["open_time"].astype(np.int64)
            spot_df["close"] = spot_df["close"].astype(float)
            spot_df = spot_df.sort_values("ts_ms").reset_index(drop=True)
            spot_path = DERIV_DIR / "spot_hourly_730d.parquet"
            spot_df.to_parquet(spot_path)
            print(f"   Saved to {spot_path}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # 4. ETHUSDT funding rates (cross-asset)
    print("\n4. Downloading ETHUSDT funding rates (730 days)...")
    try:
        eth_funding = fetch_funding_rates_full("ETHUSDT")
        if len(eth_funding) > 0:
            eth_path = DERIV_DIR / "eth_funding_rates_730d.parquet"
            eth_funding.to_parquet(eth_path)
            print(f"   Saved to {eth_path}")
    except Exception as e:
        print(f"   Error: {e}")
    
    # Save manifest
    manifest = {
        "download_date": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "binance_futures_api": "https://fapi.binance.com/fapi/v1/fundingRate",
            "binance_spot_api": "https://api.binance.com/api/v3/klines",
            "binance_perp_api": "https://fapi.binance.com/fapi/v1/klines",
        },
        "files": {
            "btcusdt_funding": "BTCUSDT/funding_rates_730d.parquet",
            "btcusdt_perp_hourly": "BTCUSDT/perp_hourly_730d.parquet",
            "btcusdt_spot_hourly": "BTCUSDT/spot_hourly_730d.parquet",
            "ethusdt_funding": "BTCUSDT/eth_funding_rates_730d.parquet",
        },
        "notes": {
            "open_interest": "NOT AVAILABLE - Binance API only provides current OI snapshot",
            "liquidations": "NOT AVAILABLE - requires paid subscription",
            "cross_venue": "NOT AVAILABLE - no free historical cross-venue data",
        }
    }
    (DERIV_DIR / "exp018_data_manifest.json").write_text(json.dumps(manifest, indent=2))
    print("\nManifest saved.")


if __name__ == "__main__":
    from datetime import timezone
    main()
