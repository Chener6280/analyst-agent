from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_diagnostic_pair(
    diagnostics_dir: Path,
    *,
    stem: str,
    scan_id: str | None,
    data: dict[str, Any],
    markdown: str,
) -> tuple[Path, Path, Path | None, Path | None]:
    diagnostics_dir.mkdir(parents=True, exist_ok=True)
    json_path = diagnostics_dir / f"{stem}.json"
    md_path = diagnostics_dir / f"{stem}.md"
    json_text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    json_path.write_text(json_text, encoding="utf-8")
    md_path.write_text(markdown, encoding="utf-8")

    scan_json_path = None
    scan_md_path = None
    if scan_id:
        safe_scan_id = sanitize_filename(scan_id)
        scan_json_path = diagnostics_dir / f"{safe_scan_id}__{stem}.json"
        scan_md_path = diagnostics_dir / f"{safe_scan_id}__{stem}.md"
        scan_json_path.write_text(json_text, encoding="utf-8")
        scan_md_path.write_text(markdown, encoding="utf-8")
    return json_path, md_path, scan_json_path, scan_md_path


def sanitize_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in {"-", "_", "."} else "_" for char in value)
