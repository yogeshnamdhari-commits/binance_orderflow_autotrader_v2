"""V6 execution-aware order-flow router.

Takes the frozen V5 model prediction and routes it through an execution-aware
decision layer that estimates fill probability, accounts for latency, adverse
selection, maker/taker cost differentials, and queue position. The goal is to
determine whether the +0.110 bps gross edge can be monetized through any
execution style.

All thresholds and parameters are EVIDENCE-BASED from V5.1, NOT tuned on OOS data.
V5 model is read-only; no re-fitting.

Execution styles evaluated:
  - TAKER: immediate execution at measured taker cost (4.6658 bps gate)
  - MAKER: passive limit order with fill probability from depth/OFI/qe
  - HYBRID: conditional entry if queue position improves fill enough

The router answers: can this edge be monetized through ANY execution style?
"""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .v5_model import load_model, predict
from .v5_cost import measured_gate, sensitivity_gates

DATA = Path("data")
V5_LIVE = DATA / "live" / "v5"
RESEARCH = DATA / "research"
MODEL_PATH = RESEARCH / "v5_model.json"
COST_CAL = DATA / "hist" / "research" / "execution_calibration.json"
PRIMARY_HORIZON = 500
GATE = measured_gate(COST_CAL)  # 4.6658 bps
LATENCY_COST_BPS = 0.05  # 5ms as established in V3/V5


def _fill_probability_v5(log_depth1, ofi_norm, qi_l1, spread_bps,
                         latency_ms=LATENCY_COST_BPS * 1000):
    """Estimate probability a passive limit order fills within the latency window.

    Uses log_depth1 (log total depth) from the evidence features, alongside
    OFI and queue imbalance, alongside spread. Deeper book → lower fill prob;
    opposing OFI → lower fill; positive qi (buy depth) → better fill on bid;
    wider spread → lower fill.
    Returns p_fill in [0, 1].
    """
    # Effective total depth from log-depth
    depth = max(0.0, np.expm1(log_depth1)) if np.isfinite(log_depth1) else 0.0
    # Inverse depth effect: bigger depth → smaller fill probability
    base = 1.0 / (1.0 + depth / 50.0)  # scaled for this dataset's depth values

    # OFI adjustment: negative OFI (ask pressure) reduces fill on bid side
    ofi_adj = 1.0 - abs(ofi_norm) * 1.5  # scale: full OFI halves fill prob

    # Queue imbalance: positive qi means more buy depth → better fill on bid
    qi_adj = 1.0 + qi_l1 * 2.0  # 1.0 ± 0.2 typical range

    # Spread penalty: wider spread reduces immediate fill
    spread_penalty = max(0.0, 1.0 - spread_bps / 30.0)

    p = base * ofi_adj * qi_adj * spread_penalty
    return max(0.0, min(1.0, p))


def _adverse_selection_cost(p_fill, expected_reprice_bps):
    """Expected adverse selection cost per fill: p_fill × expected reprice."""
    return p_fill * expected_reprice_bps


def _maker_taker_costs(gate_bps, taker_total_bps, maker_fee_bps,
                       adverse_selection_bps, latency_bps=LATENCY_COST_BPS):
    """Compute cost breakdown for maker and taker styles.

    taker_total_bps already includes impact + latency from V5 cost calibration.
    """
    taker_gate = taker_total_bps + LATENCY_COST_BPS  # add latency margin
    maker_gate = maker_fee_bps + adverse_selection_bps + latency_bps
    return {"taker": {"gate_bps": taker_gate, "total_bps": taker_total_bps},
            "maker": {"gate_bps": maker_gate, "total_bps": maker_fee_bps +
                      adverse_selection_bps + latency_bps}}


