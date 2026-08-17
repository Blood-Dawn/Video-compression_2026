"""
src/gui/services/nl_query.py - structured natural-language search (R5 TASK 5.4).

Turns a phrase like "red car after 9pm on cam2" into parameterized SQL filters
over the existing ``segments`` metadata table (object_classes, dominant_color,
scene_type, time_of_day, camera_id, timestamp, person/vehicle counts).

Deliberately deterministic: a rules parser over the controlled vocabulary the
pipeline itself writes. No LLM, no network, no model download; it works on the
slim install and gives the same answer every time. Free text that the parser
does not recognize degrades to a LIKE match instead of erroring, and EVERY
value reaches SQLite as a bound parameter, never by string concatenation.

Author: Bloodawn (KheivenD), 2026-08-16 (R5 TASK 5.4).
"""

from __future__ import annotations

import re
from typing import Any

# Controlled vocabulary. Keys are the words a person types; values are what the
# pipeline writes into the DB columns.
_CLASS_WORDS = {
    "person": "person", "people": "person", "pedestrian": "person",
    "someone": "person", "man": "person", "woman": "person",
    "car": "car", "cars": "car", "vehicle": "car", "vehicles": "car",
    "truck": "truck", "trucks": "truck", "bus": "bus", "buses": "bus",
    "bike": "bicycle", "bicycle": "bicycle", "motorcycle": "motorcycle",
    "motorbike": "motorcycle", "dog": "dog", "cat": "cat",
}
_COLOR_WORDS = {
    "red": "red", "blue": "blue", "green": "green", "black": "black",
    "white": "white", "silver": "silver", "gray": "gray", "grey": "gray",
    "yellow": "yellow", "orange": "orange", "brown": "brown",
}
_SCENE_WORDS = {
    "highway": "highway", "intersection": "intersection",
    "parking": "parking", "street": "street",
}
_TOD_WORDS = {
    "night": "night", "nighttime": "night", "day": "day", "daytime": "day",
    "dusk": "dusk_dawn", "dawn": "dusk_dawn",
}
# Day-part words that map to hour ranges rather than the time_of_day column.
_DAYPART_HOURS = {
    "morning": (5, 12), "afternoon": (12, 17), "evening": (17, 21),
}
_STOPWORDS = {
    "a", "an", "the", "on", "in", "at", "of", "and", "or", "with", "show",
    "me", "all", "any", "find", "search", "for", "clips", "clip", "video",
    "videos", "segment", "segments", "footage", "from", "to",
}

_HOUR_EXPR = "CAST(strftime('%H', timestamp) AS INTEGER)"


def _to_24h(hour: int, ampm: str | None) -> int:
    hour = hour % 12 if ampm else hour
    if ampm == "pm":
        hour += 12
    return min(max(hour, 0), 23)


