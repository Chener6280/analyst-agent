from __future__ import annotations

import json

from scripts.diagnostic_io import sanitize_filename, write_diagnostic_pair


def test_sanitize_filename() -> None:
    assert sanitize_filename("manual:2026/06/01 v1") == "manual_2026_06_01_v1"


def test_write_diagnostic_pair_writes_latest_and_scan_specific(tmp_path) -> None:
    data = {"scan_id": "manual:2026/06/01 v1", "ready": True}
    json_path, md_path, scan_json_path, scan_md_path = write_diagnostic_pair(
        tmp_path,
        stem="phase2_readiness",
        scan_id=data["scan_id"],
        data=data,
        markdown="# ready\n",
    )

    assert json_path.name == "phase2_readiness.json"
    assert md_path.name == "phase2_readiness.md"
    assert scan_json_path is not None
    assert scan_md_path is not None
    assert scan_json_path.name == "manual_2026_06_01_v1__phase2_readiness.json"
    assert scan_md_path.name == "manual_2026_06_01_v1__phase2_readiness.md"
    assert json.loads(scan_json_path.read_text(encoding="utf-8")) == data
    assert scan_md_path.read_text(encoding="utf-8") == "# ready\n"
