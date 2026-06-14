from __future__ import annotations

import json
import sqlite3
from collections import Counter
from statistics import median
from typing import Any

from core.schema.stance import dimensions_for_role
from core.store.db import connect


def aggregate_ordinal(
    scan_id: str,
    role: str,
    dim_key: str,
    *,
    db_path: str = "~/macro-strategy/analyst_views.db",
) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        return aggregate_ordinal_conn(conn, scan_id, role, dim_key)
    finally:
        conn.close()


def aggregate_categorical(
    scan_id: str,
    role: str,
    dim_key: str,
    *,
    db_path: str = "~/macro-strategy/analyst_views.db",
) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        return aggregate_categorical_conn(conn, scan_id, role, dim_key)
    finally:
        conn.close()


def who_mentioned_entity(
    scan_id: str,
    entity_canonical_id: str,
    *,
    db_path: str = "~/macro-strategy/analyst_views.db",
) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        rows = conn.execute(
            """
            SELECT ss.scan_id, ss.analyst_id, a.institution, a.role, ss.dim_key, ss.tag_text, ss.lean,
                   ss.evidence_ref, ss.verbatim
            FROM stance_selection ss
            JOIN analyst a ON a.analyst_id = ss.analyst_id
            WHERE ss.scan_id=? AND ss.tag_canonical_id=?
            ORDER BY a.role, a.institution, ss.dim_key, ss.tag_text
            """,
            (scan_id, entity_canonical_id),
        ).fetchall()
        return [attach_source_url(conn, dict(row)) for row in rows]
    finally:
        conn.close()


def who_mentioned_entity_history(
    entity_canonical_id: str,
    *,
    db_path: str = "~/macro-strategy/analyst_views.db",
    weeks: int | None = None,
) -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        scan_rows = conn.execute(
            """
            SELECT scan_id
            FROM scan
            ORDER BY window_start DESC, scan_id DESC
            """
        ).fetchall()
        scan_ids = [row["scan_id"] for row in scan_rows]
        if weeks is not None:
            scan_ids = scan_ids[: max(0, int(weeks))]
        if not scan_ids:
            return []
        placeholders = ",".join("?" for _ in scan_ids)
        rows = conn.execute(
            f"""
            SELECT ss.scan_id, sc.window_start, sc.window_end, ss.analyst_id, a.institution, a.role,
                   ss.dim_key, ss.tag_text, ss.lean, ss.evidence_ref, ss.verbatim
            FROM stance_selection ss
            JOIN analyst a ON a.analyst_id = ss.analyst_id
            JOIN scan sc ON sc.scan_id = ss.scan_id
            WHERE ss.tag_canonical_id=? AND ss.scan_id IN ({placeholders})
            ORDER BY sc.window_start DESC, a.role, a.institution, ss.dim_key, ss.tag_text
            """,
            (entity_canonical_id, *scan_ids),
        ).fetchall()
        return [attach_source_url(conn, dict(row)) for row in rows]
    finally:
        conn.close()


def aggregate_ordinal_conn(conn: sqlite3.Connection, scan_id: str, role: str, dim_key: str) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT s.*, a.institution, a.role
        FROM stance s
        JOIN analyst a ON a.analyst_id = s.analyst_id
        WHERE s.scan_id=? AND a.role=? AND s.dim_key=?
        ORDER BY a.institution
        """,
        (scan_id, role, dim_key),
    ).fetchall()
    values = [int(row["value"]) for row in rows if row["value"] is not None]
    counts = Counter(values)
    mode_value = None
    if counts:
        mode_value = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]
    dim_def = dimensions_for_role(role)[dim_key]
    teams = [attach_source_url(conn, dict(row)) for row in rows if row["value"] is not None]
    return {
        "scan_id": scan_id,
        "role": role,
        "dim_key": dim_key,
        "n_teams": len(rows),
        "n_non_null": len(values),
        "median": median(values) if values else None,
        "mode": mode_value,
        "mode_label": dim_def.get("values", {}).get(mode_value) if mode_value is not None else None,
        "n_bullish": sum(1 for value in values if value > 0),
        "n_neutral": sum(1 for value in values if value == 0),
        "n_bearish": sum(1 for value in values if value < 0),
        "dispersion_range": max(values) - min(values) if values else None,
        "teams": teams,
    }


def aggregate_categorical_conn(conn: sqlite3.Connection, scan_id: str, role: str, dim_key: str) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT ss.*, a.institution, a.role
        FROM stance_selection ss
        JOIN analyst a ON a.analyst_id = ss.analyst_id
        WHERE ss.scan_id=? AND a.role=? AND ss.dim_key=?
        ORDER BY ss.tag_text, a.institution
        """,
        (scan_id, role, dim_key),
    ).fetchall()
    grouped: dict[tuple[str, str | None], dict[str, Any]] = {}
    for row in rows:
        key = (row["tag_text"], row["tag_canonical_id"])
        item = grouped.setdefault(
            key,
            {
                "tag": row["tag_text"],
                "tag_canonical_id": row["tag_canonical_id"],
                "positive_count": 0,
                "negative_count": 0,
                "neutral_count": 0,
                "teams": [],
            },
        )
        lean = int(row["lean"])
        if lean > 0:
            item["positive_count"] += 1
        elif lean < 0:
            item["negative_count"] += 1
        else:
            item["neutral_count"] += 1
        item["teams"].append(attach_source_url(conn, dict(row)))

    tags = list(grouped.values())
    top_positive = sorted(
        [item for item in tags if item["positive_count"] > 0],
        key=lambda item: (-item["positive_count"], item["negative_count"], item["tag"]),
    )
    top_negative = sorted(
        [item for item in tags if item["negative_count"] > 0],
        key=lambda item: (-item["negative_count"], item["positive_count"], item["tag"]),
    )
    disputed = sorted(
        [item for item in tags if item["positive_count"] > 0 and item["negative_count"] > 0],
        key=lambda item: (-(item["positive_count"] + item["negative_count"]), item["tag"]),
    )
    return {
        "scan_id": scan_id,
        "role": role,
        "dim_key": dim_key,
        "n_mentions": len(rows),
        "top_positive_tags": top_positive,
        "top_negative_tags": top_negative,
        "disputed_tags": disputed,
    }


