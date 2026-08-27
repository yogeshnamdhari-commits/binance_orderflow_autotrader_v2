"""V7 economic eligibility layer — conditional execution on expected net edge.

Takes the frozen V5 signal and routes it through an execution-aware decision
layer that estimates fill probability, adverse selection, latency, and costs,
and returns EXECUTE/NO_TRADE based on whether the expected net edge survives
actual execution costs. All thresholds are EVIDENCE-BASED from V5.1, NOT tuned
on OOS data. V5 model is read-only; no re-fitting.

The gate answers: Is there a subset of order-flow states where the expected
gross edge is sufficiently large and sufficiently executable to survive actual
costs?
"""

import numpy as np
from pathlib import Path

from .v5_model import load_model, predict
from .v5_cost import measured_gate
from .v5_evidence import build_evidence_features
from .v3_labels import add_labels

# — Constants (defined before any function that references them) —
LATENCY_COST_BPS = 0.05  # 5ms as established in V3/V5
DATA = Path("data")
V5_LIVE = DATA / "live" / "v5"
RESEARCH = DATA / "research"
MODEL_PATH = RESEARCH / "v5_model.json"
COST_CAL = DATA / "hist" / "research" / "execution_calibration.json"
PRIMARY_HORIZON = 500
GATE = measured_gate(COST_CAL)  # 4.6658 bps
ECONOMIC_EDGE_FRACTION = 0.25  # edge must be >25% of gate to be "meaningful"
MIN_FILL_PROBABILITY = 0.10
MIN_ELIGIBLE_SIGNALS = 50


def _fill_probability_v5(log_depth1, ofi_norm, qi_l1, spread_bps,
                         latency_ms=LATENCY_COST_BPS * 1000):
    """Estimate p_fill using log-depth, OFI, queue imbalance, spread."""
    depth = max(0.0, np.expm1(log_depth1)) if np.isfinite(log_depth1) else 0.0
    base = 1.0 / (1.0 + depth / 50.0)
    ofi_adj = 1.0 - abs(ofi_norm) * 1.5
    qi_adj = 1.0 + qi_l1 * 2.0
    spread_penalty = max(0.0, 1.0 - spread_bps / 30.0)
    p = base * ofi_adj * qi_adj * spread_penalty
    return float(max(0.0, min(1.0, p)))


def _adverse_selection_cost(p_fill, expected_reprice_bps=0.5):
    """Expected adverse selection cost per fill: p_fill × expected reprice."""
    return p_fill * expected_reprice_bps


def _maker_taker_costs(gate_bps, taker_total_bps, maker_fee_bps,
                       adverse_selection_bps, latency_bps=LATENCY_COST_BPS):
    """Compute cost breakdown for maker and taker styles (read-only)."""
    taker_gate = taker_total_bps + LATENCY_COST_BPS
    maker_gate = maker_fee_bps + adverse_selection_bps + latency_bps
    return {"taker": {"gate_bps": taker_gate, "total_bps": taker_total_bps},
            "maker": {"gate_bps": maker_gate, "total_bps": maker_fee_bps +
                      adverse_selection_bps + latency_bps}}


