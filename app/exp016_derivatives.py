"""EXP-016: Cross-Market/Derivatives Context Feature Engineering.
Optimized for speed - loads 30 days of data efficiently."""
import pandas as pd
import numpy as np
from pathlib import Path
import json
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

NORM_DIR = Path("data/hist/normalized/BTCUSDT/aggTrades")
DERIV_DIR = Path("data/hist/derivatives/BTCUSDT")

HORIZONS_MS = [1000, 5000, 10000, 30000, 60000]
HORIZONS_SEC = [1, 5, 10, 30, 60]


def main():
    print("=" * 70)
    print("EXP-016: Cross-Market/Derivatives Context")
    print("=" * 70)

    # Load derivatives data
    funding_df = pd.read_parquet(DERIV_DIR / "funding_rates.parquet")
    funding_df['fundingTime'] = funding_df['fundingTime'].astype(np.int64)
    funding_df['fundingRate'] = funding_df['fundingRate'].astype(float)
    funding_df = funding_df.sort_values('fundingTime').reset_index(drop=True)
    print(f"Funding rates: {len(funding_df)} records")

    # Load hourly price data
    hourly_df = pd.read_parquet(DERIV_DIR / "hourly_price.parquet")
    hourly_df['ts'] = pd.to_datetime(hourly_df['ts'], unit='ms')
    hourly_df['close'] = hourly_df['close'].astype(float)
    hourly_df = hourly_df.sort_values('ts').reset_index(drop=True)
    print(f"Hourly prices: {len(hourly_df)} records")

    # Load ALL trades at once (30 days)
    trade_files = sorted(NORM_DIR.glob('*.parquet'))[:30]
    print(f"\nLoading {len(trade_files)} trade files...")

    dfs = []
    for f in trade_files:
        df = pd.read_parquet(f, columns=['transact_time', 'price', 'quantity', 'is_buyer_maker'])
        dfs.append(df)
    df = pd.concat(dfs, ignore_index=True)
    df = df.sort_values('transact_time').reset_index(drop=True)
    print(f"Total trades: {len(df):,}")

    # Compute derived columns
    df['ts_ms'] = df['transact_time'].astype(np.int64)
    df['price_f'] = df['price'].astype(np.float64)
    df['qty_f'] = df['quantity'].astype(np.float64)
    df['dv'] = df['price_f'] * df['qty_f']
    df['sign'] = np.where(df['is_buyer_maker'], -1.0, 1.0)

    # Causal funding rate features
    ft = funding_df['fundingTime'].values
    fr = funding_df['fundingRate'].values
    idx = np.searchsorted(ft, df['ts_ms'].values, side='right') - 1
    valid = idx >= 0
    df['funding_rate'] = 0.0
    df.loc[valid, 'funding_rate'] = fr[idx[valid]]
    df['funding_rate'] = df['funding_rate'].ffill().fillna(0.0)
    df['funding_sign'] = np.sign(df['funding_rate'])
    df['funding_abs'] = np.abs(df['funding_rate'])

    # Causal hourly returns
    prices_h = hourly_df['close'].values.astype(np.float64)
    ts_h = hourly_df['ts'].values
    ts_h_sec = (ts_h.view('int64') // 10**9).astype(np.int64)
    ret_1h = np.zeros(len(prices_h))
    ret_24h = np.zeros(len(prices_h))
    ret_1h[1:] = (prices_h[1:] / prices_h[:-1]) - 1.0
    ret_24h[24:] = (prices_h[24:] / prices_h[:-24]) - 1.0

    idx_h = np.searchsorted(ts_h_sec, (df['ts_ms'].values // 1000), side='right') - 1
    valid_h = idx_h >= 0
    df['hr_ret_1h'] = 0.0
    df['hr_ret_24h'] = 0.0
    df.loc[valid_h, 'hr_ret_1h'] = ret_1h[np.maximum(idx_h[valid_h], 0)]
    df.loc[valid_h, 'hr_ret_24h'] = ret_24h[np.maximum(idx_h[valid_h], 0)]
    df['hr_ret_1h'] = df['hr_ret_1h'].ffill().fillna(0.0)
    df['hr_ret_24h'] = df['hr_ret_24h'].ffill().fillna(0.0)

    # Forward returns at all horizons
    for h_sec, h_ms in zip(HORIZONS_SEC, HORIZONS_MS):
        ptr = np.searchsorted(df['ts_ms'].values, df['ts_ms'].values + h_ms, side='left')
        valid = ptr < len(df)
        ret_col = f'ret_{h_sec}s'
        df[ret_col] = 0.0
        df.loc[valid, ret_col] = (df['price_f'].values[ptr[valid]] - df['price_f'].values[valid]) / \
                                 df['price_f'].values[valid] * 1e4
        df[ret_col] = df[ret_col].where(valid, np.nan)

    # Size threshold (train only)
    train_end = int(len(df) * 0.70)
    p999 = np.percentile(df['dv'].values[:train_end], 99.9)
    print(f"\np99.9 (train): {p999:.0f} USD")

    results = {}

    for h_sec in HORIZONS_SEC:
        ret_col = f'ret_{h_sec}s'
        print(f"\n=== Horizon: {h_sec}s ===")

        for cond_name, cond_mask_fn in [
            ("p99.9", lambda: df['dv'] > p999),
            ("p99.0", lambda: df['dv'] > np.percentile(df['dv'].values[:train_end], 99.0)),
        ]:
            mask = cond_mask_fn()
            ret_col_valid = df[ret_col].notna()
            mask = mask & ret_col_valid

            n = int(mask.sum())
            if n < 50:
                print(f"  {cond_name}: n={n} (too few)")
                continue

            r = df.loc[mask, ret_col].values
            s = df.loc[mask, 'sign'].values
            fr_rate = df.loc[mask, 'funding_rate'].values
            fr_sign = df.loc[mask, 'funding_sign'].values
            fr_abs = df.loc[mask, 'funding_abs'].values
            hr_1h = df.loc[mask, 'hr_ret_1h'].values
            hr_24h = df.loc[mask, 'hr_ret_24h'].values

            split = int(n * 0.7)

            # Baseline
            ic_base = np.corrcoef(s, r)[0, 1] if np.std(r) > 0 else 0
            dp_base = (s * r).mean()
            auc_base = roc_auc_score((r > 0).astype(int), s) if len(np.unique((r > 0).astype(int))) > 1 else 0.5

            # Walk-forward predictions
            y = (r > 0).astype(int)

            # +Funding model
            X_f = np.column_stack([s, fr_sign, fr_abs])
            try:
                model_f = LogisticRegression(max_iter=2000, C=1.0, random_state=42)
                model_f.fit(X_f[:split], y[:split])
                proba_f = model_f.predict_proba(X_f[split:])[:, 1]
                pred_f = np.where(proba_f > 0.5, 1.0, -1.0)
                dp_f = (pred_f * r[split:]).mean()
                auc_f = roc_auc_score(y[split:], proba_f)
                ic_f = np.corrcoef(proba_f[:split], y[:split] * 2 - 1)[0, 1] if np.std(proba_f[:split]) > 0 else 0
            except:
                dp_f, auc_f, ic_f = dp_base, auc_base, ic_base

            # +Hourly
            X_hr = np.column_stack([s, hr_1h, hr_24h])
            try:
                model_hr = LogisticRegression(max_iter=2000, C=1.0, random_state=42)
                model_hr.fit(X_hr[:split], y[:split])
                proba_hr = model_hr.predict_proba(X_hr[split:])[:, 1]
                pred_hr = np.where(proba_hr > 0.5, 1.0, -1.0)
                dp_hr = (pred_hr * r[split:]).mean()
                auc_hr = roc_auc_score(y[split:], proba_hr)
            except:
                dp_hr, auc_hr = dp_base, auc_base

            # Full
            X_full = np.column_stack([s, fr_sign, fr_abs, hr_1h, hr_24h, s * fr_sign])
            try:
                model_full = LogisticRegression(max_iter=2000, C=1.0, random_state=42)
                model_full.fit(X_full[:split], y[:split])
                proba_full = model_full.predict_proba(X_full[split:])[:, 1]
                pred_full = np.where(proba_full > 0.5, 1.0, -1.0)
                dp_full = (pred_full * r[split:]).mean()
                auc_full = roc_auc_score(y[split:], proba_full)
            except:
                dp_full, auc_full = dp_base, auc_base

            # Bootstrap CI
            r_test = r[split:]
            s_test = s[split:]
            rng = np.random.RandomState(42)
            boots_base = []
            boots_full = []
            for _ in range(1000):
                idx = rng.randint(0, len(r_test), size=len(r_test))
                boots_base.append((s_test[idx] * r_test[idx]).mean() - 2.0)
                boots_full.append((pred_full[idx] * r_test[idx]).mean() - 2.0)
            boots_base = np.array(boots_base)
            boots_full = np.array(boots_full)

            incr = dp_full - dp_base

            print(f"  {cond_name}: n={n}")
            print(f"    Baseline: IC={ic_base:.4f}, AUC={auc_base:.4f}, dp={dp_base:.4f}, net_m={dp_base-2.0:.4f}")
            print(f"    +Funding: IC={ic_f:.4f}, AUC={auc_f:.4f}, dp={dp_f:.4f}, net_m={dp_f-2.0:.4f}")
            print(f"    +Hourly:  AUC={auc_hr:.4f}, dp={dp_hr:.4f}, net_m={dp_hr-2.0:.4f}")
            print(f"    Full:     AUC={auc_full:.4f}, dp={dp_full:.4f}, net_m={dp_full-2.0:.4f}")
            print(f"    Incremental: {incr:.4f} bps")
            print(f"    Bootstrap CI: [{np.percentile(boots_full, 2.5):.4f}, {np.percentile(boots_full, 97.5):.4f}]")

            # Funding regime
            pos_m = fr_sign > 0
            neg_m = fr_sign < 0
            for regime, label in [(pos_m, "pos_fund"), (neg_m, "neg_fund")]:
                if regime.sum() > 10:
                    r_r = r[regime]
                    s_r = s[regime]
                    ic_r = np.corrcoef(s_r, r_r)[0,1] if np.std(r_r) > 0 else 0
                    dp_r = (s_r * r_r).mean()
                    print(f"    Funding {label}: n={regime.sum()}, IC={ic_r:.4f}, dp={dp_r:.4f}")

            key = f"{h_sec}s_{cond_name}"
            results[key] = {
                "horizon": f"{h_sec}s",
                "condition": cond_name,
                "n_events": n,
                "baseline_ic": float(ic_base),
                "baseline_auc": float(auc_base),
                "baseline_dp": float(dp_base),
                "baseline_net_maker": float(dp_base - 2.0),
                "baseline_net_taker": float(dp_base - 4.0146),
                "funding_ic": float(ic_f),
                "funding_auc": float(auc_f),
                "funding_dp": float(dp_f),
                "funding_net_maker": float(dp_f - 2.0),
                "hourly_auc": float(auc_hr),
                "hourly_dp": float(dp_hr),
                "full_auc": float(auc_full),
                "full_dp": float(dp_full),
                "full_net_maker": float(dp_full - 2.0),
                "incremental_dp": float(incr),
                "bootstrap_ci_lower": float(np.percentile(boots_full, 2.5)),
                "bootstrap_ci_upper": float(np.percentile(boots_full, 97.5)),
                "bootstrap_ci_excludes_zero": bool(np.percentile(boots_full, 2.5) > 0),
            }

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY: Best incremental value across dimensions")
    print("=" * 70)

    best_incr = -999
    best_key = None
    for key, val in results.items():
        if val['incremental_dp'] > best_incr:
            best_incr = val['incremental_dp']
            best_key = key

    print(f"Best result: {best_key}, incremental={best_incr:.4f} bps")

    all_negative = all(v['full_net_maker'] <= 0 for v in results.values())
    print(f"All net_maker <= 0: {all_negative}")

    # Save
    with open(DERIV_DIR / "exp016_results.json", 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {DERIV_DIR / 'exp016_results.json'}")


if __name__ == "__main__":
    main()
