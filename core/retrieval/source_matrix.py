from __future__ import annotations

import os
from pathlib import Path
from typing import Any

DEFAULT_SOURCE_MATRIX = Path(__file__).resolve().parents[2] / "broker_wechat_matrix.md"
EXTERNAL_SOURCE_MATRIX = Path(os.environ.get("BROKER_WECHAT_MATRIX_MIRROR", "/Users/chen/Documents/ir_search/work/broker_wechat_matrix.md"))
OFFICIAL_SEARCH_INSTITUTIONS = {"中信", "中国银河"}


def load_source_matrix(path: str | Path = DEFAULT_SOURCE_MATRIX) -> dict[str, Any]:
    matrix_path = Path(path).expanduser()
    if not matrix_path.exists():
        return {"path": str(matrix_path), "rows": []}
    rows = parse_broker_wechat_matrix(matrix_path.read_text(encoding="utf-8"))
    return {"path": str(matrix_path), "rows": rows}


def parse_broker_wechat_matrix(text: str) -> list[dict[str, Any]]:
    table_lines = [line.strip() for line in text.splitlines() if line.strip().startswith("|")]
    if len(table_lines) < 3:
        return []
    headers = [_clean_cell(cell) for cell in table_lines[0].strip("|").split("|")]
    rows: list[dict[str, Any]] = []
    for line in table_lines[2:]:
        cells = [_clean_cell(cell) for cell in line.strip("|").split("|")]
        if len(cells) != len(headers):
            continue
        row = dict(zip(headers, cells))
        institution = row.get("券商/机构", "")
        if not institution:
            continue
        official = split_accounts(row.get("官方公众号", ""))
        macro = split_accounts(row.get("宏观个人号/团队号", ""))
        strategy = split_accounts(row.get("策略个人号/团队号", ""))
        macro_analysts = split_accounts(row.get("宏观分析师", ""))
        strategy_analysts = split_accounts(row.get("策略分析师", ""))
        rows.append(
            {
                "institution": institution,
                "official_accounts": official,
                "macro_accounts": macro,
                "strategy_accounts": strategy,
                "macro_analysts": macro_analysts,
                "strategy_analysts": strategy_analysts,
                "all_accounts": dedupe_accounts(official + macro + strategy),
            }
        )
    return rows


def enrich_teams_with_source_matrix(teams: list[dict[str, Any]], matrix: dict[str, Any]) -> list[dict[str, Any]]:
    return [enrich_team_with_source_matrix(team, matrix) for team in teams]


def enrich_team_with_source_matrix(team: dict[str, Any], matrix: dict[str, Any]) -> dict[str, Any]:
    entry = matrix_entry_for_team(team, matrix)
    if not entry:
        copied = dict(team)
        copied["source_matrix_accounts"] = []
        copied["source_matrix_institution"] = None
        return copied

    matrix_accounts = matrix_search_accounts_for_role(entry, str(team.get("role") or ""))
    copied = dict(team)
    copied["official_accounts"] = matrix_accounts
    copied["source_matrix_accounts"] = matrix_accounts
    copied["source_matrix_institution"] = entry["institution"]
    return copied


def matrix_entry_for_team(team: dict[str, Any], matrix: dict[str, Any]) -> dict[str, Any] | None:
    target = normalize_institution(str(team.get("institution") or ""))
    for row in matrix.get("rows") or []:
        candidate = normalize_institution(str(row.get("institution") or ""))
        if candidate == target:
            return row
    return None


def source_matrix_review(teams: list[dict[str, Any]], matrix: dict[str, Any]) -> dict[str, Any]:
    rows = []
    for team in teams:
        entry = matrix_entry_for_team(team, matrix)
        role_accounts = []
        official_accounts = []
        if entry:
            official_accounts = list(entry.get("official_accounts") or [])
            role_accounts = list(entry.get("macro_accounts") or []) if team.get("role") == "macro" else list(entry.get("strategy_accounts") or [])
            search_accounts = matrix_search_accounts_for_role(entry, str(team.get("role") or ""))
        else:
            search_accounts = dedupe_accounts(list(team.get("official_accounts") or []))
        rows.append(
            {
                "analyst_id": team.get("analyst_id"),
                "institution": team.get("institution"),
                "role": team.get("role"),
                "matrix_institution": entry.get("institution") if entry else "",
                "official_accounts": official_accounts,
                "role_accounts": role_accounts,
                "search_accounts": search_accounts,
                "matrix_match": bool(entry),
            }
        )
    return {
        "matrix_path": matrix.get("path"),
        "matrix_rows": len(matrix.get("rows") or []),
        "total_teams": len(rows),
        "matched_teams": sum(1 for row in rows if row["matrix_match"]),
        "confirmation_required": True,
        "instruction": "请在运行前自行修订 broker_wechat_matrix.md；确认后再传入 --source-list-confirmed 执行 ir_search 检索。",
        "teams": rows,
    }


def render_source_matrix_review(review: dict[str, Any]) -> str:
    lines = [
        "# Source Matrix Review Before Search",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| matrix_path | {review.get('matrix_path')} |",
        f"| matrix_rows | {review.get('matrix_rows')} |",
        f"| total_teams | {review.get('total_teams')} |",
        f"| matched_teams | {review.get('matched_teams')} |",
        "",
        f"> {review.get('instruction')}",
        "",
        "| analyst_id | matrix institution | official accounts | role accounts | search accounts |",
        "|---|---|---|---|---|",
    ]
    for row in review.get("teams") or []:
        lines.append(
            "| {analyst_id} | {matrix_institution} | {official} | {role} | {search} |".format(
                analyst_id=row.get("analyst_id") or "",
                matrix_institution=row.get("matrix_institution") or "",
                official=", ".join(row.get("official_accounts") or []),
                role=", ".join(row.get("role_accounts") or []),
                search=", ".join(row.get("search_accounts") or []),
            )
        )
    return "\n".join(lines) + "\n"


def split_accounts(value: str) -> list[str]:
    text = value.replace("<br>", "；").replace(",", "；").replace("，", "；").replace("、", "；")
    return [item.strip() for item in text.split("；") if item.strip()]


def matrix_search_accounts_for_role(entry: dict[str, Any], role: str) -> list[str]:
    role_accounts = entry["macro_accounts"] if role == "macro" else entry["strategy_accounts"]
    if role_accounts:
        return dedupe_accounts(role_accounts)
    if normalize_institution(str(entry.get("institution") or "")) in OFFICIAL_SEARCH_INSTITUTIONS:
        return dedupe_accounts(list(entry.get("official_accounts") or []))
    return []


def dedupe_accounts(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def normalize_institution(value: str) -> str:
    text = value.strip()
    for token in ["证券股份有限公司", "股份有限公司", "有限责任公司", "有限公司", "证券研究所", "证券研究", "研究所"]:
        text = text.replace(token, "")
    for token in ["证券", "公司"]:
        text = text.replace(token, "")
    return text.replace(" ", "")


def _clean_cell(value: str) -> str:
    return value.strip()
