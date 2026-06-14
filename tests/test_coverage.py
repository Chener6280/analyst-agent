from __future__ import annotations

from core.retrieval.coverage import (
    assess_team_coverage,
    classify_attribution,
    classify_source_type,
    classify_text_access,
    summarize_coverages,
    source_link_rows,
    write_coverage_report,
    write_source_link_inventory,
    write_team_cache,
)
from core.retrieval.manual_wechat import parse_manual_wechat_article
import core.retrieval.coverage as coverage_module
from scripts.run_coverage_check import purge_search_cache


TEAM = {
    "institution": "广发证券",
    "role": "macro",
    "analyst_id": "广发证券:macro",
    "team_members": ["郭磊"],
    "official_accounts": ["郭磊宏观茶座"],
}


def test_classify_text_access_levels() -> None:
    assert classify_text_access({"title": "t", "url": "u"}) == "metadata_only"
    assert classify_text_access({"title": "t", "url": "u", "snippet": "摘要"}) == "snippet_only"
    assert classify_text_access({"extra": {"content": "中" * 600}}) == "partial_text"
    assert classify_text_access({"extra": {"content": "中" * 1300}}) == "full_text"


def test_classify_attribution_high_for_official_wechat_account() -> None:
    hit = {
        "source": "wechat_opencli",
        "title": "本周宏观观点",
        "snippet": "",
        "url": "https://mp.weixin.qq.com/s/x",
        "extra": {"account_name": "郭磊宏观茶座"},
    }
    assert classify_attribution(TEAM, hit) == "high"
    assert classify_source_type(TEAM, hit) == "official_wechat"


def test_classify_source_type_uses_team_accounts_from_source_matrix() -> None:
    team = {**TEAM, "official_accounts": ["广发证券研究", "郭磊宏观茶座"]}
    hit = {
        "source": "bocha",
        "title": "广发证券研究",
        "snippet": "",
        "url": "https://mp.weixin.qq.com/s/x",
        "extra": {"account_name": "广发证券研究"},
    }

    assert classify_source_type(team, hit) == "official_wechat"


def test_classify_attribution_medium_for_member_or_institution() -> None:
    hit = {
        "source": "bocha",
        "title": "郭磊最新观点",
        "snippet": "增长边际改善",
        "url": "https://example.com/a",
        "extra": {},
    }
    assert classify_attribution(TEAM, hit) == "med"


def test_classify_attribution_ignores_query_echo_in_snippet() -> None:
    hit = {
        "source": "exa",
        "title": "Unrelated earnings article",
        "snippet": "Summary tailored to user query: 郭磊 广发证券. The page has no direct relation.",
        "url": "https://example.com/unrelated",
        "extra": {},
    }
    assert classify_attribution(TEAM, hit) == "none"


def test_classify_attribution_rejects_institution_only_pages() -> None:
    hit = {
        "source": "bocha",
        "title": "广发证券招聘官网",
        "snippet": "广发证券官方招聘平台信息",
        "url": "https://example.com/job",
        "extra": {},
    }
    assert classify_attribution(TEAM, hit) == "none"


def test_summary_gate_counts_mock_and_rates() -> None:
    items = [
        {
            "coverage": "covered",
            "text_access": "full_text",
            "attribution_confidence": "high",
            "source_type": "official_wechat",
            "mock_or_placeholder": False,
            "diagnostics": [],
        },
        {
            "coverage": "partial",
            "text_access": "snippet_only",
            "attribution_confidence": "med",
            "source_type": "financial_media",
            "mock_or_placeholder": True,
            "diagnostics": [],
        },
    ]
    summary = summarize_coverages(items)
    assert summary["covered_plus_partial_rate"] == "100%"
    assert summary["full_or_partial_text_rate"] == "50%"
    assert summary["full_text_rate"] == "50%"
    assert summary["full_text_count"] == 1
    assert summary["snippet_only_count"] == 1
    assert summary["source_type_counts"] == {"financial_media": 1, "official_wechat": 1}
    assert summary["high_or_med_attribution_rate"] == "100%"
    assert summary["mock_or_placeholder_count"] == 1
    assert summary["phase1_gate"]["mock_or_placeholder_eq_0"] is False


def test_wechat_source_lost_is_not_masked_by_fallback(monkeypatch) -> None:
    window = {
        "start": "2026-06-01",
        "end": "2026-06-07",
        "start_at": "2026-06-01T00:00:00",
        "end_at": "2026-06-07T23:59:59",
        "iso_year": 2026,
        "iso_week": 23,
    }

    def fake_search_team(team, window, sources=None):
        if sources == ["wechat_opencli"]:
            return {
                "queries": ["郭磊 广发证券"],
                "hits": [],
                "diagnostics": [
                    {
                        "source": "wechat_opencli",
                        "ok": False,
                        "adapter_mode": "live",
                        "error": "WECHAT_OPENCLI_COMMAND is not set; browser adapter is unavailable",
                        "n_results": 0,
                    }
                ],
            }
        return {
            "queries": ["郭磊 广发证券"],
            "hits": [
                {
                    "title": "郭磊最新观点",
                    "url": "https://example.com/a",
                    "snippet": "中" * 600,
                    "source": "bocha",
                    "published_at": "2026-06-03T00:00:00+08:00",
                    "adapter_mode": "live",
                    "extra": {"adapter_mode": "live"},
                }
            ],
            "diagnostics": [{"source": "bocha", "ok": True, "adapter_mode": "live", "error": None, "n_results": 1}],
        }

    monkeypatch.setattr(coverage_module, "search_team", fake_search_team)
    item = assess_team_coverage(
        TEAM,
        window,
        "manual-2026-06-01-2026-06-07-v1",
        "manual",
        sources=["wechat_opencli", "bocha"],
    )
    assert item["coverage"] == "source_lost"
    assert item["source_lost_reason"] == "WECHAT_OPENCLI_COMMAND is not set"
    assert item["fallback_hit"] is False
    assert item["escalated"] is False