def entity_mention_summary(conn: sqlite3.Connection, scan_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT ss.tag_text, ss.tag_canonical_id, ss.lean, ss.analyst_id, a.institution
        FROM stance_selection ss
        JOIN analyst a ON a.analyst_id = ss.analyst_id
        WHERE ss.scan_id=? AND ss.tag_canonical_id IS NOT NULL
        ORDER BY ss.tag_canonical_id, a.institution
        """,
        (scan_id,),
    ).fetchall()
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = row["tag_canonical_id"]
        item = grouped.setdefault(
            key,
            {"entity": key, "tag": row["tag_text"], "positive": 0, "negative": 0, "neutral": 0, "teams": set()},
        )
        lean = int(row["lean"])
        if lean > 0:
            item["positive"] += 1
        elif lean < 0:
            item["negative"] += 1
        else:
            item["neutral"] += 1
        item["teams"].add(row["analyst_id"])
    out = []
    for item in grouped.values():
        item["teams"] = sorted(item["teams"])
        out.append(item)
    return sorted(out, key=lambda item: (-(item["positive"] + item["negative"] + item["neutral"]), item["entity"]))


def attach_source_url(conn: sqlite3.Connection, row: dict[str, Any]) -> dict[str, Any]:
    refs = parse_json_list(row.get("evidence_ref"))
    source_url = None
    source_type = None
    if refs:
        source = conn.execute(
            """
            SELECT url, source_type FROM source
            WHERE scan_id=? AND analyst_id=? AND source_id=?
            """,
            (row["scan_id"], row["analyst_id"], refs[0]),
        ).fetchone()
        if source:
            source_url = source["url"]
            source_type = source["source_type"]
    row["source_url"] = source_url
    row["source_type"] = source_type
    row["evidence_ref"] = refs
    return row


def parse_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def build_cross_section(scan_id: str, *, db_path: str = "~/macro-strategy/analyst_views.db") -> dict[str, Any]:
    conn = connect(db_path)
    try:
        counts = scan_row_counts(conn, scan_id)
        ensure_scan_has_data(scan_id, counts)
        result = {
            "scan_id": scan_id,
            "db_counts": counts,
            "macro": {},
            "strategy": {},
            "entities": entity_mention_summary(conn, scan_id),
        }
        for role in ["macro", "strategy"]:
            for dim_key, dim_def in dimensions_for_role(role).items():
                if dim_def["type"] == "ordinal":
                    result[role][dim_key] = aggregate_ordinal_conn(conn, scan_id, role, dim_key)
                else:
                    result[role][dim_key] = aggregate_categorical_conn(conn, scan_id, role, dim_key)
        return result
    finally:
        conn.close()


def scan_row_counts(conn: sqlite3.Connection, scan_id: str) -> dict[str, int]:
    return {
        "scan": int(conn.execute("SELECT COUNT(*) FROM scan WHERE scan_id=?", (scan_id,)).fetchone()[0]),
        "stance": int(conn.execute("SELECT COUNT(*) FROM stance WHERE scan_id=?", (scan_id,)).fetchone()[0]),
        "stance_selection": int(
            conn.execute("SELECT COUNT(*) FROM stance_selection WHERE scan_id=?", (scan_id,)).fetchone()[0]
        ),
        "source": int(conn.execute("SELECT COUNT(*) FROM source WHERE scan_id=?", (scan_id,)).fetchone()[0]),
        "intra_window_change": int(
            conn.execute("SELECT COUNT(*) FROM intra_window_change WHERE scan_id=?", (scan_id,)).fetchone()[0]
        ),
    }


def ensure_scan_has_data(scan_id: str, counts: dict[str, int]) -> None:
    if counts.get("scan", 0) != 1:
        raise ValueError(f"scan not found in SQLite: {scan_id}")
    if counts.get("stance", 0) <= 0:
        raise ValueError(f"no stance rows found in SQLite for scan: {scan_id}")
    if counts.get("source", 0) <= 0:
        raise ValueError(f"no source rows found in SQLite for scan: {scan_id}")
