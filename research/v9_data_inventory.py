"""V9 research data inventory helpers.

This module intentionally performs schema/coverage inspection only. It does not
load remote data or make trading decisions.
"""
from pathlib import Path
import csv
from typing import Dict

REQUIRED = ("timestamp", "symbol", "close")


def inspect_file(path: Path) -> Dict:
    path = Path(path)
    result = {
        "path": str(path),
        "valid": False,
        "rows": 0,
        "columns": [],
        "missing_required": [],
    }
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        columns = list(reader.fieldnames or [])
        result["columns"] = columns
        result["missing_required"] = [c for c in REQUIRED if c not in columns]
        if result["missing_required"]:
            return result
        result["rows"] = sum(1 for _ in reader)
    result["valid"] = True
    return result
