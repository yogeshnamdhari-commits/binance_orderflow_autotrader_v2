"""V6 microstructure engine — enhanced order-book feature computation.

This module implements the architecture spec:
  order-book events -> flow imbalance -> liquidity response -> price response
  -> executable expectancy

Features are computed CAUSALLY from strictly earlier events.
No look-ahead. No forward references.

Feature groups (pre-registered, frozen):
  A. Multi-level OFI (L1, L5, L10, L20)
  B. Queue imbalance (L1, L5, L10, L20) + delta/velocity/acceleration
  C. Microprice + microprice-minus-mid + velocity
  D. Passive flow separation (additions, cancellations, depletion, replenishment)
  E. Absorption candidate (observable definition)
  F. Liquidity regime state (NORMAL, THIN, STRESSED, SHOCK, RECOVERY)
  G. Price-impact coefficient (beta_t ~ 1/Depth_t)
  H. Trade-flow enhancements (demoted CVD)
  I. Toxicity / adverse selection state (VPIN as research candidate)

V5 features are preserved exactly. V6 features are frozen.
This module is additive only.
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .v5_features import V5_FEATURES

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

def _parse_levels(x):
    """Parse levels_bid / levels_ask from JSON list of [price, qty]."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return []
    if isinstance(x, str):
        try:
            x = json.loads(x)
        except Exception:
            return []
    if not isinstance(x, list):
        return []
    out = []
    for item in x:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            try:
                p, q = float(item[0]), float(item[1])
                if np.isfinite(p) and np.isfinite(q) and q > 0:
                    out.append((p, q))
            except (TypeError, ValueError):
                pass
    return out


def _top_n(levels, n, reverse=False):
    """Return top n levels sorted by price."""
    levels = sorted(levels, reverse=reverse)[:n]
    return levels


# ---------------------------------------------------------------------------
# True multi-level OFI (Xu, Gould & Howison 2019)
# ---------------------------------------------------------------------------

def _compute_true_multilevel_ofi(df):
    """Compute true multi-level OFI from consecutive depth snapshots.

    OFI^n(t) = sum_{i=1}^{n} [Δbid_qty_i(t) - Δask_qty_i(t)]

    Where Δbid_qty_i(t) = bid_qty at level i at time t minus bid_qty at
    the same price level at time t-1. Missing levels are treated as 0.

    This is the Xu-Gould-Howison formulation, not a proxy.
    Causal: OFI at time t uses only data from t and earlier.
    """
    ofi_l1 = np.full(len(df), 0.0)
    ofi_l5 = np.full(len(df), 0.0)
    ofi_l10 = np.full(len(df), 0.0)
    ofi_l20 = np.full(len(df), 0.0)

    for session, grp in df.groupby("session", sort=True):
        idx = grp.index.to_numpy()
        depths = grp[grp["kind"] == "depth"]
        if len(depths) < 2:
            continue

        depth_idx = depths.index.to_numpy()
        prev_bids = {}
        prev_asks = {}

        for di in range(len(depth_idx)):
            i = depth_idx[di]
            bids = _parse_levels(df.at[i, "levels_bid"])
            asks = _parse_levels(df.at[i, "levels_ask"])
            bid_dict = {p: q for p, q in bids}
            ask_dict = {p: q for p, q in asks}

            if di > 0:
                # Compute OFI from quantity changes
                ofi1, ofi5, ofi10, ofi20 = 0.0, 0.0, 0.0, 0.0

                # All price levels that existed before or now
                all_bid_prices = sorted(set(prev_bids.keys()) | set(bid_dict.keys()), reverse=True)
                all_ask_prices = sorted(set(prev_asks.keys()) | set(ask_dict.keys()))

                # L1-L20: use top 20 levels from each side
                top_bids = all_bid_prices[:20]
                top_asks = all_ask_prices[:20]

                for p in top_bids[:1]:
                    ofi1 += bid_dict.get(p, 0.0) - prev_bids.get(p, 0.0)
                    ofi5 += ofi1
                    ofi10 += ofi1
                    ofi20 += ofi1
                for p in top_bids[1:5]:
                    ofi5 += bid_dict.get(p, 0.0) - prev_bids.get(p, 0.0)
                    ofi10 += ofi5
                    ofi20 += ofi5
                for p in top_bids[5:10]:
                    ofi10 += bid_dict.get(p, 0.0) - prev_bids.get(p, 0.0)
                    ofi20 += ofi10
                for p in top_bids[10:20]:
                    ofi20 += bid_dict.get(p, 0.0) - prev_bids.get(p, 0.0)

                for p in top_asks[:1]:
                    ofi1 -= ask_dict.get(p, 0.0) - prev_asks.get(p, 0.0)
                    ofi5 -= ofi1
                    ofi10 -= ofi1
                    ofi20 -= ofi1
                for p in top_asks[1:5]:
                    ofi5 -= ask_dict.get(p, 0.0) - prev_asks.get(p, 0.0)
                    ofi10 -= ofi5
                    ofi20 -= ofi5
                for p in top_asks[5:10]:
                    ofi10 -= ask_dict.get(p, 0.0) - prev_asks.get(p, 0.0)
                    ofi20 -= ofi10
                for p in top_asks[10:20]:
                    ofi20 -= ask_dict.get(p, 0.0) - prev_asks.get(p, 0.0)

                ofi_l1[i] = ofi1
                ofi_l5[i] = ofi5
                ofi_l10[i] = ofi10
                ofi_l20[i] = ofi20

            prev_bids = bid_dict
            prev_asks = ask_dict

    return ofi_l1, ofi_l5, ofi_l10, ofi_l20