def parse(q: str) -> dict[str, Any]:
    """Parse a phrase into SQL filter clauses + bound params.

    Returns {"clauses": [sql...], "params": [...], "explain": {...}}.
    ``explain`` echoes what was understood so the UI can show it and the
    user can correct a misread instead of silently getting wrong results.
    """
    text = (q or "").strip().lower()
    clauses: list[str] = []
    params: list[Any] = []
    explain: dict[str, Any] = {}

    # Time windows first (their words must not fall through to free text).
    m = re.search(r"between\s+(\d{1,2})\s*(am|pm)?\s+and\s+(\d{1,2})\s*(am|pm)?", text)
    if m:
        h1 = _to_24h(int(m.group(1)), m.group(2))
        h2 = _to_24h(int(m.group(3)), m.group(4))
        lo, hi = min(h1, h2), max(h1, h2)
        clauses.append(f"{_HOUR_EXPR} >= ? AND {_HOUR_EXPR} < ?")
        params.extend([lo, hi])
        explain["hours"] = [lo, hi]
        text = text.replace(m.group(0), " ")
    m = re.search(r"after\s+(\d{1,2})(?::\d{2})?\s*(am|pm)?", text)
    if m:
        h = _to_24h(int(m.group(1)), m.group(2))
        clauses.append(f"{_HOUR_EXPR} >= ?")
        params.append(h)
        explain["after_hour"] = h
        text = text.replace(m.group(0), " ")
    m = re.search(r"before\s+(\d{1,2})(?::\d{2})?\s*(am|pm)?", text)
    if m:
        h = _to_24h(int(m.group(1)), m.group(2))
        clauses.append(f"{_HOUR_EXPR} < ?")
        params.append(h)
        explain["before_hour"] = h
        text = text.replace(m.group(0), " ")

    # Absolute date (ISO) and relative days. timestamp is TEXT, ISO-ordered,
    # so a date is a simple prefix match on the bound value.
    m = re.search(r"\b(20\d{2}-\d{2}-\d{2})\b", text)
    if m:
        clauses.append("timestamp LIKE ? || '%'")
        params.append(m.group(1))
        explain["date"] = m.group(1)
        text = text.replace(m.group(0), " ")
    for word, delta in (("today", 0), ("yesterday", 1)):
        if re.search(rf"\b{word}\b", text):
            from datetime import date, timedelta
            day = (date.today() - timedelta(days=delta)).isoformat()
            clauses.append("timestamp LIKE ? || '%'")
            params.append(day)
            explain["date"] = day
            text = re.sub(rf"\b{word}\b", " ", text)

    # Camera: "cam2", "camera 2", "camera_north".
    m = re.search(r"\bcam(?:era)?[\s_]*([a-z0-9_-]+)\b", text)
    if m:
        cam = m.group(1)
        clauses.append("camera_id LIKE '%' || ? || '%'")
        params.append(cam)
        explain["camera"] = cam
        text = text.replace(m.group(0), " ")

    # Count comparisons: "more than 2 people", "at least 3 cars".
    m = re.search(r"(?:more than|over|at least)\s+(\d+)\s+(people|persons|person|cars|vehicles)", text)
    if m:
        n = int(m.group(1))
        col = "person_count" if m.group(2).startswith("p") else "vehicle_count"
        op = ">=" if "at least" in m.group(0) else ">"
        clauses.append(f"{col} {op} ?")
        params.append(n)
        explain["count"] = {col: f"{op} {n}"}
        text = text.replace(m.group(0), " ")

    # Word-mapped filters over the remaining tokens.
    free_text: list[str] = []
    for token in re.findall(r"[a-z0-9_-]+", text):
        if token in _STOPWORDS:
            continue
        if token in _COLOR_WORDS:
            clauses.append("dominant_color = ?")
            params.append(_COLOR_WORDS[token])
            explain.setdefault("colors", []).append(_COLOR_WORDS[token])
        elif token in _CLASS_WORDS:
            # object_classes is a JSON array in TEXT (e.g. ["car","person"]);
            # a quoted LIKE match is exact per class name.
            clauses.append("(object_classes LIKE '%' || ? || '%' OR object_type = ?)")
            cls = _CLASS_WORDS[token]
            params.extend([f'"{cls}"', "vehicle" if cls in ("car", "truck", "bus") else cls])
            explain.setdefault("classes", []).append(cls)
        elif token in _SCENE_WORDS:
            clauses.append("scene_type = ?")
            params.append(_SCENE_WORDS[token])
            explain.setdefault("scenes", []).append(_SCENE_WORDS[token])
        elif token in _TOD_WORDS:
            clauses.append("time_of_day = ?")
            params.append(_TOD_WORDS[token])
            explain.setdefault("time_of_day", []).append(_TOD_WORDS[token])
        elif token in _DAYPART_HOURS:
            lo, hi = _DAYPART_HOURS[token]
            clauses.append(f"{_HOUR_EXPR} >= ? AND {_HOUR_EXPR} < ?")
            params.extend([lo, hi])
            explain["hours"] = [lo, hi]
        else:
            free_text.append(token)

    # Unknown words degrade to a broad LIKE, never an error (R5 acceptance).
    for token in free_text:
        clauses.append(
            "(object_classes LIKE '%' || ? || '%' OR camera_id LIKE '%' || ? || '%'"
            " OR scene_type LIKE '%' || ? || '%' OR file_path LIKE '%' || ? || '%')"
        )
        params.extend([token, token, token, token])
    if free_text:
        explain["free_text"] = free_text

    return {"clauses": clauses, "params": params, "explain": explain}


def search(q: str, db_path: str, limit: int = 100) -> dict[str, Any]:
    """Run a parsed phrase against the segments DB. Parameterized throughout.

    Runs the idempotent schema migration first: an archive DB written by an
    older SVCS lacks the v2 metadata columns (object_classes, dominant_color,
    scene_type, ...) because the ALTER TABLE migrations only ran at pipeline
    startup, so the first smart search against a real deployment's DB died
    with "no such column: object_classes". initialize_database() is designed
    to be re-run against old databases and adds only what is missing.
    """
    import sqlite3

    try:
        from utils.db.schema import initialize_database
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.utils.db.schema import initialize_database
    initialize_database(db_path)

    parsed = parse(q)
    where = " AND ".join(["(hidden IS NULL OR hidden = 0)"] + parsed["clauses"])
    sql = (
        "SELECT id, timestamp, camera_id, file_path, object_type, object_classes,"
        " dominant_color, scene_type, time_of_day, person_count, vehicle_count,"
        " duration, file_size FROM segments"
        f" WHERE {where} ORDER BY timestamp DESC LIMIT ?"
    )
    limit = max(1, min(int(limit), 500))
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(sql, [*parsed["params"], limit]).fetchall()
    finally:
        conn.close()
    return {
        "query": q,
        "explain": parsed["explain"],
        "count": len(rows),
        "segments": [dict(r) for r in rows],
    }
