from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.history.timeseries import build_consensus_series, build_history_readiness, build_tag_rotation, build_team_series
from core.schema.stance import dimensions_for_role
from core.store.db import ingest_scan
from scripts.export_history_readiness import render_markdown
from scripts.query_agent_interface import run_query
from tests.test_aggregation import write_scan


def prepare_history(tmp_path: Path) -> tuple[str, Path]:
    scan_id = "manual-2026-06-01-2026-06-07-v1"
    scan_dir = tmp_path / "out" / "scans" / scan_id
    write_scan(scan_dir)
    db_path = tmp_path / "views.db"
    ingest_scan(scan_dir, db_path=db_path)
    return scan_id, db_path


def test_history_readiness_reports_insufficient_history_without_failing(tmp_path: Path) -> None:
    scan_id, db_path = prepare_history(tmp_path)

    readiness = build_history_readiness(scan_id, db_path=db_path, min_scans=4)
    text = render_markdown(readiness)

    assert readiness["status"] == "insufficient_history"
    assert readiness["available_scan_count"] == 1
    assert readiness["missing_scan_count"] == 3
    assert "P6 query functions are available" in readiness["notes"][1]
    assert "Status: **insufficient_history**" in text


def test_history_queries_return_current_scan_points(tmp_path: Path) -> None:
    scan_id, db_path = prepare_history(tmp_path)

    consensus = build_consensus_series("macro", "growth", db_path=db_path)
    team = build_team_series("广发证券:macro", "growth", db_path=db_path)
    rotation = build_tag_rotation("strategy", "theme", db_path=db_path, top_n=3)

    assert consensus["points"][0]["scan_id"] == scan_id
    assert consensus["points"][0]["n_non_null"] == 2
    assert team["points"][0]["value"] == 1
    assert rotation["points"][0]["top_positive_tags"][0]["tag"] == "AI算力"


def test_history_readiness_becomes_ready_with_enough_real_scans(tmp_path: Path) -> None:
    db_path = tmp_path / "views.db"
    for idx in range(4):
        scan_id = f"manual-2026-06-{idx + 1:02d}-2026-06-{idx + 1:02d}-v1"
        scan_dir = tmp_path / "out" / "scans" / scan_id
        write_scan(scan_dir)
        rewrite_scan_id(scan_dir, scan_id, iso_week=23 + idx)
        ingest_scan(scan_dir, db_path=db_path)

    readiness = build_history_readiness("manual-2026-06-04-2026-06-04-v1", db_path=db_path, min_scans=4)

    assert readiness["status"] == "ready"
    assert readiness["available_scan_count"] == 4
    series = build_consensus_series("macro", "growth", db_path=db_path)
    assert len(series["points"]) == 4


def test_query_agent_interface_history_readiness(tmp_path: Path) -> None:
    scan_id, db_path = prepare_history(tmp_path)

    result = run_query(
        argparse.Namespace(command="history-readiness", scan_id=scan_id, db_path=str(db_path), min_scans=4)
    )

    assert result["status"] == "insufficient_history"
    assert result["supported_queries"][0]["name"] == "consensus-series"


def rewrite_scan_id(scan_dir: Path, scan_id: str, *, iso_week: int) -> None:
    extracted = scan_dir / "extracted"
    for path in extracted.glob("*.stance.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["scan_id"] = scan_id
        doc["window"]["start"] = f"2026-06-{iso_week - 22:02d}"
        doc["window"]["end"] = f"2026-06-{iso_week - 22:02d}"
        doc["window"]["iso_week"] = iso_week
        growth = doc["dimensions"].get("growth")
        if growth and growth["value"] is not None and doc["analyst_id"] == "广发证券:macro":
            growth["value"] = 1
            growth["label"] = dimensions_for_role("macro")["growth"]["values"][1]
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    coverage_path = scan_dir / "coverage_summary.json"
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    coverage["scan_id"] = scan_id
    coverage_path.write_text(json.dumps(coverage, ensure_ascii=False), encoding="utf-8")
