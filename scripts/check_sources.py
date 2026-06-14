#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts._env_utils import load_env_file

IR_SEARCH_PATH = Path("/Users/chen/Documents/Codex/2026-06-08/files-mentioned-by-the-user-ir")


def main() -> int:
    args = parse_args()
    env_file = load_env_file(args.env_file)
    os.environ.setdefault("IR_SEARCH_LIVE", "1")

    diagnostics = build_diagnostics(env_file)
    output_dir = Path(args.output_root).expanduser() / "diagnostics"
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "source_diagnostics.json"
    md_path = output_dir / "source_diagnostics.md"
    json_path.write_text(json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(diagnostics), encoding="utf-8")

    print(f"source_diagnostics={md_path}")
    print(f"json={json_path}")
    return 0


def build_diagnostics(env_file: Path | None) -> dict[str, Any]:
    backend = load_ir_search()
    registry = {}
    if backend is not None:
        try:
            registry = backend.build_registry(live=True)
        except Exception:
            registry = {}

    env_checks = {key: bool(os.environ.get(key)) for key in ["WECHAT_OPENCLI_COMMAND", "BOCHA_API_KEY", "EXA_API_KEY"]}
    command_check = check_opencli_command(os.environ.get("WECHAT_OPENCLI_COMMAND"))
    sources = []
    for source in ["wechat_opencli", "bocha", "exa", "web_search"]:
        adapter = registry.get(source)
        mode = getattr(adapter, "mode", "unavailable") if adapter is not None else "unavailable"
        status = "live" if mode == "live" else mode
        issue = None
        if source == "wechat_opencli" and not env_checks["WECHAT_OPENCLI_COMMAND"]:
            status = "source_lost"
            issue = "wechat_opencli unavailable: WECHAT_OPENCLI_COMMAND is not set"
        elif source == "wechat_opencli" and not command_check["executable"]:
            status = "source_lost"
            issue = "WECHAT_OPENCLI_COMMAND is set but command is not executable"
        elif mode in {"mock", "placeholder", "unavailable"}:
            issue = f"adapter_mode={mode}"
        sources.append(
            {
                "source": source,
                "status": status,
                "adapter_mode": mode,
                "ok": issue is None,
                "issue": issue,
            }
        )

    return {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "env_file_loaded": str(env_file) if env_file else None,
        "environment": env_checks,
        "wechat_opencli_command": command_check,
        "ir_search": {
            "importable": backend is not None,
            "mcp_importable": check_mcp_importable(),
            "path": str(IR_SEARCH_PATH) if IR_SEARCH_PATH.exists() else None,
        },
        "sources": sources,
        "mock_or_placeholder_sources": [
            item["source"] for item in sources if item["adapter_mode"] in {"mock", "placeholder"}
        ],
    }


def load_ir_search() -> Any | None:
    if IR_SEARCH_PATH.exists() and str(IR_SEARCH_PATH) not in sys.path:
        sys.path.insert(0, str(IR_SEARCH_PATH))
    try:
        import ir_search

        return ir_search
    except Exception:
        return None


def check_mcp_importable() -> bool:
    if IR_SEARCH_PATH.exists() and str(IR_SEARCH_PATH) not in sys.path:
        sys.path.insert(0, str(IR_SEARCH_PATH))
    try:
        import ir_search.mcp_server  # noqa: F401

        return True
    except Exception:
        return False


def check_opencli_command(command: str | None) -> dict[str, Any]:
    if not command:
        return {"set": False, "executable": False, "program": None, "issue": "WECHAT_OPENCLI_COMMAND is not set"}
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return {"set": True, "executable": False, "program": None, "issue": f"cannot parse command: {exc}"}
    if not parts:
        return {"set": True, "executable": False, "program": None, "issue": "command is empty"}
    program = parts[0]
    executable = Path(program).exists() if "/" in program else shutil.which(program) is not None
    return {
        "set": True,
        "executable": executable,
        "program": program,
        "issue": None if executable else "program not found or not executable",
    }


def render_markdown(data: dict[str, Any]) -> str:
    lines = [
        "# Source Diagnostics",
        "",
        "## Environment",
        "",
        "| key | present |",
        "|---|---:|",
    ]
    for key, present in data["environment"].items():
        lines.append(f"| {key} | {'yes' if present else 'no'} |")
    lines.extend(
        [
            "",
            "## ir_search",
            "",
            "| check | value |",
            "|---|---:|",
            f"| importable | {'yes' if data['ir_search']['importable'] else 'no'} |",
            f"| mcp_importable | {'yes' if data['ir_search']['mcp_importable'] else 'no'} |",
            "",
            "## Sources",
            "",
            "| source | status | adapter_mode | issue |",
            "|---|---|---|---|",
        ]
    )
    for item in data["sources"]:
        issue = (item.get("issue") or "").replace("|", "\\|")
        lines.append(
            f"| {item['source']} | {item['status']} | {item['adapter_mode']} | {issue} |"
        )
    if data["wechat_opencli_command"].get("issue"):
        lines.extend(["", f"wechat_opencli unavailable: {data['wechat_opencli_command']['issue']}"])
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check analyst-view retrieval source configuration.")
    parser.add_argument("--env-file")
    parser.add_argument("--output-root", default="~/macro-strategy")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
