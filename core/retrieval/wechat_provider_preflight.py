from __future__ import annotations

import importlib
import json
import os
import shlex
import sys
import urllib.error
import urllib.request
from datetime import date, datetime
from pathlib import Path
from typing import Any


def build_wechat_provider_preflight(
    teams: list[dict[str, Any]],
    window: dict[str, Any],
    *,
    accounts_path: str | Path | None = None,
    wewe_base: str | None = None,
    timeout: int = 8,
    dajiala_max_pages: int = 1,
) -> dict[str, Any]:
    account_names = sorted(
        {
            account
            for team in teams
            for account in (team.get("official_accounts") or [])
            if account
        }
    )
    account_to_teams = {
        account: [
            team["analyst_id"]
            for team in teams
            if account in (team.get("official_accounts") or [])
        ]
        for account in account_names
    }
    resolved_accounts_path = resolve_accounts_path(accounts_path)
    accounts = load_accounts(resolved_accounts_path)
    gzh_fetch = load_gzh_fetch()
    start = date.fromisoformat(str(window["start"]))
    end = date.fromisoformat(str(window["end"]))
    resolved_wewe_base = wewe_base or os.environ.get("WEWE_RSS_BASE", "http://127.0.0.1:4000")

    rows = []
    for account in account_names:
        cfg = accounts.get(account) or {}
        dajiala = check_dajiala(
            gzh_fetch,
            account,
            cfg.get("dajiala") or {},
            start,
            end,
            max_pages=dajiala_max_pages,
        )
        wewe = check_wewe(
            account,
            cfg.get("wewe") or {},
            start,
            end,
            base_url=resolved_wewe_base,
            timeout=timeout,
        )
        ready = bool(dajiala.get("in_window_count") or wewe.get("in_window_count"))
        rows.append(
            {
                "account": account,
                "analyst_ids": account_to_teams.get(account, []),
                "ready": ready,
                "issues": provider_issues(dajiala, wewe, ready),
                "dajiala": dajiala,
                "wewe": wewe,
            }
        )
    team_ids = sorted({team["analyst_id"] for team in teams})
    ready_teams = {
        analyst_id
        for row in rows
        if row["ready"]
        for analyst_id in row.get("analyst_ids", [])
    }

    return {
        "window": {key: window[key] for key in ["start", "end", "iso_year", "iso_week"] if key in window},
        "accounts_path": str(resolved_accounts_path) if resolved_accounts_path else None,
        "wewe_base": resolved_wewe_base,
        "summary": {
            "teams": len(team_ids),
            "team_ready": sum(1 for analyst_id in team_ids if analyst_id in ready_teams),
            "team_not_ready": sum(1 for analyst_id in team_ids if analyst_id not in ready_teams),
            "accounts": len(rows),
            "ready": sum(1 for row in rows if row["ready"]),
            "not_ready": sum(1 for row in rows if not row["ready"]),
            "dajiala_configured": sum(1 for row in rows if row["dajiala"]["configured"]),
            "wewe_configured": sum(1 for row in rows if row["wewe"]["configured"]),
            "dual_configured": sum(1 for row in rows if row["dajiala"]["configured"] and row["wewe"]["configured"]),
            "missing_dajiala_name": sum(1 for row in rows if not row["dajiala"]["configured"]),
            "missing_wewe_mp_id": sum(1 for row in rows if not row["wewe"]["configured"]),
            "dajiala_with_window_articles": sum(1 for row in rows if row["dajiala"].get("in_window_count")),
            "wewe_with_window_articles": sum(1 for row in rows if row["wewe"].get("in_window_count")),
            "dual_with_window_articles": sum(
                1 for row in rows if row["dajiala"].get("in_window_count") and row["wewe"].get("in_window_count")
            ),
            "wewe_empty_feed": sum(1 for row in rows if is_wewe_empty_feed(row)),
            "empty_wewe_without_dajiala": sum(1 for row in rows if is_empty_wewe_without_dajiala(row)),
        },
        "accounts": rows,
    }


def write_wechat_provider_preflight(
    data: dict[str, Any],
    output_dir: str | Path,
) -> dict[str, str]:
    output = Path(output_dir)
    json_path = output / "wechat_provider_preflight.json"
    md_path = output / "wechat_provider_preflight.md"
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_wechat_provider_preflight(data), encoding="utf-8")
    return {"json": str(json_path), "md": str(md_path)}


