from __future__ import annotations

import argparse
import json
from pathlib import Path

from core.interface.read_api import (
    build_agent_handoff,
    get_dimension_summary,
    get_entity_mentions,
    get_entity_mentions_history,
    get_team_stance,
)
from core.store.db import ingest_scan
from core.store.queries import build_cross_section
from scripts.export_agent_handoff import render_markdown
from scripts.query_agent_interface import run_query
from tests.test_aggregation import write_scan


def prepare_scan(tmp_path: Path) -> tuple[str, Path, Path]:
    scan_id = "manual-2026-06-01-2026-06-07-v1"
    output_root = tmp_path / "out"
    scan_dir = output_root / "scans" / scan_id
    write_scan(scan_dir)
    db_path = tmp_path / "views.db"
    ingest_scan(scan_dir, db_path=db_path)

    reports = scan_dir / "reports"
    reports.mkdir(parents=True)
    cross_section = build_cross_section(scan_id, db_path=str(db_path))
    (reports / "weekly_cross_section.json").write_text(json.dumps(cross_section, ensure_ascii=False), encoding="utf-8")
    (reports / "weekly_cross_section.md").write_text("# cross section\n", encoding="utf-8")
    (reports / "weekly_brief.json").write_text(
        json.dumps(
            {
                "scan_id": scan_id,
                "headline": "增长：分歧较高，众数为边际走弱。",
                "quality": {"acceptance_passed": True, "full_text_rate": "10%", "quality_warnings": []},
                "macro": [{"dim_key": "growth", "name": "增长", "summary": "分歧较高", "n_non_null": 2, "n_teams": 2}],
                "strategy": {"ordinals": [], "categories": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (reports / "weekly_brief.md").write_text("# brief\n", encoding="utf-8")
    diagnostics = output_root / "diagnostics"
    diagnostics.mkdir(parents=True)
    (diagnostics / f"{scan_id}__mvp_acceptance.json").write_text(
        json.dumps({"passed": True, "quality_warnings": []}),
        encoding="utf-8",
    )
    return scan_id, output_root, db_path


def test_agent_handoff_exports_supported_queries_and_artifacts(tmp_path: Path) -> None:
    scan_id, output_root, db_path = prepare_scan(tmp_path)

    handoff = build_agent_handoff(scan_id, output_root=output_root, db_path=db_path)
    text = render_markdown(handoff)

    assert handoff["status"] == "ready"
    assert handoff["db_counts"]["stance"] == 15
    assert handoff["artifacts"]["weekly_brief_json"].endswith("weekly_brief.json")
    assert any(item["name"] == "team-stance" for item in handoff["supported_queries"])
    assert any(item["name"] == "who-mentioned-history" for item in handoff["supported_queries"])
    assert "## Supported Queries" in text


def test_agent_read_api_queries_dimension_team_and_entity(tmp_path: Path) -> None:
    scan_id, _, db_path = prepare_scan(tmp_path)

    growth = get_dimension_summary(scan_id, "macro", "growth", db_path=db_path)
    team = get_team_stance(scan_id, "广发证券:macro", db_path=db_path)
    mentions = get_entity_mentions(scan_id, "INDUSTRY:AI算力", db_path=db_path)

    assert growth["n_non_null"] == 2
    assert team["analyst"]["analyst_id"] == "广发证券:macro"
    assert len(team["dimensions"]) == 5
    growth_row = next(item for item in team["dimensions"] if item["dim_key"] == "growth")
    assert growth_row["source_type"] == "official_wechat"
    assert mentions["mentions"][0]["analyst_id"] == "国金证券:strategy"


def test_agent_read_api_queries_entity_mentions_across_recent_scans(tmp_path: Path) -> None:
    _, output_root, db_path = prepare_scan(tmp_path)
    weekly_1 = write_entity_scan(
        output_root,
        db_path,
        scan_id="2026-W23-v1",
        mode="weekly",
        start="2026-06-01",
        end="2026-06-07",
        iso_week=23,
    )
    write_entity_scan(
        output_root,
        db_path,
        scan_id="manual-2026-06-10-2026-06-11-v1",
        mode="manual",
        start="2026-06-10",
        end="2026-06-11",
        iso_week=24,
    )
    weekly_2 = write_entity_scan(
        output_root,
        db_path,
        scan_id="2026-W24-v1",
        mode="weekly",
        start="2026-06-08",
        end="2026-06-14",
        iso_week=24,
    )

    latest = get_entity_mentions_history("INDUSTRY:AI算力", db_path=db_path, weeks=1)
    last_two = get_entity_mentions_history("INDUSTRY:AI算力", db_path=db_path, weeks=2)

    assert [item["scan_id"] for item in latest["mentions"]] == [weekly_2]
    assert [item["scan_id"] for item in last_two["mentions"]] == [weekly_2, weekly_1]


def write_entity_scan(
    output_root: Path,
    db_path: Path,
    *,
    scan_id: str,
    mode: str,
    start: str,
    end: str,
    iso_week: int,
) -> str:
    scan_dir = output_root / "scans" / scan_id
    write_scan(scan_dir)
    for path in (scan_dir / "extracted").glob("*.stance.json"):
        doc = json.loads(path.read_text(encoding="utf-8"))
        doc["scan_id"] = scan_id
        doc["mode"] = mode
        doc["window"] = {"start": start, "end": end, "iso_year": 2026, "iso_week": iso_week}
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    (scan_dir / "coverage_summary.json").write_text(
        json.dumps(
            {
                "scan_id": scan_id,
                "teams": [
                    {"analyst_id": "广发证券:macro", "escalated": False},
                    {"analyst_id": "华创证券:macro", "escalated": False},
                    {"analyst_id": "国金证券:strategy", "escalated": False},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (scan_dir / "config.json").write_text(json.dumps({"created_at": "2026-06-17T00:00:00"}), encoding="utf-8")
    ingest_scan(scan_dir, db_path=db_path)
    return scan_id


def test_query_agent_interface_scan_context(tmp_path: Path) -> None:
    scan_id, output_root, db_path = prepare_scan(tmp_path)

    result = run_query(
        argparse.Namespace(
            command="scan-context",
            scan_id=scan_id,
            output_root=str(output_root),
            db_path=str(db_path),
        )
    )

    assert result["scan_id"] == scan_id
    assert result["status"] == "ready"