def economic_eligibility(pred_bps, features, gate=GATE,
                         edge_fraction=ECONOMIC_EDGE_FRACTION,
                         min_fill=MIN_FILL_PROBABILITY):
    """Determine whether the V5 signal is economically executable.

    Returns a dict with expected net edge for each style and final recommendation.
    """
    spread = features.get("spread_bps", 0.0)
    log_d1 = features.get("log_depth1", 0.0)
    ofi = features.get("ofi_norm_l1", 0.0)
    qi = features.get("qi_l1", 0.0)

    p_fill = _fill_probability_v5(log_d1, ofi, qi, spread)

    adverse_sel = _adverse_selection_cost(p_fill)
    costs = _maker_taker_costs(GATE, 4.1658, 2.0, adverse_sel, LATENCY_COST_BPS)

    edge_vs_cost = abs(pred_bps) / gate if gate > 0 else float("inf")

    # Taker: immediate execution at taker cost
    taker_net = pred_bps - costs["taker"]["total_bps"] - LATENCY_COST_BPS
    taker_state = "LONG" if pred_bps > costs["taker"]["gate_bps"] else \
        "SHORT" if pred_bps < -costs["taker"]["gate_bps"] else "NO_TRADE"

    # Maker: passive limit order with fill probability p_fill
    maker_net_if_fill = pred_bps - costs["maker"]["gate_bps"] - adverse_sel
    maker_net = p_fill * maker_net_if_fill
    if maker_net > 0:
        maker_state = "LONG"
    elif maker_net < 0:
        maker_state = "SHORT"
    else:
        maker_state = "NO_TRADE"

    # Hybrid: queue-position-adjusted fill probability
    hybrid_adj = 1.0 + qi * 2.0
    hybrid_p_fill = min(1.0, p_fill * hybrid_adj)
    hybrid_net_if_fill = pred_bps - costs["maker"]["gate_bps"] - adverse_sel
    hybrid_net = hybrid_p_fill * hybrid_net_if_fill

    # Economic eligibility assessment
    if edge_vs_cost < ECONOMIC_EDGE_FRACTION:
        recommendation = "NO_TRADE"
    elif edge_vs_cost < 1.0:
        if p_fill >= MIN_FILL_PROBABILITY and maker_net > 0:
            maker_rec_state = "LONG" if maker_net > 0 else "SHORT" if maker_net < 0 else "NO_TRADE"
        else:
            maker_rec_state = "NO_TRADE"
        if hybrid_p_fill >= MIN_FILL_PROBABILITY and hybrid_net > 0:
            hybrid_rec_state = "LONG" if hybrid_net > 0 else "SHORT" if hybrid_net < 0 else "NO_TRADE"
        else:
            hybrid_rec_state = "NO_TRADE"
        recommendation = "CONDITIONAL / INVESTIGATE EXECUTION"
    else:
        hybrid_rec_state = "LONG" if hybrid_net > 0 else "SHORT" if hybrid_net < 0 else "NO_TRADE"
        recommendation = "PASS"

    # If NO_TRADE, override style determinations
    if recommendation == "NO_TRADE":
        taker_state = maker_state = "NO_TRADE"
        hybrid_rec_state = "NO_TRADE"

    return {
        "pred_bps": float(pred_bps),
        "gate_bps": float(GATE),
        "edge_vs_cost_ratio": float(edge_vs_cost),
        "fill_probability": float(p_fill),
        "taker": {"net_bps": float(taker_net),
                  "state": taker_state,
                  "gate_bps": float(costs["taker"]["gate_bps"]),
                  "total_bps": float(costs["taker"]["total_bps"])},
        "maker": {"net_bps": float(maker_net),
                  "state": maker_state,
                  "gate_bps": float(costs["maker"]["gate_bps"]),
                  "total_bps": float(costs["maker"]["total_bps"])},
        "hybrid": {"net_bps": float(hybrid_net),
                   "state": hybrid_rec_state,
                   "gate_bps": float(costs["maker"]["gate_bps"]),
                   "total_bps": float(costs["maker"]["total_bps"])},
        "recommendation": recommendation,
        "edge_vs_cost_bps": float(edge_vs_cost * GATE),
    }


def _state_from_net(net_bps):
    """Convert net expectancy to LONG/SHORT/NO_TRADE."""
    if net_bps > 0:
        return "LONG"
    if net_bps < 0:
        return "SHORT"
    return "NO_TRADE"


