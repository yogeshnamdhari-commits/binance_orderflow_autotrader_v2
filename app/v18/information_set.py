from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence


@dataclass(frozen=True)
class MarketObservation:
    timestamp_ns: int
    source: str
    values: Mapping[str, float]


def asof_join(
    target_times: Sequence[int],
    observations: Sequence[MarketObservation],
    max_age_ns: int,
) -> list[dict[str, float | int | None]]:
    """Backward-only join: an observation must exist at or before the target."""
    ordered = sorted(observations, key=lambda x: (x.timestamp_ns, x.source))
    out: list[dict[str, float | int | None]] = []
    index = 0
    latest: MarketObservation | None = None

    for target in target_times:
        while index < len(ordered) and ordered[index].timestamp_ns <= target:
            latest = ordered[index]
            index += 1
        if latest is None or target - latest.timestamp_ns > max_age_ns:
            out.append({"timestamp_ns": target, "age_ns": None, "source": None})
            continue
        row: dict[str, float | int | None] = dict(latest.values)
        row["timestamp_ns"] = target
        row["age_ns"] = target - latest.timestamp_ns
        row["source"] = latest.source
        out.append(row)
    return out


def assemble_information_set(
    event_timestamp_ns: int,
    max_age_ns: int,
    *sources: Sequence[MarketObservation],
) -> dict[str, float | int | None]:
    """Assemble one decision-time vector using only observations available by the event."""
    result: dict[str, float | int | None] = {"timestamp_ns": event_timestamp_ns}
    for observations in sources:
        rows = asof_join([event_timestamp_ns], observations, max_age_ns)
        row = rows[0]
        source = row.pop("source", None)
        row.pop("timestamp_ns", None)
        age = row.pop("age_ns", None)
        if source is not None:
            result.update(row)
            result[f"{source}__age_ns"] = age
        else:
            for key in row:
                result[key] = None
    return result
