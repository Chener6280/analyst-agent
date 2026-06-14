from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from core.schema.stance import dimensions_for_role
from core.store.db import connect
from core.store.queries import aggregate_categorical_conn, aggregate_ordinal_conn, scan_row_counts

HISTORY_INTERFACE_VERSION = 1


def build_history_readiness(
    current_scan_id: str,
    *,
    db_path: str | Path = "~/macro-strategy/analyst_views.db",
    min_scans: int = 4,
) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        scans = list_scans_conn(conn)
        current = next((item for item in scans if item["scan_id"] == current_scan_id), None)
        current_counts = scan_row_counts(conn, current_scan_id) if current else {}
        status = history_status(scans, current, current_counts, min_scans)
        examples = build_history_examples(conn, current_scan_id)
        return {
            "interface_version": HISTORY_INTERFACE_VERSION,
            "scan_id": current_scan_id,
            "status": status,
            "min_scans_for_trend": min_scans,
            "available_scan_count": len(scans),
            "missing_scan_count": max(min_scans - len(scans), 0),
            "current_scan_counts": current_counts,
            "available_scans": scans,
            "examples": examples,
            "notes": build_notes(status, min_scans, len(scans)),
            "supported_queries": supported_history_queries(current_scan_id),
        }
    finally:
        conn.close()


def list_scans(*, db_path: str | Path = "~/macro-strategy/analyst_views.db") -> list[dict[str, Any]]:
    conn = connect(db_path)
    try:
        return list_scans_conn(conn)
    finally:
        conn.close()