def run_V7_evidence(n_sessions=10, minutes=3.0):
    """Full V7 evidence pipeline: collect → features → eligibility → verdict.

    Returns dict with verdict and all diagnostic fields.
    """
    # 1. Collect new independent sessions (3-min windows)
    from app import v5_evidence as _ce
    new = _ce.collect_sessions(n_sessions, minutes=minutes)
    if not new:
        return {"verdict": "INSUFFICIENT DATA", "reason": "no sessions collected"}

    # 2. Mirror into v5 live and replay with V4 engine
    from app import v5_replay as _replay
    mir = _ce.mirror_and_replay_new(new)

    # 3. Build causal V5 features for new sessions only
    sfeature = RESEARCH / "v7_evidence_features.parquet"
    build_evidence_features(mir, sfeature)

    # 4. Run economic eligibility on the features parquet
    from app.v3_labels import add_labels as _add_labels
    df = _add_labels(pd.read_parquet(sfeature), (PRIMARY_HORIZON,))

    # 5. Compute per-session metrics
    import scipy.stats as stats
    results = []
    for name, grp in df.groupby("session", sort=True):
        grp = grp.sort_values("ts_ms").reset_index(drop=True)
        y = grp["r_%d" % PRIMARY_HORIZON].to_numpy(float)
        finite = np.isfinite(y)
        if finite.sum() < MIN_ELIGIBLE_SIGNALS:
            results.append({"session": name,
                            "n_eligible": int(finite.sum()),
                            "recommendation": "INSUFFICIENT SIGNALS"})
            continue

        grp = grp.loc[finite]
        pred = float(np.mean(
            predict(load_model(MODEL_PATH), grp, PRIMARY_HORIZON)))
        feats = {c: float(np.median(grp[c])) for c in
                 ["spread_bps", "log_depth1", "ofi_norm_l1", "qi_l1"]}
        r = economic_eligibility(pred, feats, gate=GATE)
        r["session"] = name
        r["n_eligible"] = int(finite.sum())
        results.append(r)

    # 6. Aggregate across sessions
    valid = [r for r in results if r.get("n_eligible", 0) >= MIN_ELIGIBLE_SIGNALS]
    if not valid:
        return {"verdict": "INSUFFICIENT DATA",
                "reason": "fewer than %d eligible signals per session" % MIN_ELIGIBLE_SIGNALS}

    edge_ratios = np.array([r["edge_vs_cost_ratio"] for r in valid])
    taker_nets = np.array([r["taker"]["net_bps"] for r in valid])
    maker_nets = np.array([r["maker"]["net_bps"] for r in valid])
    hybrid_nets = np.array([r["hybrid"]["net_bps"] for r in valid])
    fill_probs = np.array([r["fill_probability"] for r in valid])
    n = len(valid)

    mean_edge = float(np.mean(edge_ratios))
    mean_taker_net = float(np.mean(taker_nets))
    mean_maker_net = float(np.mean(maker_nets))
    mean_hybrid_net = float(np.mean(hybrid_nets))
    mean_fill = float(np.mean(fill_probs))

    t_stat, p_val = stats.ttest_1samp(taker_nets, 0.0) if n >= 2 else (0.0, 1.0)

    # Economic gate verdict
    if mean_edge < ECONOMIC_EDGE_FRACTION:
        recommendation = "FAIL ECONOMICALLY"
    elif mean_edge < 1.0:
        recommendation = "CONDITIONAL / INVESTIGATE EXECUTION"
    else:
        recommendation = "PASS"

    return {
        "verdict": recommendation,
        "n_sessions": n,
        "mean_edge_vs_cost_ratio": mean_edge,
        "mean_taker_net_bps": mean_taker_net,
        "mean_maker_net_bps": mean_maker_net,
        "mean_hybrid_net_bps": float(np.mean(hybrid_nets)),
        "mean_fill_probability": mean_fill,
        "t_stat_taker": float(t_stat),
        "p_value_taker": float(p_val),
        "taker_positive_sessions": int(np.sum(taker_nets > 0)),
        "maker_positive_sessions": int(np.sum(maker_nets > 0)),
        "reason": _verdict_reason(recommendation=recommendation,
                                  edge_ratio=mean_edge,
                                  taker_net=mean_taker_net,
                                  gate=GATE),
    }


def _verdict_reason(recommendation, edge_ratio, taker_net, gate):
    """Produce human-readable verdict reason."""
    if recommendation == "PASS":
        return ("gross edge approaches/exceeds cost (edge/vs_cost=%.3f× gate=%.2f bps); "
                "positive net expectancy survives execution costs" %
                (edge_ratio, gate))
    elif recommendation == "CONDITIONAL / INVESTIGATE EXECUTION":
        return ("edge approaches cost but doesn't exceed it (edge/vs_cost=%.3f× gate=%.2f bps); "
                "maker/hybrid may be viable with adequate fill probability" %
                (edge_ratio, gate))
    elif recommendation == "FAIL ECONOMICALLY":
        return ("edge is far below cost (edge/vs_cost=%.3f× gate=%.2f bps); "
                "positive gross signal but net expectancy negative after execution costs" %
                (edge_ratio, gate))
    else:
        return "INSUFFICIENT DATA"