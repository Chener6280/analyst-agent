from __future__ import annotations

import importlib
import os
import sys
from datetime import datetime, timedelta
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
    return "all"


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