def list_scans_conn(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT sc.scan_id, sc.iso_year, sc.iso_week, sc.window_start, sc.window_end, sc.mode, sc.created_at,
               COUNT(DISTINCT st.analyst_id) AS team_count,
               COUNT(st.dim_key) AS stance_rows
        FROM scan sc
        LEFT JOIN stance st ON st.scan_id = sc.scan_id
        GROUP BY sc.scan_id
        ORDER BY sc.iso_year, sc.iso_week, sc.window_start, sc.scan_id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def history_status(
    scans: list[dict[str, Any]],
    current: dict[str, Any] | None,
    current_counts: dict[str, int],
    min_scans: int,
) -> str:
    if current is None:
        return "missing_current_scan"
    if int(current_counts.get("stance") or 0) <= 0:
        return "missing_current_stance"
    if len(scans) < min_scans:
        return "insufficient_history"
    return "ready"


def build_consensus_series(
    role: str,
    dim_key: str,
    *,
    db_path: str | Path = "~/macro-strategy/analyst_views.db",
    limit: int | None = None,
) -> dict[str, Any]:
    dim_def = dimensions_for_role(role).get(dim_key)
    if dim_def is None or dim_def["type"] != "ordinal":
        raise ValueError(f"consensus series requires an ordinal dimension: role={role} dim_key={dim_key}")

    conn = connect(db_path)
    try:
        scans = list_scans_conn(conn)
        if limit is not None:
            scans = scans[-limit:]
        points = []
        for scan in scans:
            item = aggregate_ordinal_conn(conn, scan["scan_id"], role, dim_key)
            points.append(
                {
                    "scan_id": scan["scan_id"],
                    "iso_year": scan.get("iso_year"),
                    "iso_week": scan.get("iso_week"),
                    "window_start": scan.get("window_start"),
                    "window_end": scan.get("window_end"),
                    "n_teams": item.get("n_teams"),
                    "n_non_null": item.get("n_non_null"),
                    "median": item.get("median"),
                    "mode": item.get("mode"),
                    "mode_label": item.get("mode_label"),
                    "dispersion_range": item.get("dispersion_range"),
                }
            )
        return {
            "role": role,
            "dim_key": dim_key,
            "name": dim_def["name"],
            "axis": dim_def["axis"],
            "points": points,
            "changes": point_changes(points, "median"),
        }
    finally:
        conn.close()


def build_team_series(
    analyst_id: str,
    dim_key: str,
    *,
    db_path: str | Path = "~/macro-strategy/analyst_views.db",
    limit: int | None = None,
) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        scans = list_scans_conn(conn)
        if limit is not None:
            scans = scans[-limit:]
        analyst = conn.execute(
            "SELECT analyst_id, institution, role FROM analyst WHERE analyst_id=?",
            (analyst_id,),
        ).fetchone()
        points = []
        for scan in scans:
            row = conn.execute(
                """
                SELECT value, label, confidence, coverage, text_access, attribution_confidence, evidence_ref, verbatim
                FROM stance
                WHERE scan_id=? AND analyst_id=? AND dim_key=?
                """,
                (scan["scan_id"], analyst_id, dim_key),
            ).fetchone()
            points.append(
                {
                    "scan_id": scan["scan_id"],
                    "iso_year": scan.get("iso_year"),
                    "iso_week": scan.get("iso_week"),
                    "window_start": scan.get("window_start"),
                    "window_end": scan.get("window_end"),
                    "value": row["value"] if row else None,
                    "label": row["label"] if row else None,
                    "confidence": row["confidence"] if row else None,
                    "verbatim": row["verbatim"] if row else None,
                }
            )
        return {
            "analyst": dict(analyst) if analyst else {"analyst_id": analyst_id},
            "dim_key": dim_key,
            "points": points,
            "changes": point_changes(points, "value"),
        }
    finally:
        conn.close()


def build_tag_rotation(
    role: str,
    dim_key: str,
    *,
    db_path: str | Path = "~/macro-strategy/analyst_views.db",
    limit: int | None = None,
    top_n: int = 10,
) -> dict[str, Any]:
    dim_def = dimensions_for_role(role).get(dim_key)
    if dim_def is None or dim_def["type"] != "categorical":
        raise ValueError(f"tag rotation requires a categorical dimension: role={role} dim_key={dim_key}")

    conn = connect(db_path)
    try:
        scans = list_scans_conn(conn)
        if limit is not None:
            scans = scans[-limit:]
        points = []
        for scan in scans:
            item = aggregate_categorical_conn(conn, scan["scan_id"], role, dim_key)
            points.append(
                {
                    "scan_id": scan["scan_id"],
                    "iso_year": scan.get("iso_year"),
                    "iso_week": scan.get("iso_week"),
                    "window_start": scan.get("window_start"),
                    "window_end": scan.get("window_end"),
                    "n_mentions": item.get("n_mentions"),
                    "top_positive_tags": compact_tags(item.get("top_positive_tags", []), top_n),
                    "top_negative_tags": compact_tags(item.get("top_negative_tags", []), top_n),
                    "disputed_tags": compact_tags(item.get("disputed_tags", []), top_n),
                }
            )
        return {"role": role, "dim_key": dim_key, "name": dim_def["name"], "points": points}
    finally:
        conn.close()


def build_history_examples(conn: sqlite3.Connection, current_scan_id: str) -> dict[str, Any]:
    examples: dict[str, Any] = {}
    if scan_row_counts(conn, current_scan_id).get("stance", 0) > 0:
        growth = aggregate_ordinal_conn(conn, current_scan_id, "macro", "growth")
        examples["current_growth"] = {
            "n_non_null": growth.get("n_non_null"),
            "mode_label": growth.get("mode_label"),
            "median": growth.get("median"),
            "dispersion_range": growth.get("dispersion_range"),
        }
        sector = aggregate_categorical_conn(conn, current_scan_id, "strategy", "sector")
        examples["current_sector"] = {
            "n_mentions": sector.get("n_mentions"),
            "top_positive_tags": compact_tags(sector.get("top_positive_tags", []), 5),
            "top_negative_tags": compact_tags(sector.get("top_negative_tags", []), 5),
        }
    return examples


def point_changes(points: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    changes = []
    previous = None
    for point in points:
        value = point.get(key)
        if previous is not None and previous.get(key) is not None and value is not None and value != previous.get(key):
            changes.append(
                {
                    "from_scan_id": previous["scan_id"],
                    "to_scan_id": point["scan_id"],
                    "from": previous.get(key),
                    "to": value,
                    "delta": value - previous.get(key) if isinstance(value, (int, float)) else None,
                }
            )
        previous = point
    return changes


def compact_tags(items: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    return [
        {
            "tag": item.get("tag"),
            "tag_canonical_id": item.get("tag_canonical_id"),
            "positive_count": item.get("positive_count"),
            "negative_count": item.get("negative_count"),
            "neutral_count": item.get("neutral_count"),
        }
        for item in items[:top_n]
    ]


def build_notes(status: str, min_scans: int, available: int) -> list[str]:
    if status == "ready":
        return [f"History has {available} scans, meeting the {min_scans}-scan trend threshold."]
    if status == "insufficient_history":
        return [
            f"History has {available} scan(s), below the {min_scans}-scan trend threshold.",
            "P6 query functions are available, but trend interpretation should wait for more real weekly runs.",
        ]
    if status == "missing_current_scan":
        return ["Current scan is not present in SQLite; rerun ingest before history export."]
    if status == "missing_current_stance":
        return ["Current scan has no stance rows; rerun extraction and ingest before history export."]
    return [f"Unexpected history status: {status}."]


def supported_history_queries(scan_id: str) -> list[dict[str, Any]]:
    base = "python3 scripts/query_agent_interface.py"
    return [
        {
            "name": "consensus-series",
            "description": "Return per-scan consensus for an ordinal dimension.",
            "example": f"{base} consensus-series --role macro --dim-key growth",
        },
        {
            "name": "team-series",
            "description": "Return one team's per-scan stance series for one dimension.",
            "example": f"{base} team-series --analyst-id 广发证券:macro --dim-key growth",
        },
        {
            "name": "tag-rotation",
            "description": "Return per-scan positive/negative categorical tags.",
            "example": f"{base} tag-rotation --role strategy --dim-key sector",
        },
        {
            "name": "history-readiness",
            "description": "Return P6 readiness for the current scan.",
            "example": f"{base} history-readiness --scan-id {scan_id}",
        },
    ]
