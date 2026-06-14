from __future__ import annotations

import json
from pathlib import Path

from scripts.export_full_text_recovery_report import build_recovery_report, render_markdown


def test_full_text_recovery_report_does_not_flag_unknown_completeness_for_full_text(tmp_path: Path) -> None:
    scan_dir = tmp_path / "scans" / "scan"
    extracted = scan_dir / "extracted"
    extracted.mkdir(parents=True)
    (scan_dir / "coverage_summary.json").write_text(
        json.dumps(
            {
                "scan_id": "scan",
                "summary": {
                    "total_teams": 1,
                    "full_text_count": 1,
                    "partial_text_count": 0,
                    "full_text_rate": "100%",
                    "production_coverage_rate": "100%",
                    "official_or_broker_source_rate": "100%",
                },
                "teams": [
                    {
                        "analyst_id": "国金证券:strategy",
                        "source_type": "official_wechat",
                        "text_access": "full_text",
                        "sources": [{"url": "local:///work/yiling_latest_wechat.txt"}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (extracted / "extraction_summary.json").write_text(
        json.dumps({"quality": {"zero_signal_documents": []}}, ensure_ascii=False),
        encoding="utf-8",
    )

    report = build_recovery_report(
        scan_dir,
        analyst_list="data/analyst-list-acceptance-candidates.md",
        source_whitelist="data/source_whitelist.yaml",
    )
    target = next(row for row in report["priority_recovery_list"] if row["analyst_id"] == "国金证券:strategy")

    assert target["priority"] == "OK"
    assert target["issues"] == []


def test_full_text_recovery_report_prioritizes_zero_signal_and_non_official(tmp_path: Path) -> None:
    scan_dir = tmp_path / "scans" / "scan"
    extracted = scan_dir / "extracted"
    extracted.mkdir(parents=True)
    (scan_dir / "coverage_summary.json").write_text(
        json.dumps(
            {
                "scan_id": "scan",
                "summary": {
                    "total_teams": 1,
                    "full_text_count": 0,
                    "partial_text_count": 1,
                    "full_text_rate": "0%",
                    "production_coverage_rate": "0%",
                    "official_or_broker_source_rate": "0%",
                },
                "teams": [
                    {
                        "analyst_id": "广发证券:macro",
                        "source_type": "financial_media",
                        "text_access": "partial_text",
                        "source_completeness": "excerpt",
                        "sources": [{"url": "https://finance.sina.com.cn/a"}],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (extracted / "extraction_summary.json").write_text(
        json.dumps({"quality": {"zero_signal_documents": ["广发证券:macro"]}}, ensure_ascii=False),
        encoding="utf-8",
    )

    report = build_recovery_report(
        scan_dir,
        analyst_list="data/analyst-list-acceptance-candidates.md",
        source_whitelist="data/source_whitelist.yaml",
    )
    text = render_markdown(report)

    target = next(row for row in report["priority_recovery_list"] if row["analyst_id"] == "广发证券:macro")
    assert target["priority"] == "P0"
    assert "zero_signal" in target["issues"]
    assert report["production_ready"] is False
    assert "Full-text Recovery Report" in text