def check_dajiala(
    gzh_fetch: Any,
    account: str,
    cfg: dict[str, Any],
    start: date,
    end: date,
    *,
    max_pages: int,
) -> dict[str, Any]:
    base = {"configured": bool(cfg.get("name")), "ok": False, "in_window_count": 0, "latest_title": None, "latest_published_at": None}
    if not base["configured"]:
        base["error"] = "dajiala.name missing"
        return base
    if gzh_fetch is None:
        base["error"] = "tools.gzh_fetch not importable"
        return base

    old_max_pages = getattr(gzh_fetch, "DAJIALA_MAX_PAGES", None)
    if old_max_pages is not None:
        setattr(gzh_fetch, "DAJIALA_MAX_PAGES", max_pages)
    try:
        rows = gzh_fetch.fetch_dajiala(cfg, account, start, end)
    except Exception as exc:
        base["error"] = str(exc)
        return base
    finally:
        if old_max_pages is not None:
            setattr(gzh_fetch, "DAJIALA_MAX_PAGES", old_max_pages)

    latest = latest_article(rows)
    base.update(
        {
            "ok": True,
            "in_window_count": len(rows),
            "latest_title": getattr(latest, "title", None) if latest else None,
            "latest_published_at": format_dt(getattr(latest, "published_at", None)) if latest else None,
        }
    )
    return base


def check_wewe(
    account: str,
    cfg: dict[str, Any],
    start: date,
    end: date,
    *,
    base_url: str,
    timeout: int,
) -> dict[str, Any]:
    mp_id = cfg.get("mp_id")
    base = {
        "configured": bool(mp_id),
        "ok": False,
        "feed_url": None,
        "item_count": 0,
        "in_window_count": 0,
        "latest_title": None,
        "latest_published_at": None,
    }
    if not mp_id:
        base["error"] = "wewe.mp_id missing"
        return base
    feed_url = f"{base_url.rstrip('/')}/feeds/{mp_id}.json"
    base["feed_url"] = feed_url
    try:
        with urllib.request.urlopen(feed_url, timeout=timeout) as resp:
            feed = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        base["error"] = f"HTTP {exc.code}"
        return base
    except Exception as exc:
        base["error"] = str(exc)
        return base

    items = [item for item in feed.get("items", []) if isinstance(item, dict)]
    in_window = [item for item in items if in_window_item(item, start, end)]
    latest = latest_feed_item(in_window or items)
    base.update(
        {
            "ok": True,
            "item_count": len(items),
            "in_window_count": len(in_window),
            "latest_title": latest.get("title") if latest else None,
            "latest_published_at": feed_item_date(latest) if latest else None,
        }
    )
    if feed.get("title") and feed.get("title") != account:
        base["feed_title"] = feed.get("title")
    return base


def provider_issues(dajiala: dict[str, Any], wewe: dict[str, Any], ready: bool) -> list[str]:
    issues: list[str] = []
    if not dajiala["configured"]:
        issues.append("missing_dajiala_name")
    elif dajiala.get("error"):
        issues.append("dajiala_error")
    elif not dajiala.get("in_window_count"):
        issues.append("dajiala_no_window_articles")

    if not wewe["configured"]:
        issues.append("missing_wewe_mp_id")
    elif wewe.get("error"):
        issues.append("wewe_error")
    elif wewe.get("ok") and wewe.get("item_count") == 0:
        issues.append("wewe_empty_feed")
    elif not wewe.get("in_window_count"):
        issues.append("wewe_no_window_articles")

    if not dajiala.get("configured") and wewe.get("ok") and wewe.get("item_count") == 0:
        issues.append("empty_wewe_without_dajiala")

    if not ready:
        issues.append("no_provider_window_articles")
    return issues


def is_wewe_empty_feed(row: dict[str, Any]) -> bool:
    wewe = row.get("wewe") or {}
    return bool(wewe.get("configured") and wewe.get("ok") and wewe.get("item_count") == 0)


def is_empty_wewe_without_dajiala(row: dict[str, Any]) -> bool:
    dajiala = row.get("dajiala") or {}
    return is_wewe_empty_feed(row) and not dajiala.get("configured")