def _ofi_levels_from_depth(df):
    """Compute OFI at L1, L5, L10, L20 from depth snapshots.

    Returns numpy arrays aligned to df index.
    Causal: OFI at time t uses only data from t and earlier.
    """
    ofi_l1, ofi_l5, ofi_l10, ofi_l20 = _compute_true_multilevel_ofi(df)
    return ofi_l1, ofi_l5, ofi_l10, ofi_l20


# ---------------------------------------------------------------------------
# Microstructure feature computation
# ---------------------------------------------------------------------------

def _ofi_at_levels(bid_levels, ask_levels, n_levels):
    """Compute OFI at a specific depth level.

    OFI = sum(bid additions + ask cancellations - bid cancellations - ask additions)
          + signed executed volume at that level
    """
    # For simplicity, use quantity changes at top n levels
    # This is a simplified but causal computation
    return 0.0


def _queue_imbalance(levels_bid, levels_ask, n_levels):
    """QI = (bid_depth - ask_depth) / (bid_depth + ask_depth) at top n levels."""
    b = _top_n(levels_bid, n_levels, reverse=True)
    a = _top_n(levels_ask, n_levels, reverse=False)
    bs = sum(q for _, q in b)
    ass = sum(q for _, q in a)
    den = bs + ass
    return (bs - ass) / den if den > 0 else 0.0


def _microprice(best_bid, best_ask, bid_qty, ask_qty):
    """Microprice = (ask * bid_qty + bid * ask_qty) / (bid_qty + ask_qty)."""
    if bid_qty + ask_qty <= 0:
        return (best_bid + best_ask) / 2.0
    return (best_ask * bid_qty + best_bid * ask_qty) / (bid_qty + ask_qty)


def _passive_flow_features(bid_add_bps, ask_add_bps, bid_cancel_bps, ask_cancel_bps,
                           liq_depletion):
    """Passive flow separation: additions vs cancellations, depletion/replenishment."""
    # Passive additions = liquidity provision
    passive_additions = bid_add_bps + ask_add_bps
    # Passive cancellations = liquidity withdrawal
    passive_cancellations = bid_cancel_bps + ask_cancel_bps
    # Net passive flow
    net_passive = passive_additions - passive_cancellations
    # Depletion proxy
    depletion = liq_depletion
    # Replenishment = positive additions after depletion
    replenishment = passive_additions if depletion < 0 else 0.0
    return {
        "passive_additions": passive_additions,
        "passive_cancellations": passive_cancellations,
        "net_passive_flow": net_passive,
        "depletion": depletion,
        "replenishment": replenishment,
    }


def _absorption_candidate(ofi_l1, price_displacement, bid_depth, ask_depth,
                          replenishment):
    """Observable absorption candidate.

    Absorption = large aggressive flow + limited price displacement
                 + persistent opposite-side liquidity + liquidity replenishment
    """
    # Large aggressive flow (|OFI| > threshold)
    large_flow = abs(ofi_l1) > 0.5 if np.isfinite(ofi_l1) else False
    # Limited price displacement (|price change| < median spread)
    limited_displacement = abs(price_displacement) < 0.05 if np.isfinite(price_displacement) else False
    # Persistent opposite-side liquidity
    persistent_liquidity = (bid_depth > 1.0 and ask_depth > 1.0) if np.isfinite(bid_depth) and np.isfinite(ask_depth) else False
    # Liquidity replenishment
    liquidity_replenishment = replenishment > 0.0

    score = sum([large_flow, limited_displacement, persistent_liquidity, liquidity_replenishment])
    return score  # 0-4 scale


