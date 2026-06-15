from __future__ import annotations

import importlib
import json
import os
import shlex
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

from core.retrieval.manual_wechat import search_manual_wechat

PRIMARY_SOURCES = ["manual_wechat", "wechat_opencli"]
FALLBACK_SOURCES = ["bocha", "exa", "web_search"]

_DEFAULT_IR_SEARCH_PATHS = [
]


def search_team(team: dict[str, Any], window: dict[str, Any], sources: list[str] | None = None) -> dict[str, Any]:
    selected_sources = sources or PRIMARY_SOURCES
    queries = build_queries(team)
    manual_sources = [source for source in selected_sources if source == "manual_wechat"]
    external_sources = [source for source in selected_sources if source != "manual_wechat"]
    manual_hits: list[dict[str, Any]] = []
    manual_diagnostics: list[dict[str, Any]] = []
    for text in queries:
        for source in manual_sources:
            if source == "manual_wechat":
                result = search_manual_wechat(team, window, text)
                for hit in result.get("hits", []):
                    hit.setdefault("query", text)
                    manual_hits.append(hit)
                manual_diagnostics.extend(result.get("diagnostics", []))

    if not external_sources:
        return {
            "queries": queries,
            "sources": selected_sources,
            "hits": _dedupe_hits(manual_hits),
            "diagnostics": _dedupe_diagnostics(manual_diagnostics),
        }

    backend = _load_ir_search()
    if backend is None:
        return {
            "queries": queries,
            "sources": selected_sources,
            "hits": _dedupe_hits(manual_hits),
            "diagnostics": _dedupe_diagnostics(
                manual_diagnostics
                + [
                {
                    "source": source,
                    "ok": False,
                    "adapter_mode": "unavailable",
                    "error": "ir_search package not importable; set IR_SEARCH_PATH or install ir_search",
                    "n_results": 0,
                }
                for source in external_sources
                ]
            ),
        }

    hits: list[dict[str, Any]] = list(manual_hits)
    diagnostics: list[dict[str, Any]] = list(manual_diagnostics)
    if "wechat_opencli" in external_sources:
        result = _run_wechat_accounts(team, window)
        if result is not None:
            hits.extend(result.get("hits", []))
            diagnostics.extend(result.get("diagnostics", []))
            external_sources = [source for source in external_sources if source != "wechat_opencli"]

    for text in queries:
        if not external_sources:
            break
        result = _run_query(backend, text, window, external_sources)
        for hit in result.get("hits", []):
            hit.setdefault("query", text)
            hits.append(hit)
        diagnostics.extend(result.get("diagnostics", []))

    return {
        "queries": queries,
        "sources": selected_sources,
        "hits": _dedupe_hits(hits),
        "diagnostics": _dedupe_diagnostics(diagnostics),
    }


def build_queries(team: dict[str, Any]) -> list[str]:
    institution = team["institution"]
    role_label = "宏观" if team["role"] == "macro" else "策略"
    primary_member = team.get("team_members", [""])[0] if team.get("team_members") else institution
    queries = [
        f"{primary_member} {institution}",
        f"{primary_member} {role_label} 观点",
    ]
    for account in team.get("official_accounts", []):
        queries.append(f"{account} {institution}")
    return _dedupe_text(queries)


def _run_wechat_accounts(team: dict[str, Any], window: dict[str, Any]) -> dict[str, Any] | None:
    command = os.environ.get("WECHAT_OPENCLI_COMMAND")
    if not command:
        return None
    base_cmd = _validated_wechat_opencli_command(command)
    if base_cmd is None:
        return {
            "hits": [],
            "diagnostics": [
                {
                    "source": "wechat_opencli",
                    "ok": False,
                    "adapter_mode": "live",
                    "error": "WECHAT_OPENCLI_COMMAND must invoke gzh_fetch.py",
                    "n_results": 0,
                }
            ],
        }
    try:
        timeout = _wechat_opencli_timeout()
    except ValueError as exc:
        return {
            "hits": [],
            "diagnostics": [
                {
                    "source": "wechat_opencli",
                    "ok": False,
                    "adapter_mode": "live",
                    "error": str(exc),
                    "n_results": 0,
                }
            ],
        }
    accounts = [account for account in team.get("official_accounts", []) if account]
    if not accounts:
        return None

    hits: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for account in accounts:
        started = datetime.now(timezone.utc)
        cmd = list(base_cmd)
        cmd.extend(["--account", account, "--start", window["start"], "--end", window["end"], "--fulltext"])
        if "--opencli" not in cmd:
            cmd.append("--opencli")
        try:
            completed = subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            rows = json.loads(completed.stdout)
            if isinstance(rows, dict):
                rows = rows.get("articles", [])
            if not isinstance(rows, list):
                raise ValueError("gzh_fetch stdout must be a JSON list or object with articles")
            account_hits = [_gzh_row_to_hit(row, account) for row in rows if isinstance(row, dict) and row.get("title") and row.get("url")]
            hits.extend(account_hits)
            diagnostics.append(
                {
                    "source": "wechat_opencli",
                    "ok": bool(account_hits),
                    "adapter_mode": "live",
                    "error": None if account_hits else f"gzh_fetch returned no valid rows for account={account}",
                    "n_results": len(account_hits),
                    "elapsed_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
                    "cache_hit": False,
                }
            )
        except Exception as exc:
            diagnostics.append(
                {
                    "source": "wechat_opencli",
                    "ok": False,
                    "adapter_mode": "live",
                    "error": f"gzh_fetch account fetch failed for account={account}: {exc}",
                    "n_results": 0,
                    "elapsed_ms": int((datetime.now(timezone.utc) - started).total_seconds() * 1000),
                    "cache_hit": False,
                }
            )

    return {"hits": hits, "diagnostics": diagnostics}


