"""Post-fill adverse-selection measurements for V10."""
from __future__ import annotations
import numpy as np


def conditional_mid_return(fill_mid, post_fill_mid):
    f = np.asarray(fill_mid, dtype=float)
    p = np.asarray(post_fill_mid, dtype=float)
    if f.ndim != 1 or p.ndim != 1 or len(f) == 0 or len(f) != len(p):
        raise ValueError("fill_mid and post_fill_mid must be non-empty vectors of equal length")
    if not np.all(np.isfinite(f)) or not np.all(np.isfinite(p)) or np.any(f <= 0):
        raise ValueError("mid prices must be finite and positive")
    return p / f - 1.0


def adverse_selection_bps(fill_price: float, post_fill_mid: float, side: str) -> float:
    fill = float(fill_price)
    post = float(post_fill_mid)
    if side not in {"bid", "ask"}:
        raise ValueError("side must be bid or ask")
    if not np.isfinite(fill) or not np.isfinite(post) or fill <= 0 or post <= 0:
        raise ValueError("prices must be finite and positive")
    # Positive value means the post-fill move is adverse to the passive side.
    signed_return = (post / fill - 1.0) * (1.0 if side == "ask" else -1.0)
    return float(signed_return * 10_000.0)