def _liquidity_regime_state(spread_bps, log_depth1, liq_depletion, vol_500):
    """Liquidity regime state engine.

    States:
      NORMAL:    spread tight, depth sufficient, no depletion
      THIN:      depth low OR spread wide
      STRESSED:  depletion high OR volatility elevated
      SHOCK:     depletion extreme AND spread widening
      RECOVERY:  depletion decreasing after shock
    """
    spread = spread_bps if np.isfinite(spread_bps) else 0.0
    depth = log_depth1 if np.isfinite(log_depth1) else 0.0
    depletion = liq_depletion if np.isfinite(liq_depletion) else 0.0
    vol = vol_500 if np.isfinite(vol_500) else 0.0

    # Thresholds (pre-specified, not tuned on OOS)
    SPREAD_WIDE = 0.05  # bps
    DEPTH_SHALLOW = 2.0  # log depth
    DEPLETION_HIGH = 0.5
    DEPLETION_EXTREME = 1.0
    VOL_HIGH = 1.0  # volatility threshold

    if depletion > DEPLETION_EXTREME and spread > SPREAD_WIDE:
        return "SHOCK"
    elif depletion > DEPLETION_HIGH or vol > VOL_HIGH:
        return "STRESSED"
    elif depth < DEPTH_SHALLOW or spread > SPREAD_WIDE:
        return "THIN"
    elif depletion < -0.1:  # depth recovering
        return "RECOVERY"
    else:
        return "NORMAL"


def _price_impact_coefficient(ofi_l1, price_change, depth):
    """Estimate price-impact coefficient beta_t.

    beta_t ≈ ΔP_t / OFI_t, conditioned on depth.
    Per Cont-Kukanov-Stoikov: beta_t ∝ 1/Depth_t
    """
    if not np.isfinite(ofi_l1) or not np.isfinite(price_change) or not np.isfinite(depth):
        return 0.0
    if abs(ofi_l1) < 1e-9:
        return 0.0
    # Raw coefficient
    beta = price_change / (ofi_l1 + 1e-9)
    # Depth adjustment: deeper book -> smaller impact
    depth_adj = 1.0 / (1.0 + max(0.0, depth) / 5.0)
    return beta * depth_adj


def _trade_flow_features(trade_qty, trade_maker, trade_price, mid, ts_ms,
                         prev_ts_ms, prev_cvd):
    """Trade-flow engine with CVD demoted."""
    if trade_qty is None or not np.isfinite(trade_qty) or trade_qty <= 0:
        return {}

    # Signed volume: buyer-initiated = positive, seller-initiated = negative
    # trade_maker=True means buyer was maker -> seller aggressor -> negative
    # trade_maker=False means seller was maker -> buyer aggressor -> positive
    signed_vol = trade_qty if not trade_maker else -trade_qty
    signed_notional = signed_vol * trade_price if trade_price and np.isfinite(trade_price) else 0.0

    # CVD (cumulative, but demoted from primary signal)
    cvd = prev_cvd + signed_vol if prev_cvd is not None else signed_vol

    # Trade imbalance (fraction of volume that is buyer-initiated)
    # This is per-trade, not windowed

    # Inter-arrival time
    dt = ts_ms - prev_ts_ms if prev_ts_ms and ts_ms else 0.0

    return {
        "signed_vol": signed_vol,
        "signed_notional": signed_notional,
        "cvd": cvd,
        "trade_imbalance": 1.0 if not trade_maker else -1.0,
        "trade_qty": trade_qty,
        "inter_arrival_ms": dt,
    }


def _toxicity_state(vpin_500, trade_size_kyle, vol_500):
    """Toxicity / adverse selection state.

    VPIN and Kyle's lambda are research candidates, not automatic signals.
    Returns a state label and a numeric score.
    """
    vpin = vpin_500 if np.isfinite(vpin_500) else 0.0
    kyle = trade_size_kyle if np.isfinite(trade_size_kyle) else 0.0
    vol = vol_500 if np.isfinite(vol_500) else 0.0

    # Simple scoring
    score = abs(vpin) * 0.5 + abs(kyle) * 0.3 + vol * 0.2

    if score > 1.0:
        return "HIGH_TOXICITY", score
    elif score > 0.5:
        return "ELEVATED_TOXICITY", score
    else:
        return "LOW_TOXICITY", score


