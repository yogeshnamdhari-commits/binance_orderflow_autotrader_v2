"""V3 live decision signal — three states only, driven by the economic gate.

  gross = E[ΔP_h | X]          (frozen V3 linear model, per predeclared horizon)
  gate  = Cost + predeclared safety margin     (taker or maker style)
  LONG  iff  gross - gate > 0
  SHORT iff -gross - gate > 0
  NO_TRADE otherwise

No hand weights, no confidence scores, no threshold tuning. If the gate blocks
every trade, NO_TRADE is the correct answer.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .v3_cost import decide, cost_model, load_cal, DEFAULT_NOTIONAL_USD, DEFAULT_CAL_PATH
from .v3_model import load_model, predict


@dataclass
class V3SignalResult:
    state: str
    horizon_ms: int
    gross_bps: float
    gate_bps: float
    net_long_bps: float
    net_short_bps: float
    style: str


class V3Signal:
    def __init__(self, model_path, cal_path=DEFAULT_CAL_PATH,
                 horizon_ms=500, style="taker",
                 notional_usd=DEFAULT_NOTIONAL_USD):
        self.model = load_model(model_path)
        self.cost = cost_model(load_cal(cal_path), notional_usd)
        self.horizon_ms = horizon_ms
        self.style = style
        if str(self.horizon_ms) not in self.model:
            raise ValueError("model has no frozen coefficients for horizon %dms"
                             % self.horizon_ms)

    def gross(self, df):
        return predict(self.model, df, self.horizon_ms)

    def evaluate(self, row):
        df = pd.DataFrame([row]) if isinstance(row, dict) else row
        g = float(self.gross(df)[0])
        e = decide(g, self.cost, self.style)
        return V3SignalResult(state=e["state"], horizon_ms=self.horizon_ms,
                              gross_bps=g, gate_bps=e["gate_bps"],
                              net_long_bps=e["net_long_bps"],
                              net_short_bps=e["net_short_bps"],
                              style=e["style"])

    def evaluate_frame(self, df):
        gross = self.gross(df)
        return [decide(float(g), self.cost, self.style) for g in gross]


if __name__ == "__main__":
    import argparse
    import sys
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=Path("data/research/v3_model.json"))
    ap.add_argument("--cost", type=Path, default=DEFAULT_CAL_PATH)
    ap.add_argument("--features", type=Path,
                    default=Path("data/research/v3_features.parquet"))
    ap.add_argument("--horizon-ms", type=int, default=500)
    ap.add_argument("--style", default="taker", choices=("taker", "maker"))
    a = ap.parse_args()
    df = pd.read_parquet(a.features).head(50000)
    sig = V3Signal(a.model, a.cost, a.horizon_ms, a.style)
    res = sig.evaluate_frame(df)
    from collections import Counter
    print("states:", Counter(r["state"] for r in res))
    print("example:", res[0] if res else None)