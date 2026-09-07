"""
V9 OOS Experiment — Cross-Asset Lead-Lag

Runs the pre-registered walk-forward OOS experiment.
All parameters are frozen in V9_EXPERIMENT_CONFIG.md.
"""
import pandas as pd
import numpy as np
from pathlib import Path
import json
from datetime import datetime, timezone
from sklearn.linear_model import Ridge

DATA_DIR = Path("data/hist/normalized")
RESEARCH_DIR = Path("data/research")

# Frozen configuration
HORIZONS = [5, 10, 15]
REBAL_FREQS = [5, 10, 13, 15]
UNIVERSE = ["ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "ADAUSDT",
            "AVAXUSDT", "DOTUSDT", "LINKUSDT", "POLUSDT", "DOGEUSDT"]
TRAIN_DAYS = 30  # Reduced from 60 due to 92-day data limit
VAL_DAYS = 10
OOS_DAYS = 10
STEP_DAYS = 10
RIDGE_ALPHA = 0.05
RANDOM_SEED = 42
COST_PER_REBALANCE = 85  # bps, base case

np.random.seed(RANDOM_SEED)


def load_aggtrades(symbol: str) -> pd.DataFrame:
    norm_dir = DATA_DIR / symbol / "aggTrades"
    files = sorted(norm_dir.glob("*.parquet"))
    dfs = [pd.read_parquet(f) for f in files]
    df = pd.concat(dfs, ignore_index=True)
    df = df.drop_duplicates(subset=["agg_trade_id"])
    df = df.sort_values("transact_time").reset_index(drop=True)
    return df