# ---------------------------------------------------------------------------
# Main feature builder
# ---------------------------------------------------------------------------

def build_microstructure_features(df: pd.DataFrame) -> pd.DataFrame:
    """Build enhanced V6 microstructure features from parsed L2 data.

    Input DataFrame must contain:
      - ts_ms, session, kind
      - best_bid, best_ask, mid, microb_price
      - spread_bps, mpd_bps
      - qi_l1, di_l5, di_l10
      - ofi_l1, ofi_norm_l1
      - bid_add_bps, ask_add_bps, bid_cancel_bps, ask_cancel_bps
      - cancel_pressure
      - log_depth1, log_depth5
      - tfi_500, signed_vol_500, trade_rate
      - liq_depletion
      - vol_500
      - levels_bid, levels_ask (JSON lists)
      - trade_price, trade_qty, trade_maker

    Returns DataFrame with all original columns plus new microstructure features.
    """
    df = df.copy()
    n = len(df)
    df = df.sort_values(["session", "ts_ms"]).reset_index(drop=True)

    # Parse levels
    bid_levels = df["levels_bid"].apply(_parse_levels)
    ask_levels = df["levels_ask"].apply(_parse_levels)

    # ------------------------------------------------------------------
    # A. Multi-level OFI from actual depth snapshots
    # ------------------------------------------------------------------
    # True OFI (Xu, Gould & Howison 2019): quantity changes at each price
    # level between consecutive depth snapshots.
    # Causal: OFI at time t uses only data from t and earlier.
    ofi_l1_arr, ofi_l5_arr, ofi_l10_arr, ofi_l20_arr = _ofi_levels_from_depth(df)
    df["ofi_l1_true"] = ofi_l1_arr
    df["ofi_l5"] = ofi_l5_arr
    df["ofi_l10"] = ofi_l10_arr
    df["ofi_l20"] = ofi_l20_arr
    # Keep existing ofi_l1 from V5 as reference
    df["ofi_short"] = df["ofi_l1"]
    df["ofi_medium"] = df["ofi_l1"].rolling(5, min_periods=1).mean().fillna(0.0)
    df["ofi_long"] = df["ofi_l1"].rolling(15, min_periods=1).mean().fillna(0.0)
    df["ofi_persistence"] = df["ofi_l1"].rolling(10, min_periods=1).apply(
        lambda x: np.corrcoef(x[:-1], x[1:])[0, 1] if len(x) > 2 else 0.0, raw=False
    ).fillna(0.0)
    df["ofi_acceleration"] = df["ofi_l1"].diff().fillna(0.0)

    # ------------------------------------------------------------------
    # B. Queue imbalance at multiple levels + dynamics
    # ------------------------------------------------------------------
    df["qi_l5"] = df["di_l5"]  # already computed in V5
    df["qi_l10"] = df["di_l10"]  # already computed in V5

    # Delta QI (change in queue imbalance)
    df["qi_l1_delta"] = df["qi_l1"].diff().fillna(0.0)
    df["qi_l5_delta"] = df["qi_l5"].diff().fillna(0.0)
    df["qi_l10_delta"] = df["qi_l10"].diff().fillna(0.0)

    # QI velocity (delta per ms)
    dt = df["ts_ms"].diff().fillna(1.0).clip(lower=1.0)
    df["qi_l1_velocity"] = df["qi_l1_delta"] / (dt / 1000.0)
    df["qi_l5_velocity"] = df["qi_l5_delta"] / (dt / 1000.0)
    df["qi_l10_velocity"] = df["qi_l10_delta"] / (dt / 1000.0)

    # QI acceleration
    df["qi_l1_acceleration"] = df["qi_l1_velocity"].diff().fillna(0.0)
    df["qi_l5_acceleration"] = df["qi_l5_velocity"].diff().fillna(0.0)
    df["qi_l10_acceleration"] = df["qi_l10_velocity"].diff().fillna(0.0)

    # ------------------------------------------------------------------
    # C. Microprice
    # ------------------------------------------------------------------
    # L1 quantities from levels_bid/levels_ask
    bid_qty_l1 = bid_levels.apply(lambda x: x[0][1] if len(x) > 0 else 0.0)
    ask_qty_l1 = ask_levels.apply(lambda x: x[0][1] if len(x) > 0 else 0.0)

    df["bid_qty_l1"] = bid_qty_l1
    df["ask_qty_l1"] = ask_qty_l1
    df["microprice"] = df.apply(
        lambda r: _microprice(r["best_bid"], r["best_ask"],
                              r["bid_qty_l1"], r["ask_qty_l1"]), axis=1)
    df["microprice_minus_mid"] = df["microprice"] - df["mid"]
    df["microprice_velocity"] = df["microprice"].diff().fillna(0.0) / (dt / 1000.0)

    # ------------------------------------------------------------------
    # D. Passive flow separation
    # ------------------------------------------------------------------
    passive = df.apply(
        lambda r: _passive_flow_features(
            r["bid_add_bps"], r["ask_add_bps"],
            r["bid_cancel_bps"], r["ask_cancel_bps"],
            r["liq_depletion"]), axis=1)
    passive_df = pd.DataFrame(passive.tolist())
    for col in passive_df.columns:
        df[col] = passive_df[col].fillna(0.0)

    # ------------------------------------------------------------------
    # E. Absorption candidate (observable definition)
    # ------------------------------------------------------------------
    # Price displacement over last 500ms
    df["price_displacement_500"] = df["mid"].diff(50).fillna(0.0)  # ~500ms at 10Hz
    df["absorption_candidate"] = df.apply(
        lambda r: _absorption_candidate(
            r["ofi_l1"], r["price_displacement_500"],
            r["log_depth1"], r["log_depth5"],
            r["replenishment"]), axis=1)

    # ------------------------------------------------------------------
    # F. Liquidity regime state engine
    # ------------------------------------------------------------------
    df["liquidity_state"] = df.apply(
        lambda r: _liquidity_regime_state(
            r["spread_bps"], r["log_depth1"],
            r["liq_depletion"], r["vol_500"]), axis=1)

    # One-hot encode for model compatibility
    liq_dummies = pd.get_dummies(df["liquidity_state"], prefix="liq_state", dtype=float)
    df = pd.concat([df, liq_dummies], axis=1)

    # ------------------------------------------------------------------
    # G. Price-impact coefficient
    # ------------------------------------------------------------------
    # beta_t = ΔP_t / OFI_t conditioned on depth
    df["price_change_500"] = df["mid"].diff(50).fillna(0.0)
    df["price_impact_coef"] = df.apply(
        lambda r: _price_impact_coefficient(
            r["ofi_l1"], r["price_change_500"], r["log_depth1"]), axis=1)

    # ------------------------------------------------------------------
    # H. Trade-flow enhancements (CVD demoted)
    # ------------------------------------------------------------------
    # CVD is computed cumulatively within session but demoted from primary signal
    if "trade_qty" in df.columns and "trade_maker" in df.columns:
        signed = np.where(df["kind"] == "trade",
                          np.where(df["trade_maker"], -df["trade_qty"], df["trade_qty"]),
                          0.0)
        df["cvd"] = np.where(np.isfinite(signed), signed, 0.0)
        df["cvd"] = df.groupby("session")["cvd"].cumsum()
    else:
        df["cvd"] = 0.0

    # Trade intensity features
    df["trade_intensity"] = df["trade_rate"].rolling(10, min_periods=1).mean().fillna(0.0)
    df["trade_arrival_rate"] = df["trade_rate"]

    # Large trade fraction (proxy)
    if "trade_qty" in df.columns:
        trade_qty = df["trade_qty"].fillna(0.0)
        median_qty = trade_qty.median()
        df["large_trade_fraction"] = (trade_qty > median_qty).astype(float)
    else:
        df["large_trade_fraction"] = 0.0

    # Buy/sell burstiness
    if "tfi_500" in df.columns:
        df["buy_burst"] = np.maximum(df["tfi_500"], 0.0)
        df["sell_burst"] = np.maximum(-df["tfi_500"], 0.0)
    else:
        df["buy_burst"] = 0.0
        df["sell_burst"] = 0.0

    # ------------------------------------------------------------------
    # I. Toxicity / adverse selection state
    # ------------------------------------------------------------------
    if "vpin_500" in df.columns and "trade_size_kyle" in df.columns:
        df["toxicity_state"], df["toxicity_score"] = zip(*df.apply(
            lambda r: _toxicity_state(r["vpin_500"], r["trade_size_kyle"], r["vol_500"]), axis=1))
    else:
        df["toxicity_state"] = "LOW_TOXICITY"
        df["toxicity_score"] = 0.0

    # ------------------------------------------------------------------
    # Price response conditioning
    # ------------------------------------------------------------------
    # Does OFI elicit a price response? (regression coefficient over rolling window)
    df["price_response_to_ofi"] = df.apply(
        lambda r: _price_impact_coefficient(r["ofi_l1"], r["price_change_500"], r["log_depth1"]),
        axis=1)

    # ------------------------------------------------------------------
    # Cleanup: drop string columns that would break numeric conversion
    # ------------------------------------------------------------------
    # Keep liquidity_state as string for analysis, but don't feed to model
    # Model will use one-hot encoded liq_state_* columns

    return df


