from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from core.store.db import ingest_scan, init_db
from core.store.queries import aggregate_categorical, aggregate_ordinal, build_cross_section, who_mentioned_entity
from scripts.aggregate_cross_section import render_markdown, render_quality_notes
from tests.test_store import make_doc


def write_scan(scan_dir: Path) -> None:
    extracted = scan_dir / "extracted"
    extracted.mkdir(parents=True)
    docs = [
        make_doc(analyst_id="广发证券:macro", institution="广发证券", role="macro", dim_values={"growth": 1}),
        make_doc(analyst_id="华创证券:macro", institution="华创证券", role="macro", dim_values={"growth": -1}),
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
                },
                {
                    "dim_key": "theme",
                    "tag": "新能源",
                    "tag_canonical_id": "INDUSTRY:新能源",
                    "lean": -1,
                    "evidence_ref": ["s1"],
                    "verbatim": "新能源",
                },
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


def test_aggregate_ordinal_and_categorical(tmp_path: Path) -> None:
    scan_dir = tmp_path / "scan"
    db_path = tmp_path / "views.db"
    write_scan(scan_dir)
    ingest_scan(scan_dir, db_path=db_path)

    growth = aggregate_ordinal("manual-2026-06-01-2026-06-07-v1", "macro", "growth", db_path=str(db_path))
    assert growth["n_teams"] == 2
    assert growth["n_non_null"] == 2
    assert growth["n_bullish"] == 1
    assert growth["n_bearish"] == 1
    assert growth["dispersion_range"] == 2
    assert growth["teams"][0]["source_url"] == "https://example.com/source"
    assert growth["teams"][0]["source_type"] == "official_wechat"

    theme = aggregate_categorical("manual-2026-06-01-2026-06-07-v1", "strategy", "theme", db_path=str(db_path))
    assert theme["top_positive_tags"][0]["tag"] == "AI算力"
    assert theme["top_negative_tags"][0]["tag"] == "新能源"


def test_build_cross_section_requires_current_scan_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "views.db"
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        init_db(conn)
    finally:
        conn.close()

    try:
        build_cross_section("missing-scan", db_path=str(db_path))
    except ValueError as exc:
        assert "scan not found in SQLite" in str(exc)
    else:
        raise AssertionError("missing scan should fail aggregation")


def test_build_cross_section_includes_db_counts_and_report_summary(tmp_path: Path) -> None:
    scan_dir = tmp_path / "scan"
    db_path = tmp_path / "views.db"
    write_scan(scan_dir)
    ingest_scan(scan_dir, db_path=db_path)

    data = build_cross_section("manual-2026-06-01-2026-06-07-v1", db_path=str(db_path))
    assert data["db_counts"]["scan"] == 1
    assert data["db_counts"]["stance"] == 15
    assert data["db_counts"]["source"] == 3

    text = render_markdown(data, {"summary": {}, "teams": []})
    assert "## 2. SQLite Summary" in text
    assert "| stance | 15 |" in text


def test_who_mentioned_entity(tmp_path: Path) -> None:
    scan_dir = tmp_path / "scan"
    db_path = tmp_path / "views.db"
    write_scan(scan_dir)
    ingest_scan(scan_dir, db_path=db_path)

    mentions = who_mentioned_entity("manual-2026-06-01-2026-06-07-v1", "INDUSTRY:AI算力", db_path=str(db_path))
    assert len(mentions) == 1
    assert mentions[0]["analyst_id"] == "国金证券:strategy"
    assert mentions[0]["source_url"] == "https://example.com/source"


def test_quality_notes_show_text_and_source_type_distribution() -> None:
    notes = "\n".join(
        render_quality_notes(
            {
                "teams": [
                    {
                        "analyst_id": "广发证券:macro",
                        "text_access": "partial_text",
                        "source_type": "financial_media",
                        "fallback_hit": False,
                        "attribution_confidence": "med",
                    },
                    {
                        "analyst_id": "国金证券:strategy",
                        "text_access": "full_text",
                        "source_type": "official_wechat",
                        "fallback_hit": False,
                        "attribution_confidence": "high",
                    },
                ]
            }
        )
    )
    assert "文本访问分布：full_text=1, partial_text=1" in notes
    assert "来源类型分布：financial_media=1, official_wechat=1" in notes
    assert "非官方来源样本：广发证券:macro(financial_media)" in notes
