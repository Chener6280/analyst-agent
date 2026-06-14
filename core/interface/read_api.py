from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.schema.stance import dimensions_for_role
from core.store.db import connect
from core.store.queries import (
    aggregate_categorical_conn,
    aggregate_ordinal_conn,
    attach_source_url,
    ensure_scan_has_data,
    scan_row_counts,
    who_mentioned_entity,
)

INTERFACE_VERSION = 1


def build_agent_handoff(
    scan_id: str,
    *,
    output_root: str | Path = "~/macro-strategy",
    db_path: str | Path = "~/macro-strategy/analyst_views.db",
) -> dict[str, Any]:
    output_dir = Path(output_root).expanduser()
    scan_dir = output_dir / "scans" / scan_id
    reports_dir = scan_dir / "reports"
    brief = read_required_json(reports_dir / "weekly_brief.json")
    cross_section = read_required_json(reports_dir / "weekly_cross_section.json")
    acceptance = read_json(output_dir / "diagnostics" / f"{scan_id}__mvp_acceptance.json") or read_json(
        output_dir / "diagnostics" / "mvp_acceptance.json"
    )
    counts = read_db_counts(scan_id, db_path=db_path)
    ensure_scan_has_data(scan_id, counts)

    return {
        "interface_version": INTERFACE_VERSION,
        "scan_id": scan_id,
        "status": "ready" if acceptance.get("passed") is True else "review_required",
        "headline": brief.get("headline"),
        "artifacts": {
            "database": str(Path(db_path).expanduser()),
            "weekly_brief_md": str(reports_dir / "weekly_brief.md"),
            "weekly_brief_json": str(reports_dir / "weekly_brief.json"),
            "weekly_cross_section_md": str(reports_dir / "weekly_cross_section.md"),
            "weekly_cross_section_json": str(reports_dir / "weekly_cross_section.json"),
            "mvp_acceptance": str(output_dir / "diagnostics" / f"{scan_id}__mvp_acceptance.md"),
        },
        "db_counts": counts,
        "quality": brief.get("quality", {}),
        "macro": compact_ordinal_list(brief.get("macro", [])),
        "strategy": {
            "ordinals": compact_ordinal_list((brief.get("strategy") or {}).get("ordinals", [])),
            "categories": compact_category_list((brief.get("strategy") or {}).get("categories", [])),
        },
        "top_entities": (cross_section.get("entities") or [])[:10],
        "supported_queries": supported_queries(scan_id, cross_section.get("entities") or []),
    }


def read_db_counts(scan_id: str, *, db_path: str | Path = "~/macro-strategy/analyst_views.db") -> dict[str, int]:
    conn = connect(db_path)
    try:
        return scan_row_counts(conn, scan_id)
    finally:
        conn.close()


def get_dimension_summary(
    scan_id: str,
    role: str,
    dim_key: str,
    *,
    db_path: str | Path = "~/macro-strategy/analyst_views.db",
) -> dict[str, Any]:
    dim_def = dimensions_for_role(role).get(dim_key)
    if dim_def is None:
        raise ValueError(f"unknown dimension for role={role}: {dim_key}")

    conn = connect(db_path)
    try:
        counts = scan_row_counts(conn, scan_id)
        ensure_scan_has_data(scan_id, counts)
        if dim_def["type"] == "ordinal":
            return aggregate_ordinal_conn(conn, scan_id, role, dim_key)
        return aggregate_categorical_conn(conn, scan_id, role, dim_key)
    finally:
        conn.close()


