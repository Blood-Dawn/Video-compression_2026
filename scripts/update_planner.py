#!/usr/bin/env python3
"""
Keep docs/PLANNER-FALL-2026.csv and docs/PLANNER-FALL-2026.md in sync.

Why this exists: the planner's own maintenance notes say "A planner that
does not match the report costs points from everyone" -- but the CSV (the
source used to populate the MS Teams Planner) and the Markdown (the
human-readable, per-week tables used for the roadmap and the weekly
report) were being hand-edited independently, and drifted. This script
makes the CSV the single source of truth for task status and regenerates
the Markdown "Status" column from it, so there is exactly one place to
update a task's progress.

Usage
-----
List every task and its current status:
    python scripts/update_planner.py list
    python scripts/update_planner.py list --week 3

Mark a task done (updates the CSV, then regenerates the Markdown):
    python scripts/update_planner.py set 3.1 Completed --date 2026-09-14
    python scripts/update_planner.py set 2.3 "Not started" --note "Carried to week 3."

Progress must be one of: "Not started", "In progress", "Completed"
(these are the three values Microsoft Planner itself uses).

Regenerate the Markdown Status columns from the CSV without changing any
task's progress (e.g. after hand-editing the CSV):
    python scripts/update_planner.py sync-md

Check that the Markdown Status columns already agree with the CSV
(exit code 1 on any mismatch -- wire this into a pre-commit hook or CI):
    python scripts/update_planner.py check

Note: Microsoft Planner has no supported bulk CSV import/export for an
existing plan, so a completed task still needs its checkbox ticked by
hand in Teams. This script only keeps the two files *in this repo*
honest with each other; treat the CSV as the thing you update first.

Author: Bloodawn (KheivenD), 2026-09-15.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = REPO_ROOT / "docs" / "PLANNER-FALL-2026.csv"
MD_PATH = REPO_ROOT / "docs" / "PLANNER-FALL-2026.md"

VALID_PROGRESS = ("Not started", "In progress", "Completed")

CSV_FIELDS = [
    "Task Name",
    "Bucket Name",
    "Assigned To",
    "Start Date",
    "Due Date",
    "Progress",
    "Completed Date",
    "Notes",
]

TASK_ID_RE = re.compile(r"^(\d+\.\d+)\s+(.*)$")


def task_id_of(task_name: str) -> str | None:
    m = TASK_ID_RE.match(task_name.strip())
    return m.group(1) if m else None


def read_csv_rows() -> list[dict]:
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    # Older copies of the CSV predate the "Completed Date" column; backfill
    # it so DictWriter doesn't choke on a missing key.
    for row in rows:
        row.setdefault("Completed Date", "")
    return rows


def write_csv_rows(rows: list[dict]) -> None:
    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})


def short_date(iso: str) -> str:
    """'2026-09-14' -> 'Sep 14' (matches the Week 1 table's existing style).

    Deliberately avoids the %-d / %e strftime extensions (glibc-only, not
    available on Windows Python) so this runs the same in PowerShell as it
    does anywhere else.
    """
    d = datetime.date.fromisoformat(iso)
    return f"{d.strftime('%b')} {d.day}"


CARRIED_RE = re.compile(r"Carried to week (\d+)")


def status_text(row: dict) -> str:
    progress = row.get("Progress", "Not started").strip() or "Not started"
    if progress == "Completed":
        cdate = (row.get("Completed Date") or "").strip()
        return f"Complete {short_date(cdate)}" if cdate else "Complete"
    # A slipped task keeps Progress = "Not started" (that is still true, and
    # is the only value Planner itself understands), but the Notes column
    # can flag *why* -- surface that in the Status cell instead of a bare
    # "Not started" so the roadmap reads the same way the weekly report
    # explains it.
    m = CARRIED_RE.search(row.get("Notes") or "")
    if m and progress != "In progress":
        return f"Carried to week {m.group(1)}"
    return progress


def cmd_list(args: argparse.Namespace) -> int:
    rows = read_csv_rows()
    for row in rows:
        tid = task_id_of(row["Task Name"])
        if tid is None:
            continue
        if args.week is not None and not tid.startswith(f"{args.week}."):
            continue
        print(f"{tid:<6} {status_text(row):<16} {row['Assigned To']:<26} {row['Task Name']}")
    return 0


def cmd_set(args: argparse.Namespace) -> int:
    if args.progress not in VALID_PROGRESS:
        print(f"error: Progress must be one of {VALID_PROGRESS}, got {args.progress!r}", file=sys.stderr)
        return 2

    rows = read_csv_rows()
    matched = [row for row in rows if task_id_of(row["Task Name"]) == args.task_id]
    if not matched:
        print(f"error: no task with ID {args.task_id!r} in {CSV_PATH}", file=sys.stderr)
        return 1

    for row in matched:
        row["Progress"] = args.progress
        if args.progress == "Completed":
            row["Completed Date"] = args.date or datetime.date.today().isoformat()
        else:
            row["Completed Date"] = ""
        if args.note:
            existing = (row.get("Notes") or "").strip()
            row["Notes"] = f"{existing} {args.note}".strip() if (args.append and existing) else args.note

    write_csv_rows(rows)
    for row in matched:
        print(f"updated {args.task_id}: Progress={row['Progress']!r}"
              + (f", Completed Date={row['Completed Date']!r}" if row["Progress"] == "Completed" else ""))

    return cmd_sync_md(args, quiet=True)


TABLE_HEADER_RE = re.compile(r"^\|\s*ID\s*\|\s*Task\s*\|\s*Owner\s*\|\s*Outcome\s*(\|\s*Status\s*)?\|\s*$")


def _find_tables(lines: list[str]) -> list[tuple[int, int]]:
    """Return (header_index, separator_index) for every planner task table."""
    spans = []
    for i, line in enumerate(lines):
        if TABLE_HEADER_RE.match(line.strip()):
            if i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
                spans.append((i, i + 1))
    return spans


def _split_row(line: str) -> list[str]:
    inner = line.strip()
    assert inner.startswith("|") and inner.endswith("|")
    return [c.strip() for c in inner[1:-1].split("|")]


def _join_row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def regenerate_markdown(rows_by_id: dict[str, dict]) -> tuple[str, int]:
    """Rewrite every week table's Status column. Returns (new_text, rows_changed)."""
    text = MD_PATH.read_text(encoding="utf-8")
    lines = text.split("\n")
    changed = 0

    for header_idx, sep_idx in _find_tables(lines):
        header_cells = _split_row(lines[header_idx])
        has_status = len(header_cells) == 5
        if not has_status:
            lines[header_idx] = _join_row(header_cells + ["Status"])
            sep_cells = _split_row(lines[sep_idx])
            lines[sep_idx] = _join_row(sep_cells + ["---"])

        i = sep_idx + 1
        while i < len(lines) and lines[i].strip().startswith("|"):
            cells = _split_row(lines[i])
            tid = cells[0].strip()
            row = rows_by_id.get(tid)
            if row is not None:
                new_status = status_text(row)
                if len(cells) >= 5:
                    if cells[4] != new_status:
                        cells[4] = new_status
                        changed += 1
                else:
                    cells = cells + [new_status]
                    changed += 1
                lines[i] = _join_row(cells)
            i += 1

    return "\n".join(lines), changed


def cmd_sync_md(args: argparse.Namespace, quiet: bool = False) -> int:
    rows = read_csv_rows()
    rows_by_id = {task_id_of(r["Task Name"]): r for r in rows if task_id_of(r["Task Name"])}
    new_text, changed = regenerate_markdown(rows_by_id)
    MD_PATH.write_text(new_text, encoding="utf-8")
    if not quiet:
        print(f"synced {changed} Status cell(s) in {MD_PATH}")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    rows = read_csv_rows()
    rows_by_id = {task_id_of(r["Task Name"]): r for r in rows if task_id_of(r["Task Name"])}
    current = MD_PATH.read_text(encoding="utf-8")
    regenerated, _ = regenerate_markdown(rows_by_id)
    if current == regenerated:
        print("OK: planner Markdown matches planner CSV.")
        return 0
    print("MISMATCH: docs/PLANNER-FALL-2026.md is out of sync with docs/PLANNER-FALL-2026.csv.")
    print("Run: python scripts/update_planner.py sync-md")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="Print every task and its current status.")
    p_list.add_argument("--week", type=int, default=None, help="Only show tasks NN.* for this week number.")
    p_list.set_defaults(func=cmd_list)

    p_set = sub.add_parser("set", help="Update one task's Progress in the CSV, then re-sync the Markdown.")
    p_set.add_argument("task_id", help='Task ID, e.g. "3.1"')
    p_set.add_argument("progress", help=f'One of {VALID_PROGRESS}')
    p_set.add_argument("--date", default=None, help="Completion date (YYYY-MM-DD). Defaults to today when marking Completed.")
    p_set.add_argument("--note", default=None, help="Set (or append with --append) the Notes cell.")
    p_set.add_argument("--append", action="store_true", help="Append --note to the existing Notes instead of replacing it.")
    p_set.set_defaults(func=cmd_set)

    p_sync = sub.add_parser("sync-md", help="Regenerate the Markdown Status columns from the CSV.")
    p_sync.set_defaults(func=cmd_sync_md)

    p_check = sub.add_parser("check", help="Exit 1 if the Markdown Status columns disagree with the CSV.")
    p_check.set_defaults(func=cmd_check)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
