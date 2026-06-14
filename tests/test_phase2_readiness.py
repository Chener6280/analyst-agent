from __future__ import annotations

import json
from pathlib import Path

from scripts.check_phase2_readiness import build_readiness


def write_phase2_inputs(base: Path, *, validation_window: dict, coverage_window: dict) -> tuple[Path, Path]:
    scan_dir = base / "scans" / "manual-test-v1"
    diagnostics = base / "diagnostics"
    scan_dir.mkdir(parents=True)
    diagnostics.mkdir(parents=True)
    (diagnostics / "manual_wechat_validation.json").write_text(
        json.dumps(
            {
                "passed": True,
                "file_count": 1,
                "template_count": 0,
                "passed_teams": 1,
                "total_teams": 1,
                "week_dir": "/tmp/articles",
                "window": validation_window,
            }
        ),
        encoding="utf-8",
    )
    (scan_dir / "coverage_summary.json").write_text(
        json.dumps(
            {
                "scan_id": "manual-test-v1",
                "summary": {
                    "phase1_gate": {
                        "covered_plus_partial_ge_60": True,
                        "full_or_partial_text_ge_40": True,
                        "high_or_med_attribution_ge_70": True,
                        "mock_or_placeholder_eq_0": True,
                    }
                },
                "teams": [
                    {
                        "analyst_id": "广发证券:macro",
                        "coverage": "covered",
                        "text_access": "partial_text",
                        "attribution_confidence": "med",
                        "window": coverage_window,
                        "sources": [
                            {
                                "source": "manual_wechat",
                                "adapter_mode": "live",
                                "content_path": "/tmp/a.md",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return scan_dir, diagnostics


def write_validation(path: Path, window: dict) -> None:
    path.write_text(
        json.dumps(
            {
                "scan_id": "manual-test-v1",
                "passed": True,
                "file_count": 1,
                "template_count": 0,
                "passed_teams": 1,
                "total_teams": 1,
                "week_dir": "/tmp/articles",
                "window": window,
            }
        ),
        encoding="utf-8",
    )


def test_phase2_readiness_includes_scan_id_and_passes_matching_window(tmp_path: Path) -> None:
    window = {"start": "2026-06-01", "end": "2026-06-07", "iso_year": 2026, "iso_week": 23}
    scan_dir, diagnostics = write_phase2_inputs(tmp_path, validation_window=window, coverage_window=window)

    result = build_readiness(scan_dir, diagnostics)

    assert result["ready"] is True
    assert result["scan_id"] == "manual-test-v1"


def test_phase2_readiness_fails_window_mismatch(tmp_path: Path) -> None:
    scan_dir, diagnostics = write_phase2_inputs(
        tmp_path,
        validation_window={"start": "2026-06-01", "end": "2026-06-07", "iso_year": 2026, "iso_week": 23},
        coverage_window={"start": "2026-06-08", "end": "2026-06-14", "iso_year": 2026, "iso_week": 24},
    )

    result = build_readiness(scan_dir, diagnostics)

    assert result["ready"] is False
    assert "manual_wechat validation window does not match coverage window" in result["failed_reasons"]


def test_phase2_readiness_prefers_scan_specific_validation(tmp_path: Path) -> None:
    correct = {"start": "2026-06-01", "end": "2026-06-07", "iso_year": 2026, "iso_week": 23}
    stale = {"start": "2026-06-08", "end": "2026-06-14", "iso_year": 2026, "iso_week": 24}
    scan_dir, diagnostics = write_phase2_inputs(tmp_path, validation_window=stale, coverage_window=correct)
    write_validation(diagnostics / "manual-test-v1__manual_wechat_validation.json", correct)

    result = build_readiness(scan_dir, diagnostics)

    assert result["ready"] is True
    assert result["validation"]["window"] == correct


def test_phase2_readiness_does_not_require_manual_validation_for_live_wechat(tmp_path: Path) -> None:
    scan_dir = tmp_path / "scans" / "live-test"
    diagnostics = tmp_path / "diagnostics"
    scan_dir.mkdir(parents=True)
    diagnostics.mkdir(parents=True)
    window = {"start": "2026-06-08", "end": "2026-06-14", "iso_year": 2026, "iso_week": 24}
    (scan_dir / "coverage_summary.json").write_text(
        json.dumps(
            {
                "scan_id": "live-test",
                "summary": {
                    "phase1_gate": {
                        "covered_plus_partial_ge_60": True,
                        "full_or_partial_text_ge_40": True,
                        "high_or_med_attribution_ge_70": True,
                        "mock_or_placeholder_eq_0": True,
                    }
                },
                "teams": [
                    {
                        "analyst_id": "国金证券:strategy",
                        "coverage": "covered",
                        "text_access": "full_text",
                        "attribution_confidence": "high",
                        "window": window,
                        "sources": [
                            {
                                "source": "wechat_opencli",
                                "adapter_mode": "live",
                                "content_path": "/tmp/live.md",
                            }
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = build_readiness(scan_dir, diagnostics)

    assert result["ready"] is True
    assert result["validation"]["required"] is False
