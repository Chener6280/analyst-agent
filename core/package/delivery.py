from __future__ import annotations

import hashlib
import json
from html import escape
from pathlib import Path
from typing import Any

PACKAGE_VERSION = 1


def build_project_package(
    scan_id: str,
    *,
    output_root: str | Path = "~/macro-strategy",
    db_path: str | Path = "~/macro-strategy/analyst_views.db",
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    repo_dir = Path(repo_root).resolve() if repo_root else Path.cwd().resolve()
    output_dir = Path(output_root).expanduser()
    scan_dir = output_dir / "scans" / scan_id
    reports_dir = scan_dir / "reports"
    package_dir = reports_dir / "project_package"
    package_dir.mkdir(parents=True, exist_ok=True)

    inputs = read_inputs(scan_id, output_dir, reports_dir)
    manifest = build_manifest(scan_id, output_dir, reports_dir, package_dir, db_path=Path(db_path).expanduser(), repo_root=repo_dir, inputs=inputs)

    report_md = render_markdown_report(manifest, inputs)
    report_html = render_html_report(manifest, inputs)
    checklist = render_completion_checklist(manifest, inputs)
    launchd = render_launchd_plist(repo_dir=repo_dir, output_root=output_dir, db_path=Path(db_path).expanduser())

    files = {
        "final_report_md": package_dir / "final_report.md",
        "final_report_html": package_dir / "final_report.html",
        "completion_checklist": package_dir / "completion_checklist.md",
        "weekly_launchd_plist": package_dir / "com.local.analyst-views.weekly.plist",
    }
    files["final_report_md"].write_text(report_md, encoding="utf-8")
    files["final_report_html"].write_text(report_html, encoding="utf-8")
    files["completion_checklist"].write_text(checklist, encoding="utf-8")
    files["weekly_launchd_plist"].write_text(launchd, encoding="utf-8")

    manifest["package_files"] = {key: str(path) for key, path in files.items()}
    manifest["checksums"] = checksums(list(required_artifact_paths(manifest)) + list(files.values()))
    manifest["status"] = package_status(manifest, inputs)
    manifest_path = package_dir / "project_completion.json"
    manifest["package_files"]["project_completion_json"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def read_inputs(scan_id: str, output_dir: Path, reports_dir: Path) -> dict[str, Any]:
    diagnostics_dir = output_dir / "diagnostics"
    return {
        "weekly_brief": read_json(reports_dir / "weekly_brief.json"),
        "agent_handoff": read_json(reports_dir / "agent_handoff.json"),
        "history_readiness": read_json(reports_dir / "history_readiness.json"),
        "visual_pack": read_json(reports_dir / "visual_pack.json"),
        "full_text_recovery": read_json(reports_dir / "full_text_recovery_report.json"),
        "acceptance": read_scan_acceptance(diagnostics_dir, scan_id),
    }


def read_scan_acceptance(diagnostics_dir: Path, scan_id: str) -> dict[str, Any]:
    return read_json(diagnostics_dir / f"{scan_id}__mvp_acceptance.json")


def build_manifest(
    scan_id: str,
    output_dir: Path,
    reports_dir: Path,
    package_dir: Path,
    *,
    db_path: Path,
    repo_root: Path,
    inputs: dict[str, Any],
) -> dict[str, Any]:
    artifacts = {
        "database": str(db_path),
        "coverage_report": str(output_dir / "scans" / scan_id / "coverage_report.md"),
        "weekly_cross_section": str(reports_dir / "weekly_cross_section.md"),
        "weekly_brief": str(reports_dir / "weekly_brief.md"),
        "agent_handoff": str(reports_dir / "agent_handoff.md"),
        "history_readiness": str(reports_dir / "history_readiness.md"),
        "visual_pack": str(reports_dir / "visual_pack.md"),
        "full_text_recovery": str(reports_dir / "full_text_recovery_report.md"),
        "mvp_acceptance": str(output_dir / "diagnostics" / f"{scan_id}__mvp_acceptance.md"),
        "mcp_server": str(repo_root / "mcp" / "analyst_views_server.py"),
        "pipeline_script": str(repo_root / "scripts" / "run_mvp_pipeline.py"),
    }
    for item in (inputs.get("visual_pack") or {}).get("visuals", []):
        key = "chart_" + str(item.get("title", "chart")).lower().replace(" ", "_")
        artifacts[key] = str(item.get("path"))

    return {
        "package_version": PACKAGE_VERSION,
        "scan_id": scan_id,
        "package_dir": str(package_dir),
        "artifacts": artifacts,
        "acceptance_passed": (inputs.get("acceptance") or {}).get("passed"),
        "engineering_ready": (inputs.get("acceptance") or {}).get("engineering_ready", (inputs.get("acceptance") or {}).get("passed")),
        "production_ready": bool((inputs.get("full_text_recovery") or {}).get("production_ready")),
        "agent_handoff_status": (inputs.get("agent_handoff") or {}).get("status"),
        "history_status": (inputs.get("history_readiness") or {}).get("status"),
        "visual_pack_status": (inputs.get("visual_pack") or {}).get("status"),
        "mcp": {
            "server": str(repo_root / "mcp" / "analyst_views_server.py"),
            "example": f"python3 {repo_root / 'mcp' / 'analyst_views_server.py'} --output-root {output_dir} --db-path {db_path}",
        },
        "automation": {
            "type": "launchd_template",
            "template_note": "Template only. It is not installed automatically.",
        },
    }


def package_status(manifest: dict[str, Any], inputs: dict[str, Any]) -> str:
    required_exist = all(path_exists(path) for path in required_artifact_paths(manifest))
    if not required_exist:
        return "incomplete"
    if manifest.get("acceptance_passed") is not True:
        return "review_required"
    if manifest.get("agent_handoff_status") not in {"ready", "review_required"}:
        return "incomplete"
    if manifest.get("history_status") not in {"ready", "insufficient_history"}:
        return "incomplete"
    if manifest.get("visual_pack_status") != "ready":
        return "incomplete"
    return "ready" if manifest.get("engineering_ready") else "review_required"


def required_artifact_paths(manifest: dict[str, Any]) -> list[Path]:
    return [Path(value) for value in (manifest.get("artifacts") or {}).values() if value]


def path_exists(path: str | Path) -> bool:
    p = Path(path)
    return p.exists() and p.stat().st_size > 0


def checksums(paths: list[Path]) -> dict[str, str]:
    result = {}
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        result[str(path)] = sha256(path)
    return result


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_markdown_report(manifest: dict[str, Any], inputs: dict[str, Any]) -> str:
    brief = inputs.get("weekly_brief") or {}
    lines = [
        "# Analyst Views Final Report",
        "",
        f"Scan: `{manifest['scan_id']}`",
        "",
        f"> {quality_banner(brief, inputs)}",
        "",
        "## Executive Summary",
        "",
        brief.get("headline") or "n/a",
        "",
        "## Status",
        "",
        f"- acceptance_passed: {manifest.get('acceptance_passed')}",
        f"- engineering_ready: {manifest.get('engineering_ready')}",
        f"- production_ready: {manifest.get('production_ready')}",
        f"- agent_handoff_status: {manifest.get('agent_handoff_status')}",
        f"- history_status: {manifest.get('history_status')}",
        f"- visual_pack_status: {manifest.get('visual_pack_status')}",
        "",
        "## Artifacts",
        "",
        "| artifact | path |",
        "|---|---|",
    ]
    for key, path in (manifest.get("artifacts") or {}).items():
        lines.append(f"| {key} | `{path}` |")
    lines.extend(["", "## Quality Warnings", ""])
    quality = brief.get("quality") or {}
    warnings = quality.get("quality_warnings") or []
    if warnings:
        for warning in warnings:
            lines.append(f"- {warning}")
    else:
        lines.append("- none")
    lines.extend(["", "## MCP-Compatible Local Server", "", f"`{manifest['mcp']['example']}`", ""])
    return "\n".join(lines)


def render_html_report(manifest: dict[str, Any], inputs: dict[str, Any]) -> str:
    brief = inputs.get("weekly_brief") or {}
    visuals = (inputs.get("visual_pack") or {}).get("visuals", [])
    warnings = ((brief.get("quality") or {}).get("quality_warnings") or [])
    banner = quality_banner(brief, inputs)
    visual_html = "\n".join(
        f'<section><h3>{escape(item["title"])}</h3><img src="../charts/{escape(Path(item["path"]).name)}" alt="{escape(item["title"])}"></section>'
        for item in visuals
    )
    warning_html = "".join(f"<li>{escape(str(warning))}</li>" for warning in warnings) or "<li>none</li>"
    artifact_rows = "".join(
        f"<tr><td>{escape(key)}</td><td><code>{escape(str(path))}</code></td></tr>" for key, path in (manifest.get("artifacts") or {}).items()
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Analyst Views Final Report</title>
  <style>
    body {{ font-family: Arial, sans-serif; color: #172026; margin: 32px; line-height: 1.5; }}
    h1, h2, h3 {{ margin-bottom: 8px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    td, th {{ border: 1px solid #D0D5DD; padding: 8px; text-align: left; vertical-align: top; }}
    code {{ font-size: 12px; }}
    img {{ max-width: 100%; border: 1px solid #EAECF0; }}
  </style>
</head>
<body>
  <h1>Analyst Views Final Report</h1>
  <p><strong>Scan:</strong> {escape(manifest['scan_id'])}</p>
  <h2>Executive Summary</h2>
  <p><strong>{escape(banner)}</strong></p>
  <p>{escape(str(brief.get('headline') or 'n/a'))}</p>
  <h2>Status</h2>
  <ul>
    <li>acceptance_passed: {escape(str(manifest.get('acceptance_passed')))}</li>
    <li>engineering_ready: {escape(str(manifest.get('engineering_ready')))}</li>
    <li>production_ready: {escape(str(manifest.get('production_ready')))}</li>
    <li>agent_handoff_status: {escape(str(manifest.get('agent_handoff_status')))}</li>
    <li>history_status: {escape(str(manifest.get('history_status')))}</li>
    <li>visual_pack_status: {escape(str(manifest.get('visual_pack_status')))}</li>
  </ul>
  <h2>Visuals</h2>
  {visual_html}
  <h2>Quality Warnings</h2>
  <ul>{warning_html}</ul>
  <h2>Artifacts</h2>
  <table><tbody>{artifact_rows}</tbody></table>
</body>
</html>
"""


def render_completion_checklist(manifest: dict[str, Any], inputs: dict[str, Any]) -> str:
    checks = [
        ("MVP acceptance passed", manifest.get("acceptance_passed") is True),
        ("Engineering ready", manifest.get("engineering_ready") is True),
        ("Production ready", manifest.get("production_ready") is True),
        ("Agent handoff exported", manifest.get("agent_handoff_status") in {"ready", "review_required"}),
        ("History readiness exported", manifest.get("history_status") in {"ready", "insufficient_history"}),
        ("Visual pack exported", manifest.get("visual_pack_status") == "ready"),
        ("MCP-compatible server present", path_exists((manifest.get("mcp") or {}).get("server", ""))),
        ("All required artifact paths exist", all(path_exists(path) for path in required_artifact_paths(manifest))),
    ]
    lines = ["# Project Completion Checklist", ""]
    for label, passed in checks:
        lines.append(f"- [{'x' if passed else ' '}] {label}")
    lines.extend(["", "## Remaining Real-World Conditions", ""])
    if manifest.get("history_status") == "insufficient_history":
        lines.append("- Accumulate at least 4 real weekly scans before interpreting trends.")
    if manifest.get("production_ready") is not True:
        lines.append("- Full-text/source-quality gates are not production-ready yet.")
    quality = (inputs.get("weekly_brief") or {}).get("quality") or {}
    if quality.get("quality_warnings"):
        lines.append("- Review quality warnings before using the report for investment decisions.")
    return "\n".join(lines) + "\n"


def quality_banner(brief: dict[str, Any], inputs: dict[str, Any]) -> str:
    quality = brief.get("quality") or {}
    recovery = inputs.get("full_text_recovery") or {}
    history = inputs.get("history_readiness") or {}
    if recovery.get("production_ready") is True and history.get("status") == "ready":
        return "数据质量提示：当前结果满足 production profile。"
    return "数据质量提示：本周结果为 sample MVP 输出。全文覆盖率低，部分来源为转载或研报平台，当前结果不应作为正式投研结论。"


def render_launchd_plist(*, repo_dir: Path, output_root: Path, db_path: Path) -> str:
    script = repo_dir / "scripts" / "run_mvp_pipeline.py"
    analyst_list = repo_dir / "data" / "analyst-list-acceptance-candidates.md"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.local.analyst-views.weekly</string>
  <key>ProgramArguments</key>
  <array>
    <string>python3</string>
    <string>{escape(str(script))}</string>
    <string>--analyst-list</string>
    <string>{escape(str(analyst_list))}</string>
    <string>--max-teams</string>
    <string>10</string>
    <string>--output-root</string>
    <string>{escape(str(output_root))}</string>
    <string>--db-path</string>
    <string>{escape(str(db_path))}</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key>
    <integer>1</integer>
    <key>Hour</key>
    <integer>8</integer>
    <key>Minute</key>
    <integer>30</integer>
  </dict>
  <key>WorkingDirectory</key>
  <string>{escape(str(repo_dir))}</string>
  <key>StandardOutPath</key>
  <string>{escape(str(output_root / "logs" / "weekly.out.log"))}</string>
  <key>StandardErrorPath</key>
  <string>{escape(str(output_root / "logs" / "weekly.err.log"))}</string>
</dict>
</plist>
"""


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))
