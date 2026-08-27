"""V3 feature construction — buffers V3 replay derived rows into a parquet.

One row per event (depth + trade), preserving ts_ms/session for the
chronological split. Feature set is the predeclared execution-aware stack
(see v3_replay); no feature is added or dropped after OOS examination.
"""

import json
from pathlib import Path

import pandas as pd

COLUMNS = ["ts_ms", "recv_ms", "session", "kind", "seq",
           "best_bid", "best_ask", "mid", "microb_price", "spread_bps",
           "mpd_bps", "qi_l1", "di_l5", "di_l10", "depth_slope_bps",
           "ofi_l1", "ofi_norm_l1", "bid_add_bps", "bid_cancel_bps",
           "ask_add_bps", "ask_cancel_bps", "cancel_pressure",
           "log_depth1", "log_depth5", "log_event_rate",
           "tfi_500", "signed_vol_500", "trade_rate", "liq_depletion",
           "regime"]

# Predeclared model feature set (compact, economically motivated).
MODEL_FEATURES = ["ofi_l1", "ofi_norm_l1", "qi_l1", "di_l5", "di_l10",
                  "mpd_bps", "spread_bps", "bid_cancel_bps", "ask_add_bps",
                  "cancel_pressure", "tfi_500", "liq_depletion",
                  "log_depth1", "log_event_rate", "depth_slope_bps"]

PREDECLARED_HORIZONS_MS = (250, 500, 1000)


def build_features(out_path, session_dirs):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for sd in session_dirs:
        sd = Path(sd)
        derived = sd / "derived.jsonl"
        if not derived.exists():
            continue
        rows = [json.loads(line) for line in derived.open()
                if line.strip()]
        df = pd.DataFrame(rows)
        df["session"] = sd.name
        frames.append(df)
    if not frames:
        raise ValueError("no v3 derived rows found")
    df = pd.concat(frames, ignore_index=True)
    df["seq"] = df["seq"].astype(str)
    df = df[COLUMNS].sort_values(["session", "ts_ms"]).reset_index(drop=True)
    df.to_parquet(out_path, index=False)
    return out_path


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path,
                    default=Path("data/research/v3_features.parquet"))
    ap.add_argument("sessions", nargs="+", type=Path)
    a = ap.parse_args()
    p = build_features(a.out, a.sessions)
    print("wrote", p)