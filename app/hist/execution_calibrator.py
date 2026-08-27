"""Execution calibration: consolidate AUTHENTIC execution evidence.

Consumes ONLY observed/empirical data:
  1. Live cost-sampler JSONL (data/live/cost_sampler_*.jsonl) written by
     app/cost_sampler.py from the real Binance USD-M feed (bookTicker +
     depth@100ms, snapshot-synchronized local book).
  2. fill_calib.json (app/hist/fill_calib.py): empirical passive-fill
     probability + adverse-selection-corrected fill return per frozen
     condition x horizon, estimated from authentic aggTrades.

Outputs data/hist/research/execution_calibration.{json,md}.

This module performs NO synthetic L2, NO assumed queue position, NO assumed
fills, and NO signal modification. It only aggregates measured evidence into
a single calibration artifact for the cost model and economic gate.
"""

import argparse
import json
from pathlib import Path

import pandas as pd

from .costmodel import FEE_BPS, fee_scaled

ROOT = Path("data")
LIVE = ROOT / "live"
RESEARCH = ROOT / "hist" / "research"
DELTA_BREAK_EVEN_REF_BPS = 2.0
NOTIONAL_BANDS = (1000, 5000, 10000, 25000, 50000)
LATENCY_MS_ASSUMED = 5.0  # decision->fill latency assumption, documented (not measured order-level)


def _pct(x):
    return round(float(x) * 100.0, 2)


def load_sampler_files():
    files = sorted(LIVE.glob("cost_sampler_*.jsonl"))
    if not files:
        raise SystemExit("no cost_sampler_*.jsonl under %s" % LIVE)
    rows = []
    for f in files:
        for line in f.read_text().splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return files, rows


def calibrate_spread(df):
    sp = df["spread_bps"]
    return {
        "mean_bps": round(float(sp.mean()), 4),
        "median_bps": round(float(sp.median()), 4),
        "p90_bps": round(float(sp.quantile(0.90)), 4),
        "p99_bps": round(float(sp.quantile(0.99)), 4),
        "max_bps": round(float(sp.max()), 4),
        "pct_le_1_0": _pct((sp <= 1.0).mean()),
        "pct_le_1_9": _pct((sp <= 1.9).mean()),
        "pct_le_2_1": _pct((sp <= 2.1).mean()),
    }


def calibrate_depth(df):
    return {
        "bb_qty_usd_mean": round(float(df["bb_qty"].mean()), 2),
        "ba_qty_usd_mean": round(float(df["ba_qty"].mean()), 2),
        "bid_depth5_btc_mean": round(float(df["bid_depth5"].mean()), 7),
        "ask_depth5_btc_mean": round(float(df["ask_depth5"].mean()), 7),
        "imb5_mean": round(float(df["imb5"].mean()), 6),
    }


def calibrate_slippage(df):
    slip = {}
    for n in NOTIONAL_BANDS:
        b = df["slip_buy%d" % n]
        s = df["slip_sell%d" % n]
        slip[str(n)] = {
            "buy_median_bps": round(float(b.median()), 4),
            "buy_p90_bps": round(float(b.quantile(0.90)), 4),
            "sell_median_bps": round(float(s.median()), 4),
            "sell_p90_bps": round(float(s.quantile(0.90)), 4),
            "pct_depth_insufficient": _pct(b.isna().mean()),
        }
    return slip


def calibrate_taker_rt(df):
    eff = {}
    for n in NOTIONAL_BANDS:
        b = df["slip_buy%d" % n]
        s = df["slip_sell%d" % n]
        rt = b - s + 2.0 * FEE_BPS["taker"]
        valid = rt.dropna()
        eff[str(n)] = {
            "median_bps": round(float(valid.median()), 4) if len(valid) else None,
            "p90_bps": round(float(valid.quantile(0.90)), 4) if len(valid) else None,
            "pct_le_2_0": _pct((valid <= DELTA_BREAK_EVEN_REF_BPS).mean()) if len(valid) else 0.0,
        }
    return eff


def load_fill_calib():
    p = RESEARCH / "fill_calib.json"
    if not p.exists():
        return {}
    fc = json.loads(p.read_text())
    out = {}
    for k, v in fc["results"].items():
        out[k] = {
            "n": v["n"],
            "p_fill_same_tick": v["p_fill_same_tick"],
            "e_fill_return_bps": v["e_fill_return_bps"],
            "gross_unconditional_bps": v["gross_unconditional_bps"],
            "mean_time_to_fill_ms": v["mean_time_to_fill_ms"],
        }
    return out