def render_wechat_provider_preflight(data: dict[str, Any]) -> str:
    summary = data.get("summary") or {}
    lines = [
        "# WeChat Provider Preflight",
        "",
        "| metric | value |",
        "|---|---:|",
    ]
    for key in [
        "teams",
        "team_ready",
        "team_not_ready",
        "accounts",
        "ready",
        "not_ready",
        "dajiala_configured",
        "wewe_configured",
        "dual_configured",
        "missing_dajiala_name",
        "missing_wewe_mp_id",
        "dajiala_with_window_articles",
        "wewe_with_window_articles",
        "dual_with_window_articles",
        "wewe_empty_feed",
        "empty_wewe_without_dajiala",
    ]:
        lines.append(f"| {key} | {summary.get(key, 0)} |")
    lines.extend(
        [
            f"| accounts_path | {data.get('accounts_path') or ''} |",
            f"| wewe_base | {data.get('wewe_base') or ''} |",
            "",
            "## Accounts",
            "",
            "| account | analyst_ids | ready | dajiala | wewe | issues |",
            "|---|---|---|---|---|---|",
        ]
    )
    for row in data.get("accounts", []):
        lines.append(
            "| {account} | {analysts} | {ready} | {dajiala} | {wewe} | {issues} |".format(
                account=escape_pipe(row.get("account")),
                analysts=escape_pipe(",".join(row.get("analyst_ids") or [])),
                ready="yes" if row.get("ready") else "no",
                dajiala=escape_pipe(provider_cell(row.get("dajiala") or {})),
                wewe=escape_pipe(provider_cell(row.get("wewe") or {})),
                issues=escape_pipe(",".join(row.get("issues") or [])),
            )
        )
    return "\n".join(lines) + "\n"


def provider_cell(provider: dict[str, Any]) -> str:
    if not provider.get("configured"):
        return "missing_config"
    if provider.get("error"):
        return f"error: {provider['error']}"
    count = provider.get("in_window_count") or 0
    title = provider.get("latest_title") or ""
    date_text = provider.get("latest_published_at") or ""
    return f"{count} in-window; {date_text}; {title}".strip()


def resolve_accounts_path(path: str | Path | None = None) -> Path | None:
    if path:
        return Path(path).expanduser()
    if os.environ.get("WECHAT_ACCOUNTS_PATH"):
        return Path(os.environ["WECHAT_ACCOUNTS_PATH"]).expanduser()
    if os.environ.get("IR_SEARCH_PATH"):
        candidate = Path(os.environ["IR_SEARCH_PATH"]).expanduser() / "accounts.json"
        if candidate.exists():
            return candidate
    command_path = accounts_path_from_command(os.environ.get("WECHAT_OPENCLI_COMMAND"))
    if command_path:
        return command_path
    return None


def accounts_path_from_command(command: str | None) -> Path | None:
    if not command:
        return None
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    for idx, part in enumerate(parts):
        if part == "--accounts" and idx + 1 < len(parts):
            return Path(parts[idx + 1]).expanduser()
        if part.startswith("--accounts="):
            return Path(part.split("=", 1)[1]).expanduser()
    return None


def load_accounts(path: Path | None) -> dict[str, Any]:
    if not path or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_gzh_fetch() -> Any | None:
    configured = os.environ.get("IR_SEARCH_PATH")
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
    try:
        return importlib.import_module("tools.gzh_fetch")
    except Exception:
        return None


def latest_article(rows: list[Any]) -> Any | None:
    dated = [row for row in rows if getattr(row, "published_at", None)]
    if not dated:
        return rows[0] if rows else None
    return max(dated, key=lambda item: item.published_at)


def latest_feed_item(items: list[dict[str, Any]]) -> dict[str, Any] | None:
    dated = [(feed_item_date(item), item) for item in items]
    dated = [(date_text, item) for date_text, item in dated if date_text]
    if not dated:
        return items[0] if items else None
    return max(dated, key=lambda pair: pair[0])[1]


def in_window_item(item: dict[str, Any], start: date, end: date) -> bool:
    date_text = feed_item_date(item)
    if not date_text:
        return False
    try:
        published = date.fromisoformat(date_text[:10])
    except ValueError:
        return False
    return start <= published <= end


def feed_item_date(item: dict[str, Any] | None) -> str | None:
    if not item:
        return None
    value = item.get("date_published") or item.get("date_modified") or item.get("published_at")
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return str(value)[:10]


def format_dt(value: Any) -> str | None:
    if not value:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def escape_pipe(value: Any) -> str:
    return str(value or "").replace("|", "\\|")
