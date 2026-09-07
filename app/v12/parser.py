"""V12 data parser — reuses V10 raw schema parser.

Parses v10.raw.v1 schema (events.jsonl + snapshot.json) into structured data.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.v11.parser import V11DataParser


class V12DataParser:
    """V12 data parser — wrapper around V11 parser for v10.raw.v1 schema."""

    def __init__(self, session_dir: Path):
        self._parser = V11DataParser(session_dir)

    def parse(self) -> tuple[list, list]:
        """Parse session into book snapshots and trades."""
        return self._parser.parse()