def load_oos_fill():
    """Fill/adverse-selection measured on the UNTOUCHED OOS window only."""
    p = RESEARCH / "oos_oos.json"
    if not p.exists():
        return {}
    oos = json.loads(p.read_text())
    out = {}
    for r in oos["rows"]:
        fl = r.get("fill") or {}
        key = "%s@%ds" % (r["label"], r["horizon_ms"] // 1000)
        out[key] = {
            "n": r["n"],
            "p_fill_same_tick": fl.get("p_fill_same_tick"),
            "e_fill_return_bps": fl.get("e_fill_return_bps"),
            "gross_unconditional_bps": r["gross_mean_bps"],
            "mean_time_to_fill_ms": fl.get("mean_time_to_fill_ms"),
        }
    return out


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-samples", type=int, default=100)
    args = ap.parse_args(argv)

    files, rows = load_sampler_files()
    df = pd.DataFrame(rows)
    if len(df) < args.min_samples:
        raise SystemExit("only %d samples; need >= %d" % (len(df), args.min_samples))
    span_s = (df["ts_ms"].max() - df["ts_ms"].min()) / 1000.0

    payload = {
        "source": {"files": [f.name for f in files], "n_samples": int(len(df)),
                   "window_seconds": round(span_s, 1)},
        "delta_breakeven_ref_bps": DELTA_BREAK_EVEN_REF_BPS,
        "latency_assumption_ms": LATENCY_MS_ASSUMED,
        "fees_per_side_bps": dict(FEE_BPS),
        "maker_fee_rt_bps": round(2.0 * FEE_BPS["maker"], 3),
        "maker_fee_rt_vip10_bnb_bps": round(2.0 * fee_scaled(FEE_BPS["maker"], 10, 10), 3),
        "taker_fee_rt_bps": round(2.0 * FEE_BPS["taker"], 3),
        "spread": calibrate_spread(df),
        "depth": calibrate_depth(df),
        "slippage_by_notional": calibrate_slippage(df),
        "effective_taker_roundtrip": calibrate_taker_rt(df),
        "fill_calib": load_fill_calib(),
        "oos_fill": load_oos_fill(),
    }
    RESEARCH.mkdir(parents=True, exist_ok=True)
    (RESEARCH / "execution_calibration.json").write_text(json.dumps(payload, indent=2))
    (RESEARCH / "execution_calibration.md").write_text(render_md(payload, files))
    print("execution_calibration -> %s" % (RESEARCH / "execution_calibration.md"))
    return 0


def render_md(p, files):
    L = ["# Execution calibration (authentic evidence only)", "",
         "- Source: %s" % ", ".join(f.name for f in files),
         "- Samples: %d, window %.0f s" % (p["source"]["n_samples"], p["source"]["window_seconds"]),
         "- Fees per side: %s; maker rt %.2f / vip10+bnb %.2f; taker rt %.2f bps"
         % (p["fees_per_side_bps"], p["maker_fee_rt_bps"], p["maker_fee_rt_vip10_bnb_bps"],
            p["taker_fee_rt_bps"]),
         "", "## Measured spread (bps wrt mid)", ""]
    sp = p["spread"]
    L.append("| mean | median | p90 | p99 | max | <=1.0 | <=1.9 | <=2.1 |")
    L.append("|---|---|---|---|---|---|---|---|")
    L.append("| %.3f | %.3f | %.3f | %.3f | %.3f | %.1f%% | %.1f%% | %.1f%% |" % (
        sp["mean_bps"], sp["median_bps"], sp["p90_bps"], sp["p99_bps"], sp["max_bps"],
        sp["pct_le_1_0"], sp["pct_le_1_9"], sp["pct_le_2_1"]))
    d = p["depth"]
    L += ["", "## Top-of-book depth", "",
          "| bb usd | ba usd | bid5 btc | ask5 btc | imb5 |",
          "|---|---|---|---|---|",
          "| %.2f | %.2f | %.7f | %.7f | %+.4f |" % (
              d["bb_qty_usd_mean"], d["ba_qty_usd_mean"], d["bid_depth5_btc_mean"],
              d["ask_depth5_btc_mean"], d["imb5_mean"])]
    L += ["", "## Market-order slippage by notional (bps, measured)", "",
          "| notional | buy med | buy p90 | sell med | sell p90 | insuff |",
          "|---|---|---|---|---|---|"]
    for n, v in p["slippage_by_notional"].items():
        L.append("| %s | %.4f | %.4f | %.4f | %.4f | %.1f%% |" % (
            n, v["buy_median_bps"], v["buy_p90_bps"], v["sell_median_bps"],
            v["sell_p90_bps"], v["pct_depth_insufficient"]))
    L += ["", "## Effective taker round trip (bps)", "",
          "| notional | median | p90 | share <= 2.0 |", "|---|---|---|---|"]
    for n, v in p["effective_taker_roundtrip"].items():
        L.append("| %s | %s | %s | %.1f%% |" % (
            n, v["median_bps"], v["p90_bps"], v["pct_le_2_0"]))
    L += ["", "## Empirical fill calibration (frozen conditions, authentic trades)", "",
          "| condition | n | P(fill) | E[fill return] | uncond | TTF ms |",
          "|---|---|---|---|---|---|"]
    for k, v in p["fill_calib"].items():
        if "dec10_long" not in k and "dec1_short" not in k:
            continue
        L.append("| %s | %d | %.3f | %+.2f | %+.2f | %.0f |" % (
            k, v["n"], v["p_fill_same_tick"], v["e_fill_return_bps"],
            v["gross_unconditional_bps"], v["mean_time_to_fill_ms"]))
    L += ["", "## Empirical fill calibration — UNTOUCHED OOS window only (146 days)", "",
          "| condition | n | P(fill) | E[fill return] | gross | TTF ms |",
          "|---|---|---|---|---|---|"]
    for k, v in p["oos_fill"].items():
        L.append("| %s | %d | %.3f | %+.2f | %+.2f | %.0f |" % (
            k, v["n"], v["p_fill_same_tick"], v["e_fill_return_bps"],
            v["gross_unconditional_bps"], v["mean_time_to_fill_ms"]))
    L += ["", "- Latency assumption (decision->fill): %.0f ms (documented, not measured order-level)."
          % p["latency_assumption_ms"], ""]
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    import sys
    sys.exit(main())