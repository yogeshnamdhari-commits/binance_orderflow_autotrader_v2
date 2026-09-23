"""Deterministic parity checks for replayed versus reference book state."""
from __future__ import annotations
from collections.abc import Mapping


def compare_replay_states(replay: Mapping[str, object], reference: Mapping[str, object]) -> dict[str, object]:
    """Compare required state fields without silently filling missing values."""
    keys = sorted(set(replay) | set(reference))
    mismatches = [key for key in keys if replay.get(key) != reference.get(key)]
    return {
        "pass": not mismatches,
        "mismatches": mismatches,
        "compared_fields": keys,
    }
