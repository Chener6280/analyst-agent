from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core.schema.stance import dimensions_for_role
from core.store.db import count_rows, ingest_scan


def make_doc(*, analyst_id: str, institution: str, role: str, dim_values: dict, selections: list[dict] | None = None) -> dict:
    dims = {}
    for dim_key, dim_def in dimensions_for_role(role).items():
        value = dim_values.get(dim_key)
        dims[dim_key] = {
            "type": dim_def["type"],
            "axis": dim_def["axis"],
            "value": value,
            "label": dim_def.get("values", {}).get(value) if value is not None else None,
            "confidence": "med" if value is not None else None,
            "evidence_ref": ["s1"] if value is not None else [],
            "verbatim": "测试证据" if value is not None else None,
        }
    return {
        "scan_id": "manual-2026-06-01-2026-06-07-v1",
        "schema_version": 1,
        "model_version": "rules-mvp-v1",
        "mode": "manual",
        "institution": institution,
        "role": role,
        "analyst_id": analyst_id,
        "team_members": ["测试"],
        "window": {"start": "2026-06-01", "end": "2026-06-07", "iso_year": 2026, "iso_week": 23},
        "coverage": "covered",
        "text_access": "partial_text",
        "attribution_confidence": "med",
        "dimensions": dims,
        "selections": selections or [],
        "intra_window_changes": [],
        "sources": [
            {
                "id": "s1",
                "title": "测试来源",
                "date": "2026-06-02",
                "source": "manual_wechat",
                "source_type": "official_wechat",
                "url": "https://example.com/source",
                "adapter_mode": "live",
            }
        ],
    }


def write_scan(scan_dir: Path) -> None:
    extracted = scan_dir / "extracted"
    extracted.mkdir(parents=True)
    docs = [
        make_doc(analyst_id="广发证券:macro", institution="广发证券", role="macro", dim_values={"growth": 1}),
        make_doc(
            analyst_id="国金证券:strategy",
            institution="国金证券",
            role="strategy",
            dim_values={"market_view": 1},
            selections=[
                {
                    "dim_key": "theme",
                    "tag": "AI算力",
                    "tag_canonical_id": "INDUSTRY:AI算力",
                    "lean": 1,
                    "evidence_ref": ["s1"],
                    "verbatim": "AI算力",
                }
            ],
        ),
    ]
    for idx, doc in enumerate(docs, start=1):
        (extracted / f"doc_{idx}.stance.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    (scan_dir / "coverage_summary.json").write_text(
        json.dumps({"scan_id": docs[0]["scan_id"], "teams": [{"analyst_id": doc["analyst_id"], "escalated": False} for doc in docs]}, ensure_ascii=False),
        encoding="utf-8",
    )
    (scan_dir / "config.json").write_text(json.dumps({"created_at": "2026-06-10T00:00:00"}), encoding="utf-8")


def test_ingest_scan_is_idempotent(tmp_path: Path) -> None:
    scan_dir = tmp_path / "scan"
    write_scan(scan_dir)
    db_path = tmp_path / "views.db"

    first = ingest_scan(scan_dir, db_path=db_path)
    second = ingest_scan(scan_dir, db_path=db_path)

    assert first["stance_rows"] == second["stance_rows"]
    conn = sqlite3.connect(db_path)
    try:
        assert count_rows(conn, "scan") == 1
        assert count_rows(conn, "source") == 2
        assert count_rows(conn, "stance") == 10
        assert count_rows(conn, "stance_selection") == 1
        source_type = conn.execute("SELECT source_type FROM source LIMIT 1").fetchone()[0]
        assert source_type == "official_wechat"
    finally:
        conn.close()


def test_ingest_scan_removes_stale_rows_for_same_scan(tmp_path: Path) -> None:
    scan_dir = tmp_path / "scan"
    write_scan(scan_dir)
    db_path = tmp_path / "views.db"
    ingest_scan(scan_dir, db_path=db_path)

    strategy_path = scan_dir / "extracted" / "doc_2.stance.json"
    strategy_path.unlink()
    summary = ingest_scan(scan_dir, db_path=db_path)

    assert summary["stance_docs"] == 1
    conn = sqlite3.connect(db_path)
    try:
        assert count_rows(conn, "source") == 1
        assert count_rows(conn, "stance") == 5
        assert count_rows(conn, "stance_selection") == 0
        analysts = {
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT analyst_id FROM stance WHERE scan_id='manual-2026-06-01-2026-06-07-v1'"
            ).fetchall()
        }
        assert analysts == {"广发证券:macro"}
    finally:
        conn.close()


def test_ingest_rejects_mixed_scan_ids(tmp_path: Path) -> None:
    scan_dir = tmp_path / "scan"
    write_scan(scan_dir)
    path = scan_dir / "extracted" / "doc_2.stance.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["scan_id"] = "other-scan"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    try:
        ingest_scan(scan_dir, db_path=tmp_path / "views.db")
    except ValueError as exc:
        assert "exactly one scan_id" in str(exc)
    else:
        raise AssertionError("mixed scan ids should be rejected")


def test_ingest_rejects_mock_source(tmp_path: Path) -> None:
    scan_dir = tmp_path / "scan"
    write_scan(scan_dir)
    path = next((scan_dir / "extracted").glob("*.stance.json"))
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["sources"][0]["adapter_mode"] = "mock"
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    try:
        ingest_scan(scan_dir, db_path=tmp_path / "views.db")
    except ValueError as exc:
        assert "refusing to ingest bad adapter source" in str(exc)
    else:
        raise AssertionError("mock source should be rejected")
