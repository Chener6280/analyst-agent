from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from core.retrieval.manual_wechat import search_manual_wechat

PRIMARY_SOURCES = ["manual_wechat", "wechat_opencli"]
FALLBACK_SOURCES = ["bocha", "exa", "web_search"]

_DEFAULT_IR_SEARCH_PATHS = [
    Path("/Users/chen/Documents/ir_search"),
    Path("../ir-search").resolve(),
    Path("../files-mentioned-by-the-user-ir").resolve(),
    Path("/Users/chen/Documents/Codex/2026-06-08/files-mentioned-by-the-user-ir"),
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
    for text in queries:
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
            window=TimeWindow(raw="oneWeek", start=_parse_dt(window["start_at"]), end=_parse_dt(window["end_at"])),
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
    return {
        "title": getattr(hit, "title", "") or "",
        "url": getattr(hit, "url", "") or "",
        "snippet": getattr(hit, "snippet", "") or "",
        "source": getattr(hit, "source", "") or "",
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


def _dedupe_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for hit in hits:
        key = hit.get("url") or f"{hit.get('source')}:{hit.get('title')}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


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
