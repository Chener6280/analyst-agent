from __future__ import annotations

import json
from pathlib import Path

from mcp.analyst_views_server import handle_request
from tests.test_agent_interface import prepare_scan


def test_mcp_server_lists_tools() -> None:
    response = handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, output_root="/tmp", db_path="/tmp/missing.db")

    assert response is not None
    tools = response["result"]["tools"]
    assert any(tool["name"] == "scan_context" for tool in tools)
    assert any(tool["name"] == "consensus_series" for tool in tools)


def test_mcp_server_calls_dim_summary(tmp_path: Path) -> None:
    scan_id, output_root, db_path = prepare_scan(tmp_path)

    response = handle_request(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "dim_summary", "arguments": {"scan_id": scan_id, "role": "macro", "dim_key": "growth"}},
        },
        output_root=output_root,
        db_path=db_path,
    )

    assert response is not None
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["n_non_null"] == 2