def get_team_stance(
    scan_id: str,
    analyst_id: str,
    *,
    db_path: str | Path = "~/macro-strategy/analyst_views.db",
) -> dict[str, Any]:
    conn = connect(db_path)
    try:
        counts = scan_row_counts(conn, scan_id)
        ensure_scan_has_data(scan_id, counts)
        analyst = conn.execute(
            "SELECT analyst_id, institution, role, team_members, official_accounts, active FROM analyst WHERE analyst_id=?",
            (analyst_id,),
        ).fetchone()
        stance_rows = conn.execute(
            """
            SELECT s.*, a.institution, a.role
            FROM stance s
            JOIN analyst a ON a.analyst_id = s.analyst_id
            WHERE s.scan_id=? AND s.analyst_id=?
            ORDER BY s.dim_key
            """,
            (scan_id, analyst_id),
        ).fetchall()
        selection_rows = conn.execute(
            """
            SELECT ss.*, a.institution, a.role
            FROM stance_selection ss
            JOIN analyst a ON a.analyst_id = ss.analyst_id
            WHERE ss.scan_id=? AND ss.analyst_id=?
            ORDER BY ss.dim_key, ss.tag_text
            """,
            (scan_id, analyst_id),
        ).fetchall()
        source_rows = conn.execute(
            """
            SELECT source_id, title, date, source, source_type, url, adapter_mode, text_access, attribution_confidence, escalated
            FROM source
            WHERE scan_id=? AND analyst_id=?
            ORDER BY source_id
            """,
            (scan_id, analyst_id),
        ).fetchall()
        return {
            "scan_id": scan_id,
            "analyst": row_to_dict(analyst) if analyst else {"analyst_id": analyst_id},
            "dimensions": [row_to_dict(attach_source_url(conn, dict(row))) for row in stance_rows],
            "selections": [row_to_dict(attach_source_url(conn, dict(row))) for row in selection_rows],
            "sources": [row_to_dict(row) for row in source_rows],
        }
    finally:
        conn.close()


def get_entity_mentions(
    scan_id: str,
    entity_canonical_id: str,
    *,
    db_path: str | Path = "~/macro-strategy/analyst_views.db",
) -> dict[str, Any]:
    return {
        "scan_id": scan_id,
        "entity_canonical_id": entity_canonical_id,
        "mentions": who_mentioned_entity(scan_id, entity_canonical_id, db_path=str(db_path)),
    }


def compact_ordinal_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "dim_key": item.get("dim_key"),
            "name": item.get("name"),
            "summary": item.get("summary"),
            "n_non_null": item.get("n_non_null"),
            "n_teams": item.get("n_teams"),
            "mode_label": item.get("mode_label"),
            "dispersion_range": item.get("dispersion_range"),
        }
        for item in items
    ]


def compact_category_list(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compacted = []
    for item in items:
        compacted.append(
            {
                "dim_key": item.get("dim_key"),
                "name": item.get("name"),
                "n_mentions": item.get("n_mentions"),
                "top_positive_tags": compact_tags(item.get("top_positive_tags", [])),
                "top_negative_tags": compact_tags(item.get("top_negative_tags", [])),
            }
        )
    return compacted


def compact_tags(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "tag": item.get("tag"),
            "positive_count": item.get("positive_count"),
            "negative_count": item.get("negative_count"),
            "neutral_count": item.get("neutral_count"),
        }
        for item in items[:5]
    ]


def supported_queries(scan_id: str, entities: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    base = "python3 scripts/query_agent_interface.py"
    entity_example = "ENTITY:EXAMPLE"
    if entities:
        entity_example = str(entities[0].get("entity") or entity_example)
    return [
        {
            "name": "scan-context",
            "description": "Return P5 handoff context for one scan.",
            "example": f"{base} scan-context --scan-id {scan_id}",
        },
        {
            "name": "dim-summary",
            "description": "Return one macro or strategy dimension summary from SQLite.",
            "example": f"{base} dim-summary --scan-id {scan_id} --role macro --dim-key growth",
        },
        {
            "name": "team-stance",
            "description": "Return all dimensions, selections, and sources for one analyst team.",
            "example": f"{base} team-stance --scan-id {scan_id} --analyst-id 广发证券:macro",
        },
        {
            "name": "who-mentioned",
            "description": "Return teams that mentioned one canonical entity.",
            "example": f"{base} who-mentioned --scan-id {scan_id} --entity {entity_example}",
        },
    ]


def row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    result = dict(row)
    for key in ["team_members", "official_accounts", "evidence_ref"]:
        if key in result:
            result[key] = parse_json_value(result[key])
    return result


def parse_json_value(value: Any) -> Any:
    if value is None:
        return None
    if value == "":
        return []
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def read_required_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"missing required P5 input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
