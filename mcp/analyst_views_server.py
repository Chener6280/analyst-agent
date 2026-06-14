#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.history.timeseries import build_consensus_series, build_history_readiness, build_tag_rotation, build_team_series
from core.interface.read_api import build_agent_handoff, get_dimension_summary, get_entity_mentions, get_team_stance

SERVER_NAME = "analyst-views-local"
PROTOCOL_VERSION = "2024-11-05"


def main() -> int:
    args = parse_args()
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request, output_root=args.output_root, db_path=args.db_path)
        except Exception as exc:  # pragma: no cover - final fallback for stdio server robustness
            response = json_rpc_error(None, -32603, str(exc))
        if response is not None:
            print(json.dumps(response, ensure_ascii=False), flush=True)
    return 0


def handle_request(request: dict[str, Any], *, output_root: str | Path, db_path: str | Path) -> dict[str, Any] | None:
    method = request.get("method")
    request_id = request.get("id")
    if method in {"notifications/initialized", "notifications/cancelled"}:
        return None
    if method == "initialize":
        return json_rpc_result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": "0.1.0"},
            },
        )
    if method == "tools/list":
        return json_rpc_result(request_id, {"tools": tool_definitions()})
    if method == "tools/call":
        params = request.get("params") or {}
        try:
            result = call_tool(params.get("name"), params.get("arguments") or {}, output_root=output_root, db_path=db_path)
        except ValueError as exc:
            return json_rpc_error(request_id, -32602, str(exc))
        return json_rpc_result(
            request_id,
            {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]},
        )
    return json_rpc_error(request_id, -32601, f"unsupported method: {method}")


def call_tool(name: str | None, arguments: dict[str, Any], *, output_root: str | Path, db_path: str | Path) -> dict[str, Any]:
    if name == "scan_context":
        return build_agent_handoff(require(arguments, "scan_id"), output_root=output_root, db_path=db_path)
    if name == "dim_summary":
        return get_dimension_summary(require(arguments, "scan_id"), require(arguments, "role"), require(arguments, "dim_key"), db_path=db_path)
    if name == "team_stance":
        return get_team_stance(require(arguments, "scan_id"), require(arguments, "analyst_id"), db_path=db_path)
    if name == "who_mentioned":
        return get_entity_mentions(require(arguments, "scan_id"), require(arguments, "entity"), db_path=db_path)
    if name == "history_readiness":
        return build_history_readiness(require(arguments, "scan_id"), db_path=db_path, min_scans=int(arguments.get("min_scans") or 4))
    if name == "consensus_series":
        return build_consensus_series(require(arguments, "role"), require(arguments, "dim_key"), db_path=db_path, limit=arguments.get("limit"))
    if name == "team_series":
        return build_team_series(require(arguments, "analyst_id"), require(arguments, "dim_key"), db_path=db_path, limit=arguments.get("limit"))
    if name == "tag_rotation":
        return build_tag_rotation(
            require(arguments, "role"),
            require(arguments, "dim_key"),
            db_path=db_path,
            limit=arguments.get("limit"),
            top_n=int(arguments.get("top_n") or 10),
        )
    raise ValueError(f"unsupported tool: {name}")


def require(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if value in {None, ""}:
        raise ValueError(f"missing required argument: {key}")
    return str(value)


def tool_definitions() -> list[dict[str, Any]]:
    return [
        tool("scan_context", "Return the P5 handoff context for one scan.", {"scan_id": string_schema()}),
        tool("dim_summary", "Return one macro or strategy dimension summary.", {"scan_id": string_schema(), "role": string_schema(), "dim_key": string_schema()}),
        tool("team_stance", "Return all stance rows, selections, and sources for one analyst team.", {"scan_id": string_schema(), "analyst_id": string_schema()}),
        tool("who_mentioned", "Return teams that mentioned one canonical entity.", {"scan_id": string_schema(), "entity": string_schema()}),
        tool("history_readiness", "Return P6 history readiness for one scan.", {"scan_id": string_schema(), "min_scans": integer_schema()}),
        tool("consensus_series", "Return per-scan consensus for an ordinal dimension.", {"role": string_schema(), "dim_key": string_schema(), "limit": integer_schema()}),
        tool("team_series", "Return one team's per-scan stance series.", {"analyst_id": string_schema(), "dim_key": string_schema(), "limit": integer_schema()}),
        tool("tag_rotation", "Return per-scan categorical tag rotation.", {"role": string_schema(), "dim_key": string_schema(), "limit": integer_schema(), "top_n": integer_schema()}),
    ]


def tool(name: str, description: str, properties: dict[str, Any]) -> dict[str, Any]:
    required = [key for key, schema in properties.items() if not schema.get("optional")]
    cleaned = {key: {k: v for k, v in schema.items() if k != "optional"} for key, schema in properties.items()}
    return {"name": name, "description": description, "inputSchema": {"type": "object", "properties": cleaned, "required": required}}


def string_schema() -> dict[str, Any]:
    return {"type": "string"}


def integer_schema() -> dict[str, Any]:
    return {"type": "integer", "optional": True}


def json_rpc_result(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def json_rpc_error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local stdio MCP-compatible server for analyst views.")
    parser.add_argument("--output-root", default="~/macro-strategy")
    parser.add_argument("--db-path", default="~/macro-strategy/analyst_views.db")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
