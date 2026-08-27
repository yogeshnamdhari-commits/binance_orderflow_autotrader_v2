"""V3 untouched-OOS validation scoreboard (chronological split only).

Applies the frozen v3_model.json to the UNTOUCHED OOS slice. Nothing is
re-estimated; no feature/threshold changes allowed after this runs.
Stop rule: if OOS net expectancy <= 0 on a sample large enough to conclude ->
STOP (no re-fitting). Writes v3_oos.json to the run dir.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .v3_cost import cost_model, load_cal, DEFAULT_NOTIONAL_USD
from .v3_labels import add_labels
from .v3_model import SPLIT_FRACTIONS, chrono_split_masks, load_model, predict
from .v3_features import PREDECLARED_HORIZONS_MS


def _score(label, pred, gate_bps, direction):
    pred = np.asarray(pred, dtype=float)
    label = np.asarray(label, dtype=float)
    sel = (pred > 0) & np.isfinite(label) if direction == "long" \
        else (pred < 0) & np.isfinite(label)
    if int(sel.sum()) == 0:
        return {"direction": direction, "n": 0}
    y = label[sel]
    gross = y if direction == "long" else -y
    net = gross - gate_bps
    wins = net[net > 0]
    losses = -net[net <= 0]
    pf = float(wins.sum() / losses.sum()) if losses.sum() > 0 \
        else (float("inf") if wins.sum() > 0 else 0.0)
    return {"direction": direction, "n": int(sel.sum()),
            "gross_mean_bps": round(float(gross.mean()), 6),
            "net_mean_bps": round(float(net.mean()), 6),
            "net_median_bps": round(float(np.median(net)), 6),
            "hit_rate": round(float((net > 0).mean()), 6),
            "profit_factor": pf}


def validate(model_path, cost_path, feature_path, out_dir, horizon_ms=500,
             style="taker", notional_usd=DEFAULT_NOTIONAL_USD):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model = load_model(model_path)
    cost = cost_model(load_cal(cost_path), notional_usd)
    gate = cost[style]["gate_bps"]
    df = add_labels(pd.read_parquet(feature_path))
    splits = chrono_split_masks(df)
    oos = df.loc[splits[2]["mask"]]

    pred = predict(model, oos, horizon_ms)
    label = oos["r_%d" % horizon_ms].to_numpy(float)
    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "model": str(model_path), "cost_calibration": str(cost_path),
        "style": style, "notional_usd": float(notional_usd),
        "horizon_ms": horizon_ms, "gate_bps": gate,
        "cost_model": cost,
        "split_fractions": list(SPLIT_FRACTIONS),
        "days": {s["name"]: {"lo_ms": int(df.loc[s["mask"], "ts_ms"].min()),
                             "hi_ms": int(df.loc[s["mask"], "ts_ms"].max()),
                             "rows": int(s["mask"].sum())} for s in splits},
        "blocks": {},
    }
    for name, spl in ((splits[1]["name"], df.loc[splits[1]["mask"]]),
                      (splits[2]["name"], oos)):
        p = predict(model, spl, horizon_ms)
        y = spl["r_%d" % horizon_ms].to_numpy(float)
        report["blocks"][name] = {
            "rows": int(len(spl)),
            "gross_expectancy_bps": round(float(np.nanmean(y * np.sign(p))), 6),
            "net_expectancy_bps": round(float(np.nanmean(y * np.sign(p) - gate)), 6),
            "long": _score(y, p, gate, "long"),
            "short": _score(y, p, gate, "short"),
        }
    oosb = report["blocks"]["oos"]
    long_n, short_n = oosb["long"]["n"], oosb["short"]["n"]
    net = oosb["net_expectancy_bps"]
    conclude = long_n >= 200 and short_n >= 200
    report["verdict"] = ("STOP" if (conclude and net <= 0)
                         else ("PASS" if conclude and net > 0
                               else "INSUFFICIENT"))
    (out_dir / "v3_oos.json").write_text(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=Path("data/research/v3_model.json"))
    ap.add_argument("--cost", type=Path,
                    default=Path("data/hist/research/execution_calibration.json"))
    ap.add_argument("--features", type=Path,
                    default=Path("data/research/v3_features.parquet"))
    ap.add_argument("--out", type=Path, default=Path("data/research"))
    ap.add_argument("--horizon-ms", type=int, default=500)
    ap.add_argument("--style", default="taker", choices=("taker", "maker"))
    ap.add_argument("--notional-usd", type=float, default=DEFAULT_NOTIONAL_USD)
    a = ap.parse_args()
    r = validate(a.model, a.cost, a.features, a.out, a.horizon_ms,
                 a.style, a.notional_usd)
    print(json.dumps({"verdict": r["verdict"],
                      "oos_net_expectancy_bps": r["blocks"]["oos"]["net_expectancy_bps"],
                      "long_n": r["blocks"]["oos"]["long"]["n"],
                      "short_n": r["blocks"]["oos"]["short"]["n"]}, indent=1))