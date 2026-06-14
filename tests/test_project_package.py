from __future__ import annotations

import json
from pathlib import Path

from core.package.delivery import build_project_package
from core.visual.charts import build_visual_pack
from tests.test_visual_pack import prepare_visual_inputs


def test_project_package_exports_final_report_manifest_and_launchd_template(tmp_path: Path) -> None:
    scan_id, output_root, db_path = prepare_visual_inputs(tmp_path)
    visual_pack = build_visual_pack(scan_id, output_root=output_root, db_path=db_path)
    reports_dir = output_root / "scans" / scan_id / "reports"
    (output_root / "scans" / scan_id / "coverage_report.md").write_text("# coverage\n", encoding="utf-8")
    (output_root / "scans" / scan_id / "source_links.md").write_text("# links\n", encoding="utf-8")
    (output_root / "scans" / scan_id / "source_links.csv").write_text("url\nhttps://example.com\n", encoding="utf-8")
    (output_root / "scans" / scan_id / "source_links.json").write_text(json.dumps({"links": []}), encoding="utf-8")
    (reports_dir / "visual_pack.json").write_text(json.dumps(visual_pack), encoding="utf-8")
    (reports_dir / "visual_pack.md").write_text("# visual pack\n", encoding="utf-8")
    (reports_dir / "full_text_recovery_report.json").write_text(json.dumps({"production_ready": False}), encoding="utf-8")
    (reports_dir / "full_text_recovery_report.md").write_text("# recovery\n", encoding="utf-8")
    (reports_dir / "agent_handoff.json").write_text(json.dumps({"status": "ready"}), encoding="utf-8")
    (reports_dir / "agent_handoff.md").write_text("# handoff\n", encoding="utf-8")
    (output_root / "diagnostics" / f"{scan_id}__mvp_acceptance.md").write_text("# acceptance\n", encoding="utf-8")
    (output_root / "diagnostics" / f"{scan_id}__mvp_acceptance.json").write_text(
        json.dumps({"passed": True}),
        encoding="utf-8",
    )

    manifest = build_project_package(scan_id, output_root=output_root, db_path=db_path, repo_root=Path.cwd())

    assert manifest["status"] == "ready"
    assert Path(manifest["package_files"]["final_report_html"]).exists()
    assert Path(manifest["package_files"]["weekly_launchd_plist"]).read_text(encoding="utf-8").startswith("<?xml")
    assert "mcp/analyst_views_server.py" in manifest["mcp"]["server"]
    assert manifest["artifacts"]["source_links_csv"].endswith("source_links.csv")
    assert manifest["checksums"]


def test_project_package_does_not_reuse_global_acceptance_for_different_scan(tmp_path: Path) -> None:
    scan_id, output_root, db_path = prepare_visual_inputs(tmp_path)
    visual_pack = build_visual_pack(scan_id, output_root=output_root, db_path=db_path)
    reports_dir = output_root / "scans" / scan_id / "reports"
    (output_root / "scans" / scan_id / "coverage_report.md").write_text("# coverage\n", encoding="utf-8")
    (output_root / "scans" / scan_id / "source_links.md").write_text("# links\n", encoding="utf-8")
    (output_root / "scans" / scan_id / "source_links.csv").write_text("url\nhttps://example.com\n", encoding="utf-8")
    (output_root / "scans" / scan_id / "source_links.json").write_text(json.dumps({"links": []}), encoding="utf-8")
    (reports_dir / "visual_pack.json").write_text(json.dumps(visual_pack), encoding="utf-8")
    (reports_dir / "visual_pack.md").write_text("# visual pack\n", encoding="utf-8")
    (reports_dir / "full_text_recovery_report.json").write_text(json.dumps({"production_ready": False}), encoding="utf-8")
    (reports_dir / "full_text_recovery_report.md").write_text("# recovery\n", encoding="utf-8")
    (reports_dir / "agent_handoff.json").write_text(json.dumps({"status": "ready"}), encoding="utf-8")
    (reports_dir / "agent_handoff.md").write_text("# handoff\n", encoding="utf-8")
    (output_root / "diagnostics" / f"{scan_id}__mvp_acceptance.json").unlink()
    (output_root / "diagnostics" / "mvp_acceptance.json").write_text(
        json.dumps({"scan_id": "other", "passed": True}),
        encoding="utf-8",
    )
    (output_root / "diagnostics" / "mvp_acceptance.md").write_text("# stale\n", encoding="utf-8")

    manifest = build_project_package(scan_id, output_root=output_root, db_path=db_path, repo_root=Path.cwd())

    assert manifest["acceptance_passed"] is None
    assert manifest["status"] == "incomplete"
