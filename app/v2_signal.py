"""V2 frozen signal — three states only.

  LONG   : expected long net edge > 0   (frozen model gross forecast minus
                                          measured execution cost at the tail)
  SHORT  : expected short net edge > 0
  NO_TRADE : everything else

Maps the frozen linear model's gross mid-return forecast through the
empirical cost gate. Long and short are gated independently; no hand weights,
no scoring, no thresholds invented after results.
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .v2_cost_gate import DEFAULT_CAL_PATH, DEFAULT_NOTIONAL_USD, decide, net_edges, taker_cost_bps
from .v2_model import load_model, predict


@dataclass
class V2SignalResult:
    state: str
    horizon_ms: int
    gross_bps: float
    cost_bps: float
    long_net_bps: float
    short_net_bps: float
    style: str
    components: dict


class V2Signal:
    def __init__(self, model_path, cal_path=DEFAULT_CAL_PATH, horizon_ms=500,
                 style="taker", notional_usd=DEFAULT_NOTIONAL_USD):
        self.model = load_model(model_path)
        self.cal = json.load(open(cal_path))
        self.horizon_ms = horizon_ms
        self.style = style
        self.notional_usd = notional_usd
        if str(self.horizon_ms) not in self.model:
            raise ValueError("model has no frozen coefficients for horizon %dms" % horizon_ms)

    def gross(self, df):
        return predict(self.model, df, self.horizon_ms)

    def evaluate(self, row):
        df = pd.DataFrame([row]) if isinstance(row, dict) else row
        gross = float(self.gross(df)[0])
        e = decide(gross, self.cal, self.notional_usd, self.style)
        return V2SignalResult(
            state=e["state"], horizon_ms=self.horizon_ms, gross_bps=e["gross_bps"],
            cost_bps=e["cost_bps"], long_net_bps=e["long"], short_net_bps=e["short"],
            style=e["components"]["style"], components=e["components"])

    def evaluate_frame(self, df):
        gross = self.gross(df)
        out = []
        for g in gross:
            e = decide(float(g), self.cal, self.notional_usd, self.style)
            out.append(e)
        return out


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", type=Path, default=Path("data/hist/research/v2_model.json"))
    ap.add_argument("--cost", type=Path, default=DEFAULT_CAL_PATH)
    ap.add_argument("--features", type=Path, default=Path("data/hist/research/v2_features.parquet"))
    ap.add_argument("--horizon-ms", type=int, default=500)
    ap.add_argument("--notional-usd", type=float, default=DEFAULT_NOTIONAL_USD)
    ap.add_argument("--style", default="taker", choices=("taker", "maker"))
    a = ap.parse_args()
    df = pd.read_parquet(a.features).head(100000)
    sig = V2Signal(a.model, a.cost, a.horizon_ms, a.style, a.notional_usd)
    res = sig.evaluate_frame(df)
    from collections import Counter
    print("states:", Counter(r["state"] for r in res))
    for r in res[:3]:
        print(json.dumps(r))