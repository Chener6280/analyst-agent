from __future__ import annotations

from core.retrieval.source_whitelist import is_official_account, load_source_whitelist, official_account_suggestions


def test_source_whitelist_requires_account_and_allowed_domain() -> None:
    whitelist = load_source_whitelist("data/source_whitelist.yaml")

    assert is_official_account("广发证券:macro", "郭磊宏观茶座", "https://mp.weixin.qq.com/s/x", whitelist) is True
    assert is_official_account("广发证券:macro", "新浪财经", "https://mp.weixin.qq.com/s/x", whitelist) is False
    assert is_official_account("广发证券:macro", "郭磊宏观茶座", "https://finance.sina.com.cn/a", whitelist) is False


def test_official_account_suggestions_flags_mismatches() -> None:
    whitelist = load_source_whitelist("data/source_whitelist.yaml")
    row = official_account_suggestions(
        {
            "analyst_id": "广发证券:macro",
            "institution": "广发证券",
            "role": "macro",
            "team_members": ["郭磊"],
            "official_accounts": ["郭磊宏观茶座", "错误账号"],
        },
        whitelist,
    )

    assert row["needs_review"] is True
    assert "错误账号" in row["missing_from_whitelist"]
