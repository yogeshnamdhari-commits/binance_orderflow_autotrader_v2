"""V2 final verdict (Task 10) — exactly one of PASS / CONDITIONAL PASS / FAIL.

PASS            positive net economic expectancy after measured costs AND
                robustness across independent OOS conditions (time blocks +
                liquidity/spread/volatility regimes), on a sample large enough
                to matter (>= MIN_OOS_PERIODS distinct periods and >=
                MIN_SIGNALS_PER_DIRECTION per side).

CONDITIONAL PASS  directional sample too small to measure an edge; predictive
                economics are neither proven nor refuted.

FAIL            the measured OOS economics are refuted (net expectancy <= 0)
                on a directional sample large enough to conclude, or the edge
                is not robust. STOP; no re-fitting, no rescue.

Decision inputs come from v2_economic_report (net expectancies) and
v2_robustness (condition coverage). Nothing here selects parameters.
"""

MIN_OOS_PERIODS = 3                 # distinct periods (sessions/days) in OOS
MIN_SIGNALS_PER_DIRECTION = 200     # per-side signal count required
MIN_REGIME_POSITIVE_FRACTION = 0.5  # robustness cells with positive net


def decide(oos, robustness):
    periods = int(oos.get("oos_periods", 0))
    long_n = int(oos.get("long", {}).get("n", 0))
    short_n = int(oos.get("short", {}).get("n", 0))
    directional_sample_ok = (long_n >= MIN_SIGNALS_PER_DIRECTION and
                             short_n >= MIN_SIGNALS_PER_DIRECTION)
    periods_ok = periods >= MIN_OOS_PERIODS
    net_taker = float(oos.get("net_expectancy_taker_bps", 0.0))
    net_maker = float(oos.get("net_expectancy_maker_bps", 0.0))

    cells = robustness.get("cells", [])
    sizes = [c for c in cells if int(c.get("n", 0)) >= 20]
    positive = [c for c in sizes if float(c.get("net_mean_bps", 0.0)) > 0.0]
    robust = False
    if sizes:
        robust = len(positive) / len(sizes) >= MIN_REGIME_POSITIVE_FRACTION

    reasons = []
    if not directional_sample_ok:
        verdict = "CONDITIONAL PASS"
        reasons.append("OOS directional sample too small to measure an edge: "
                       "long=%d short=%d (need >=%d each)" % (
                           long_n, short_n, MIN_SIGNALS_PER_DIRECTION))
        reasons.append("predictive economics neither proven nor refuted; "
                       "observed net taker %.4f bps, maker %.4f bps"
                       % (net_taker, net_maker))
    elif (net_taker > 0.0 and net_maker > 0.0 and robust and periods_ok):
        verdict = "PASS"
        reasons.append("net expectancy positive (taker %.4f bps, maker %.4f bps) "
                       "across %d periods and robust across %.0f%% of %d "
                       "condition cells" % (net_taker, net_maker, periods,
                                            100 * len(positive) / len(sizes),
                                            len(sizes)))
    else:
        verdict = "FAIL"
        reasons.append("measured OOS economics refuted on a large directional "
                       "sample: long=%d short=%d; net taker %.4f bps, maker "
                       "%.4f bps (cost-adjusted edge <= 0)" % (
                           long_n, short_n, net_taker, net_maker))
        if not periods_ok:
            reasons.append("OOS periods=%d < %d (result rests on one window)"
                           % (periods, MIN_OOS_PERIODS))
        if not robust:
            reasons.append("robustness coverage %.0f%% < %.0f%%"
                           % (100 * len(positive) / len(sizes) if sizes else 0.0,
                              100 * MIN_REGIME_POSITIVE_FRACTION))
    return {
        "verdict": verdict,
        "reasons": reasons,
        "criteria": {"directional_sample_ok": directional_sample_ok,
                     "periods_ok": periods_ok,
                     "net_taker_positive": net_taker > 0,
                     "net_maker_positive": net_maker > 0,
                     "robustness_positive_fraction":
                         len(positive) / len(sizes) if sizes else None,
                     "min_oos_periods": MIN_OOS_PERIODS,
                     "min_signals_per_direction": MIN_SIGNALS_PER_DIRECTION},
    }