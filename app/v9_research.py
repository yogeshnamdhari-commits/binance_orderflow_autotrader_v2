"""
V9 Research Pipeline — Cross-Asset Lead-Lag

Orchestrates the full V9 research workflow:
data → features → model → validation → evaluation → report
"""
import pandas as pd
import numpy as np
from pathlib import Path
import json
from datetime import datetime, timezone

DATA_DIR = Path("data/hist/normalized")
RESEARCH_DIR = Path("data/research")

HORIZONS = [5, 10, 15]  # minutes
UNIVERSE = [
    "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
    "AVAXUSDT", "DOTUSDT", "LINKUSDT", "MATICUSDT", "DOGEUSDT",
]


def run_btc_data_validation() -> dict:
    """Validate BTCUSDT data integrity."""
    from app.v9_features import load_aggtrades, construct_minute_bars, build_predictor_frame

    print("=" * 60)
    print("BTC DATA VALIDATION")
    print("=" * 60)

    results = {}

    # 1. Load full history
    print("\n1. Loading BTCUSDT aggTrades (full 730 days)...")
    try:
        btc = load_aggtrades("BTCUSDT")
        results["total_trades"] = len(btc)
        print(f"   Total trades: {len(btc):,}")
    except Exception as e:
        print(f"   ERROR: {e}")
        return results

    # 2. Schema check
    print("\n2. Schema validation...")
    expected_cols = {"agg_trade_id", "price", "quantity", "first_trade_id", "last_trade_id", "transact_time", "is_buyer_maker"}
    actual_cols = set(btc.columns)
    results["schema_ok"] = expected_cols == actual_cols
    print(f"   Schema OK: {results['schema_ok']}")
    if not results["schema_ok"]:
        print(f"   Missing: {expected_cols - actual_cols}")
        print(f"   Extra: {actual_cols - expected_cols}")

    # 3. Duplicate check
    print("\n3. Duplicate check...")
    dups = btc.duplicated(subset=["agg_trade_id"]).sum()
    results["duplicates"] = int(dups)
    print(f"   Duplicates: {dups}")

    # 4. Timestamp continuity
    print("\n4. Timestamp continuity...")
    ts_min = btc["transact_time"].min()
    ts_max = btc["transact_time"].max()
    results["timestamp_range"] = {"min": int(ts_min), "max": int(ts_max)}
    print(f"   Range: {ts_min} to {ts_max}")
    span_days = (ts_max - ts_min) / (1000 * 60 * 60 * 24)
    print(f"   Span: {span_days:.1f} days")

    # 5. Price sanity
    print("\n5. Price sanity...")
    results["price_range"] = {
        "min": float(btc["price"].min()),
        "max": float(btc["price"].max()),
    }
    print(f"   Min: {btc['price'].min():.2f}, Max: {btc['price'].max():.2f}")

    # 6. Minute bar construction
    print("\n6. Constructing minute bars...")
    bars = construct_minute_bars(btc)
    results["minute_bars"] = len(bars)
    print(f"   Minute bars: {len(bars):,}")

    # 7. Predictor frame
    print("\n7. Building predictor frame...")
    pred = build_predictor_frame(bars)
    results["predictor_rows"] = len(pred)
    print(f"   Predictor rows: {len(pred):,}")
    print(f"   Columns: {list(pred.columns)}")

    # 8. Predictor statistics
    print("\n8. Predictor statistics...")
    for col in ["btc_ret_1m", "btc_ret_5m", "btc_ret_10m", "ofi_5m", "realized_vol_5m"]:
        if col in pred.columns:
            s = pred[col].dropna()
            print(f"   {col}: mean={s.mean():.6f}, std={s.std():.6f}, min={s.min():.6f}, max={s.max():.6f}")

    # 9. Data gaps
    print("\n9. Checking for data gaps...")
    if len(bars) > 1:
        gaps = bars["timestamp"].diff()
        gap_threshold = 5 * 60 * 1000  # 5 minutes
        large_gaps = gaps[gaps > gap_threshold]
        results["large_gaps"] = len(large_gaps)
        print(f"   Gaps > 5 min: {len(large_gaps)}")
        if len(large_gaps) > 0:
            print(f"   Max gap: {gaps.max() / (1000 * 60):.1f} minutes")

    print("\n" + "=" * 60)
    print("BTC DATA VALIDATION COMPLETE")
    print("=" * 60)

    return results


def run_altcoin_availability_check() -> dict:
    """Check which altcoin data is available."""
    print("\n" + "=" * 60)
    print("ALTCOIN AVAILABILITY CHECK")
    print("=" * 60)

    results = {}
    for sym in UNIVERSE:
        norm_dir = DATA_DIR / sym / "aggTrades"
        if norm_dir.exists():
            files = list(norm_dir.glob("*.parquet"))
            results[sym] = {"available": True, "files": len(files)}
            print(f"   {sym}: {len(files)} files")
        else:
            results[sym] = {"available": False, "files": 0}
            print(f"   {sym}: NOT AVAILABLE")

    available = sum(1 for v in results.values() if v["available"])
    print(f"\n   Available: {available}/{len(UNIVERSE)}")

    return results


def main():
    print("V9 Research Pipeline")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print()

    # Step 1: Validate BTC data
    btc_results = run_btc_data_validation()

    # Step 2: Check altcoin availability
    alt_results = run_altcoin_availability_check()

    # Step 3: Save results
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "btc_validation": btc_results,
        "altcoin_availability": alt_results,
        "v9_testable": any(v["available"] for v in alt_results.values()),
    }

    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    output_path = RESEARCH_DIR / "v9_pipeline_check.json"
    output_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nResults saved to {output_path}")

    if not output["v9_testable"]:
        print("\n*** V9 FULL TEST BLOCKED: No altcoin data available ***")
        print("Run: python -m app.v9_data_pipeline to acquire altcoin data")


if __name__ == "__main__":
    main()
