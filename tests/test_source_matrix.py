from __future__ import annotations

from core.retrieval.source_matrix import (
    DEFAULT_SOURCE_MATRIX,
    enrich_team_with_source_matrix,
    parse_broker_wechat_matrix,
    source_matrix_review,
)


MATRIX = """# matrix

| 券商/机构 | 官方公众号 | 宏观个人号/团队号 | 策略个人号/团队号 |
|---|---|---|---|
| 中信建投证券 | 中信建投证券研究 | CSC研究 宏观团队 | CSC研究 策略团队 |
| 国金证券 | 国金证券研究 | 雪涛宏观笔记 | 一凌策略研究 |
"""


def test_default_source_matrix_lives_in_project_root() -> None:
    assert DEFAULT_SOURCE_MATRIX.name == "broker_wechat_matrix.md"
    assert DEFAULT_SOURCE_MATRIX.exists()
    assert (DEFAULT_SOURCE_MATRIX.parent / "pyproject.toml").exists()


def test_parse_broker_wechat_matrix_splits_role_accounts() -> None:
    rows = parse_broker_wechat_matrix(MATRIX)

    assert rows[0]["institution"] == "中信建投证券"
    assert rows[0]["official_accounts"] == ["中信建投证券研究"]
    assert rows[0]["macro_accounts"] == ["CSC研究 宏观团队"]
    assert rows[1]["strategy_accounts"] == ["一凌策略研究"]


def test_enrich_team_with_source_matrix_uses_role_specific_accounts() -> None:
    matrix = {"path": "matrix.md", "rows": parse_broker_wechat_matrix(MATRIX)}
    team = {
        "institution": "中信建投",
        "role": "macro",
        "analyst_id": "中信建投:macro",
        "official_accounts": ["宏观芝道"],
    }

    enriched = enrich_team_with_source_matrix(team, matrix)

    assert enriched["source_matrix_institution"] == "中信建投证券"
    assert enriched["source_matrix_accounts"] == ["中信建投证券研究", "CSC研究 宏观团队"]
    assert enriched["official_accounts"] == ["中信建投证券研究", "CSC研究 宏观团队", "宏观芝道"]


def test_source_matrix_review_has_no_revision_recommendations() -> None:
    matrix = {"path": "matrix.md", "rows": parse_broker_wechat_matrix(MATRIX)}
    review = source_matrix_review(
        [
            {
                "institution": "国金证券",
                "role": "strategy",
                "analyst_id": "国金证券:strategy",
                "official_accounts": [],
            }
        ],
        matrix,
    )

    assert review["matched_teams"] == 1
    assert review["teams"][0]["search_accounts"] == ["国金证券研究", "一凌策略研究"]
    assert "needs_review_count" not in review
