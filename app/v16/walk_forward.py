"""V16 walk-forward validation — chronological, no shuffle."""
from __future__ import annotations

import numpy as np
import pandas as pd

from app.v16.config import V16Config
from app.v16.features import V16_FEATURES


class V16WalkForward:
    def __init__(self, config: V16Config):
        self._cfg = config
        self.n_folds = config.walk_forward_n_folds
        self.train_pct = config.walk_forward_train_pct
        self.val_pct = config.walk_forward_val_pct
        self.fwd_pct = config.walk_forward_forward_pct
        self.min_obs = config.min_obs_per_fold

    def split(self, df: pd.DataFrame) -> list[dict]:
        n = len(df)
        fold_size = max(self.min_obs, n // self.n_folds)
        folds = []
        for i in range(self.n_folds):
            start = i * fold_size
            end = min((i + 1) * fold_size, n)
            if end - start < self.min_obs:
                break
            fold_df = df.iloc[start:end].copy()
            train_end = int(len(fold_df) * self.train_pct)
            val_end = int(len(fold_df) * (self.train_pct + self.val_pct))
            folds.append({
                "fold": i,
                "train": fold_df.iloc[:train_end],
                "validate": fold_df.iloc[train_end:val_end],
                "forward": fold_df.iloc[val_end:],
                "start_ns": int(fold_df["ts_ms"].iloc[0] * 1e6) if "ts_ms" in fold_df.columns else start,
                "end_ns": int(fold_df["ts_ms"].iloc[-1] * 1e6) if "ts_ms" in fold_df.columns else end,
            })
        return folds
