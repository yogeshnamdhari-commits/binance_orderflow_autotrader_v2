"""V3 economic report — final cost-adjusted OOS gate + regime/absorption analysis.

Per predeclared horizon, using the FROZEN V3 model on the UNTOUCHED OOS slice:
  - per-direction gross and net expectancy under measured taker/maker costs
    with the predeclared safety margin
  - decision-state counts (LONG / SHORT / NO_TRADE per style)
  - robustness decomposition: time halves + descriptive regime buckets
    (thin_book / high_impact / normal) + absorption analysis (trade-flow
    tercile x realized move)
  - final verdict (PASS / CONDITIONAL PASS / FAIL) via v2_verdict
  - optional walk-forward diagnostic: the SAME ridge procedure re-estimated on
    expanding windows, block-by-block gross (stability research; NOT the frozen
    production model)

No parameter is fitted here; nothing measured feeds back into the model.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .v2_verdict import decide as verdict_decide
from .v3_cost import cost_model, load_cal, SAFETY_MARGIN_BPS, DEFAULT_NOTIONAL_USD
from .v3_labels import add_labels
from .v3_model import SPLIT_FRACTIONS, chrono_split_masks, load_model, predict
from .v3_features import MODEL_FEATURES, PREDECLARED_HORIZONS_MS
from .v3_model import RIDGE_ALPHA
from .v3_model import fit_horizon

REGIMES = ("normal", "thin_book", "high_impact")


def _stats(net):
    net = np.asarray(net, dtype=float)
    out = {"n": int(len(net))}
    if not len(net):
        return out
    sd = net.std(ddof=1) if len(net) > 1 else 0.0
    w = net[net > 0].sum()
    l = -net[net < 0].sum()
    pf = float(w / l) if l > 0 else (float("inf") if w > 0 else 0.0)
    out.update({"net_mean_bps": float(net.mean()),
                "net_median_bps": float(np.median(net)),
                "win_rate": float((net > 0).mean()),
                "profit_factor": pf,
                "t_stat": float(net.mean() / (sd / np.sqrt(len(net)))) if sd > 0
                else None})
    return out


def _dir_stats(sign, gross_label, gate_bps):
    y = np.asarray(gross_label, dtype=float)
    net = (y - gate_bps) if sign > 0 else (-y - gate_bps)
    return _stats(net)


def _summarize(label, pred, gate_bps):
    pred = np.asarray(pred, dtype=float)
    label = np.asarray(label, dtype=float)
    ok = np.isfinite(label) & np.isfinite(pred)
    label, pred = label[ok], pred[ok]
    side = np.sign(pred)
    long_n = int((side > 0).sum())
    short_n = int((side < 0).sum())
    net_all = np.concatenate([label[side > 0] - gate_bps,
                              -label[side < 0] - gate_bps]) \
        if (long_n + short_n) else np.array([])
    return {"signals": int((side != 0).sum()),
            "long": _dir_stats(1, label[side > 0], gate_bps),
            "short": _dir_stats(-1, label[side < 0], gate_bps),
            "gross_expectancy_bps": float(np.mean(label * side)),
            "net_expectancy_bps": float(np.mean(net_all)) if len(net_all) else None}


def _states(pred, gate_bps):
    from collections import Counter
    c = Counter()
    for p in pred:
        net_l = p - gate_bps
        net_s = -p - gate_bps
        if net_l > 0 or net_s > 0:
            c["LONG" if net_l >= net_s else "SHORT"] += 1
        else:
            c["NO_TRADE"] += 1
    return dict(c)


def _bucket_rows(oos, name_mask_pairs, label, pred, gate_bps):
    cells = []
    for name, m in name_mask_pairs:
        m = np.asarray(m, dtype=bool) & np.isfinite(label) & np.isfinite(pred)
        if not m.any():
            cells.append({"name": name, "n": 0})
            continue
        side = np.sign(pred[m])
        net = label[m] * side - gate_bps
        cells.append({"name": name, "n": int(m.sum()),
                      "net_mean_bps": float(np.mean(net)),
                      "gross_mean_bps": float(np.mean(label[m] * side))})
    return cells


def horizon_report(model_d, df, train_mask, oos_mask, h, cost, notional):
    oos = df.loc[oos_mask]
    pred = predict(model_d, oos, h)
    label = oos["r_%d" % h].to_numpy(float)

    out = {"horizon_ms": h}
    for style in ("taker", "maker"):
        gate = cost[style]["gate_bps"]
        out[style] = _summarize(label, pred, gate)
        out[style]["decision_states"] = _states(pred, gate)
        out[style]["gate_bps"] = gate

    ts = oos["ts_ms"].to_numpy(float)
    lo, hi = ts.min(), ts.max()
    half = (hi - lo) / 2.0
    halves = [("time_block_0", (ts >= lo) & (ts < lo + half)),
              ("time_block_1", (ts >= lo + half) & (ts <= hi))]
    regimes = [(rg, (oos["regime"] == rg).to_numpy()) for rg in REGIMES]
    gate_t = cost["taker"]["gate_bps"]
    out["robustness_cells"] = _bucket_rows(
        oos, halves + regimes, label, pred, gate_t)

    # absorption: trade-flow terciles x realized gross
    tfi = oos["tfi_500"].to_numpy(float)
    q = np.nanpercentile(tfi, [33.33, 66.67])
    tf_buckets = [("tfi_low_buy", tfi > q[1]),
                  ("tfi_mid", (tfi >= q[0]) & (tfi <= q[1])),
                  ("tfi_high_sell", tfi < q[0])]
    out["absorption_cells"] = _bucket_rows(oos, tf_buckets, label, pred, gate_t)
    out["oos_n"] = int(len(oos))
    return out


def build_report(args, model_d, df, cost):
    masks = chrono_split_masks(df)
    train_mask, val_mask, oos_mask = (m["mask"] for m in masks)
    oos = df.loc[oos_mask]
    periods = int(oos["session"].nunique()) if "session" in oos else 1

    horizons = {}
    for h in args.horizons:
        horizons[str(h)] = horizon_report(model_d, df, train_mask, oos_mask,
                                          h, cost, args.notional_usd)

    # verdict uses predeclared primary horizon (500ms), taker style
    primary = horizons[str(args.primary_horizon)]["taker"]
    verdict_in = {
        "oos_periods": periods,
        "long": primary["long"], "short": primary["short"],
        "net_expectancy_taker_bps":
            horizons[str(args.primary_horizon)]["taker"]["net_expectancy_bps"],
        "net_expectancy_maker_bps":
            horizons[str(args.primary_horizon)]["maker"]["net_expectancy_bps"],
    }
    cell_blocks = {"cells": [c for h in horizons.values()
                             for c in h["robustness_cells"]]}
    verdict = verdict_decide(verdict_in, cell_blocks)

    walk = None
    if args.walk_forward:
        walk = walk_forward(df, args.horizons, cost)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": {"path": str(args.model), "train_rows": int(train_mask.sum()),
                  "oos_rows": int(oos_mask.sum()), "oos_periods": periods},
        "cost_model": cost,
        "safety_margin_bps": SAFETY_MARGIN_BPS,
        "horizons": horizons,
        "verdict": verdict,
        "walk_forward": walk,
    }


def walk_forward(df, horizons, cost, block=2500):
    """Diagnostic only: refit the SAME ridge on expanding windows, report gross
    and net per block. NOT the frozen production model."""
    idx = df.index.to_numpy()
    blocks = []
    t_mask = np.zeros(len(df), dtype=bool)
    for start in range(0, len(df), block):
        end = min(start + block, len(df))
        t_mask |= (np.arange(len(df)) >= start) & (np.arange(len(df)) < end)
        eos = (np.arange(len(df)) >= end)
        if eos.sum() < 50:
            break
        Xtr = df[MODEL_FEATURES].to_numpy(float)
        for h in horizons:
            ytr = df["r_%d" % h].to_numpy(float)
            beta, b0, mu, sd, r2, n = fit_horizon(
                Xtr[t_mask], ytr[t_mask], alpha=RIDGE_ALPHA)
            Xe = Xtr[eos]
            Ze = (Xe - mu) / sd
            Ze = np.where(np.isfinite(Ze), Ze, 0.0)
            pred = b0 + Ze @ beta
            lab = ytr[eos]
            ok = np.isfinite(lab)
            b = {"block_ofs": start, "rows": int(eos.sum()), "horizon_ms": h,
                 "gross_bps": float(np.mean(lab[ok] * np.sign(pred[ok])))}
            b["net_taker_bps"] = b["gross_bps"] - cost["taker"]["gate_bps"]
            blocks.append(b)
    return blocks


def write_report(out_path, report):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=1, default=str))
    return out_path


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path, default=Path("data/research/v3_features.parquet"))
    ap.add_argument("--model", type=Path, default=Path("data/research/v3_model.json"))
    ap.add_argument("--cost-cal", type=Path,
                    default=Path("data/hist/research/execution_calibration.json"))
    ap.add_argument("--horizons", default="250,500,1000")
    ap.add_argument("--primary-horizon", type=int, default=500)
    ap.add_argument("--notional-usd", type=float, default=DEFAULT_NOTIONAL_USD)
    ap.add_argument("--walk-forward", action="store_true")
    ap.add_argument("--out", type=Path, default=Path("data/research/V3_ECONOMIC_REPORT.json"))
    a = ap.parse_args()
    a.horizons = tuple(int(x) for x in a.horizons.split(","))
    df = add_labels(pd.read_parquet(a.features), horizons=a.horizons)
    model_d = load_model(a.model)
    cost = cost_model(load_cal(a.cost_cal), a.notional_usd)
    report = build_report(a, model_d, df, cost)
    p = write_report(a.out, report)
    print("wrote", p)
    print("verdict:", report["verdict"]["verdict"])
    for h, hr in report["horizons"].items():
        t = hr["taker"]
        print("H=%4sms gross=%+.4f net_taker=%+.4f net_maker=%+.4f "
              "LONG=%d SHORT=%d NO_TRADE=%d" % (
                  h, t["gross_expectancy_bps"], t["net_expectancy_bps"],
                  hr["maker"]["net_expectancy_bps"],
                  t["decision_states"].get("LONG", 0),
                  t["decision_states"].get("SHORT", 0),
                  t["decision_states"].get("NO_TRADE", 0)))


if __name__ == "__main__":
    main()