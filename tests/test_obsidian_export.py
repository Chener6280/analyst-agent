from __future__ import annotations

import json
from pathlib import Path

from core.obsidian.export import export_scan_to_obsidian


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_obsidian_export_builds_weekly_vault_notes(tmp_path: Path) -> None:
    scan_id = "2026-W24-full-v2"
    output_root = tmp_path / "out"
    scan_dir = output_root / "scans" / scan_id
    reports = scan_dir / "reports"
    extracted = scan_dir / "extracted"
    diagnostics = output_root / "diagnostics"
    vault = tmp_path / "Obsidian Vault"

    write_json(
        scan_dir / "config.json",
        {
            "scan_id": scan_id,
            "window": {"start": "2026-06-08", "end": "2026-06-14", "iso_year": 2026, "iso_week": 24},
        },
    )
    write_json(reports / "weekly_brief.json", weekly_brief(scan_id))
    write_json(reports / "weekly_cross_section.json", weekly_cross_section(scan_id))
    write_json(
        scan_dir / "source_links.json",
        {
            "scan_id": scan_id,
            "links": [
                {
                    "institution": "广发证券",
                    "role": "macro",
                    "published_at": "2026-06-14",
                    "account_name": "郭磊宏观茶座",
                    "title": "增长修复",
                    "text_access": "full_text",
                    "url": "https://example.com/gf",
                }
            ],
        },
    )
    write_json(extracted / "macro_001_广发证券.stance.json", stance(scan_id))
    (scan_dir / "coverage_report.md").write_text("# coverage\n", encoding="utf-8")
    (extracted / "extraction_report.md").write_text("# extraction\n", encoding="utf-8")
    (reports / "history_readiness.md").write_text("# history\n", encoding="utf-8")
    (diagnostics / f"{scan_id}__mvp_acceptance.md").parent.mkdir(parents=True, exist_ok=True)
    (diagnostics / f"{scan_id}__mvp_acceptance.md").write_text("# acceptance\n", encoding="utf-8")
    (reports / "weekly_brief.md").write_text("# raw brief\n", encoding="utf-8")
    (reports / "weekly_cross_section.md").write_text("# raw cross\n", encoding="utf-8")
    (scan_dir / "source_links.md").write_text("# raw links\n", encoding="utf-8")
    (reports / "charts").mkdir(parents=True, exist_ok=True)
    (reports / "charts" / "macro_consensus.svg").write_text("<svg></svg>\n", encoding="utf-8")

    manifest = export_scan_to_obsidian(scan_id, output_root=output_root, vault_path=vault)

    entry = Path(manifest["entry_note"])
    assert entry.exists()
    text = entry.read_text(encoding="utf-8")
    assert "[[主题 - 增长|增长]]" in text
    assert "[[机构 - 广发证券 macro|广发证券:macro]]" in text
    assert "[原文](https://example.com/gf)" in text
    assert (vault / "Analyst Agent" / "Institutions" / "机构 - 广发证券 macro.md").exists()
    assert (vault / "Analyst Agent" / "Topics" / "主题 - 增长.md").exists()
    assert (vault / "Analyst Agent" / "Weekly" / "2026-W24" / "2026-W24 来源链接.md").exists()
    assert (reports / "obsidian_export.json").exists()
    assert manifest["institution_notes"] == 1
    assert manifest["source_links"] == 1


def weekly_brief(scan_id: str) -> dict:
    return {
        "scan_id": scan_id,
        "headline": "增长：共识偏向边际改善。",
        "macro": [
            {
                "dim_key": "growth",
                "name": "增长",
                "summary": "共识偏向边际改善",
                "n_teams": 1,
                "n_non_null": 1,
                "mode_label": "边际改善",
                "median": 1,
                "dispersion_range": 0,
            }
        ],
        "strategy": {
            "ordinals": [],
            "categories": [
                {
                    "dim_key": "sector",
                    "name": "板块配置",
                    "n_mentions": 1,
                    "top_positive_tags": [{"tag": "AI算力", "positive_count": 1}],
                    "top_negative_tags": [],
                    "disputed_tags": [],
                }
            ],
        },
        "quality": {"acceptance_passed": True, "quality_warnings": []},
        "evidence": [
            {
                "role": "macro",
                "dim_key": "growth",
                "dim_name": "增长",
                "analyst_id": "广发证券:macro",
                "institution": "广发证券",
                "label": "边际改善",
                "verbatim": "经济修复动能延续",
                "source_url": "https://example.com/gf",
                "source_type": "official_wechat",
            }
        ],
    }


def weekly_cross_section(scan_id: str) -> dict:
    return {
        "scan_id": scan_id,
        "entities": [
            {"entity": "INDUSTRY:AI算力", "tag": "AI算力", "positive": 1, "negative": 0, "neutral": 0, "teams": ["广发证券:macro"]}
        ],
    }


def stance(scan_id: str) -> dict:
    return {
        "scan_id": scan_id,
        "institution": "广发证券",
        "role": "macro",
        "analyst_id": "广发证券:macro",
        "team_members": ["郭磊"],
        "coverage": "covered",
        "text_access": "full_text",
        "attribution_confidence": "high",
        "dimensions": {
            "growth": {
                "label": "边际改善",
                "confidence": "med",
                "verbatim": "经济修复动能延续",
            }
        },
        "sources": [
            {
                "date": "2026-06-14",
                "title": "增长修复",
                "source_type": "official_wechat",
                "url": "https://example.com/gf",
            }
        ],
    }