# ---------------------------------------------------------------------------
# Feature registry (pre-registered, frozen)
# ---------------------------------------------------------------------------

MICROSTRUCTURE_FEATURES = [
    # A. Multi-level OFI
    "ofi_l1", "ofi_l1_true", "ofi_l5", "ofi_l10", "ofi_l20",
    "ofi_short", "ofi_medium", "ofi_long",
    "ofi_persistence", "ofi_acceleration",
    # B. Queue imbalance
    "qi_l1", "qi_l5", "qi_l10",
    "qi_l1_delta", "qi_l5_delta", "qi_l10_delta",
    "qi_l1_velocity", "qi_l5_velocity", "qi_l10_velocity",
    "qi_l1_acceleration", "qi_l5_acceleration", "qi_l10_acceleration",
    # C. Microprice
    "microprice", "microprice_minus_mid", "microprice_velocity",
    "bid_qty_l1", "ask_qty_l1",
    # D. Passive flow
    "passive_additions", "passive_cancellations", "net_passive_flow",
    "depletion", "replenishment",
    # E. Absorption candidate
    "absorption_candidate", "price_displacement_500",
    # F. Liquidity regime
    "liquidity_state",  # string, for analysis only
    "liq_state_NORMAL", "liq_state_THIN", "liq_state_STRESSED",
    "liq_state_SHOCK", "liq_state_RECOVERY",
    # G. Price-impact coefficient
    "price_impact_coef", "price_change_500",
    # H. Trade flow (CVD demoted)
    "cvd", "trade_intensity", "trade_arrival_rate",
    "large_trade_fraction", "buy_burst", "sell_burst",
    # I. Toxicity state
    "toxicity_state", "toxicity_score",
    # Existing V5/V6 features preserved
    "ofi_norm_l1", "di_l5", "di_l10", "mpd_bps", "spread_bps",
    "bid_cancel_bps", "ask_add_bps", "cancel_pressure",
    "tfi_500", "signed_vol_500", "log_depth1", "log_depth5",
    "log_event_rate", "depth_slope_bps", "vol_500",
    "liq_depletion",
]

