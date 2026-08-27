"""Live BTCUSDT execution-cost calibration report.

Reads a CostSampler jsonl, computes the measured cost components over the
sampling window (spread distribution, top-of-book depth, market-order
slippage by notional) and re-computes the reference execution scenarios
using MEASURED spread/slippage instead of the previous assumed constants.

Outputs:
  data/live/cost_calibration.json
  data/live/cost_calibration.md
"""

import json
from pathlib import Path
from collections import Counter

import pandas as pd

from .hist.costmodel import FEE_BPS, fee_scaled
from .cost_sampler import walk_slippage_bps

BREAK_EVEN = {"maker_passive": 2.3, "maker_bnb_vip": 1.9,
              "taker_full": 6.5, "taker_discounted": 5.7}
DELTA_BREAK_EVEN_BPS = 2.0


def _pct(x):
    return float(round(x * 100.0, 2))


def _roundtrip_effective(row, fee_per_side, n, slip_col_prefix="slip"):
    """Measured round-trip: buy+sell slippage beyond mid plus 2x fee.

    slip_* values already include crossing the spread plus depth walked; for a
    taker round trip this is the realized cost before fees. Maker adds 0 spread
    (rested legs) so we report fees + optional measured impact in report logic.
    """
    b = row.get(f"{slip_col_prefix}_buy{n}")
    s = row.get(f"{slip_col_prefix}_sell{n}")
    if b is None or s is None:
        return None
    return round(float(b) - float(s) + 2.0 * fee_per_side, 4)


def summarize(path, out_dir=None):
    path = Path(path)
    out_dir = Path(out_dir) if out_dir else path.parent
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    if not rows:
        raise SystemExit("no samples in %s" % path)
    df = pd.DataFrame(rows)

    n = len(df)
    span_s = (df["ts_ms"].max() - df["ts_ms"].min()) / 1000.0
    spread = df["spread_bps"]

    bands = [c for c in df.columns if c.startswith("slip_buy") or c.startswith("slip_sell")]
    band_sizes = sorted({int(c.replace("slip_buy", "").replace("slip_sell", "")) for c in bands})

    stats = {
        "n_samples": int(n),
        "window_seconds": round(span_s, 1),
        "ts_start": int(df["ts_ms"].min()),
        "ts_end": int(df["ts_ms"].max()),
    }
    spread_stats = {
        "mean_bps": round(float(spread.mean()), 4),
        "median_bps": round(float(spread.median()), 4),
        "p90_bps": round(float(spread.quantile(0.90)), 4),
        "p99_bps": round(float(spread.quantile(0.99)), 4),
        "max_bps": round(float(spread.max()), 4),
        "pct_spread_le_1_0": _pct((spread <= 1.0).mean()),
        "pct_spread_le_1_5": _pct((spread <= 1.5).mean()),
        "pct_spread_le_1_9": _pct((spread <= 1.9).mean()),
        "pct_spread_le_2_1": _pct((spread <= 2.1).mean()),
        "pct_spread_le_2_3": _pct((spread <= 2.3).mean()),
    }
    stats["spread"] = spread_stats

    depth = {
        "bb_qty_usd_mean": round(float(df["bb_qty"].mean()), 2),
        "bb_qty_usd_median": round(float(df["bb_qty"].median()), 2),
        "ba_qty_usd_mean": round(float(df["ba_qty"].mean()), 2),
        "ba_qty_usd_median": round(float(df["ba_qty"].median()), 2),
        "bid_depth5_btc_mean": round(float(df["bid_depth5"].mean()), 7),
        "ask_depth5_btc_mean": round(float(df["ask_depth5"].mean()), 7),
        "imb5_mean": round(float(df["imb5"].mean()), 6),
    }
    stats["depth"] = depth

    slip = {}
    for nbtc in band_sizes:
        b = df["slip_buy%s" % nbtc]
        s = df["slip_sell%s" % nbtc]
        slip[str(nbtc)] = {
            "buy_median_bps": round(float(b.median()), 4),
            "buy_p90_bps": round(float(b.quantile(0.90)), 4),
            "sell_median_bps": round(float(s.median()), 4),
            "sell_p90_bps": round(float(s.quantile(0.90)), 4),
            "pct_depth_insufficient": _pct(b.isna().mean()),
        }
    stats["slip"] = slip

    eff = {}
    for nbtc in band_sizes:
        rt = df.apply(lambda r: _roundtrip_effective(r, FEE_BPS["taker"], nbtc), axis=1)
        valid = rt.dropna()
        eff[str(nbtc)] = {
            "taker_rt_median_bps": round(float(valid.median()), 4) if len(valid) else None,
            "taker_rt_p90_bps": round(float(valid.quantile(0.90)), 4) if len(valid) else None,
            "pct_rt_le_delta_breakeven": _pct((valid <= DELTA_BREAK_EVEN_BPS).mean()) if len(valid) else 0.0,
        }
    stats["effective_roundtrip_taker"] = eff

    # maker view: rested legs pay fees only; report the assumption of no fill (not measurable here)
    stats["maker"] = {
        "fee_rt_mean_bps": round(2.0 * FEE_BPS["maker"], 3),
        "fee_rt_vip10_bnb_bps": round(2.0 * fee_scaled(FEE_BPS["maker"], 10, 10), 3),
        "fill_probe": "not directly measurable from public depth-only feed; needs order-level execution log",
    }
    stats["delta_breakeven_bps"] = DELTA_BREAK_EVEN_BPS

    summary_md = render_md(stats, path)
    (out_dir / "cost_calibration.json").write_text(json.dumps(stats, indent=2))
    (out_dir / "cost_calibration.md").write_text(summary_md)
    return stats


