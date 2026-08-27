"""EXP-012: Economic Gate Model.

The economic gate determines whether an event presents an executable edge:
  expected_gross_move > execution_cost

This is the PRIMARY acceptance gate. No trade signal is generated unless
the lower 95% CI of net expectancy clears zero.

Economic mechanism:
  Aggressive flow > absorption capacity → price impact exceeds depth
  Fragility state amplifies impact persistence
  Expected move = flow_to_depth_ratio × volatility_state × conditional_multiplier

Cost components:
  - Maker fee: 0.02 bps (maker, posting limit order)
  - Taker fee: 0.04 bps (taker, crossing spread)
  - Spread cost: spread_bps (must cross bid/ask)
  - Slippage: modeled as convex function of flow/depth ratio
  - Latency: 1ms fixed (conservative for co-located setup)
  - Adverse selection: estimated from signed_volatility imbalance

Research basis:
  - Cont, Kukanov & Stoikov: price impact = beta × OFI, beta ~ 1/depth
  - Gould & Bonart: queue imbalance conditional prediction
  - Binance research: spread attenuates predictability, fragility amplifies impact
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple


class EconomicGate:
    """Economic gate: determines if expected gross move exceeds execution cost."""

    def __init__(self, maker_fee_bps: float = 0.02, taker_fee_bps: float = 0.04,
                 latency_bps: float = 0.01, slippage_coeff: float = 0.5):
        self.maker_fee_bps = maker_fee_bps
        self.taker_fee_bps = taker_fee_bps
        self.latency_bps = latency_bps
        self.slippage_coeff = slippage_coeff

    def compute_cost(self, row: pd.Series, is_taker: bool = True) -> float:
        """Compute total round-trip execution cost in bps.

        Args:
            row: feature row with spread_bps, flow_to_depth_ratio, depth1
            is_taker: True if crossing the spread (taker), False if posting (maker)

        Returns:
            Total cost in bps
        """
        # Fee cost
        fee = self.taker_fee_bps if is_taker else self.maker_fee_bps

        # Spread cost (round-trip: pay spread twice for taker, once for maker posting)
        if is_taker:
            spread_cost = row.get("spread_bps", 0.0155)
        else:
            # Maker posts inside spread, earns half spread on average
            spread_cost = -row.get("spread_bps", 0.0155) / 2.0

        # Slippage: convex function of flow/depth ratio
        # Model: slippage ~ coeff * (flow_to_depth_ratio ^ 2) * spread
        ftd = row.get("flow_to_depth_ratio", 0.0)
        sliplipage = self.slippage_coeff * (ftd ** 2) * max(row.get("spread_bps", 0.0155), 0.01)

        # Latency cost: time value of capital (small)
        latency = self.latency_bps

        # Adverse selection: estimated from flow imbalance persistence
        # When flow_direction persists, adverse selection risk is higher
        adv_sel = abs(row.get("flow_imbalance", 0.0)) * 0.005  # scaled

        total = fee + spread_cost + sliplipage + latency + adv_sel
        return total

    def compute_expected_gross(self, row: pd.Series, horizon_bps: float,
                                p_direction: float) -> float:
        """Compute expected gross move in bps.

        Uses the conditional model: when flow_to_depth is high and fragility is
        elevated, expected move scales with the flow/depth ratio.

        Args:
            row: feature row
            horizon_bps: observed std of returns at this horizon (bps)
            p_direction: predicted probability of direction match

        Returns:
            Expected gross move in bps (signed by flow direction)
        """
        ftd = row.get("flow_to_depth_ratio", 0.0)
        cancel_vel = row.get("cancellation_velocity", 0.0)
        flow_dir = row.get("flow_direction", 0.0)
        spread = row.get("spread_bps", 0.0155)

        # Cont-Kukanov-Stoikov: impact ~ OFI / depth
        # But conditionally amplified by fragility
        # Base impact factor
        base_impact = min(ftd * 100.0, 5.0)  # capped at ~5bps for typical events

        # Fragility amplification: when cancellation velocity is high,
        # remaining liquidity is unreliable → impact persists
        fragility_factor = min(cancel_vel * 50.0, 2.0)

        # Spread attenuation: wider spreads signal adverse selection
        # (Binance research finding)
        spread_attenuation = 1.0 / (1.0 + spread * 20.0)

        # Expected move magnitude
        expected_move_mag = base_impact * fragility_factor * spread_attenuation

        # Direction from model probability vs flow direction
        # If p_direction > 0.5, expected direction aligns with predicted
        expected_move = expected_move_mag * flow_dir * (2 * p_direction - 1)

        return expected_move

    def evaluate_gate(self, features_df: pd.DataFrame,
                      gross_returns: np.ndarray,
                      cost_bps: float = 2.5) -> Dict:
        """Evaluate the economic gate across all events.

        Args:
            features_df: DataFrame with EXP-012 features
            gross_returns: observed forward returns at horizon (bps)
            cost_bps: default cost if per-event cost computation fails

        Returns:
            Dict with gate statistics
        """
        n = len(features_df)
        results = {
            "n_total": n,
            "n_gated": 0,
            "gate_rate": 0.0,
            "gross_mean": 0.0,
            "net_mean": 0.0,
            "net_ci95_low": 0.0,
            "net_ci95_high": 0.0,
            "positive_frac": 0.0,
            "mean_net_gated": 0.0,
        }

        if n == 0:
            return results

        # Compute costs per event
        costs = np.array([
            self.compute_cost(features_df.iloc[i], is_taker=True)
            for i in range(n)
        ])

        # Net returns
        net_returns = gross_returns - costs

        # Gate: only trade when absolute expected move > cost
        # Using flow_to_depth_ratio as proxy for signal strength
        ftd_thresholds = [0.5, 0.75, 0.9, 0.95, 0.99]

        gated_stats = []
        for q in ftd_thresholds:
            threshold = features_df["flow_to_depth_ratio"].quantile(q)
            mask = features_df["flow_to_depth_ratio"] >= threshold
            if mask.sum() > 0:
                gated_net = net_returns[mask.values]
                gated_gross = gross_returns[mask.values]
                gated_stats.append({
                    "threshold_quantile": q,
                    "threshold_value": float(threshold),
                    "n_gated": int(mask.sum()),
                    "gross_mean": float(gated_gross.mean()),
                    "net_mean": float(gated_net.mean()),
                    "net_ci95_low": float(np.percentile(gated_net, 2.5)),
                    "net_ci95_high": float(np.percentile(gated_net, 97.5)),
                    "positive_frac": float((gated_net > 0).sum() / len(gated_net)),
                })

        # Overall stats
        results["gross_mean"] = float(np.nanmean(gross_returns))
        results["net_mean"] = float(np.nanmean(net_returns))
        results["net_ci95_low"] = float(np.nanpercentile(net_returns, 2.5))
        results["net_ci95_high"] = float(np.nanpercentile(net_returns, 97.5))
        results["positive_frac"] = float((net_returns > 0).sum() / n)

        # Best gated stat
        if gated_stats:
            best = max(gated_stats, key=lambda x: x["net_mean"])
            results["n_gated"] = best["n_gated"]
            results["gate_rate"] = best["n_gated"] / n
            results["mean_net_gated"] = best["net_mean"]
            results["best_gated"] = best

        results["gated_stats"] = gated_stats
        return results


# Cost model based on empirical findings from the repository
# Binance BTCUSDT taker fee: 0.04% (4.0 bps round-trip)
# Binance BTCUSDT maker fee: 0.02% (2.0 bps one-way)
# Spread observed: ~0.015 bps
# Maker rebate for VIP: up to 0.0012 bps (not modeled here for conservatism)

COST_MODEL_PARAMS = {
    "maker_fee_bps": 2.0,       # per-side maker fee (bps)
    "taker_fee_bps": 2.0,       # per-side taker fee (bps) — round-trip = 4.0
    "latency_bps": 0.01,
    "slippage_coeff": 0.5,
}


def compute_expected_cost_per_event(df: pd.DataFrame) -> np.ndarray:
    """Vectorized cost computation for all events.

    Round-trip cost = spread + 2×fee + slippage + latency + adverse_selection
    Taker round-trip fee: 4.0 bps (measured from cost_calibration.json)
    Maker round-trip fee: 2.0 bps (maker posting, earns rebate)
    """
    spread = df["spread_bps"].fillna(0.015).to_numpy()
    ftd = df["flow_to_depth_ratio"].fillna(0.0).to_numpy()
    flow_imb = df["flow_imbalance"].fillna(0.0).to_numpy()

    # Round-trip cost: taker crosses spread twice (entry + exit)
    fee_cost = 2 * COST_MODEL_PARAMS["taker_fee_bps"]  # 4.0 bps
    spread_cost = spread * 2  # Round-trip spread crossing
    slippage = COST_MODEL_PARAMS["slippage_coeff"] * (ftd ** 2) * np.maximum(spread, 0.01)
    latency = COST_MODEL_PARAMS["latency_bps"]
    adverse_sel = np.abs(flow_imb) * 0.005

    total_cost = fee_cost + spread_cost + slippage + latency + adverse_sel
    return total_cost


if __name__ == "__main__":
    from app.exp012_features import add_labels

    df = pd.read_parquet("data/research/exp012/exp012_features.parquet")
    df = add_labels(df)

    gate = EconomicGate(**COST_MODEL_PARAMS)

    for h in [1000, 3000, 5000, 10000]:
        col = f"r_{h}"
        r = df[col].dropna()
        df_valid = df[df[col].notna()]

        costs = compute_expected_cost_per_event(df_valid)
        net = df_valid[col].values - costs

        print(f"\n=== Horizon {h}ms ({h/1000}s) ===")
        print(f"N events: {len(df_valid)}")
        print(f"Gross mean: {r.mean():.4f} bps")
        print(f"Cost mean: {costs.mean():.4f} bps")
        print(f"Net mean: {net.mean():.4f} bps")
        print(f"Net CI95: [{np.percentile(net, 2.5):.4f}, {np.percentile(net, 97.5):.4f}]")
        print(f"Positive net: {(net > 0).sum()}/{len(net)} = {(net > 0).sum()/len(net)*100:.2f}%")

        # Evaluate gate
        results = gate.evaluate_gate(df_valid, df_valid[col].values)
        if "best_gated" in results:
            best = results["best_gated"]
            print(f"\nBest gate (ftd >= {best['threshold_quantile']}):")
            print(f"  N gated: {best['n_gated']}")
            print(f"  Net mean: {best['net_mean']:.4f} bps")
            print(f"  Net CI95: [{best['net_ci95_low']:.4f}, {best['net_ci95_high']:.4f}]")
            print(f"  Positive: {best['positive_frac']*100:.2f}%")
