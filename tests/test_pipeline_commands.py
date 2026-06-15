from __future__ import annotations

import argparse
from pathlib import Path

from scripts.run_mvp_pipeline import build_steps
from scripts.run_phase1_manual_check import build_commands, phase1_result


def test_phase1_commands_pass_scan_and_output_paths(tmp_path: Path) -> None:
    args = argparse.Namespace(
        mode="manual",
        start="2026-06-08",
        end="2026-06-14",
        max_teams=10,
        analyst_list="data/analyst-list-acceptance-candidates.md",
        run_version="v2",
        sources="manual_wechat,wechat_opencli",
        env_file=None,
        articles_root=str(tmp_path / "articles"),
        output_root=str(tmp_path / "out"),
        source_whitelist="data/source_whitelist.yaml",
        source_matrix="/tmp/broker_wechat_matrix.md",
        skip_wewe_login_prepare=False,
        skip_wechat_dual_source_check=False,
        allow_single_wechat_provider=False,
        allow_empty_wewe_feeds=False,
        wewe_base="http://localhost:4001",
        wewe_container="wewe-rss-ir",
        wewe_auth_code="irsearch",
        wewe_login_wait_seconds=0,
        wechat_accounts="/Users/chen/Documents/ir_search/accounts.json",
    )
    validation_cmd, coverage_cmd, readiness_cmd = build_commands(args)

    assert "--articles-root" in validation_cmd
    assert str(tmp_path / "articles") in validation_cmd
    assert "--run-version" in validation_cmd
    assert "v2" in validation_cmd
    assert "--output-root" in validation_cmd
    assert "--source-list-confirmed" not in validation_cmd
    assert str(tmp_path / "out") in coverage_cmd
    assert "--source-list-confirmed" in coverage_cmd
    assert "--source-whitelist" in coverage_cmd
    assert "data/source_whitelist.yaml" in coverage_cmd
    assert "--source-matrix" in coverage_cmd
    assert "/tmp/broker_wechat_matrix.md" in coverage_cmd
    assert "--scan-dir" in readiness_cmd
    assert str(tmp_path / "out" / "scans" / "manual-2026-06-08-2026-06-14-v2") in readiness_cmd
    assert "--diagnostics-dir" in readiness_cmd
    assert str(tmp_path / "out" / "diagnostics") in readiness_cmd


def test_phase1_result_requires_all_steps_to_pass() -> None:
    assert phase1_result(0, 0, 0) == (True, "ok")
    assert phase1_result(1, 0, 0) == (False, "manual_wechat validation failed")
    assert phase1_result(0, 1, 0) == (False, "coverage command failed")
    assert phase1_result(0, 0, 1) == (False, "phase2 readiness gate failed")


def test_pipeline_steps_use_requested_scan_output_and_db_paths(tmp_path: Path) -> None:
    args = argparse.Namespace(
        mode="manual",
        start="2026-06-08",
        end="2026-06-14",
        run_version="v2",
        max_teams=10,
        analyst_list="data/analyst-list-acceptance-candidates.md",
        retrieval_profile="manual",
        sources="manual_wechat,wechat_opencli,bocha,exa,web_search",
        min_teams=10,
        min_extracted=5,
        quality_profile="sample",
        env_file=None,
        articles_root=str(tmp_path / "articles"),
        output_root=str(tmp_path / "out"),
        db_path=str(tmp_path / "views.db"),
        source_whitelist="data/source_whitelist.yaml",
        source_matrix="/tmp/broker_wechat_matrix.md",
        skip_wewe_login_prepare=False,
        allow_single_wechat_provider=False,
        allow_empty_wewe_feeds=False,
        wewe_base="http://localhost:4001",
        wewe_container="wewe-rss-ir",
        wewe_auth_code="irsearch",
        wewe_login_wait_seconds=0,
        wechat_accounts="/Users/chen/Documents/ir_search/accounts.json",
    )
    steps = build_steps(args)
    flattened = [" ".join(step) for step in steps]

    scan_id = "manual-2026-06-08-2026-06-14-v2"
    scan_dir = str(tmp_path / "out" / "scans" / scan_id)
    diagnostics_dir = str(tmp_path / "out" / "diagnostics")
    assert any("scripts/check_phase3_readiness.py" in step and scan_dir in step for step in flattened)
    assert any("scripts/check_phase3_readiness.py" in step and diagnostics_dir in step for step in flattened)
    assert any("scripts/run_phase1_manual_check.py" in step and "/tmp/broker_wechat_matrix.md" in step for step in flattened)
    assert all(str(tmp_path / "out") in step for step in flattened if "run_phase1_manual_check.py" not in step or "--output-root" in step)
    assert any("scripts/ingest_sqlite.py" in step and str(tmp_path / "views.db") in step for step in flattened)
    assert any("scripts/generate_weekly_brief.py" in step and str(tmp_path / "out") in step for step in flattened)
    assert any("scripts/export_agent_handoff.py" in step and str(tmp_path / "views.db") in step for step in flattened)
    assert any("scripts/export_history_readiness.py" in step and str(tmp_path / "views.db") in step for step in flattened)
    assert any("scripts/export_visual_pack.py" in step and str(tmp_path / "views.db") in step for step in flattened)
    assert any("scripts/export_project_package.py" in step and str(tmp_path / "views.db") in step for step in flattened)
    assert any("scripts/check_mvp_acceptance.py" in step and str(tmp_path / "views.db") in step for step in flattened)
    assert any("scripts/check_mvp_acceptance.py" in step and "--quality-profile sample" in step for step in flattened)
    acceptance_idx = next(idx for idx, step in enumerate(flattened) if "scripts/check_mvp_acceptance.py" in step)
    package_indices = [idx for idx, step in enumerate(flattened) if "scripts/export_project_package.py" in step]
    brief_indices = [idx for idx, step in enumerate(flattened) if "scripts/generate_weekly_brief.py" in step]
    handoff_indices = [idx for idx, step in enumerate(flattened) if "scripts/export_agent_handoff.py" in step]
    assert package_indices[0] < acceptance_idx < package_indices[-1]
    assert brief_indices[0] < acceptance_idx < brief_indices[-1]
    assert handoff_indices[0] < acceptance_idx < handoff_indices[-1]


