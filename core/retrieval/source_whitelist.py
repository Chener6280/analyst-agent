from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import urlparse

DEFAULT_SOURCE_WHITELIST = Path(__file__).resolve().parents[2] / "data" / "source_whitelist.yaml"


def load_source_whitelist(path: str | Path = DEFAULT_SOURCE_WHITELIST) -> dict[str, Any]:
    source_path = Path(path)
    if not source_path.exists():
        return {"official_accounts": {}}
    return parse_simple_yaml(source_path.read_text(encoding="utf-8"))


def whitelist_entry(analyst_id: str, whitelist: dict[str, Any] | None = None) -> dict[str, Any]:
    data = whitelist or load_source_whitelist()
    return (data.get("official_accounts") or {}).get(analyst_id, {})


def is_official_account(analyst_id: str, account_name: str | None, url: str | None, whitelist: dict[str, Any] | None = None) -> bool:
    entry = whitelist_entry(analyst_id, whitelist)
    if not entry or not account_name:
        return False
    accounts = set(entry.get("accounts") or [])
    if account_name not in accounts:
        return False
    allowed_domains = set(entry.get("allowed_domains") or [])
    if not allowed_domains:
        return True
    host = urlparse(url or "").netloc.lower()
    return any(domain in host for domain in allowed_domains)


def official_account_suggestions(team: dict[str, Any], whitelist: dict[str, Any] | None = None) -> dict[str, Any]:
    analyst_id = str(team.get("analyst_id") or "")
    entry = whitelist_entry(analyst_id, whitelist)
    current_accounts = list(team.get("official_accounts") or [])
    whitelist_accounts = list(entry.get("accounts") or [])
    missing_from_whitelist = [item for item in current_accounts if item not in whitelist_accounts]
    extra_in_whitelist = [item for item in whitelist_accounts if item not in current_accounts]
    return {
        "analyst_id": analyst_id,
        "institution": team.get("institution"),
        "role": team.get("role"),
        "team_members": team.get("team_members", []),
        "current_official_accounts": current_accounts,
        "whitelist_accounts": whitelist_accounts,
        "allowed_domains": entry.get("allowed_domains", []),
        "missing_from_whitelist": missing_from_whitelist,
        "extra_in_whitelist": extra_in_whitelist,
        "needs_review": bool(missing_from_whitelist or extra_in_whitelist or not whitelist_accounts),
        "recommended_action": recommended_action(missing_from_whitelist, extra_in_whitelist, whitelist_accounts),
    }


def recommended_action(missing: list[str], extra: list[str], whitelist_accounts: list[str]) -> str:
    if not whitelist_accounts:
        return "补充官方公众号白名单"
    if missing and extra:
        return "核对 analyst-list 与 source_whitelist 的公众号差异"
    if missing:
        return "将 analyst-list 中的公众号补入 source_whitelist 或删除错误项"
    if extra:
        return "核对 source_whitelist 中额外公众号是否应同步到 analyst-list"
    return "无需修改"


def parse_simple_yaml(text: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, Any]] = [(-1, root)]
    last_key_at_indent: dict[int, str] = {}
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        stripped = raw.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if stripped.startswith("- "):
            if not isinstance(parent, list):
                raise ValueError(f"list item without list parent: {raw}")
            parent.append(clean_scalar(stripped[2:]))
            continue
        if ":" not in stripped:
            raise ValueError(f"invalid whitelist line: {raw}")
        if stripped.endswith(":"):
            key, value = stripped.rsplit(":", 1)
        else:
            key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()
        if value:
            parent[key] = clean_scalar(value)
            last_key_at_indent[indent] = key
            continue
        next_container: Any = [] if key in {"team_members", "accounts", "allowed_domains"} else {}
        parent[key] = next_container
        last_key_at_indent[indent] = key
        stack.append((indent, next_container))
    return root


def clean_scalar(value: str) -> str:
    text = value.strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    return text