def _validated_wechat_opencli_command(command: str) -> list[str] | None:
    try:
        parts = shlex.split(command)
    except ValueError:
        return None
    if not parts:
        return None
    if not any(Path(part).name == "gzh_fetch.py" for part in parts):
        return None
    executable = Path(parts[0]).name
    if executable not in {"python", "python3", "gzh_fetch.py"} and not executable.startswith("python3."):
        return None
    return parts


def _wechat_opencli_timeout() -> int:
    value = os.environ.get("WECHAT_OPENCLI_TIMEOUT", "60")
    try:
        timeout = int(value)
    except ValueError as exc:
        raise ValueError(f"WECHAT_OPENCLI_TIMEOUT must be an integer, got {value!r}") from exc
    if timeout <= 0:
        raise ValueError("WECHAT_OPENCLI_TIMEOUT must be positive")
    return timeout


def _gzh_row_to_hit(row: dict[str, Any], account: str) -> dict[str, Any]:
    account_name = row.get("account_name") or account
    canonical_url = _canonicalize_url(row.get("url") or "")
    found_in = row.get("found_in") or row.get("source")
    extra = {
        "platform": "wechat",
        "account_name": account_name,
        "extraction_method": "gzh_crosscheck",
        "requires_login": False,
        "canonical_url": canonical_url,
        "tier": "MEDIA",
        "evidence_type": "opinion",
        "matched_entities": [],
        "found_by": ["wechat_opencli"],
        "content": row.get("content") or "",
        "content_source": row.get("content_source"),
        "content_errors": row.get("content_errors"),
        "found_in": found_in,
        "url_key": row.get("url_key"),
        "source_type": "official_wechat",
        "source_completeness": "full_article" if len(row.get("content") or "") >= 1200 else "excerpt",
    }
    return {
        "title": row.get("title") or "",
        "url": row.get("url") or "",
        "canonical_url": canonical_url,
        "snippet": row.get("snippet") or "",
        "source": "wechat_opencli",
        "tier": "MEDIA",
        "evidence_type": "opinion",
        "matched_entities": [],
        "found_by": ["wechat_opencli"],
        "published_at": row.get("published_at"),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "raw_score": None,
        "rank_score": None,
        "extra": extra,
        "adapter_mode": "live",
        "query": account_name,
    }


def _load_ir_search() -> Any | None:
    configured = os.environ.get("IR_SEARCH_PATH")
    candidates = [Path(configured).expanduser()] if configured else []
    candidates.extend(_DEFAULT_IR_SEARCH_PATHS)

    for candidate in candidates:
        if candidate and candidate.exists() and str(candidate) not in sys.path:
            sys.path.insert(0, str(candidate))
            break

    try:
        return importlib.import_module("ir_search")
    except Exception:
        return None


def _run_query(backend: Any, text: str, window: dict[str, Any], sources: list[str]) -> dict[str, Any]:
    try:
        Query = backend.Query
        Intent = backend.Intent
        Lang = backend.Lang
        TimeWindow = backend.TimeWindow
        query = Query(
            text=text,
            intent=Intent.BROKER_RESEARCH,
            lang=Lang.ZH,
            sources=sources,
            count=8,
            window=TimeWindow(
                raw=coarse_freshness(window),
                start=_parse_dt(window["start_at"]),
                end=_parse_dt(window["end_at"]),
            ),
        )
        result = backend.search(query)
    except Exception as exc:
        return {
            "hits": [],
            "diagnostics": [
                {
                    "source": ",".join(sources),
                    "ok": False,
                    "adapter_mode": "unknown",
                    "error": f"ir_search query failed: {exc}",
                    "n_results": 0,
                }
            ],
        }

    return {
        "hits": [_hit_to_dict(hit) for hit in result.hits],
        "diagnostics": [_status_to_dict(status) for status in result.diagnostics],
    }