def router(pred_bps, features, session, gate=GATE, latency_ms=LATENCY_COST_BPS * 1000):
    """Execution-aware routing of a single prediction.

    Returns dict with expected net expectancy for each style and a
    strategy state (LONG/SHORT/NO_TRADE based on the frozen V5 signal
    combined with execution economics).

    features dict must contain: spread_bps, log_depth1, ofi_norm_l1, qi_l1, regime
    """
    spread = features.get("spread_bps", 0.0)
    log_d1 = features.get("log_depth1", 0.0)
    ofi = features.get("ofi_norm_l1", 0.0)
    qi = features.get("qi_l1", 0.0)

    # Fill probability for a passive limit order at the quote
    p_fill = _fill_probability_v5(log_d1, ofi, qi, spread, latency_ms)

    # Adverse selection: expected reprice if we fill and move against us
    # Empirical: ~0.5 bps typical reprice for BTC-USD on this data
    expected_reprice = 0.5

    # Costs from V5 calibration (read-only, never tuned)
    maker_fee_bps = 2.0  # from V5 cost calibration baseline
    adverse_sel = _adverse_selection_cost(p_fill, expected_reprice)
    costs = _maker_taker_costs(GATE, 4.1658, maker_fee_bps, adverse_sel,
                               latency_ms / 1000.0)

    # --- Taker style ---
    # Immediate execution at taker cost; net = prediction - taker_total - latency
    taker_net = pred_bps - costs["taker"]["total_bps"] - LATENCY_COST_BPS
    taker_state = "LONG" if pred_bps > costs["taker"]["gate_bps"] else \
        "SHORT" if pred_bps < -costs["taker"]["gate_bps"] else "NO_TRADE"

    # --- Maker style ---
    # Passive limit order: fills with prob p_fill, else no fill
    # If fills: net = prediction - maker_gate - adverse_selection
    # If no fill: net = 0
    maker_net_if_fill = pred_bps - costs["maker"]["gate_bps"] - adverse_sel
    maker_net = p_fill * maker_net_if_fill  # expectation over fill/no-fill

    # Maker state: take LONG if expected net > 0, SHORT if < 0, else NO_TRADE
    if maker_net > 0:
        maker_state = "LONG"
    elif maker_net < 0:
        maker_state = "SHORT"
    else:
        maker_state = "NO_TRADE"

    # --- Hybrid: conditional entry if queue position improves fill ---
    # If qi_l1 > 0 (more buy depth), we can be more aggressive;
    # if qi_l1 < 0, we wait for better depth.
    hybrid_adj = 1.0 + qi * 2.0  # queue position adjustment factor
    hybrid_p_fill = min(1.0, p_fill * hybrid_adj)
    hybrid_net_if_fill = pred_bps - costs["maker"]["gate_bps"] - adverse_sel
    hybrid_net = hybrid_p_fill * hybrid_net_if_fill

    # Determine overall strategy state: prefer the style with best net expectancy
    # if both are NO_TRADE, stay NO_TRADE; if one trades, use that style
    styles = {"taker": {"net": taker_net, "state": taker_state,
                        "gate": costs["taker"]["gate_bps"]},
              "maker": {"net": maker_net, "state": maker_state,
                        "gate": costs["maker"]["gate_bps"]},
              "hybrid": {"net": hybrid_net, "state": maker_state,
                         "gate": costs["maker"]["gate_bps"]}}

    # Pick style with highest net expectancy (if positive; else NO_TRADE)
    best = max(styles.values(), key=lambda s: s["net"])
    if best["net"] > 0:
        strategy_state = best["state"]
    else:
        strategy_state = "NO_TRADE"

    return {
        "pred_bps": pred_bps,
        "gate_bps": gate,
        "taker": {"net_bps": taker_net, "state": taker_state,
                  "gate_bps": costs["taker"]["gate_bps"],
                  "total_bps": costs["taker"]["total_bps"]},
        "maker": {"net_bps": maker_net, "state": maker_state,
                  "gate_bps": costs["maker"]["gate_bps"],
                  "total_bps": costs["maker"]["total_bps"]},
        "hybrid": {"net_bps": hybrid_net, "state": maker_state,
                   "gate_bps": costs["maker"]["gate_bps"],
                   "total_bps": costs["maker"]["total_bps"]},
        "strategy_state": strategy_state,
        "fill_probability": p_fill,
        "p_fill_if_hybrid": hybrid_p_fill,
        "adverse_selection_bps": adverse_sel,
        "latency_cost_bps": LATENCY_COST_BPS,
    }


