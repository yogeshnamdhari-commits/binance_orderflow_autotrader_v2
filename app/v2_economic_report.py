"""V2 economic evaluation / final report (Task 8).

Applies the PASS-locked model and measured cost calibration to the fully-HIDDEN
OOS slice, tabulates per-direction gross and net (post-cost) expectancy,
latency, spread and slippage distributions, then folds in robustness (Task 9)
and the final verdict (Task 10).

All outcomes are REPORTED from the OOS slice only. No parameter is fitted
here; nothing measured here may feed back into the model.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .v2_model import load_model, predict, MODEL_FEATURES
from .v2_cost_gate import decide, taker_cost_bps, maker_cost_bps, DEFAULT_CAL_PATH
from . import v2_robustness
from . import v2_verdict


def _stats(net):
    net = np.asarray(net, dtype=float)
    out = {"n": int(len(net))}
    if not len(net):
        return out
    sd = net.std(ddof=1) if len(net) > 1 else 0.0
    out.update({
        "net_mean_bps": float(net.mean()),
        "net_median_bps": float(np.median(net)),
        "win_rate": float((net > 0).mean()),
        "expectancy_bps": float(net.mean()),
        "profit_factor": _profit_factor(net),
        "net_std_bps": float(sd),
        "t_stat": float(net.mean() / (sd / np.sqrt(len(net)))) if sd > 0 else None,
        "per_trade_sharpe": float(net.mean() / sd) if sd > 0 else None,
        "max_drawdown_bps": _max_drawdown(net),
    })
    return out


def _profit_factor(net):
    w = net[net > 0].sum()
    l = -net[net < 0].sum()
    if l <= 0:
        return float("inf") if w > 0 else None
    return float(w / l)


def _max_drawdown(net):
    cum = np.cumsum(net)
    peak = np.maximum.accumulate(cum)
    dd = cum - peak
    return float(dd.min())


def _direction_stats(sign_mask, label, cost_bps):
    label = np.asarray(label, dtype=float)
    if sign_mask > 0:
        net = label - cost_bps
    elif sign_mask < 0:
        net = -label - cost_bps
    else:
        net = np.array([])
    return _stats(net)


def _summarize(label, pred, cost_bps):
    label = np.asarray(label, dtype=float)
    pred = np.asarray(pred, dtype=float)
    ok = np.isfinite(label) & np.isfinite(pred)
    label, pred = label[ok], pred[ok]
    side = np.sign(pred)
    long_n = int((side > 0).sum())
    short_n = int((side < 0).sum())
    tot = long_n + short_n
    long = _direction_stats(1, label[side > 0], cost_bps)
    short = _direction_stats(-1, label[side < 0], cost_bps)
    net = np.concatenate([label[side > 0] - cost_bps,
                          -label[side < 0] - cost_bps]) if tot else np.array([])
    return {
        "long": long, "short": short,
        "net_expectancy_bps": float(net.mean()) if len(net) else None,
        "gross_expectancy_bps": float(np.mean(np.abs(side) * label)) if len(label) else None,
        "signals": tot,
    }


def build_report(args, features_df, model_d):
    oos = features_df.iloc[args.train_n:]
    train_df = features_df.iloc[:args.train_n]

    pred = predict(model_d, oos, args.horizon_ms)
    oos_pred_np = np.asarray(pred, dtype=float)
    label_np = oos["r_%d" % args.horizon_ms].to_numpy(float)

    cal = json.load(open(args.cost_cal))
    cost_taker = taker_cost_bps(cal, args.notional_usd)
    cost_maker, maker_comp = maker_cost_bps(cal)

    taker = _summarize(label_np, oos_pred_np, cost_taker)
    maker = _summarize(label_np, oos_pred_np, cost_maker)

    oos_np = {
        "pred": oos_pred_np,
        "label": label_np,
        "r_250": oos["r_250"].to_numpy(float),
        "ts": oos["ts_ms"].to_numpy(np.float64),
        "liquidity": oos["log_depth10"].to_numpy(float),
        "spread_bps": oos["spread_bps"].to_numpy(float),
    }
    train_np = {
        "label": train_df["r_%d" % args.horizon_ms].to_numpy(float),
        "r_250": train_df["r_250"].to_numpy(float),
        "ts": train_df["ts_ms"].to_numpy(np.float64),
        "liquidity": train_df["log_depth10"].to_numpy(float),
        "spread_bps": train_df["spread_bps"].to_numpy(float),
    }
    robustness = v2_robustness.evaluate(oos_np, train_np,
                                        {"taker_bps": cost_taker})

    verdict_in = {
        "oos_periods": args.oos_periods,
        "long": taker["long"], "short": taker["short"],
        "net_expectancy_taker_bps": taker["net_expectancy_bps"],
        "net_expectancy_maker_bps": maker["net_expectancy_bps"],
    }
    verdict = v2_verdict.decide(verdict_in, robustness)

    spread = oos_np["spread_bps"]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": {"run": str(args.rundir), "id": model_d.get("id"),
                  "train_n": len(train_df), "oos_n": len(oos)},
        "horizon_ms": args.horizon_ms,
        "notional_usd": args.notional_usd,
        "costs_bps": {"taker_rt": cost_taker, "maker_rt": cost_maker,
                      "maker_components": maker_comp},
        "taker": taker, "maker": maker,
        "decision_state_counts": _states(oos_pred_np, cal, args.notional_usd),
        "robustness": robustness,
        "verdict": verdict,
        "distributions": {
            "spread_bps_p50": float(np.percentile(spread, 50)),
            "spread_bps_p90": float(np.percentile(spread, 90)),
            "spread_bps_p99": float(np.percentile(spread, 99)),
            "spread_n": int(len(spread)),
        },
    }


def _states(pred, cal, notional_usd):
    from collections import Counter
    c = Counter()
    for p in pred:
        c[decide(float(p), cal, notional_usd, "taker")["state"]] += 1
    return dict(c)


def write_report(out_path, report):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=1, default=str))
    return out_path


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--rundir", type=Path, default=Path("data/hist/research"))
    ap.add_argument("--features", type=Path,
                    default=Path("data/hist/research/v2_features.parquet"))
    ap.add_argument("--labels", type=Path,
                    default=Path("data/hist/research/v2_labels.parquet"))
    ap.add_argument("--model", type=Path,
                    default=Path("data/hist/research/v2_model.json"))
    ap.add_argument("--cost-cal", type=Path, default=DEFAULT_CAL_PATH)
    ap.add_argument("--horizon-ms", type=int, default=500)
    ap.add_argument("--train-n", type=int, default=None,
                    help="explicit OOS cut row; default from model splits train_n")
    ap.add_argument("--oos-periods", type=int, default=3)
    ap.add_argument("--notional-usd", type=float, default=1000.0)
    ap.add_argument("--out", type=Path,
                    default=Path("data/hist/research/V2_ECONOMIC_REPORT.json"))
    a = ap.parse_args()

    fdf = pd.read_parquet(a.features)
    if a.labels and a.labels.exists():
        labs = pd.read_parquet(a.labels).drop_duplicates(["session", "ts_ms"])
        fdf = fdf.merge(labs, on=["session", "ts_ms"],
                        how="left", suffixes=("", "_l"))
        fdf = fdf.loc[:, ~fdf.columns.str.endswith("_l")]
    model_d = load_model(a.model)
    if a.train_n is None:
        cut = int(model_d["splits"]["train"]["hi_ms"])
        a.train_n = int((fdf["ts_ms"] <= cut).sum())
    df = fdf
    report = build_report(a, df, model_d)
    p = write_report(a.out, report)
    print(p, "written")
    print(json.dumps({k: report[k] for k in ("verdict",)}, indent=1))


if __name__ == "__main__":
    main()