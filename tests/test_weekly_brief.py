from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_weekly_brief import build_brief, render_markdown


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_weekly_brief_builds_from_cross_section_and_quality_inputs(tmp_path: Path) -> None:
    scan_id = "manual-2026-06-01-2026-06-07-v1"
    scan_dir = tmp_path / "scans" / scan_id
    diagnostics = tmp_path / "diagnostics"
    write_json(scan_dir / "reports" / "weekly_cross_section.json", cross_section(scan_id))
    write_json(
        scan_dir / "coverage_summary.json",
        {
            "summary": {
                "total_teams": 10,
                "covered_plus_partial_rate": "100%",
                "full_text_rate": "10%",
                "source_type_counts": {"official_wechat": 1, "financial_media": 9},
            }
        },
    )
    write_json(
        scan_dir / "extracted" / "extraction_summary.json",
        {"quality": {"documents_with_any_signal": 7, "zero_signal_documents": ["兴业证券:macro"]}},
    )
    write_json(
        diagnostics / f"{scan_id}__mvp_acceptance.json",
        {"passed": True, "quality_warnings": ["Full-text coverage is low (10%)."]},
    )

    brief = build_brief(scan_dir, diagnostics_dir=diagnostics)
    text = render_markdown(brief)

    assert brief["scan_id"] == scan_id
    assert brief["quality"]["acceptance_passed"] is True
    assert brief["quality"]["zero_signal_documents"] == ["兴业证券:macro"]
    assert "增长：共识偏向边际改善" in brief["headline"]
    assert "## 5. 证据摘录" in text
    assert "[official_wechat](https://example.com/gf)" in text
    assert "Full-text coverage is low" in text


def test_weekly_brief_requires_stance_rows(tmp_path: Path) -> None:
    scan_id = "empty"
    scan_dir = tmp_path / "scans" / scan_id
    write_json(scan_dir / "reports" / "weekly_cross_section.json", {"scan_id": scan_id, "db_counts": {"stance": 0}})

    try:
        build_brief(scan_dir, diagnostics_dir=tmp_path / "diagnostics")
    except ValueError as exc:
        assert "no stance rows" in str(exc)
    else:
        raise AssertionError("empty cross-section should fail brief generation")


def cross_section(scan_id: str) -> dict:
    return {
        "scan_id": scan_id,
        "db_counts": {"scan": 1, "stance": 50, "stance_selection": 3, "source": 10, "intra_window_change": 0},
        "macro": {
            "growth": {
                "n_teams": 2,
                "n_non_null": 2,
                "mode": 1,
                "mode_label": "边际改善",
                "median": 1,
                "dispersion_range": 0,
                "n_bullish": 2,
                "n_neutral": 0,
                "n_bearish": 0,
                "teams": [
                    {
                        "scan_id": scan_id,
                        "analyst_id": "广发证券:macro",
                        "institution": "广发证券",
                        "role": "macro",
                        "dim_key": "growth",
                        "value": 1,
                        "label": "边际改善",
                        "verbatim": "经济修复动能延续",
                        "source_url": "https://example.com/gf",
                        "source_type": "official_wechat",
                    }
                ],
            },
            "inflation": {"n_teams": 0, "n_non_null": 0, "teams": []},
            "monetary": {"n_teams": 0, "n_non_null": 0, "teams": []},
            "fiscal": {"n_teams": 0, "n_non_null": 0, "teams": []},
            "overseas": {"n_teams": 0, "n_non_null": 0, "teams": []},
        },
        "strategy": {
            "market_view": {
                "n_teams": 1,
                "n_non_null": 1,
                "mode": 1,
                "mode_label": "谨慎偏多",
                "median": 1,
                "dispersion_range": 0,
                "n_bullish": 1,
                "n_neutral": 0,
                "n_bearish": 0,
                "teams": [],
            },
            "liquidity": {"n_teams": 0, "n_non_null": 0, "teams": []},
            "sector": {
                "n_mentions": 1,
                "top_positive_tags": [
                    {
                        "tag": "AI算力",
                        "positive_count": 1,
                        "negative_count": 0,
                        "teams": [
                            {
                                "scan_id": scan_id,
                                "analyst_id": "国金证券:strategy",
                                "institution": "国金证券",
                                "role": "strategy",
                                "dim_key": "sector",
                                "verbatim": "AI算力景气度较高",
                                "source_url": "https://example.com/gj",
                                "source_type": "financial_media",
                            }
                        ],
                    }
                ],
                "top_negative_tags": [],
                "disputed_tags": [],
            },
            "style": {"n_mentions": 0, "top_positive_tags": [], "top_negative_tags": [], "disputed_tags": []},
            "theme": {"n_mentions": 0, "top_positive_tags": [], "top_negative_tags": [], "disputed_tags": []},
        },
    }
