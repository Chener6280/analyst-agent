from __future__ import annotations

from core.config import load_analyst_list
from scripts.audit_manual_wechat_gap import build_gap_report
from scripts.scaffold_manual_wechat_templates import template_context


def test_acceptance_candidate_list_is_parseable() -> None:
    teams = load_analyst_list("data/analyst-list-acceptance-candidates.md")
    assert len([team for team in teams if team["active"]]) == 10
    assert teams[0]["analyst_id"] == "广发证券:macro"


def test_template_context_uses_window_end() -> None:
    team = {
        "institution": "测试证券",
        "role": "macro",
        "analyst_id": "测试证券:macro",
        "team_members": ["测试员"],
        "official_accounts": ["测试公众号"],
    }
    window = {"end": "2026-06-07"}
    template = template_context(team, window)
    assert template["filename"] == "测试证券_macro_测试员_2026-06-07.md.template"
    assert template["account_name"] == "测试公众号"


def test_gap_report_counts_missing_samples() -> None:
    validation = {
        "window": {"start": "2026-06-01", "end": "2026-06-07"},
        "articles_root": "/tmp/articles",
        "week_dir": "/tmp/articles/2026-W23",
        "total_teams": 2,
        "teams": [
            {
                "analyst_id": "A:macro",
                "institution": "A",
                "role": "macro",
                "official_accounts": ["A号"],
                "status": "covered",
                "best": {"path": "/tmp/a.md", "text_access": "full_text", "attribution_confidence": "high"},
            },
            {
                "analyst_id": "B:macro",
                "institution": "B",
                "role": "macro",
                "official_accounts": ["B号"],
                "status": "missing",
                "issue": "no file",
            },
        ],
    }
    report = build_gap_report(validation, min_teams=2, min_extracted=1)
    assert report["eligible_samples"] == 1
    assert report["missing_samples"] == 1
    assert report["ready_for_global_acceptance_inputs"] is False
