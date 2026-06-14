from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from core.config import load_analyst_list

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = REPO_ROOT / "docs" / "db_schema.sql"
BAD_ADAPTER_MODES = {"mock", "placeholder"}


def connect(db_path: str | Path = "~/macro-strategy/analyst_views.db") -> sqlite3.Connection:
    conn = sqlite3.connect(Path(db_path).expanduser())
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection, schema_path: str | Path = SCHEMA_PATH) -> None:
    conn.executescript(Path(schema_path).read_text(encoding="utf-8"))
    ensure_column(conn, "source", "source_type", "TEXT")
    conn.commit()


def ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
    existing = {row["name"] if isinstance(row, sqlite3.Row) else row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


def ingest_scan(
    scan_dir: str | Path,
    *,
    db_path: str | Path = "~/macro-strategy/analyst_views.db",
    analyst_list_path: str | Path = "data/analyst-list.md",
) -> dict[str, Any]:
    scan_path = Path(scan_dir).expanduser()
    extracted_dir = scan_path / "extracted"
    stance_paths = sorted(extracted_dir.glob("*.stance.json"))
    if not stance_paths:
        raise FileNotFoundError(f"no stance JSON files found in {extracted_dir}")

    docs = [json.loads(path.read_text(encoding="utf-8")) for path in stance_paths]
    coverage = read_json(scan_path / "coverage_summary.json")
    config = read_json(scan_path / "config.json")

    db_file = Path(db_path).expanduser()
    db_file.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_file)
    try:
        init_db(conn)
        with conn:
            scan_id = ensure_single_scan_id(docs)
            upsert_analysts(conn, analyst_list_path)
            upsert_scan(conn, docs[0], config)
            purge_scan_rows(conn, scan_id)
            for doc in docs:
                ingest_stance_doc(conn, doc, coverage)
    finally:
        conn.close()

    return {
        "db_path": str(db_file),
        "scan_id": docs[0]["scan_id"],
        "stance_docs": len(docs),
        "stance_rows": sum(len(doc["dimensions"]) for doc in docs),
        "selection_rows": sum(len(doc.get("selections", [])) for doc in docs),
        "source_rows": sum(len(doc.get("sources", [])) for doc in docs),
    }


def ensure_single_scan_id(docs: list[dict[str, Any]]) -> str:
    scan_ids = {doc.get("scan_id") for doc in docs}
    if len(scan_ids) != 1:
        raise ValueError(f"stance JSON files must have exactly one scan_id, got: {sorted(str(item) for item in scan_ids)}")
    scan_id = next(iter(scan_ids))
    if not scan_id:
        raise ValueError("stance JSON scan_id is required")
    return str(scan_id)


def purge_scan_rows(conn: sqlite3.Connection, scan_id: str) -> None:
    for table in ["stance_selection", "intra_window_change", "source", "stance"]:
        conn.execute(f"DELETE FROM {table} WHERE scan_id=?", (scan_id,))


def upsert_analysts(conn: sqlite3.Connection, analyst_list_path: str | Path) -> None:
    for team in load_analyst_list(str(analyst_list_path)):
        conn.execute(
            """
            INSERT INTO analyst(analyst_id, institution, role, team_members, official_accounts, active)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(analyst_id) DO UPDATE SET
              institution=excluded.institution,
              role=excluded.role,
              team_members=excluded.team_members,
              official_accounts=excluded.official_accounts,
              active=excluded.active
            """,
            (
                team["analyst_id"],
                team["institution"],
                team["role"],
                json.dumps(team.get("team_members", []), ensure_ascii=False),
                json.dumps(team.get("official_accounts", []), ensure_ascii=False),
                1 if team.get("active") else 0,
            ),
        )


def upsert_scan(conn: sqlite3.Connection, doc: dict[str, Any], config: dict[str, Any]) -> None:
    window = doc["window"]
    conn.execute(
        """
        INSERT INTO scan(scan_id, iso_year, iso_week, window_start, window_end, mode, is_weekly, run_version, schema_version, model_version, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(scan_id) DO UPDATE SET
          iso_year=excluded.iso_year,
          iso_week=excluded.iso_week,
          window_start=excluded.window_start,
          window_end=excluded.window_end,
          mode=excluded.mode,
          is_weekly=excluded.is_weekly,
          run_version=excluded.run_version,
          schema_version=excluded.schema_version,
          model_version=excluded.model_version
        """,
        (
            doc["scan_id"],
            int(window["iso_year"]),
            int(window["iso_week"]),
            window["start"],
            window["end"],
            doc["mode"],
            1 if doc["mode"] == "weekly" else 0,
            infer_run_version(doc["scan_id"]),
            int(doc["schema_version"]),
            doc["model_version"],
            config.get("created_at") or datetime.now().isoformat(timespec="seconds"),
        ),
    )


