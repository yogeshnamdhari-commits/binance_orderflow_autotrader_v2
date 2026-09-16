"""V12 feature extractor — reuses V5 feature definitions.

All features are microstructurally motivated and causally computed.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from app.v11.features import extract_v11_features, build_targets, build_regression_target


def parse_session_v10_format(session_dir: Path) -> tuple[list, list]:
    """Parse v10.raw.v1 schema into book snapshots and trade records."""
    from app.v11.parser import V11DataParser
    parser = V11DataParser(session_dir)
    return parser.parse()


def extract_v12_features(books: list, trades: list, window_ms: int = 500) -> pd.DataFrame:
    """Extract V5 feature set from parsed data.

    Uses the existing V11 feature extractor (which implements V5 features).
    """
    return extract_v11_features(books, trades, window_ms=window_ms)


def build_v12_targets(df: pd.DataFrame, horizon_ms: int = 500) -> pd.Series:
    """Build binary classification target."""
    return build_targets(df, horizon_ms=horizon_ms)


def build_v12_returns(df: pd.DataFrame, horizon_ms: int = 500) -> pd.Series:
    """Build regression target (forward returns in bps)."""
    return build_regression_target(df, horizon_ms=horizon_ms)