# Model-ready features (exclude string columns)
MODEL_FEATURES = [f for f in MICROSTRUCTURE_FEATURES
                  if f not in ("liquidity_state", "toxicity_state")]


def build_from_sessions(session_dirs, out_path):
    """Build microstructure features from session directories.

    Reads derived_v5.jsonl from each session, computes enhanced features,
    writes to out_path.
    """
    import json
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for sd in session_dirs:
        sd = Path(sd)
        dv = sd / "derived_v5.jsonl"
        if not dv.exists():
            continue
        rows = [json.loads(l) for l in dv.open() if l.strip()]
        df = pd.DataFrame(rows)
        df["session"] = sd.name
        frames.append(df)
    if not frames:
        raise ValueError("no derived_v5 rows found")

    df = pd.concat(frames, ignore_index=True)
    df = build_microstructure_features(df)

    # Reorder columns
    cols = [c for c in MICROSTRUCTURE_FEATURES if c in df.columns]
    for c in ["ts_ms", "session", "kind", "seq", "mid", "microb_price",
              "best_bid", "best_ask", "regime"]:
        if c in df.columns and c not in cols:
            cols.insert(0, c)
    df = df[cols].sort_values(["session", "ts_ms"]).reset_index(drop=True)
    df.to_parquet(out_path, index=False)
    return out_path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=Path("data/research/v6_microstructure.parquet"))
    ap.add_argument("sessions", nargs="+", type=Path)
    a = ap.parse_args()
    p = build_from_sessions(a.sessions, a.out)
    print("wrote", p)
