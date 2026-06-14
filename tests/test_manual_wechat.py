from __future__ import annotations

from pathlib import Path

import pytest

from core.retrieval.coverage import assess_team_coverage, classify_source_type
from core.retrieval.manual_wechat import parse_manual_wechat_article, search_manual_wechat
from scripts.import_manual_wechat_article import render_article


TEAM = {
    "institution": "广发证券",
    "role": "macro",
    "analyst_id": "广发证券:macro",
    "team_members": ["郭磊"],
    "official_accounts": ["郭磊宏观茶座"],
    "active": True,
}

WINDOW = {
    "start": "2026-06-01",
    "end": "2026-06-07",
    "start_at": "2026-06-01T00:00:00",
    "end_at": "2026-06-07T23:59:59",
    "iso_year": 2026,
    "iso_week": 23,
}


def fixture_root() -> Path:
    return Path("tests/fixtures/manual_wechat")


def test_parse_manual_wechat_front_matter() -> None:
    article = parse_manual_wechat_article(fixture_root() / "2026-W23" / "广发证券_macro_郭磊_2026-06-06.md")
    assert article["metadata"]["title"] == "广发宏观郭磊：六月增长观察"
    assert article["metadata"]["team_members"] == ["郭磊"]
    assert len(article["body"]) >= 500


def test_missing_required_field_raises(tmp_path: Path) -> None:
    path = tmp_path / "bad.md"
    path.write_text(
        """---
title: "bad"
url: "https://mp.weixin.qq.com/s/bad"
---
正文
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="missing required"):
        parse_manual_wechat_article(path)


def test_search_manual_wechat_outputs_live_official_hit() -> None:
    result = search_manual_wechat(TEAM, WINDOW, "郭磊 广发证券", root=fixture_root())
    assert result["diagnostics"][0]["adapter_mode"] == "live"
    assert result["diagnostics"][0]["n_results"] == 1
    hit = result["hits"][0]
    assert hit["source"] == "manual_wechat"
    assert hit["adapter_mode"] == "live"
    assert hit["extra"]["text_access"] == "partial_text"
    assert hit["extra"]["attribution_confidence"] == "high"
    assert classify_source_type(TEAM, hit) == "official_wechat"


def test_search_manual_wechat_filters_out_of_window(tmp_path: Path) -> None:
    week_dir = tmp_path / "2026-W23"
    week_dir.mkdir()
    path = week_dir / "old.md"
    path.write_text(
        """---
title: "广发宏观郭磊：旧文"
url: "https://mp.weixin.qq.com/s/old"
published_at: "2026-05-20"
account_name: "郭磊宏观茶座"
institution: "广发证券"
role: "macro"
analyst_id: "广发证券:macro"
---
正文内容
""",
        encoding="utf-8",
    )
    result = search_manual_wechat(TEAM, WINDOW, "郭磊 广发证券", root=tmp_path)
    assert result["hits"] == []


def test_short_body_is_partial_text(tmp_path: Path) -> None:
    week_dir = tmp_path / "2026-W23"
    week_dir.mkdir()
    path = week_dir / "short.md"
    path.write_text(
        """---
title: "广发宏观郭磊：短文"
url: "https://mp.weixin.qq.com/s/short"
published_at: "2026-06-06"
account_name: "郭磊宏观茶座"
institution: "广发证券"
role: "macro"
analyst_id: "广发证券:macro"
---
短正文
""",
        encoding="utf-8",
    )
    result = search_manual_wechat(TEAM, WINDOW, "郭磊 广发证券", root=tmp_path)
    assert result["hits"][0]["extra"]["text_access"] == "snippet_only"


def test_manual_wechat_coverage_not_blocked_by_opencli_loss(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANUAL_WECHAT_ROOT", str(fixture_root()))
    item = assess_team_coverage(
        TEAM,
        WINDOW,
        "manual-2026-06-01-2026-06-07-v1",
        "manual",
        sources=["manual_wechat", "wechat_opencli", "bocha", "exa", "web_search"],
    )
    assert item["coverage"] == "covered"
    assert item["source_type"] == "official_wechat"
    assert item["attribution_confidence"] == "high"
    assert item["mock_or_placeholder"] is False


def test_import_renderer_outputs_parseable_markdown(tmp_path: Path) -> None:
    path = tmp_path / "article.md"
    text = render_article(
        title='标题 "quoted"',
        url="https://mp.weixin.qq.com/s/x",
        published_at="2026-06-06",
        account_name="郭磊宏观茶座",
        institution="广发证券",
        role="macro",
        analyst_id="广发证券:macro",
        team_members=["郭磊"],
        body="正文内容" * 100,
        source_note="manual import",
        source_type="official_wechat",
    )
    path.write_text(text, encoding="utf-8")
    article = parse_manual_wechat_article(path)
    assert article["metadata"]["analyst_id"] == "广发证券:macro"
    assert article["metadata"]["team_members"] == ["郭磊"]
    assert article["metadata"]["source_type"] == "official_wechat"
    assert "正文内容" in article["body"]


def test_manual_source_type_override(tmp_path: Path) -> None:
    week_dir = tmp_path / "2026-W23"
    week_dir.mkdir()
    path = week_dir / "media.md"
    path.write_text(
        """---
title: "财经媒体转载"
url: "https://finance.sina.com.cn/a"
published_at: "2026-06-06"
account_name: "新浪财经"
institution: "广发证券"
role: "macro"
analyst_id: "广发证券:macro"
source_type: "financial_media"
---
郭磊表示增长边际改善。
""",
        encoding="utf-8",
    )
    result = search_manual_wechat(TEAM, WINDOW, "郭磊 广发证券", root=tmp_path)
    assert classify_source_type(result["hits"][0]) == "financial_media"
