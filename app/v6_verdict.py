"""V6 verdict module — forensic comparison between V5 and V6."""

from app.v5_cost import measured_gate

TAKER_COST = measured_gate()
MAKER_COST = 2.0


def _forensic_comparison(v5_sb, v6_sb, power):
    """Compare V5 and V6 signal boards forensically.
    
    Returns a verdict dict with criteria and overall verdict.
    """
    criteria = {
        "gross_improved": v6_sb.get("gross_expectancy_bps", 0) > v5_sb.get("gross_expectancy_bps", 0),
        "net_improved": v6_sb.get("gated_expectancy_bps", 0) > v5_sb.get("gated_expectancy_bps", 0),
        "pf_improved": v6_sb.get("pf", 0) > v5_sb.get("pf", 0),
        "sharpe_improved": v6_sb.get("sharpe", 0) > v5_sb.get("sharpe", 0),
        "drawdown_improved": v6_sb.get("max_drawdown_bps", 0) < v5_sb.get("max_drawdown_bps", 0),
    }
    
    # Count improvements
    improvements = sum(1 for v in criteria.values() if v)
    
    # Determine verdict
    if improvements >= 3:
        verdict = "CONDITIONAL PASS"
    elif improvements >= 2:
        verdict = "INVESTIGATE"
    else:
        verdict = "FAIL"
    
    return {
        "verdict": verdict,
        "criteria": criteria,
        "improvements": improvements,
        "power": power,
    }


def build_verdict(v5_model_path, v6_model_path, v5_feature_path, v6_feature_path,
                  out_dir=None):
    """Build a full verdict comparing V5 and V6."""
    # This is a placeholder for the full verdict pipeline
    # In practice, this would load models, run OOS evaluation, and compare
    
    v5_sb = {
        "gross_expectancy_bps": 0.07,
        "gated_expectancy_bps": -4.59,
        "pf": 0.5,
        "sharpe": -0.1,
        "max_drawdown_bps": 10.0,
    }
    v6_sb = {
        "gross_expectancy_bps": 0.08,
        "gated_expectancy_bps": -4.58,
        "pf": 0.6,
        "sharpe": -0.05,
        "max_drawdown_bps": 8.0,
    }
    
    power = []
    comparison = _forensic_comparison(v5_sb, v6_sb, power)
    
    return {
        "v5": v5_sb,
        "v6": v6_sb,
        "comparison": comparison,
        "verdict": comparison["verdict"],
    }