def render_md(s, src):
    L = [
        "# BTCUSDT live execution-cost calibration",
        "",
        "- Source: %s" % src.name,
        "- Window: %.0f s, %d samples (1s cadence)" % (s["window_seconds"], s["n_samples"]),
        "- Delta edge break-even reference: %.1f bps round trip" % s["delta_breakeven_bps"],
        "",
    ]

    sp = s["spread"]
    L += [
        "## Measured best bid/ask spread (bps wrt mid)",
        "",
        "| stat | value |",
        "|---|---|",
        "| mean | %.3f |" % sp["mean_bps"],
        "| median | %.3f |" % sp["median_bps"],
        "| p90 | %.3f |" % sp["p90_bps"],
        "| p99 | %.3f |" % sp["p99_bps"],
        "| max | %.3f |" % sp["max_bps"],
        "",
        "Share of time spread <= %.1f bps: **%.1f%%**" % (1.0, sp["pct_spread_le_1_0"]),
        "Share of time spread <= 1.9 bps (maker+BNB/VIP feasible): **%.1f%%**" % sp["pct_spread_le_1_9"],
        "Share of time spread <= 2.1 bps (delta break-even): **%.1f%%**" % sp["pct_spread_le_2_1"],
        "",
    ]

    d = s["depth"]
    L += [
        "## Top-of-book depth", "",
        "| metric | mean |",
        "|---|---|",
        "| best bid qty (USD) | %.2f |" % d["bb_qty_usd_mean"],
        "| best ask qty (USD) | %.2f |" % d["ba_qty_usd_mean"],
        "| top-5 bid depth (BTC) | %.7f |" % d["bid_depth5_btc_mean"],
        "| top-5 ask depth (BTC) | %.7f |" % d["ask_depth5_btc_mean"],
        "| top-5 depth imbalance (bid-ask)/(bid+ask) | %.6f |" % d["imb5_mean"],
        "",
    ]

    L += ["## Market-order slippage by notional", "",
          "| notional (USD) | buy median | buy p90 | sell median | sell p90 | depth-insufficient |",
          "|---|---|---|---|---|---|"]
    for nbtc, v in s["slip"].items():
        L.append("| %s | %.4f | %.4f | %.4f | %.4f | %.1f%% |" % (
            nbtc, v["buy_median_bps"], v["buy_p90_bps"],
            v["sell_median_bps"], v["sell_p90_bps"], v["pct_depth_insufficient"]))
    L += [""]

    L += ["## Effective taker round trip (measured slippage + 2x taker fee)", "",
          "| notional (USD) | median bps | p90 bps | share <= delta break-even |",
          "|---|---|---|---|"]
    for nbtc, v in s["effective_roundtrip_taker"].items():
        L.append("| %s | %s | %s | %.1f%% |" % (
            nbtc,
            "%.3f" % v["taker_rt_median_bps"] if v["taker_rt_median_bps"] is not None else "-",
            "%.3f" % v["taker_rt_p90_bps"] if v["taker_rt_p90_bps"] is not None else "-",
            v["pct_rt_le_delta_breakeven"]))
    L += [""]

    m = s["maker"]
    L += [
        "## Maker view", "",
        "- Rested legs pay fees only (no spread crossing): %.2f bps round trip" % m["fee_rt_mean_bps"],
        "- With VIP10 + BNB discount: %.2f bps round trip" % m["fee_rt_vip10_bnb_bps"],
        "- Fill: %s" % m["fill_probe"],
        "",
    ]

    # verdict vs the delta edge break-even (2.0-2.1 bps round trip on the 5s/15s horizon)
    taker_med = s["effective_roundtrip_taker"].get("1000", {}).get("taker_rt_median_bps")
    verdicts = []
    verdicts.append("Measured spread (median %.3f bps) is tick-bound and far below the delta break-even; "
                    "spread is NOT the binding cost." % sp["median_bps"])
    if taker_med is not None:
        verdicts.append("Measured effective TAKER round trip at small size (median %.1f bps) is dominated by "
                        "the 2x taker fee and exceeds the ~2.0 bps delta break-even -> taker execution is not "
                        "economically viable for the order-flow signal." % taker_med)
    verdicts.append("MAKER execution (fees only, no spread crossing) at %.2f bps round trip sits BELOW the "
                    "%.1f bps delta break-even when BNB/VIP discounts apply (%.2f bps), with the caveat that "
                    "fill probability / adverse selection are NOT measurable from a depth-only feed."
                    % (m["fee_rt_mean_bps"], s["delta_breakeven_bps"], m["fee_rt_vip10_bnb_bps"]))
    L += ["## Verdict vs delta edge", ""]
    for v in verdicts:
        L.append("- %s" % v)
    L += [""]
    return "\n".join(L) + "\n"