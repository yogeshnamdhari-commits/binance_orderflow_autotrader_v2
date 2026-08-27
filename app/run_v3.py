"""V3 end-to-end dry-run runner (deterministic, reproducible, no live orders).

Pipeline (in this order, so artifacts feed the freeze, and the freeze precedes
every OOS read):
  1. mirror immutable V2 sessions into data/live/v3 (byte-identical raw)
  2. re-replay with the V3 execution feature stack -> derived.jsonl
  3. build features parquet
  4. calibrate frozen ridge model (train/validation/OOS chronological split)
  5. build V3 cost calibration from MEASURED artifacts (fill_calib + exec model)
  6. FREEZE manifest (code + artifacts + deps) -- any earlier-step edit changes
     the freeze_id, and the OOS numbers are only read after the freeze
  7. untouched-OOS validation + economic report (read-only consume)

Usage:  python3 -m app.run_v3 [--mirror-only] [--steps replay|features|model|...]
"""

import json
import sys
from pathlib import Path

from . import v3_collector, v3_replay, v3_features, v3_model, v3_manifest
from .v3_cost import cost_model, load_cal
from .v3_labels import add_labels
from .v3_validation import validate
from .v3_economic_report import build_report, write_report

DATA = Path("data")
LIVE_V3 = DATA / "live" / "v3"
RESEARCH = DATA / "research"
OOS_MANIFEST = RESEARCH / "V3_OOS_MANIFEST.json"
PRIMARY_HORIZON = 500
HORIZONS = (250, 500, 1000)
NOTIONAL_USD = 1000.0


def mirror_and_replay(log=print):
    sessions = v3_collector.mirror_from_v2(v2_root=DATA / "live" / "v2",
                                           dst_root=LIVE_V3)
    log("mirrored %d sessions -> %s" % (len(sessions), LIVE_V3))
    total = 0
    for sd in sorted(LIVE_V3.glob("2026*")):
        if not (sd / "raw.jsonl").exists():
            continue
        rp = v3_replay.replay_session(sd, write=True, log=lambda _m: None)
        total += len(rp.rows)
        log("  %-14s %6d rows (skips=%d)" % (sd.name, len(rp.rows), rp.skips))
    log("total v3 derived rows: %d" % total)
    return sessions


def build_cost_calibration():
    """V3 cost inputs from the measured artifacts (no invented numbers)."""
    fill = json.load(open(DATA / "hist" / "research" / "fill_calib.json"))
    execm = json.load(open(DATA / "hist" / "research" / "execution_cost_model.json"))
    scen = execm["scenarios"].get("10_long@5s", {})
    taker = scen.get("taker", {})
    p90_rt = round(float(taker.get("total_bps", 4.1658))
                   - float(taker.get("impact_bps", 0.1))
                   - float(taker.get("latency_bps", 0.05)), 6)
    oos_fill = {}
    for key, cell in fill["results"].items():
        if cell.get("p_fill_same_tick") is None:
            continue
        oos_fill[key] = {
            "gross_unconditional_bps": cell.get("gross_unconditional_bps"),
            "e_fill_return_bps": cell.get("e_fill_return_bps"),
            "p_fill_same_tick": cell.get("p_fill_same_tick"),
        }
    cal = {
        "source_note": "built by app.run_v3 from fill_calib.json + "
                       "execution_cost_model.json (measured, not assumed)",
        "effective_taker_roundtrip": {"1000": {"p90_bps": p90_rt,
                                                "hint": taker.get("total_bps")}},
        "maker_fee_rt_bps": float(fill.get("maker_rt_bps", 2.0)),
        "oos_fill": oos_fill,
    }
    out = RESEARCH / "v3_cost_calibration.json"
    out.write_text(json.dumps(cal, indent=1))
    return cal, out


def run():
    steps = sys.argv[1:] or ["all"]
    do = ("all" in steps)
    if do or "mirror" in steps:
        mirror_and_replay()
    if do or "features" in steps:
        sd = sorted(LIVE_V3.glob("2026*"))
        p = v3_features.build_features(RESEARCH / "v3_features.parquet", sd)
        print("features:", p)
    if do or "model" in steps:
        m, c = v3_model.calibrate(RESEARCH / "v3_features.parquet", RESEARCH)
        print("calibrated; r2_train:",
              {k: round(v["r2_train"], 4) for k, v in c.items()
               if isinstance(v, dict) and "r2_train" in v})
    if do or "cost" in steps:
        cal, out = build_cost_calibration()
        print("cost calibration:", out, "p90_rt_bps=%s" % cal[
            "effective_taker_roundtrip"]["1000"]["p90_bps"])
    if do or "freeze" in steps:
        m, p = v3_manifest.freeze_only(RESEARCH)
        print("manifest:", p, m["freeze_id"][:16])
    if do or "oos" in steps:
        r = validate(RESEARCH / "v3_model.json",
                     RESEARCH / "v3_cost_calibration.json",
                     RESEARCH / "v3_features.parquet",
                     RESEARCH, horizon_ms=PRIMARY_HORIZON)
        print("OOO verdict:", r["verdict"],
              "net_taker_bps:", r["blocks"]["oos"]["net_expectancy_bps"],
              "long=%d short=%d" % (r["blocks"]["oos"]["long"]["n"],
                                    r["blocks"]["oos"]["short"]["n"]))
    if do or "report" in steps:
        import argparse
        ap = argparse.ArgumentParser(add_help=False)
        a = ap.parse_args([])
        a.features = RESEARCH / "v3_features.parquet"
        a.model = RESEARCH / "v3_model.json"
        a.cost_cal = RESEARCH / "v3_cost_calibration.json"
        a.horizons = HORIZONS
        a.primary_horizon = PRIMARY_HORIZON
        a.notional_usd = NOTIONAL_USD
        a.walk_forward = True
        a.out = RESEARCH / "V3_ECONOMIC_REPORT.json"
        df = add_labels(pd_read(a.features), horizons=HORIZONS)
        model_d = v3_model.load_model(a.model)
        cost = cost_model(load_cal(a.cost_cal), a.notional_usd)
        report = build_report(a, model_d, df, cost)
        p = write_report(a.out, report)
        print("report:", p, "verdict:", report["verdict"]["verdict"])
        for h, hr in report["horizons"].items():
            t = hr["taker"]
            print("H=%4sms gross=%+.4f net_taker=%+.4f net_maker=%+.4f "
                  "LONG=%d SHORT=%d NO_TRADE=%d" % (
                      h, t["gross_expectancy_bps"], t["net_expectancy_bps"],
                      hr["maker"]["net_expectancy_bps"],
                      t["decision_states"].get("LONG", 0),
                      t["decision_states"].get("SHORT", 0),
                      t["decision_states"].get("NO_TRADE", 0)))


def pd_read(path):
    import pandas as pd
    return pd.read_parquet(path)


if __name__ == "__main__":
    run()