def test_coverage_report_shows_source_type_without_success_noise(tmp_path) -> None:
    path = tmp_path / "coverage.md"
    write_coverage_report(
        "scan",
        [
            {
                "analyst_id": "广发证券:macro",
                "role": "macro",
                "coverage": "covered",
                "text_access": "partial_text",
                "source_type": "financial_media",
                "attribution_confidence": "med",
                "latest_published_at": "2026-06-02",
                "primary_source_hit": True,
                "fallback_hit": False,
                "escalated": False,
                "freshness_note": None,
                "source_lost_reason": None,
                "mock_or_placeholder": False,
                "diagnostics": [
                    {
                        "source": "wechat_opencli",
                        "error": "WECHAT_OPENCLI_COMMAND is not set",
                    }
                ],
            }
        ],
        path,
    )
    text = path.read_text(encoding="utf-8")
    assert "| analyst_id | role | coverage | text_access | source_type |" in text
    assert "financial_media" in text
    assert "WECHAT_OPENCLI_COMMAND is not set" not in text


def test_purge_search_cache_removes_generated_cache_files(tmp_path) -> None:
    cache_dir = tmp_path / "search_cache"
    cache_dir.mkdir()
    (cache_dir / "old.json").write_text("{}", encoding="utf-8")
    (cache_dir / "old.md").write_text("# old", encoding="utf-8")
    keep = cache_dir / "README.keep"
    keep.write_text("keep", encoding="utf-8")

    purge_search_cache(tmp_path)

    assert not (cache_dir / "old.json").exists()
    assert not (cache_dir / "old.md").exists()
    assert keep.exists()


def test_write_team_cache_materializes_live_content_for_extraction(tmp_path) -> None:
    item = {
        "analyst_id": "广发证券:macro",
        "institution": "广发证券",
        "role": "macro",
        "team_members": ["郭磊"],
        "sources": [
            {
                "id": "s1",
                "title": "【广发宏观团队】测试",
                "url": "https://mp.weixin.qq.com/s/test",
                "source": "wechat_opencli",
                "source_type": "official_wechat",
                "published_at": "2026-06-14",
                "account_name": "郭磊宏观茶座",
                "text_access": "full_text",
                "attribution_confidence": "high",
                "content": "增长边际改善。" * 500,
            }
        ],
        "raw_hits": {"primary": [], "fallback": []},
    }

    write_team_cache(item, tmp_path, 1)

    source = item["sources"][0]
    assert "content" not in source
    article = parse_manual_wechat_article(source["content_path"])
    assert article["metadata"]["account_name"] == "郭磊宏观茶座"
    assert "增长边际改善" in article["body"]


def test_source_link_inventory_preserves_attributed_and_raw_links(tmp_path) -> None:
    item = {
        "scan_id": "scan",
        "analyst_id": "广发证券:macro",
        "institution": "广发证券",
        "role": "macro",
        "sources": [
            {
                "id": "s1",
                "candidate_type": "primary",
                "source": "wechat_opencli",
                "source_type": "official_wechat",
                "account_name": "郭磊宏观茶座",
                "title": "公众号文章",
                "published_at": "2026-06-14",
                "url": "https://mp.weixin.qq.com/s/source",
                "canonical_url": "wechat:tok:source",
                "found_by": ["wechat_opencli"],
                "text_access": "full_text",
                "attribution_confidence": "high",
                "source_completeness": "full_article",
                "adapter_mode": "live",
                "content_path": "/tmp/source.md",
            }
        ],
        "raw_hits": {
            "primary": [
                {
                    "source": "wechat_opencli",
                    "title": "公众号文章",
                    "url": "https://mp.weixin.qq.com/s/source",
                    "published_at": "2026-06-14T08:00:00+08:00",
                    "adapter_mode": "live",
                    "extra": {"account_name": "郭磊宏观茶座", "canonical_url": "wechat:tok:source"},
                }
            ],
            "fallback": [
                {
                    "source": "bocha",
                    "title": "网页转载",
                    "url": "https://example.com/repost",
                    "published_at": "2026-06-14",
                    "adapter_mode": "live",
                    "extra": {"source_type": "aggregator"},
                }
            ],
        },
    }

    rows = source_link_rows([item])
    assert [row["record_type"] for row in rows] == ["attributed_source", "raw_primary", "raw_fallback"]
    assert {row["url"] for row in rows} == {
        "https://mp.weixin.qq.com/s/source",
        "https://example.com/repost",
    }

    paths = write_source_link_inventory("scan", [item], tmp_path)
    assert "网页转载" in (tmp_path / "source_links.md").read_text(encoding="utf-8")
    assert "raw_fallback" in (tmp_path / "source_links.csv").read_text(encoding="utf-8")
    assert set(paths) == {"json", "csv", "md"}
