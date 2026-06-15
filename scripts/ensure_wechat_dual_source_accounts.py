#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.config import load_analyst_list
from core.retrieval.source_matrix import enrich_teams_with_source_matrix, load_source_matrix


DEFAULT_ACCOUNTS = Path(os.environ.get("WECHAT_ACCOUNTS_PATH", "/Users/chen/Documents/ir_search/accounts.json"))
DEFAULT_FULL_ANALYST_LIST = REPO_ROOT / "data/analyst-list-full-2026w24.md"
DEFAULT_ANALYST_LIST = DEFAULT_FULL_ANALYST_LIST if DEFAULT_FULL_ANALYST_LIST.exists() else REPO_ROOT / "data/analyst-list.md"


def main() -> int:
    args = parse_args()
    accounts_path = Path(args.accounts).expanduser()
    accounts = load_accounts(accounts_path)
    account_names = source_account_names(args.analyst_list, args.source_matrix)

    missing_accounts = [name for name in account_names if name not in accounts]
    missing_wewe = [name for name in account_names if not ((accounts.get(name) or {}).get("wewe") or {}).get("mp_id")]
    missing_dajiala = [name for name in account_names if not ((accounts.get(name) or {}).get("dajiala") or {}).get("name")]

    added_dajiala = []
    if args.apply:
        for name in missing_dajiala:
            cfg = accounts.setdefault(name, {})
            cfg.setdefault("dajiala", {"name": name})
            added_dajiala.append(name)
        if added_dajiala:
            backup_path = backup_accounts(accounts_path)
            write_accounts(accounts_path, accounts)
        else:
            backup_path = None
    else:
        backup_path = None

    result = {
        "accounts_path": str(accounts_path),
        "analyst_list": str(Path(args.analyst_list).expanduser()),
        "source_matrix": str(Path(args.source_matrix).expanduser()),
        "source_accounts": len(account_names),
        "missing_accounts": missing_accounts,
        "missing_wewe_mp_id": missing_wewe,
        "missing_dajiala_name": missing_dajiala,
        "added_dajiala_name": added_dajiala,
        "backup_path": str(backup_path) if backup_path else None,
        "applied": args.apply,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if args.fail_on_missing and (missing_accounts or missing_wewe or (missing_dajiala and not args.apply)):
        return 1
    return 0


def load_accounts(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_accounts(path: Path, accounts: dict[str, Any]) -> None:
    path.write_text(json.dumps(accounts, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def backup_accounts(path: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_path = path.with_name(f"{path.name}.{timestamp}.bak")
    backup_path.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup_path


def source_account_names(analyst_list: str, source_matrix: str) -> list[str]:
    teams = [team for team in load_analyst_list(analyst_list) if team.get("active")]
    matrix = load_source_matrix(source_matrix)
    enriched = enrich_teams_with_source_matrix(teams, matrix)
    seen = set()
    names = []
    for team in enriched:
        for account in team.get("official_accounts") or []:
            if account and account not in seen:
                seen.add(account)
                names.append(account)
    return names


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ensure live WeChat source accounts have both dajiala and wewe config.")
    parser.add_argument("--accounts", default=str(DEFAULT_ACCOUNTS))
    parser.add_argument("--analyst-list", default=str(DEFAULT_ANALYST_LIST))
    parser.add_argument("--source-matrix", default=str(REPO_ROOT / "broker_wechat_matrix.md"))
    parser.add_argument("--apply", action="store_true", help="Add missing dajiala.name entries using the account name.")
    parser.add_argument("--fail-on-missing", action="store_true", help="Exit non-zero when accounts or provider config are missing.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