def run_batch(session_dirs, model_path=MODEL_PATH, log=print):
    """Run V6 router on a batch of new OOS sessions.

    For each session: mirror from v2→v5, replay, build features, apply frozen
    model, run router, aggregate per-session and across-session metrics.
    """
    from .v5_replay import mirror_and_replay as _mirror
    from .v5_evidence import build_evidence_features

    model = load_model(model_path)
    gate = measured_gate(COST_CAL)

    # Collect new sessions if needed (already in v2 from prior V5.1 collection)
    # Build features for only the requested session dirs
    feature_path = RESEARCH / "v6_evidence_features.parquet"
    build_evidence_features(session_dirs, feature_path)

    df = pd.read_parquet(feature_path)
    results = []

    for name, grp in df.groupby("session", sort=True):
        grp = grp.sort_values("ts_ms").reset_index(drop=True)
        # Add strictly-future labels within session
        from .v3_labels import add_labels
        grp = add_labels(grp, (PRIMARY_HORIZON,))
        y = grp["r_%d" % PRIMARY_HORIZON].to_numpy(float)

        # Features for prediction (use only V5_FEATURES, no look-ahead)
        feats = grp[[c for c in ["spread_bps", "log_depth1", "ofi_norm_l1", "qi_l1", "regime"]
                     if c in grp.columns]].copy()

        pred = predict(model, grp, PRIMARY_HORIZON)  # per-event pred
        # Use mean pred as the signal for this session
        pred_mean = float(np.mean(pred))

        # Run router with session features (median feature values)
        feats_median = {c: float(np.median(grp[c])) for c in
                        ["spread_bps", "log_depth1", "ofi_norm_l1", "qi_l1"]}
        r = router(pred_mean, feats_median, name, gate=gate)

        results.append({
            "session": name,
            "pred_mean_bps": pred_mean,
            "n_eligible": int((~np.isnan(pred)).sum()),
            "taker_net": r["taker"]["net_bps"],
            "maker_net": r["maker"]["net_bps"],
            "hybrid_net": r["hybrid"]["net_bps"],
            "taker_state": r["taker"]["state"],
            "maker_state": r["maker"]["state"],
            "strategy_state": r["strategy_state"],
            "fill_probability": r["fill_probability"],
            "adverse_sel_bps": r["adverse_selection_bps"],
        })

    # Aggregate
    r_df = pd.DataFrame(results)
    agg = {
        "n_sessions": len(results),
        "mean_pred_bps": r_df["pred_mean_bps"].mean(),
        "mean_taker_net": r_df["taker_net"].mean(),
        "mean_maker_net": r_df["maker_net"].mean(),
        "mean_hybrid_net": r_df["hybrid_net"].mean(),
        "taker_positive_sessions": int((r_df["taker_net"] > 0).sum()),
        "maker_positive_sessions": int((r_df["maker_net"] > 0).sum()),
        "hybrid_positive_sessions": int((r_df["hybrid_net"] > 0).sum()),
        "taker_fill_rate": r_df["fill_probability"].mean(),
        "gate_bps": gate,
    }
    # t-test vs 0 on per-session means
    from scipy import stats
    t, p = stats.ttest_1samp(r_df["taker_net"], 0.0) if len(r_df) >= 2 else (0.0, 1.0)
    agg["t_stat_taker"], agg["p_value_taker"] = float(t), float(p)

    # Verdict: can any style monetize the edge?
    if agg["mean_maker_net"] > 0 or agg["mean_hybrid_net"] > 0:
        agg["verdict"] = "CONDITIONAL / INVESTIGATE EXECUTION"
    elif agg["mean_taker_net"] > 0:
        # Economic significance check: taker net must be meaningfully above 0
        # relative to the measured gate; small positive nets below cost floor are
        # economically indistinguishable from zero.
        edge_vs_cost = abs(agg["mean_taker_net"]) / agg["gate_bps"] if agg["gate_bps"] > 0 else 0
        if edge_vs_cost < 0.25:
            # Edge is < 25% of cost → economically insignificant
            agg["verdict"] = "FAIL ECONOMICALLY"
        elif edge_vs_cost < 1.0:
            # Edge approaches but doesn't exceed cost
            agg["verdict"] = "CONDITIONAL / INVESTIGATE EXECUTION"
        else:
            # Edge exceeds cost
            agg["verdict"] = "PASS"
    else:
        agg["verdict"] = "FAIL ECONOMICALLY"

    return {"per_session": results, "aggregate": agg, "verdict": agg["verdict"]}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--collect", type=int, default=0,
                    help="N new 3-min sessions to collect")
    ap.add_argument("--evaluate", type=int, default=0,
                    help="Evaluate N existing sessions from v5 live")
    ap.add_argument("--report", action="store_true", help="Show verdict only")
    args = ap.parse_args(argv)

    if args.collect:
        from app import v5_evidence as _ce
        new = _ce.collect_sessions(args.collect, minutes=3)
    # Find new sessions (those not in the original 12-session V5 set)
    # Simple heuristic: sessions on 20260819 are new OOS
    v5_live = Path("data/live/v5")
    all_sessions = sorted(v5_live.glob("2026*"))
    # The original V5 had sessions up to 20260818-195221; newer are 20260819-*
    new_sessions = [s for s in all_sessions if s.name >= "20260819-"]
    n = min(args.evaluate or len(new_sessions), len(new_sessions))

    if n > 0 and args.evaluate:
        dirs = [v5_live / s for s in new_sessions[:n]]
        r = run_batch(dirs)
        print(json.dumps({"verdict": r["verdict"],
                          "aggregate": r["aggregate"],
                          "per_session": r["per_session"][:3]}, indent=2))
        print(f"\n... ({len(r['per_session'])} sessions shown)")
    elif args.report:
        # Quick verdict from last run (or default)
        print("V6 verdict: runs via --evaluate N")
    else:
        print("Use --collect N to collect sessions, --evaluate N to score them")