def ingest_stance_doc(conn: sqlite3.Connection, doc: dict[str, Any], coverage: dict[str, Any]) -> None:
    ensure_no_bad_sources(doc)
    scan_id = doc["scan_id"]
    analyst_id = doc["analyst_id"]

    team_coverage = find_team_coverage(coverage, analyst_id)
    escalated = 1 if team_coverage.get("escalated") else 0
    for source in doc.get("sources", []):
        conn.execute(
            """
            INSERT INTO source(scan_id, analyst_id, source_id, title, date, source, source_type, url, adapter_mode, text_access, attribution_confidence, escalated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scan_id, analyst_id, source_id) DO UPDATE SET
              title=excluded.title,
              date=excluded.date,
              source=excluded.source,
              source_type=excluded.source_type,
              url=excluded.url,
              adapter_mode=excluded.adapter_mode,
              text_access=excluded.text_access,
              attribution_confidence=excluded.attribution_confidence,
              escalated=excluded.escalated
            """,
            (
                scan_id,
                analyst_id,
                source["id"],
                source.get("title"),
                source.get("date"),
                source.get("source"),
                source.get("source_type"),
                source.get("url"),
                source.get("adapter_mode"),
                doc.get("text_access"),
                doc.get("attribution_confidence"),
                escalated,
            ),
        )

    for dim_key, dim in doc["dimensions"].items():
        conn.execute(
            """
            INSERT INTO stance(scan_id, analyst_id, dim_key, type, value, label, confidence, coverage, text_access, attribution_confidence, evidence_ref, verbatim)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(scan_id, analyst_id, dim_key) DO UPDATE SET
              type=excluded.type,
              value=excluded.value,
              label=excluded.label,
              confidence=excluded.confidence,
              coverage=excluded.coverage,
              text_access=excluded.text_access,
              attribution_confidence=excluded.attribution_confidence,
              evidence_ref=excluded.evidence_ref,
              verbatim=excluded.verbatim
            """,
            (
                scan_id,
                analyst_id,
                dim_key,
                dim.get("type"),
                dim.get("value"),
                dim.get("label"),
                dim.get("confidence"),
                doc.get("coverage"),
                doc.get("text_access"),
                doc.get("attribution_confidence"),
                json.dumps(dim.get("evidence_ref", []), ensure_ascii=False),
                dim.get("verbatim"),
            ),
        )

    for selection in doc.get("selections", []):
        conn.execute(
            """
            INSERT INTO stance_selection(scan_id, analyst_id, dim_key, tag_text, tag_canonical_id, lean, evidence_ref, verbatim)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scan_id,
                analyst_id,
                selection.get("dim_key"),
                selection.get("tag"),
                selection.get("tag_canonical_id"),
                selection.get("lean"),
                json.dumps(selection.get("evidence_ref", []), ensure_ascii=False),
                selection.get("verbatim"),
            ),
        )

    for change in doc.get("intra_window_changes", []):
        conn.execute(
            """
            INSERT INTO intra_window_change(scan_id, analyst_id, dim_key, from_label, to_label, note, from_ref, to_ref)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                scan_id,
                analyst_id,
                change.get("dim_key"),
                change.get("from_label"),
                change.get("to_label"),
                change.get("note"),
                json.dumps(change.get("from_ref", []), ensure_ascii=False),
                json.dumps(change.get("to_ref", []), ensure_ascii=False),
            ),
        )


def ensure_no_bad_sources(doc: dict[str, Any]) -> None:
    for source in doc.get("sources", []):
        if source.get("adapter_mode") in BAD_ADAPTER_MODES:
            raise ValueError(f"refusing to ingest bad adapter source: {source.get('id')} mode={source.get('adapter_mode')}")


def find_team_coverage(coverage: dict[str, Any], analyst_id: str) -> dict[str, Any]:
    for team in coverage.get("teams", []):
        if team.get("analyst_id") == analyst_id:
            return team
    return {}


def infer_run_version(scan_id: str) -> str:
    match = re.search(r"-(v\d+)$", scan_id)
    return match.group(1) if match else ""


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def count_rows(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
