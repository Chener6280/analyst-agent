from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from scripts.check_mvp_acceptance import (
    acceptance_stem,
    build_acceptance,
    build_quality_warnings,
    format_nested_count_map,
    parse_percent,
    render_markdown,
    sqlite_counts,
)


def test_parse_percent() -> None:
    assert parse_percent("10%") == 0.1
    assert parse_percent("100%") == 1.0
    assert parse_percent(None) is None
    assert parse_percent("n/a") is None


def test_acceptance_stem_keeps_sample_as_default_artifact() -> None:
    assert acceptance_stem("sample") == "mvp_acceptance"
    assert acceptance_stem("production") == "mvp_acceptance_production"


def test_nested_count_format_skips_empty_roles() -> None:
    assert format_nested_count_map({"macro": {}, "strategy": {"sector": 10}}) == "strategy(sector=10)"


def test_quality_warnings_surface_non_blocking_extraction_risks() -> None:
    warnings = build_quality_warnings(
        {
            "full_text_rate": "10%",
            "source_type_counts": {"financial_media": 6, "official_wechat": 1, "research_platform": 3},
        },
        {
            "written_count": 10,
            "quality": {
                "documents_with_any_signal": 7,
                "zero_signal_documents": ["兴业证券:macro", "国泰海通:macro"],
                "dimension_non_null_counts": {
                    "macro": {"growth": 3, "fiscal": 0},
                    "strategy": {"market_view": 1, "liquidity": 1},
                },
                "categorical_selection_counts": {
                    "strategy": {"sector": 10, "style": 0, "theme": 4},
                },
            },
        },
    )
    assert any("no stance signal" in warning for warning in warnings)
    assert any("Full-text coverage is low" in warning for warning in warnings)
    assert any("Non-official source types" in warning for warning in warnings)
    assert any("macro.fiscal" in warning and "strategy.sector" not in warning for warning in warnings)
    assert any("strategy.style" in warning for warning in warnings)


def test_acceptance_markdown_includes_quality_without_failing() -> None:
    text = render_markdown(
        {
            "passed": True,
            "metrics": [{"metric": "coverage teams", "required": 10, "actual": 10, "passed": True}],
            "failed_metrics": [],
            "quality_warnings": ["Full-text coverage is low (10%); most extraction relies on excerpts."],
            "quality": {
                "full_text_rate": "10%",
                "documents_with_any_signal": 7,
                "zero_signal_documents": ["兴业证券:macro"],
                "source_type_counts": {"financial_media": 6},
                "categorical_selection_counts": {"strategy": {"sector": 10, "style": 6, "theme": 4}},
            },
        }
    )
    assert "Passed: **yes**" in text
    assert "## Quality Warnings" in text
    assert "Full-text coverage is low" in text
    assert "documents_with_any_signal: 7" in text
    assert "categorical_selection_counts: strategy(sector=10, style=6, theme=4)" in text


def test_sqlite_counts_are_scoped_to_scan_id(tmp_path: Path) -> None:
    db_path = tmp_path / "views.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE analyst(analyst_id TEXT);
            CREATE TABLE scan(scan_id TEXT);
            CREATE TABLE stance(scan_id TEXT);
            CREATE TABLE stance_selection(scan_id TEXT);
            CREATE TABLE source(scan_id TEXT);
            CREATE TABLE intra_window_change(scan_id TEXT);
            INSERT INTO analyst VALUES ('A'), ('B');
            INSERT INTO scan VALUES ('target'), ('other');
            INSERT INTO stance VALUES ('target'), ('other'), ('other');
            INSERT INTO stance_selection VALUES ('other');
            INSERT INTO source VALUES ('target'), ('other');
            """
        )
        conn.commit()
    finally:
        conn.close()

    counts = sqlite_counts(db_path, "target")
    assert counts["analyst"] == 2
    assert counts["scan"] == 1
    assert counts["stance"] == 1
    assert counts["stance_selection"] == 0
    assert counts["source"] == 1


def test_acceptance_fails_on_phase3_scan_mismatch(tmp_path: Path) -> None:
    scan_dir = tmp_path / "scans" / "target"
    extracted = scan_dir / "extracted"
    reports = scan_dir / "reports"
    diagnostics = tmp_path / "diagnostics"
    extracted.mkdir(parents=True)
    reports.mkdir(parents=True)
    diagnostics.mkdir(parents=True)

    (scan_dir / "coverage_summary.json").write_text(
        json.dumps(
            {
                "scan_id": "target",
                "summary": {
                    "total_teams": 10,
                    "covered_plus_partial_rate": "100%",
                    "full_or_partial_text_rate": "100%",
                    "high_or_med_attribution_rate": "100%",
                    "mock_or_placeholder_count": 0,
                    "phase1_gate": {
                        "covered_plus_partial_ge_60": True,
                        "full_or_partial_text_ge_40": True,
                        "high_or_med_attribution_ge_70": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (extracted / "extraction_summary.json").write_text(
        json.dumps({"written_count": 5, "quality": {}}),
        encoding="utf-8",
    )
    (diagnostics / "phase3_readiness.json").write_text(
        json.dumps({"ready": True, "scan_id": "other"}),
        encoding="utf-8",
    )
    (reports / "weekly_cross_section.md").write_text("# report\n", encoding="utf-8")

    db_path = tmp_path / "views.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE analyst(analyst_id TEXT);
            CREATE TABLE scan(scan_id TEXT);
            CREATE TABLE stance(scan_id TEXT);
            CREATE TABLE stance_selection(scan_id TEXT);
            CREATE TABLE source(scan_id TEXT);
            CREATE TABLE intra_window_change(scan_id TEXT);
            INSERT INTO analyst VALUES ('A');
            INSERT INTO scan VALUES ('target');
            INSERT INTO stance VALUES ('target');
            """
        )
        conn.commit()
    finally:
        conn.close()

    result = build_acceptance(scan_dir, diagnostics_dir=diagnostics, db_path=db_path, min_teams=10, min_extracted=5)
    assert result["passed"] is False
    failed_names = {item["metric"] for item in result["failed_metrics"]}
    assert "phase3 readiness scan_id" in failed_names