def test_live_pipeline_uses_coverage_and_phase2_readiness_without_manual_validation(tmp_path: Path) -> None:
    args = argparse.Namespace(
        mode="weekly",
        start="2026-06-08",
        end="2026-06-14",
        run_version="live",
        max_teams=5,
        analyst_list="data/analyst-list-production-sample.md",
        retrieval_profile="live",
        sources="wechat_opencli,bocha",
        min_teams=5,
        min_extracted=5,
        quality_profile="production",
        env_file="/tmp/ir_search.env",
        articles_root=str(tmp_path / "articles"),
        output_root=str(tmp_path / "out"),
        db_path=str(tmp_path / "views.db"),
        source_whitelist="data/source_whitelist.yaml",
        source_matrix="broker_wechat_matrix.md",
        skip_wewe_login_prepare=False,
        skip_wechat_dual_source_check=False,
        allow_single_wechat_provider=False,
        allow_empty_wewe_feeds=False,
        wewe_base="http://localhost:4001",
        wewe_container="wewe-rss-ir",
        wewe_auth_code="irsearch",
        wewe_login_wait_seconds=0,
        wechat_accounts="/Users/chen/Documents/ir_search/accounts.json",
    )

    steps = build_steps(args)
    flattened = [" ".join(step) for step in steps]

    assert "scripts/ensure_wechat_dual_source_accounts.py" in flattened[0]
    assert "--fail-on-missing" in flattened[0]
    assert "scripts/prepare_wewe_login.py" in flattened[1]
    assert "--base-url http://localhost:4001" in flattened[1]
    assert "--container wewe-rss-ir" in flattened[1]
    assert "scripts/run_phase1_manual_check.py" not in flattened[2]
    assert "scripts/run_coverage_check.py" in flattened[2]
    assert "--mode weekly" in flattened[2]
    assert "--source-list-confirmed" in flattened[2]
    assert "--env-file /tmp/ir_search.env" in flattened[2]
    assert "scripts/check_phase2_readiness.py" in flattened[3]
    assert any("scripts/check_mvp_acceptance.py" in step and "--quality-profile production" in step for step in flattened)


def test_live_pipeline_can_skip_wewe_prepare(tmp_path: Path) -> None:
    args = argparse.Namespace(
        mode="weekly",
        start="2026-06-08",
        end="2026-06-14",
        run_version="live",
        max_teams=5,
        analyst_list="data/analyst-list-production-sample.md",
        retrieval_profile="live",
        sources="wechat_opencli",
        min_teams=5,
        min_extracted=5,
        quality_profile="production",
        env_file=None,
        articles_root=str(tmp_path / "articles"),
        output_root=str(tmp_path / "out"),
        db_path=str(tmp_path / "views.db"),
        source_whitelist="data/source_whitelist.yaml",
        source_matrix="broker_wechat_matrix.md",
        skip_wewe_login_prepare=True,
        skip_wechat_dual_source_check=False,
        allow_single_wechat_provider=True,
        allow_empty_wewe_feeds=True,
        wewe_base="http://localhost:4001",
        wewe_container="wewe-rss-ir",
        wewe_auth_code="irsearch",
        wewe_login_wait_seconds=0,
        wechat_accounts="/Users/chen/Documents/ir_search/accounts.json",
    )

    flattened = [" ".join(step) for step in build_steps(args)]

    assert not any("scripts/prepare_wewe_login.py" in step for step in flattened)
    assert "scripts/run_coverage_check.py" in flattened[0]
    assert "--allow-single-wechat-provider" in flattened[0]
    assert "--allow-empty-wewe-feeds" in flattened[0]