def construct_minute_bars(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["minute"] = (df["transact_time"] // 60000) * 60000
    bars = df.groupby("minute").agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("quantity", "sum"),
        trade_count=("agg_trade_id", "count"),
    ).reset_index().rename(columns={"minute": "timestamp"})
    return bars.sort_values("timestamp").reset_index(drop=True)


def build_predictor_frame(btc_bars: pd.DataFrame) -> pd.DataFrame:
    df = btc_bars.copy().sort_values("timestamp").reset_index(drop=True)
    df["log_ret"] = np.log(df["close"] / df["close"].shift(1))

    df["btc_ret_1m"] = df["log_ret"].shift(1)
    df["btc_ret_5m"] = np.log(df["close"] / df["close"].shift(6)).shift(1)
    df["btc_ret_10m"] = np.log(df["close"] / df["close"].shift(11)).shift(1)
    df["ofi_5m"] = df["log_ret"].rolling(5, min_periods=1).sum().shift(1)
    df["realized_vol_5m"] = df["log_ret"].rolling(5, min_periods=1).std().shift(1)

    pred = df[["timestamp", "close", "btc_ret_1m", "btc_ret_5m", "btc_ret_10m",
               "ofi_5m", "realized_vol_5m"]].copy()
    pred = pred.dropna(subset=["btc_ret_1m", "btc_ret_5m", "btc_ret_10m"])
    return pred.reset_index(drop=True)


def build_target_frame(alt_bars: pd.DataFrame, horizon: int = 5) -> pd.DataFrame:
    df = alt_bars.copy().sort_values("timestamp").reset_index(drop=True)
    df[f"target_{horizon}m"] = (
        np.log(df["close"].shift(-horizon) / df["close"]) * 10000
    )
    df = df.dropna(subset=[f"target_{horizon}m"])
    return df


def compute_hac_tstat(returns: np.ndarray) -> tuple[float, float]:
    """Compute HAC-robust t-statistic (Newey-West with automatic lag)."""
    if len(returns) < 10:
        return 0.0, 1.0
    r = returns - np.mean(returns)
    T = len(r)
    mu = np.mean(returns)

    # Newey-West variance with lag = floor(4*(T/100)^(2/9))
    lag = int(np.floor(4 * (T / 100) ** (2 / 9)))
    lag = min(lag, T - 1)

    gamma0 = np.sum(r ** 2) / T
    var = gamma0
    for l in range(1, lag + 1):
        w = 1 - l / (lag + 1)
        gamma_l = np.sum(r[l:] * r[:-l]) / T
        var += 2 * w * gamma_l

    if var <= 0:
        return 0.0, 1.0
    se = np.sqrt(var / T)
    t_stat = mu / se
    from scipy import stats
    p_val = 2 * (1 - stats.t.cdf(abs(t_stat), df=T - 1))
    return t_stat, p_val


def run_single_fold(
    train_data: pd.DataFrame,
    oos_data: pd.DataFrame,
    predictor_cols: list[str],
    target_col: str,
    horizon: int,
    rebal_freq: int,
) -> dict:
    """Run a single OOS fold."""
    X_train = train_data[predictor_cols].values
    y_train = train_data[target_col].values

    # Standardize using train stats
    mu = X_train.mean(axis=0)
    std = X_train.std(axis=0)
    std[std == 0] = 1
    X_train_std = (X_train - mu) / std

    model = Ridge(alpha=RIDGE_ALPHA, fit_intercept=True)
    model.fit(X_train_std, y_train)

    # OOS evaluation
    X_oos = oos_data[predictor_cols].values
    X_oos_std = (X_oos - mu) / std
    predictions = model.predict(X_oos_std)
    actuals = oos_data[target_col].values

    # Portfolio: equal-weight long-short based on predicted direction
    # Long top quintile, short bottom quintile
    n_coins = len(UNIVERSE)
    signals = pd.DataFrame({
        "predicted": predictions,
        "actual": actuals,
    })

    if len(signals) == 0:
        return {"valid": False}

    # Generate trading signals (simplified: trade when |pred| > threshold)
    threshold = 0  # Trade all periods (simplified for research)
    signals["signal"] = np.where(signals["predicted"] > threshold, 1,
                                  np.where(signals["predicted"] < -threshold, -1, 0))

    # Gross P&L: signal * actual return
    signals["gross_pnl"] = signals["signal"] * signals["actual"]

    # Count trades (signal changes)
    trades = (signals["signal"].diff() != 0).sum()

    # Net P&L: subtract costs per rebalance
    cost_per_trade = COST_PER_REBALANCE  # bps
    signals["net_pnl"] = signals["gross_pnl"] - (cost_per_trade * (signals["signal"] != 0))

    gross_mean = signals["gross_pnl"].mean()
    net_mean = signals["net_pnl"].mean()
    gross_std = signals["gross_pnl"].std()
    net_std = signals["net_pnl"].std()

    # HAC t-stat
    t_stat, p_val = compute_hac_tstat(signals["net_pnl"].values)

    # 95% CI
    ci_half = 1.96 * net_std / np.sqrt(len(signals))
    ci_low = net_mean - ci_half
    ci_high = net_mean + ci_half

    return {
        "valid": True,
        "n_obs": len(signals),
        "trades": int(trades),
        "gross_mean_bps": float(gross_mean),
        "net_mean_bps": float(net_mean),
        "gross_std": float(gross_std),
        "net_std": float(net_std),
        "t_stat": float(t_stat),
        "p_val": float(p_val),
        "ci_low": float(ci_low),
        "ci_high": float(ci_high),
        "hit_rate": float((signals["gross_pnl"] > 0).mean()),
        "max_drawdown": float(signals["net_pnl"].cumsum().cummax().sub(signals["net_pnl"].cumsum()).max()),
    }


def run_v9_experiment():
    """Run the complete V9 OOS experiment."""
    print("=" * 70)
    print("V9 CROSS-ASSET LEAD-LAG OOS EXPERIMENT")
    print("=" * 70)

    # 1. Load data
    print("\n1. Loading BTC data...")
    btc = load_aggtrades("BTCUSDT")
    btc_bars = construct_minute_bars(btc)
    print(f"   BTC: {len(btc):,} trades, {len(btc_bars):,} minute bars")

    print("\n2. Loading altcoin data...")
    alt_bars = {}
    for sym in UNIVERSE:
        try:
            df = load_aggtrades(sym)
            bars = construct_minute_bars(df)
            alt_bars[sym] = bars
            print(f"   {sym}: {len(df):,} trades, {len(bars):,} minute bars")
        except Exception as e:
            print(f"   {sym}: FAILED - {e}")

    # 3. Build predictors
    print("\n3. Building predictor frame...")
    predictors = build_predictor_frame(btc_bars)
    print(f"   Predictors: {len(predictors):,} rows, {list(predictors.columns)}")

    # 4. Build targets for each horizon
    print("\n4. Building target frames...")
    targets = {}
    for horizon in HORIZONS:
        targets[horizon] = {}
        for sym in UNIVERSE:
            if sym in alt_bars:
                targets[horizon][sym] = build_target_frame(alt_bars[sym], horizon)

    # 5. Determine date range
    min_ts = predictors["timestamp"].min()
    max_ts = predictors["timestamp"].max()
    for sym in UNIVERSE:
        if sym in alt_bars:
            min_ts = max(min_ts, alt_bars[sym]["timestamp"].min())
            max_ts = min(max_ts, alt_bars[sym]["timestamp"].max())

    start_date = pd.Timestamp(min_ts, unit="ms", tz="UTC")
    end_date = pd.Timestamp(max_ts, unit="ms", tz="UTC")
    total_days = (end_date - start_date).days
    print(f"\n5. Common date range: {start_date.date()} to {end_date.date()} ({total_days} days)")

    # 6. Run walk-forward for each horizon
    print("\n6. Running walk-forward OOS experiment...")
    all_results = {}

    predictor_cols = ["btc_ret_1m", "btc_ret_5m", "btc_ret_10m", "ofi_5m", "realized_vol_5m"]

    for horizon in HORIZONS:
        print(f"\n   --- Horizon: {horizon} minutes ---")
        horizon_results = []

        # Build merged dataset for this horizon
        merged = predictors.copy()
        for sym in UNIVERSE:
            if sym in targets.get(horizon, {}):
                t = targets[horizon][sym][["timestamp", f"target_{horizon}m"]].copy()
                t = t.rename(columns={f"target_{horizon}m": f"{sym}_target"})
                merged = merged.merge(t, on="timestamp", how="inner")

        # Add equal-weighted portfolio target
        target_cols = [f"{sym}_target" for sym in UNIVERSE if f"{sym}_target" in merged.columns]
        merged["portfolio_target"] = merged[target_cols].mean(axis=1)

        # Add date column for splitting
        merged["date"] = pd.to_datetime(merged["timestamp"], unit="ms", utc=True)

        # Walk-forward
        fold_start = start_date
        fold_num = 0

        while True:
            train_start = fold_start
            train_end = train_start + pd.Timedelta(days=TRAIN_DAYS)
            val_end = train_end + pd.Timedelta(days=VAL_DAYS)
            oos_end = val_end + pd.Timedelta(days=OOS_DAYS)

            if oos_end > end_date:
                break

            train_mask = (merged["date"] >= train_start) & (merged["date"] < train_end)
            oos_mask = (merged["date"] >= val_end) & (merged["date"] < oos_end)

            train_data = merged[train_mask]
            oos_data = merged[oos_mask]

            if len(train_data) < 100 or len(oos_data) < 10:
                fold_start += pd.Timedelta(days=STEP_DAYS)
                fold_num += 1
                continue

            fold_num += 1
            result = run_single_fold(
                train_data, oos_data,
                predictor_cols, "portfolio_target",
                horizon, 5
            )

            result.update({
                "fold": fold_num,
                "horizon": horizon,
                "train_start": str(train_start.date()),
                "train_end": str(train_end.date()),
                "oos_start": str(val_end.date()),
                "oos_end": str(oos_end.date()),
            })
            horizon_results.append(result)

            print(f"   Fold {fold_num}: OOS {val_end.date()} to {oos_end.date()}, "
                  f"net={result.get('net_mean_bps', 0):.4f} bps, t={result.get('t_stat', 0):.2f}")

            fold_start += pd.Timedelta(days=STEP_DAYS)

        all_results[horizon] = horizon_results

    # 7. Aggregate results
    print("\n" + "=" * 70)
    print("RESULTS SUMMARY")
    print("=" * 70)

    for horizon in HORIZONS:
        results = all_results[horizon]
        if not results:
            print(f"\nHorizon {horizon}m: NO FOLDS COMPLETED")
            continue

        valid = [r for r in results if r.get("valid")]
        if not valid:
            print(f"\nHorizon {horizon}m: NO VALID FOLDS")
            continue

        net_means = [r["net_mean_bps"] for r in valid]
        gross_means = [r["gross_mean_bps"] for r in valid]
        t_stats = [r["t_stat"] for r in valid]

        avg_net = np.mean(net_means)
        avg_gross = np.mean(gross_means)
        avg_t = np.mean(t_stats)
        pct_positive = np.mean([1 if n > 0 else 0 for n in net_means]) * 100

        print(f"\nHorizon {horizon}m ({len(valid)} folds):")
        print(f"  Avg Gross: {avg_gross:.4f} bps")
        print(f"  Avg Net:   {avg_net:.4f} bps")
        print(f"  Avg t-stat: {avg_t:.2f}")
        print(f"  % Positive: {pct_positive:.0f}%")

    # 8. Save results
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "config": {
            "horizons": HORIZONS,
            "rebal_freqs": REBAL_FREQS,
            "universe": UNIVERSE,
            "train_days": TRAIN_DAYS,
            "val_days": VAL_DAYS,
            "oos_days": OOS_DAYS,
            "step_days": STEP_DAYS,
            "ridge_alpha": RIDGE_ALPHA,
            "cost_per_rebal": COST_PER_REBALANCE,
        },
        "results": {str(h): all_results[h] for h in HORIZONS},
    }

    output_path = RESEARCH_DIR / "v9_oos_results.json"
    output_path.write_text(json.dumps(output, indent=2, default=str))
    print(f"\nResults saved to {output_path}")

    return output


if __name__ == "__main__":
    run_v9_experiment()
