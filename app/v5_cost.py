"""V5 cost — measured taker-side cost gate for directional entries.

Gate is the measured execution cost (realized on this data lineage), NOT a
free parameter:

  gate_bps(v5) = effective taker round-trip (measured rt p90, 1000-notional
                 band: fee + spread + slippage) + impact + latency margin
                 + predeclared 0.5 bps conservatism
               = 4.0158 + 0.10 + 0.05 + 0.50 = 4.6658 bps

Decision state (strategy convention, predeclared):
  LONG      iff  E[ΔP] >  +gate
  SHORT     iff  E[ΔP] <  -gate
  NO_TRADE  otherwise

Cost sensitivity is reported (gate +/- 0.5, 1.0 bps) in validation/economic
report as an ANALYSIS artifact, used neither for parameter selection nor for
the verdict — the verdict always binds to the measured gate.
"""

from pathlib import Path

from .v3_cost import (cost_model, load_cal as _load_cal, DEFAULT_CAL_PATH,
                      SAFETY_MARGIN_BPS)

DATA = Path("data")
MARGIN_BPS = SAFETY_MARGIN_BPS
NOTIONAL = 1000
DEFAULT_COST_CAL = DEFAULT_CAL_PATH


def measured_gate(cal_path=DEFAULT_COST_CAL):
    cal = _load_cal(cal_path) if isinstance(cal_path, (str, Path)) else cal_path
    return float(cost_model(cal, notional_usd=NOTIONAL)["taker"]["gate_bps"])


def total_cost_bps(cal_path=DEFAULT_COST_CAL):
    cal = _load_cal(cal_path) if isinstance(cal_path, (str, Path)) else cal_path
    return float(cost_model(cal, notional_usd=NOTIONAL)["taker"]["total_bps"])


def decide(pred, gate):
    """Strategy state given expected move (bps) and gate (bps).

    LONG iff pred > +gate, SHORT iff pred < -gate, else NO_TRADE.
    """
    if pred > gate:
        return {"state": "LONG", "gross_bps": pred, "gate_bps": gate}
    if pred < -gate:
        return {"state": "SHORT", "gross_bps": pred, "gate_bps": gate}
    return {"state": "NO_TRADE", "gross_bps": pred, "gate_bps": gate}


def sensitivity_gates(gate):
    return {"gate_minus_1": gate - 1.0,
            "gate_minus_half": gate - 0.5,
            "gate": gate,
            "gate_plus_half": gate + 0.5,
            "gate_plus_1": gate + 1.0}