def _hit_to_dict(hit: Any) -> dict[str, Any]:
    extra = dict(getattr(hit, "extra", {}) or {})
    published_at = getattr(hit, "published_at", None)
    fetched_at = getattr(hit, "fetched_at", None)
    canonical_url = getattr(hit, "canonical_url", "") or _canonicalize_url(getattr(hit, "url", "") or "")
    tier = _enum_name(getattr(hit, "tier", None))
    evidence_type = _enum_value(getattr(hit, "evidence_type", None))
    matched_entities = list(getattr(hit, "matched_entities", []) or [])
    found_by = list(getattr(hit, "found_by", []) or [])
    extra.setdefault("canonical_url", canonical_url)
    extra.setdefault("tier", tier)
    extra.setdefault("evidence_type", evidence_type)
    extra.setdefault("matched_entities", matched_entities)
    extra.setdefault("found_by", found_by)
    return {
        "title": getattr(hit, "title", "") or "",
        "url": getattr(hit, "url", "") or "",
        "canonical_url": canonical_url,
        "snippet": getattr(hit, "snippet", "") or "",
        "source": getattr(hit, "source", "") or "",
        "tier": tier,
        "evidence_type": evidence_type,
        "matched_entities": matched_entities,
        "found_by": found_by,
        "published_at": published_at.isoformat() if published_at else None,
        "fetched_at": fetched_at.isoformat() if fetched_at else None,
        "raw_score": getattr(hit, "raw_score", None),
        "rank_score": getattr(hit, "rank_score", None),
        "extra": extra,
        "adapter_mode": extra.get("adapter_mode", "unknown"),
    }


def _status_to_dict(status: Any) -> dict[str, Any]:
    return {
        "source": getattr(status, "source", "unknown"),
        "ok": bool(getattr(status, "ok", False)),
        "adapter_mode": getattr(status, "adapter_mode", "unknown"),
        "error": getattr(status, "error", None),
        "n_results": int(getattr(status, "n_results", 0) or 0),
        "elapsed_ms": int(getattr(status, "elapsed_ms", 0) or 0),
        "cache_hit": getattr(status, "cache_hit", None),
    }


def _parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value)


def coarse_freshness(window: dict[str, Any]) -> str:
    start = _parse_dt(window["start_at"])
    end = _parse_dt(window["end_at"])
    span = end - start
    if span <= timedelta(days=1):
        return "oneDay"
    if span <= timedelta(days=7):
        return "oneWeek"
    if span <= timedelta(days=31):
        return "oneMonth"
    if span <= timedelta(days=366):
        return "oneYear"
    return "noLimit"


def _dedupe_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for hit in hits:
        key = _hit_dedupe_key(hit)
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


def _hit_dedupe_key(hit: dict[str, Any]) -> str:
    extra = hit.get("extra", {}) or {}
    canonical_url = hit.get("canonical_url") or extra.get("canonical_url")
    if canonical_url:
        return f"canonical:{canonical_url}"
    url = hit.get("url") or ""
    if url:
        canonicalized = _canonicalize_url(url)
        return f"url:{canonicalized or url}"
    return f"title:{hit.get('source')}:{hit.get('title')}"


def _canonicalize_url(url: str) -> str:
    if not url:
        return ""
    try:
        module = importlib.import_module("ir_search.urlnorm")
        return str(module.canonicalize_url(url))
    except Exception:
        return url


def _enum_name(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "name", None) or str(value)


def _enum_value(value: Any) -> str | None:
    if value is None:
        return None
    return getattr(value, "value", None) or _enum_name(value)


def _dedupe_diagnostics(diagnostics: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[tuple[str, str, str | None], dict[str, Any]] = {}
    for item in diagnostics:
        key = (item.get("source", "unknown"), item.get("adapter_mode", "unknown"), item.get("error"))
        existing = merged.get(key)
        if existing is None:
            merged[key] = dict(item)
        else:
            existing["n_results"] = int(existing.get("n_results", 0) or 0) + int(item.get("n_results", 0) or 0)
    return list(merged.values())


def _dedupe_text(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out
