"""V5 economic report — robustness cells, cost sensitivity, verdict, JSON/MD.

Robustness is always evaluated on the SAME untouched OOS rows as the
scoreboard: stability of the gated net across (a) chronological halves of OOS,
(b) raw regime buckets, (c) trailing-vol terciles. Verdict binds to the
measured gate via the reused V2 engine.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from .v2_verdict import decide
from .v5_model import PRIMARY_HORIZON, predict, load_model
from .v5_validation import scoreboard, oos_frame
from .v5_cost import measured_gate, sensitivity_gates


def _terciles(x):
    """Quantile terciles without label-count failures on sparse finite data."""
    import numpy as np
    x = np.asarray(x, dtype=float)
    finite = np.isfinite(x)
    if finite.sum() < 30:
        return np.where(finite, "mid", "nan").astype(object)
    lo, hi = np.quantile(x[finite], [1 / 3, 2 / 3])
    out = np.empty(len(x), dtype=object)
    out[~finite] = "nan"
    out[finite] = np.where(x[finite] <= lo, "lo",
                           np.where(x[finite] <= hi, "mid", "hi"))
    return out


def robustness_cells(oos, pred, gate):
    r = oos
    half = np.where(r["ts_ms"] >= r["ts_ms"].median(), "second", "first")
    cells = []
    binned3 = _terciles(r["vol_500"].to_numpy(float))
    for label, mask in [("half", half),
                        ("regime", r["regime"].astype(str).to_numpy()),
                        ("vol_tercile", binned3)]:
        for k in sorted(set(mask)):
            sel = mask == k
            if not sel.any():
                continue
            pred_k = pred[sel]
            y = r["r_%d" % PRIMARY_HORIZON].to_numpy(float)[sel]
            gt = np.abs(pred_k) > gate
            gross = np.sign(pred_k) * y
            net = np.where(gt, gross - gate, 0.0)
            cells.append({"cell": "%s:%s" % (label, k), "n": int(sel.sum()),
                          "executed_n": int(gt.sum()),
                          "net_bps": float(net[gt].mean()) if gt.any() else 0.0,
                          "gross_bps": float(np.nanmean(gross))})
    return {"cells": cells, "n_cells": len(cells)}


def build_report(feature_path, model_path, cost_cal_path, out_path, log=print):
    feature_path = Path(feature_path)
    model = load_model(model_path)
    df, _ = oos_frame(feature_path, model)
    oos = df.loc[df.index.isin(df.index)]  # OOS rows are already isolated by oos_frame
    pred = predict(model, oos, PRIMARY_HORIZON)
    gate = measured_gate(cost_cal_path)
    sb = scoreboard(oos, pred, gate)
    rob = robustness_cells(oos, pred, gate)
    sensit = {}
    for name, g in sensitivity_gates(gate).items():
        s = scoreboard(oos, pred, g)
        sensit[name] = {"gate_bps": round(g, 4),
                        "gated_expectancy_bps": s["gated_expectancy_bps"],
                        "executed_rows": s["executed_rows"]}
    n_per = sb["per_direction"]
    oos_input = {
        "oos_periods": int(len(set(oos["session"]))),
        "long": {"n": n_per["LONG"]["n"]},
        "short": {"n": n_per["SHORT"]["n"]},
        "net_expectancy_taker_bps": sb["gated_expectancy_bps"],
        "net_expectancy_maker_bps": sb["gross_expectancy_bps"],
    }
    verdict = decide(oos_input, rob)
    report = {"generated_at": datetime.now(timezone.utc).isoformat(),
              "model_path": str(model_path), "feature_path": str(feature_path),
              "primary_horizon_ms": PRIMARY_HORIZON,
              "measured_gate_bps": round(gate, 4),
              "cost_calibration": str(cost_cal_path), "scoreboard": sb,
              "robustness": rob, "cost_sensitivity": sensit,
              "oos_input": oos_input, "verdict": verdict}
    out_path = Path(out_path)
    out_path.mkdir(parents=True, exist_ok=True)
    (out_path / "v5_verdict.json").write_text(json.dumps(report, indent=1))
    _write_md(report, out_path / "v5_verdict.md")
    log("verdict: %s | net_taker=%.4f gate=%.4f" % (
        verdict.get("verdict", verdict), sb["gated_expectancy_bps"], gate))
    return report


def _write_md(report, path):
    sb = report["scoreboard"]
    v = report["verdict"]
    lines = ["# V5 verdict", "",
             "- measured gate (1000 notional): %.4f bps" % report["measured_gate_bps"],
             "- verdict: **%s**" % (v.get("verdict", v) if isinstance(v, dict) else v),
             "",
             "## OOS scoreboard (h=%dms)" % report["primary_horizon_ms"],
             "| metric | value |", "|---|---|"]
    for k in ("oos_rows", "gross_dir_n", "executed_rows", "no_trade_rows",
              "gross_expectancy_bps", "gated_expectancy_bps", "pf", "sharpe",
              "max_drawdown_bps", "net_trail_n", "largest_session_share"):
        if k in sb:
            lines.append("| %s | %s |" % (k, sb[k]))
    for st, d in sb["per_direction"].items():
        lines.append("| %s n | %d |" % (st, d["n"]))
        lines.append("| %s net_bps | %.4f |" % (st, d["net_bps"]))
    lines += ["", "## Robustness cells", "| cell | n | executed | net_bps | gross_bps |"]
    for c in report["robustness"]["cells"]:
        lines.append("| %s | %d | %d | %.4f | %.4f |" % (c["cell"], c["n"],
                                                         c["executed_n"],
                                                         c["net_bps"], c["gross_bps"]))
    lines += ["", "## Cost sensitivity (bps)", "| gate | exp net bps | executed |"]
    for k, v in report["cost_sensitivity"].items():
        lines.append("| %s | %.4f | %d |" % (k, v["gated_expectancy_bps"],
                                             v["executed_rows"]))
    path.write_text("\n".join(lines) + "\n")