def test_production_profile_fails_when_quality_is_sample_level(tmp_path: Path) -> None:
    scan_dir = tmp_path / "scans" / "target"
    extracted = scan_dir / "extracted"
    reports = scan_dir / "reports"
    diagnostics = tmp_path / "diagnostics"
    extracted.mkdir(parents=True)
    reports.mkdir(parents=True)
    diagnostics.mkdir(parents=True)
    (scan_dir / "coverage_summary.json").write_text(
        json.dumps(
            {
                "scan_id": "target",
                "summary": {
                    "total_teams": 10,
                    "covered_plus_partial_rate": "100%",
                    "full_or_partial_text_rate": "100%",
                    "full_text_rate": "10%",
                    "production_coverage_rate": "0%",
                    "official_or_broker_source_rate": "10%",
                    "high_or_med_attribution_rate": "100%",
                    "mock_or_placeholder_count": 0,
                    "phase1_gate": {
                        "covered_plus_partial_ge_60": True,
                        "full_or_partial_text_ge_40": True,
                        "high_or_med_attribution_ge_70": True,
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (extracted / "extraction_summary.json").write_text(
        json.dumps(
            {
                "written_count": 5,
                "quality": {
                    "zero_signal_documents": ["A", "B"],
                    "dimension_non_null_counts": {"macro": {"growth": 1, "inflation": 0, "monetary": 0, "fiscal": 0, "overseas": 0}},
                },
            }
        ),
        encoding="utf-8",
    )
    (diagnostics / "phase3_readiness.json").write_text(json.dumps({"ready": True, "scan_id": "target"}), encoding="utf-8")
    for name in [
        "weekly_cross_section.md",
        "weekly_brief.md",
    ]:
        (reports / name).write_text("# ok\n", encoding="utf-8")
    for name, data in {
        "agent_handoff.json": {"status": "ready"},
        "history_readiness.json": {"status": "insufficient_history"},
        "visual_pack.json": {"status": "ready"},
        "full_text_recovery_report.json": {"production_ready": False},
    }.items():
        (reports / name).write_text(json.dumps(data), encoding="utf-8")
    package = reports / "project_package"
    package.mkdir()
    (package / "project_completion.json").write_text(json.dumps({"status": "ready"}), encoding="utf-8")

    db_path = tmp_path / "views.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE analyst(analyst_id TEXT);
            CREATE TABLE scan(scan_id TEXT);
            CREATE TABLE stance(scan_id TEXT);
            CREATE TABLE stance_selection(scan_id TEXT);
            CREATE TABLE source(scan_id TEXT);
            CREATE TABLE intra_window_change(scan_id TEXT);
            INSERT INTO analyst VALUES ('A');
            INSERT INTO scan VALUES ('target');
            INSERT INTO stance VALUES ('target');
            INSERT INTO source VALUES ('target');
            """
        )
        conn.commit()
    finally:
        conn.close()

    sample = build_acceptance(scan_dir, diagnostics_dir=diagnostics, db_path=db_path, min_teams=10, min_extracted=5)
    production = build_acceptance(
        scan_dir,
        diagnostics_dir=diagnostics,
        db_path=db_path,
        min_teams=10,
        min_extracted=5,
        quality_profile="production",
    )

    assert sample["engineering_ready"] is True
    assert production["passed"] is False
    assert production["production_ready"] is False
    failed = {item["metric"] for item in production["failed_metrics"]}
    assert "full_text_rate" in failed
    assert "history readiness for trend" in failed
