"""V5 replay — deterministic L2 reconstruction feeding the directional model.

Reuses the verified V4 engine (ReplayV4) which already produces, for every
depth/trade event of the immutable raw log, the full V3 feature row plus
top-10 price-level snapshots. V5 therefore has byte-identical event rows to the
frozen V3/V4 lineage; this module only routes them under data/live/v5 and
provides the integrity gate (V5 rows must reproduce the frozen V3 features and
frozen-model predictions event-for-event) BEFORE any OOS read.
"""

import json
from pathlib import Path

from . import v3_collector
from .v4_replay import ReplayV4
from .v3_model import load_model, predict as v3_predict
from .v3_features import MODEL_FEATURES

DATA = Path("data")
LIVE = Path("data/live/v5")


def mirror_and_replay(log=print):
    LIVE.mkdir(parents=True, exist_ok=True)
    sessions = v3_collector.mirror_from_v2(v2_root=DATA / "live" / "v2",
                                           dst_root=LIVE)
    total = 0
    for sd in sorted(LIVE.glob("2026*")):
        if not (sd / "raw.jsonl").exists():
            continue
        rp = ReplayV4(log=lambda _m: None)
        with open(sd / "raw.jsonl") as f:
            for line in f:
                line = line.strip()
                if line:
                    rp.feed_line(line)
        with open(sd / "derived_v5.jsonl", "w") as f:
            for row in rp.rows:
                f.write(json.dumps(row) + "\n")
        total += len(rp.rows)
        log("  %-14s %6d rows (skips=%d)" % (sd.name, len(rp.rows), rp.skips))
    log("total v5 rows: %d" % total)
    return sessions


def integrity_check(log=print):
    """V5 rows must be event-for-event identical to the frozen V3 chain."""
    import numpy as np
    import pandas as pd
    feats = pd.read_parquet(DATA / "research" / "v3_features.parquet")
    model = load_model(DATA / "research" / "v3_model.json")
    fail = []
    FE = [c for c in MODEL_FEATURES if c in feats]
    for sd in sorted(LIVE.glob("2026*")):
        dv = sd / "derived_v5.jsonl"
        if not dv.exists():
            continue
        rows = [json.loads(l) for l in dv.open() if l.strip()]
        v5 = pd.DataFrame(rows)
        v3 = feats[feats.session == sd.name]
        if len(v5) != len(v3):
            fail.append("%s count %d vs v3 %d" % (sd.name, len(v5), len(v3)))
            continue
        v5 = v5.assign(k=v5["ts_ms"].astype(str) + "|" + v5["seq"].astype(str))
        v3 = v3.assign(k=v3["ts_ms"].astype(str) + "|" + v3["seq"].astype(str))
        if not (np.sort(v5["k"].to_numpy()) == np.sort(v3["k"].to_numpy())).all():
            fail.append("%s event alignment mismatch" % sd.name)
            continue
        v5s = v5.set_index("k").reindex(v3["k"]).reset_index(drop=True)
        for c in FE:
            if not np.allclose(v5s[c].to_numpy(float), v3[c].to_numpy(float),
                               rtol=0, atol=1e-9):
                fail.append("%s feature %r differs" % (sd.name, c))
        if not np.allclose(v3_predict(model, v5s, 500),
                           v3_predict(model, v3, 500), rtol=0, atol=1e-9):
            fail.append("%s frozen preds differ" % sd.name)
    return fail


if __name__ == "__main__":
    mirror_and_replay()
    print("integrity failures:", integrity_check())