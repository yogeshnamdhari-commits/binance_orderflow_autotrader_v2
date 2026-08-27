"""V2 Phase-6 untouched-OOS validation scoreboard.

The frozen v2_model.json (trained on the predeclared TRAINING slice only) is
applied to the UNTOUCHED OOS slice. Nothing is re-estimated, no feature or
threshold changes are allowed after this runs.

Scoreboard follows v2_PROTOCOL.md section 5:
  gross expectancy, net expectancy, profit factor, median, 5th percentile,
  long and short independently, spread/slippage/adverse-selection costs
  reported as measured components.

Stop rule: if OOS net expectancy <= 0 -> STOP (protocol section 8). The
scoreboard is recorded verbatim in v2_oos.json; the validation slice scoreboard
is also reported but never used for tuning.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .v2_cost_gate import DEFAULT_CAL_PATH, DEFAULT_NOTIONAL_USD, decide, net_edges
from .v2_features import LABEL_HORIZONS_MS
from .v2_labels import add_labels
from .v2_model import SPLIT_FRACTIONS, chrono_split_masks, load_model, predict


def _day(ms):
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).strftime("%Y-%m-%d")


def _score(frame, pred, label, cost_bps, direction):
    pred = np.asarray(pred)
    label = np.asarray(label, dtype=float)
    if direction == "long":
        sel = (pred > 0) & np.isfinite(label)
    else:
        sel = (pred < 0) & np.isfinite(label)
    if int(sel.sum()) == 0:
        return {"direction": direction, "n": 0}
    p = pred[sel]
    y = label[sel]
    net = y - cost_bps
    wins = net[net > 0]
    losses = -net[net <= 0]
    pf = float(wins.sum() / losses.sum()) if losses.sum() > 0 else (float("inf") if wins.sum() > 0 else 0.0)
    return {
        "direction": direction, "n": int(sel.sum()),
        "gross_mean_bps": round(float(y.mean()), 6),
        "gross_median_bps": round(float(np.median(y)), 6),
        "gross_p5_bps": round(float(np.percentile(y, 5)), 6),
        "net_mean_bps": round(float(net.mean()), 6),
        "net_median_bps": round(float(np.median(net)), 6),
        "net_p5_bps": round(float(np.percentile(net, 5)), 6),
        "hit_rate": round(float((net > 0).mean()), 6),
        "profit_factor": pf,
        "pred_mean_bps": round(float(p.mean()), 6),
        "pred_p90_bps": round(float(np.percentile(np.abs(p), 90)), 6),
    }


def validate(model_path, cost_path, feature_path, out_dir,
             horizon_ms=500, notional_usd=DEFAULT_NOTIONAL_USD, style="taker"):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model = load_model(model_path)
    cal = json.load(open(cost_path))
    df = pd.read_parquet(feature_path)
    df = add_labels(df, horizons=LABEL_HORIZONS_MS)
    splits = chrono_split_masks(df)
    train = df.loc[splits[0]["mask"]]
    val = df.loc[splits[1]["mask"]]
    oos = df.loc[splits[2]["mask"]]

    e = net_edges(0.0, cal, notional_usd, style)
    cost_bps = e["cost_bps"]

    label_col = "r_%d" % horizon_ms
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": str(model_path), "cost_calibration": str(cost_path),
        "style": style, "notional_usd": float(notional_usd),
        "horizon_ms": horizon_ms, "cost_bps": cost_bps,
        "cost_components": e["components"],
        "split_fractions": list(SPLIT_FRACTIONS),
        "label_available": int(df[label_col].notna().sum()),
        "days": {"train": _day(train["ts_ms"].min()), "train_end": _day(train["ts_ms"].max()),
                 "oos": _day(oos["ts_ms"].min()), "oos_end": _day(oos["ts_ms"].max())},
        "blocks": {},
    }
    for name, spl in (("validation", val), ("oos", oos)):
        pred = predict(model, spl, horizon_ms)
        label = spl[label_col].to_numpy(float)
        block = {
            "rows": int(len(spl)), "label_n": int(np.isfinite(label).sum()),
            "gross_expectancy_bps": round(float(np.nanmean(label)), 6),
            "net_expectancy_bps": round(float(np.nanmean(label - cost_bps)), 6),
            "spread_cost_bps": cal.get("spread", {}).get("p90_bps"),
            "slippage_cost_bps": cal.get("slippage_by_notional", {})
                                  .get(str(int(notional_usd)), {}).get("buy_p90_bps"),
            "long": _score(spl, pred, label, cost_bps, "long"),
            "short": _score(spl, pred, label, cost_bps, "short"),
        }
        valid = np.isfinite(label) & np.isfinite(pred)
        net = label - cost_bps
        block["net_p5_bps"] = round(float(np.percentile(net[valid], 5)), 6)
        block["profit_factor_top50"] = None
        report["blocks"][name] = block

    oosb = report["blocks"]["oos"]
    report["verdict"] = "PASS" if oosb.get("net_expectancy_bps", 0) > 0 else "STOP"
    report["stop_rule"] = ("OOS net expectancy <= 0 => STOP, no re-fitting; "
                           "protocol section 8")
    out = out_dir / "v2_oos.json"
    out.write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=Path("data/hist/research/v2_model.json"))
    ap.add_argument("--cost", type=Path, default=DEFAULT_CAL_PATH)
    ap.add_argument("--features", type=Path, default=Path("data/hist/research/v2_features.parquet"))
    ap.add_argument("--out", type=Path, default=Path("data/hist/research"))
    ap.add_argument("--horizon-ms", type=int, default=500)
    ap.add_argument("--notional-usd", type=float, default=DEFAULT_NOTIONAL_USD)
    ap.add_argument("--style", default="taker", choices=("taker", "maker"))
    a = ap.parse_args()
    r = validate(a.model, a.cost, a.features, a.out, a.horizon_ms, a.notional_usd, a.style)
    print(json.dumps({"verdict": r["verdict"],
                      "oos_net_expectancy_bps": r["blocks"]["oos"]["net_expectancy_bps"],
                      "long": r["blocks"]["oos"]["long"],
                      "short": r["blocks"]["oos"]["short"]}, indent=1))