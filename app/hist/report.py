"""Assemble the 2-year availability report (JSON + markdown)."""

from datetime import date
from pathlib import Path
import json


def available_dates(avail_payload, dtype):
    return [d for d, rec in avail_payload["detail"][dtype].items() if rec.get("status") == 200]


def coverage_title(dates, payload):
    dlist = sorted(dates)
    if not dlist:
        return "no data"
    n = len(dlist)
    total = payload["types"][next(iter(payload["types"]))].get("num_dates", 0)
    pct = 100.0 * n / total if total else 0.0
    return "available %d/%d days (%.1f%%)" % (n, total, pct)


def coverage_gaps(dates, payload):
    """Dates inside [start,end] where type is missing while neighbours exist."""
    start = date.fromisoformat(payload["start"])
    end = date.fromisoformat(payload["end"])
    all_days = [d.isoformat() for d in (start + __import__("datetime").timedelta(days=i)
                                        for i in range((end - start).days + 1))]
    present = set(dates)
    gaps = []
    for i, day in enumerate(all_days):
        if day in present:
            continue
        before_ok = any(prev in present for prev in all_days[max(0, i - 5):i])
        after_ok = any(nxt in present for nxt in all_days[i + 1:i + 6])
        if before_ok and after_ok:
            gaps.append(day)
    return gaps


def build_report(payload, integrity_rows, l2_comment, out_dir):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append("# Binance USD-M Futures historical-data availability report")
    lines.append("")
    lines.append("- Audit date: %s" % payload["audit_date_iso"])
    lines.append("- Symbol: %s" % payload["symbol"])
    lines.append("- Window: %s .. %s" % (payload["start"], payload["end"]))
    lines.append("- Source: %s" % payload["source"])
    lines.append("- Reference: %s" % payload["reference"])
    lines.append("")
    lines.append("## Coverage by archive type")
    lines.append("")
    lines.append("| type | coverage | first day | last day | coverage gaps (inside window) |")
    lines.append("|---|---|---|---|---|")
    for t in payload["types"]:
        dates = available_dates(payload, t)
        gaps = coverage_gaps(dates, payload)
        first = min(dates) if dates else "-"
        last = max(dates) if dates else "-"
        lines.append("| %s | %s | %s | %s | %s |" % (t, coverage_title(dates, payload), first, last,
                                                 "; ".join(gaps[:8]) if gaps else "-"))
    lines.append("")
    lines.append("## Authentic historical L2 (T_DEPTH)")
    lines.append("")
    lines.append(l2_comment)
    lines.append("")
    lines.append("## Integrity + gap audit (sampled days)")
    lines.append("")
    lines.append("| date | type | checksum | rows | id_gaps | id_gap_rows | dup/desc ids | ts_out_of_order | first_ts | last_ts |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    if not integrity_rows:
        lines.append("| _none yet_ | | | | | | | | | |")
    for r in integrity_rows:
        lines.append("| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |" % (
            r.get("date"), r.get("type"), r.get("checksum"), r.get("rows"),
            r.get("id_gaps"), r.get("id_gap_rows"), r.get("duplicate_or_desc_ids"),
            r.get("ts_out_of_order"), r.get("first_transact_time"), r.get("last_transact_time")))
    lines.append("")
    lines.append("## Milestone conclusion")
    lines.append("")
    lines.append("- Aggregate trades (authentic, checksum-verified): above coverage. These support Delta/CVD/trade-flow features.")
    lines.append("- Tick-by-tick L2 (T_DEPTH): separate Binance facility; coverage NOT claimable until authenticated access + audit.")
    lines.append("- Order-flow research requiring L2 (imbalance, OFI) is gated on L2 availability and is NOT reconstructed from candles.")
    lines.append("- A historical day with no authentic L2 is explicitly marked unavailable, never synthesized.")
    lines.append("")
    text = "\n".join(lines)
    (out_dir / "report.md").write_text(text, encoding="utf-8")
    bundle = dict(payload)
    bundle["integrity_audit"] = integrity_rows
    bundle["l2_comment"] = l2_comment
    (out_dir / "report.json").write_text(json.dumps(bundle, indent=2, default=str))
    return text