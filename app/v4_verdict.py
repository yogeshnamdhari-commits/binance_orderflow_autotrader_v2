"""V4 verdict — strictly one of PASS / CONDITIONAL_PASS / FAIL / INSUFFICIENT_DATA.

Decision inputs are measured by v4_validation from the untouched OOS maker
execution. Nothing here fits or rescues; thresholds are predeclared and fixed.

  INSUFFICIENT_DATA  the OOS dataset is too short to draw any economic
                     conclusion (fewer than MIN_OOS_PERIODS independent periods
                     or too few gated directional signals)
  PASS               ONLY if net maker expectancy > 0 after realistic costs,
                     measured fills support the fill assumptions, economics stay
                     positive across independent OOS periods, no single session
                     dominates, robustness positive, and OOS sample sufficient
  CONDITIONAL_PASS   economics promising (net > 0) but the sample is too small
                     to conclude — hypothesis survives, needs more data
  FAIL               net maker expectancy <= 0, OR maker economics vanish under
                     realistic fill assumptions, OR adverse selection consumes
                     the gross edge, OR single-session domination
"""

MIN_OOS_PERIODS = 3
MIN_SIGNALS_PER_DIRECTION = 200
MIN_FILLED_FOR_SUPPORT = 50
MAX_SINGLE_SESSION_NET_SHARE = 0.50
MIN_SESSION_POSITIVE_FRACTION = 0.60


def decide(score):
    """score: dict from v4_validation.validate_sessions."""
    reasons = []
    net = score.get("net_expectancy_bps")
    n_filled = int(score.get("entries_filled", 0))
    periods = int(score.get("oos_periods", 0))
    posted = int(score.get("posted_signals", 0))
    share = score.get("largest_session_net_share")
    drag = score.get("fill_conditional_drag_bps")
    uncond = score.get("unconditional_gross_bps")
    per_session = score.get("per_session", {})
    pos_sessions = [s for s in per_session.values()
                    if s.get("net_mean_bps") is not None
                    and s["net_mean_bps"] > 0 and s.get("signals", 0) >= 20]
    n_pos = len(pos_sessions)
    n_sample_sessions = len([s for s in per_session.values()
                             if s.get("signals", 0) >= 20])
    robust = (n_pos / n_sample_sessions >= MIN_SESSION_POSITIVE_FRACTION) \
        if n_sample_sessions >= 2 else False

    sufficient = periods >= MIN_OOS_PERIODS and posted >= MIN_SIGNALS_PER_DIRECTION
    supported = n_filled >= MIN_FILLED_FOR_SUPPORT
    adv_consumes = (drag is not None and uncond is not None and uncond > 0
                    and drag >= uncond - 1e-12)

    dominant = share is not None and share >= MAX_SINGLE_SESSION_NET_SHARE

    criteria = {
        "net_expectancy_bps": net,
        "oos_periods": periods,
        "posted_signals": posted,
        "officials_ok": sufficient,
        "fill_supported": supported,
        "single_session_share": share,
        "dominance_ok": not dominant,
        "positive_session_fraction": round(n_pos / n_sample_sessions, 4)
        if n_sample_sessions else None,
        "robust": robust,
        "adverse_consumes_edge": adv_consumes,
    }

    if score.get("conclusion") == "insufficient" or net is None:
        return verdict("INSUFFICIENT_DATA", reasons + score.get("reasons", []),
                       criteria)
    if periods < MIN_OOS_PERIODS:
        reasons.append("too few independent OOS periods (%d < %d): dataset too "
                       "short to conclude" % (periods, MIN_OOS_PERIODS))
        return verdict("INSUFFICIENT_DATA", reasons, criteria)
    if posted < MIN_SIGNALS_PER_DIRECTION:
        reasons.append("OOS directional sample too small (posted=%d < %d)"
                       % (posted, MIN_SIGNALS_PER_DIRECTION))
        if net > 0:
            reasons.append("promising maker net expectancy %.4f bps but sample "
                           "insufficient" % net)
            return verdict("CONDITIONAL_PASS", reasons, criteria)
        return verdict("INSUFFICIENT_DATA", reasons, criteria)

    if net <= 0:
        reasons.append("net maker expectancy %.4f bps <= 0 after realistic "
                       "maker costs" % net)
        return verdict("FAIL", reasons, criteria)
    if not supported:
        reasons.append("fill assumptions unsupported empirically: filled=%d < %d"
                       % (n_filled, MIN_FILLED_FOR_SUPPORT))
        return verdict("FAIL", reasons, criteria)
    if adv_consumes:
        reasons.append("adverse selection (%s bps fill-conditional drag) "
                       "consumes the unconditional gross edge %.4f bps"
                       % (drag, uncond))
        return verdict("FAIL", reasons, criteria)
    if dominant:
        reasons.append("single session dominates the net result (share %.3f >= %.2f)"
                       % (share, MAX_SINGLE_SESSION_NET_SHARE))
        return verdict("FAIL", reasons, criteria)
    if not robust:
        reasons.append("robustness: only %.0f/%.0f sampled sessions positive "
                       "(need >= %.0f%%)" % (n_pos, n_sample_sessions,
                                             100 * MIN_SESSION_POSITIVE_FRACTION))
        return verdict("FAIL", reasons, criteria)

    reasons.append("positive maker net %.4f bps across %d periods, robust "
                   "(%.0f%% of sampled sessions positive), fills measured from "
                   "L2 stream (n=%d)"
                   % (net, periods, 100 * n_pos / n_sample_sessions, n_filled))
    return verdict("PASS", reasons, criteria)


def verdict(name, reasons, criteria):
    return {"verdict": name, "reasons": reasons, "criteria": criteria}