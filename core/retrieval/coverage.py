from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.retrieval.search_client import FALLBACK_SOURCES, PRIMARY_SOURCES, search_team
from core.retrieval.source_whitelist import is_official_account, load_source_whitelist

COVERAGE_ORDER = {"not_found": 0, "source_lost": 0, "partial": 1, "covered": 2}
TEXT_ACCESS_ORDER = {"failed": 0, "metadata_only": 1, "snippet_only": 2, "partial_text": 3, "full_text": 4}
ATTRIBUTION_ORDER = {"none": 0, "low": 1, "med": 2, "high": 3}
BAD_ADAPTER_MODES = {"mock", "placeholder"}


def assess_team_coverage(
    team: dict[str, Any],
    window: dict[str, Any],
    scan_id: str,
    mode: str,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    primary_sources, fallback_sources = split_sources(sources)
    primary = search_team(team, window, primary_sources)
    primary_hits = _usable_hits(primary["hits"])
    primary_candidates = _candidate_sources(team, window, primary_hits, candidate_type="primary")
    best_primary = _best_source(primary_candidates)
    source_lost_reason = None if best_primary else _primary_source_lost_reason(primary["diagnostics"])

    escalated = False
    fallback_reason = None
    fallback: dict[str, Any] | None = None
    fallback_candidates: list[dict[str, Any]] = []
    best_fallback: dict[str, Any] | None = None

    if not best_primary:
        # Keep fallback visible for diagnosis, but never let it mask a broken wechat primary source.
        if source_lost_reason:
            fallback = search_team(team, window, fallback_sources)
        else:
            escalated = True
            fallback_reason = "primary source returned no covered or partial attributed in-window content"
            fallback = search_team(team, window, fallback_sources)
            fallback_hits = _usable_hits(fallback["hits"])
            fallback_candidates = [
                candidate
                for candidate in _candidate_sources(team, window, fallback_hits, candidate_type="fallback_candidate")
                if _fallback_candidate_eligible(candidate)
            ]
            best_fallback = _best_source(fallback_candidates)

    if source_lost_reason:
        best = best_primary
        coverage = "source_lost"
    elif best_primary:
        best = best_primary
        coverage = _coverage_from_primary(best_primary)
    elif best_fallback:
        best = best_fallback
        coverage = "partial"
    else:
        best = None
        coverage = "not_found"

    if source_lost_reason:
        escalated = False
        fallback_reason = None

    all_candidates = primary_candidates + fallback_candidates
    diagnostics = primary["diagnostics"] + (fallback["diagnostics"] if fallback else [])
    sources = _assign_source_ids(all_candidates)

    return {
        "scan_id": scan_id,
        "mode": mode,
        "window": _public_window(window),
        "institution": team["institution"],
        "role": team["role"],
        "analyst_id": team["analyst_id"],
        "team_members": team.get("team_members", []),
        "official_accounts": team.get("official_accounts", []),
        "coverage": coverage,
        "source_lost_reason": source_lost_reason,
        "text_access": best.get("text_access", "failed") if best else "failed",
        "attribution_confidence": best.get("attribution_confidence", "none") if best else "none",
        "source_type": best.get("source_type", "unknown") if best else "unknown",
        "source_completeness": best.get("source_completeness", "unknown") if best else "unknown",
        "official_account_match": best.get("official_account_match") if best else False,
        "escalated": escalated,
        "fallback_reason": fallback_reason if escalated else None,
        "freshness_note": _freshness_note(best, bool(best_fallback and best is best_fallback)),
        "latest_published_at": _latest_published_at(sources),
        "primary_source_hit": bool(best_primary),
        "fallback_hit": bool(best_fallback) and not source_lost_reason,
        "mock_or_placeholder": _has_bad_adapter(diagnostics, primary["hits"] + (fallback["hits"] if fallback else [])),
        "sources": sources,
        "diagnostics": diagnostics,
        "queries": {
            "primary": primary.get("queries", []),
            "fallback": fallback.get("queries", []) if fallback else [],
        },
        "raw_hits": {
            "primary": primary.get("hits", []),
            "fallback": fallback.get("hits", []) if fallback else [],
        },
    }


def split_sources(sources: list[str] | None) -> tuple[list[str], list[str]]:
    if not sources:
        return PRIMARY_SOURCES, FALLBACK_SOURCES
    primary = [source for source in sources if source in PRIMARY_SOURCES]
    fallback = [source for source in sources if source in FALLBACK_SOURCES]
    return primary or PRIMARY_SOURCES, fallback or FALLBACK_SOURCES


def summarize_coverages(items: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(items)
    counts = {key: sum(1 for item in items if item["coverage"] == key) for key in ["covered", "partial", "not_found", "source_lost"]}
    text_counts = {
        key: sum(1 for item in items if item["text_access"] == key)
        for key in ["full_text", "partial_text", "snippet_only", "metadata_only", "failed"]
    }
    source_type_counts = {
        key: sum(1 for item in items if item.get("source_type", "unknown") == key)
        for key in sorted({item.get("source_type", "unknown") for item in items})
    }
    full_or_partial = sum(1 for item in items if item["text_access"] in {"full_text", "partial_text"})
    high_or_med = sum(1 for item in items if item["attribution_confidence"] in {"high", "med"})
    production = sum(1 for item in items if is_production_coverage(item))
    official_or_broker = sum(1 for item in items if item.get("source_type") in {"official_wechat", "broker_official"})
    mock_count = sum(1 for item in items if item["mock_or_placeholder"])
    covered_plus_partial = counts["covered"] + counts["partial"]
    return {
        "total_teams": total,
        **counts,
        **{f"{key}_count": value for key, value in text_counts.items()},
        "source_type_counts": source_type_counts,
        "covered_plus_partial_rate": _rate(covered_plus_partial, total),
        "discovery_coverage_rate": _rate(covered_plus_partial, total),
        "extraction_coverage_rate": _rate(full_or_partial, total),
        "production_coverage_rate": _rate(production, total),
        "full_or_partial_text_rate": _rate(full_or_partial, total),
        "full_text_rate": _rate(text_counts["full_text"], total),
        "high_or_med_attribution_rate": _rate(high_or_med, total),
        "official_or_broker_source_rate": _rate(official_or_broker, total),
        "mock_or_placeholder_count": mock_count,
        "phase1_gate": {
            "covered_plus_partial_ge_60": _ratio(covered_plus_partial, total) >= 0.60,
            "full_or_partial_text_ge_40": _ratio(full_or_partial, total) >= 0.40,
            "high_or_med_attribution_ge_70": _ratio(high_or_med, total) >= 0.70,
            "mock_or_placeholder_eq_0": mock_count == 0,
            "source_lost_not_config_error": not _has_config_source_loss(items),
        },
    }


def is_production_coverage(item: dict[str, Any]) -> bool:
    return (
        item.get("text_access") == "full_text"
        and item.get("source_type") in {"official_wechat", "broker_official"}
        and item.get("attribution_confidence") == "high"
        and item.get("source_completeness") == "full_article"
        and not item.get("mock_or_placeholder")
    )


def write_coverage_report(scan_id: str, coverages: list[dict[str, Any]], output_path: str | Path) -> None:
    summary = summarize_coverages(coverages)
    lines = [
        f"# Coverage Report: {scan_id}",
        "",
        "## Summary",
        "",
        "| metric | value |",
        "|---|---:|",
    ]
    for key in [
        "total_teams",
        "covered",
        "partial",
        "not_found",
        "source_lost",
        "covered_plus_partial_rate",
        "discovery_coverage_rate",
        "extraction_coverage_rate",
        "production_coverage_rate",
        "full_or_partial_text_rate",
        "full_text_rate",
        "high_or_med_attribution_rate",
        "official_or_broker_source_rate",
        "mock_or_placeholder_count",
    ]:
        lines.append(f"| {key} | {summary[key]} |")
    lines.append(f"| source_type_counts | {_format_counts(summary['source_type_counts'])} |")

    lines.extend(
        [
            "",
            "## Detail",
            "",
            "| analyst_id | role | coverage | text_access | source_type | attribution_confidence | latest_published_at | primary_hit | fallback_hit | escalated | note |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for item in coverages:
        note = item.get("freshness_note") or _diagnostic_note(item)
        lines.append(
            "| {analyst_id} | {role} | {coverage} | {text_access} | {source_type} | {attr} | {date} | {primary} | {fallback} | {escalated} | {note} |".format(
                analyst_id=item["analyst_id"],
                role=item["role"],
                coverage=item["coverage"],
                text_access=item["text_access"],
                source_type=item.get("source_type", "unknown"),
                attr=item["attribution_confidence"],
                date=item.get("latest_published_at") or "",
                primary="yes" if item.get("primary_source_hit") else "no",
                fallback="yes" if item.get("fallback_hit") else "no",
                escalated="yes" if item.get("escalated") else "no",
                note=_escape_pipe(note),
            )
        )

    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_team_cache(item: dict[str, Any], output_dir: str | Path, index: int) -> None:
    cache_dir = Path(output_dir) / "search_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{item['role']}_{index:03d}_{item['institution']}"
    json_path = cache_dir / f"{stem}.json"
    md_path = cache_dir / f"{stem}.md"

    for source in item["sources"]:
        if source.get("content_path") is None and md_path.name:
            source["content_path"] = f"search_cache/{md_path.name}"

    json_path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_team_markdown(item), encoding="utf-8")


def _candidate_sources(
    team: dict[str, Any],
    window: dict[str, Any],
    hits: list[dict[str, Any]],
    *,
    candidate_type: str,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for hit in hits:
        if not _in_window(hit.get("published_at"), window):
            continue
        text_access = classify_text_access(hit)
        attribution = classify_attribution(team, hit)
        if attribution == "none":
            continue
        candidates.append(
            {
                "title": hit.get("title", ""),
                "url": hit.get("url", ""),
                "canonical_url": hit.get("canonical_url") or (hit.get("extra", {}) or {}).get("canonical_url"),
                "source": hit.get("source", "unknown"),
                "source_type": classify_source_type(team, hit),
                "tier": hit.get("tier") or (hit.get("extra", {}) or {}).get("tier"),
                "evidence_type": hit.get("evidence_type") or (hit.get("extra", {}) or {}).get("evidence_type"),
                "matched_entities": hit.get("matched_entities") or (hit.get("extra", {}) or {}).get("matched_entities", []),
                "found_by": hit.get("found_by") or (hit.get("extra", {}) or {}).get("found_by", []),
                "source_completeness": (hit.get("extra", {}) or {}).get("source_completeness"),
                "source_origin": (hit.get("extra", {}) or {}).get("source_origin"),
                "official_account_match": (hit.get("extra", {}) or {}).get("official_account_match"),
                "published_at": _date_only(hit.get("published_at")),
                "adapter_mode": hit.get("adapter_mode") or hit.get("extra", {}).get("adapter_mode", "unknown"),
                "text_access": text_access,
                "attribution_confidence": attribution,
                "is_attributed": attribution in {"high", "med", "low"},
                "snippet": hit.get("snippet", ""),
                "content_path": hit.get("extra", {}).get("content_path"),
                "fallback_from": hit.get("extra", {}).get("fallback_from"),
                "candidate_type": candidate_type,
            }
        )
    return candidates


def classify_text_access(hit: dict[str, Any]) -> str:
    extra = hit.get("extra", {}) or {}
    if extra.get("text_access"):
        return str(extra["text_access"])
    content = extra.get("content") or extra.get("text") or extra.get("raw_content") or ""
    snippet = hit.get("snippet") or ""
    body = str(content or "")
    if len(body) >= 1200:
        return "full_text"
    if len(body) >= 500 or len(snippet) >= 500:
        return "partial_text"
    if snippet:
        return "snippet_only"
    if hit.get("title") or hit.get("url"):
        return "metadata_only"
    return "failed"


def classify_attribution(team: dict[str, Any], hit: dict[str, Any]) -> str:
    account = (hit.get("extra", {}) or {}).get("account_name") or ""
    extra = hit.get("extra", {}) or {}
    if hit.get("source") == "manual_wechat" and extra.get("attribution_confidence"):
        return str(extra["attribution_confidence"])
    text = " ".join([hit.get("title", ""), hit.get("url", ""), account])
    institution = team["institution"]
    members = team.get("team_members", [])
    official_accounts = team.get("official_accounts", [])
    has_member = any(member and member in text for member in members)
    has_account = any(account_name and account_name in text for account_name in official_accounts)
    has_role_context = any(token in text for token in ["宏观", "策略", "观点", "研报", "研究", "首席", "分析师"])

    if hit.get("source") == "wechat_opencli" and account in official_accounts:
        return "high"
    if institution in text and has_member:
        return "high"
    if has_account:
        return "med"
    if has_member and has_role_context:
        return "med"
    return "none"


def classify_source_type(team: dict[str, Any] | dict[str, Any], hit: dict[str, Any] | None = None) -> str:
    if hit is None:
        hit = team
        team = {"analyst_id": "", "official_accounts": []}
    extra_source_type = (hit.get("extra", {}) or {}).get("source_type")
    if extra_source_type:
        return str(extra_source_type)
    source = hit.get("source", "")
    url = hit.get("url", "")
    account = (hit.get("extra", {}) or {}).get("account_name")
    host = urlparse(url).netloc.lower()
    official_accounts = set(team.get("official_accounts") or [])
    if account and account in official_accounts and ("mp.weixin.qq.com" in host or source in {"manual_wechat", "wechat_opencli"}):
        return "official_wechat"
    whitelist = load_source_whitelist()
    if source in {"manual_wechat", "wechat_opencli"} and is_official_account(team["analyst_id"], account, url, whitelist):
        return "official_wechat"
    if "mp.weixin.qq.com" in host:
        return "aggregator"
    if any(token in host for token in ["eastmoney", "stcn", "cnstock", "yicai", "sina", "163", "qq.com"]):
        return "financial_media"
    if any(token in host for token in ["wind", "choice", "research"]):
        return "research_platform"
    if source in {"bocha", "exa", "web_search"}:
        return "aggregator"
    return "unknown"


def _usable_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [hit for hit in hits if (hit.get("adapter_mode") or hit.get("extra", {}).get("adapter_mode")) not in BAD_ADAPTER_MODES]


def _best_source(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None
    return max(candidates, key=lambda item: (TEXT_ACCESS_ORDER[item["text_access"]], ATTRIBUTION_ORDER[item["attribution_confidence"]], item.get("published_at") or ""))


def _coverage_from_primary(best: dict[str, Any]) -> str:
    text_access = best["text_access"]
    attribution = best["attribution_confidence"]
    if text_access in {"full_text", "partial_text"} and attribution in {"high", "med"}:
        return "covered"
    return "partial"


def _fallback_candidate_eligible(candidate: dict[str, Any]) -> bool:
    return (
        candidate["text_access"] in {"full_text", "partial_text"}
        and candidate["attribution_confidence"] in {"high", "med"}
        and candidate["source_type"] != "unknown"
    )


def _assign_source_ids(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, item in enumerate(candidates, start=1):
        source = {key: value for key, value in item.items() if key != "snippet"}
        source["id"] = f"s{idx}"
        out.append(source)
    return out


def _primary_source_lost_reason(diagnostics: list[dict[str, Any]]) -> str | None:
    manual_diags = [item for item in diagnostics if item.get("source") == "manual_wechat"]
    if any(item.get("ok") for item in manual_diags):
        return None
    reasons: list[str] = []
    for item in manual_diags:
        if item.get("error"):
            reasons.append(str(item["error"]))

    primary_diags = [item for item in diagnostics if item.get("source") == "wechat_opencli"]
    if not primary_diags:
        return "; ".join(reasons) if reasons else "wechat_opencli diagnostics missing"
    if any(item.get("ok") for item in primary_diags):
        return "; ".join(reasons) if reasons else None

    errors = "; ".join(str(item.get("error") or "") for item in primary_diags).strip()
    lower = errors.lower()
    if "wechat_opencli_command is not set" in lower:
        reasons.append("WECHAT_OPENCLI_COMMAND is not set")
        return "; ".join(reasons)
    if "login" in lower or "登录" in errors:
        reasons.append("wechat login expired or unavailable")
        return "; ".join(reasons)
    if errors:
        reasons.append(f"WECHAT_OPENCLI_COMMAND is set but command failed: {errors}")
        return "; ".join(reasons)
    reasons.append("wechat_opencli unavailable")
    return "; ".join(reasons)


def _in_window(value: str | None, window: dict[str, Any]) -> bool:
    if not value:
        return False
    published = _date_only(value)
    return bool(published and window["start"] <= published <= window["end"])


def _date_only(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        try:
            return date.fromisoformat(value[:10]).isoformat()
        except ValueError:
            return None


def _latest_published_at(sources: list[dict[str, Any]]) -> str | None:
    dates = [source["published_at"] for source in sources if source.get("published_at")]
    return max(dates) if dates else None


def _freshness_note(best: dict[str, Any] | None, escalated: bool) -> str | None:
    if not best:
        return None
    if escalated and best.get("source_type") in {"aggregator", "financial_media"}:
        return "fallback hit; possible repost/aggregation, original opinion date not fully confirmed"
    return None


def _has_bad_adapter(diagnostics: list[dict[str, Any]], hits: list[dict[str, Any]]) -> bool:
    return any(item.get("adapter_mode") in BAD_ADAPTER_MODES for item in diagnostics) or any(
        (hit.get("adapter_mode") or hit.get("extra", {}).get("adapter_mode")) in BAD_ADAPTER_MODES for hit in hits
    )


def _is_formal_success(diagnostic: dict[str, Any]) -> bool:
    if not diagnostic.get("ok"):
        return False
    adapter_mode = diagnostic.get("adapter_mode")
    return adapter_mode not in BAD_ADAPTER_MODES


def _has_config_source_loss(items: list[dict[str, Any]]) -> bool:
    needles = ["not set", "not importable", "api key", "command not found", "command failed", "login expired", "unavailable"]
    for item in items:
        if item["coverage"] != "source_lost":
            continue
        reason = (item.get("source_lost_reason") or "").lower()
        if any(needle in reason for needle in needles):
            return True
        for diagnostic in item.get("diagnostics", []):
            error = (diagnostic.get("error") or "").lower()
            if any(needle in error for needle in needles):
                return True
    return False


def _public_window(window: dict[str, Any]) -> dict[str, Any]:
    return {key: window[key] for key in ["start", "end", "iso_year", "iso_week"] if key in window}


def _rate(value: int, total: int) -> str:
    if total == 0:
        return "0%"
    return f"{round(value / total * 100):.0f}%"


def _ratio(value: int, total: int) -> float:
    return value / total if total else 0.0


def _diagnostic_note(item: dict[str, Any]) -> str:
    if item.get("source_lost_reason"):
        return str(item["source_lost_reason"])
    if item.get("coverage") == "covered" and item.get("primary_source_hit"):
        return ""
    errors = []
    for diag in item.get("diagnostics", []):
        if diag.get("error"):
            errors.append(f"{diag.get('source')}: {diag.get('error')}")
    if errors:
        return "; ".join(errors[:3])
    if item.get("mock_or_placeholder"):
        return "mock or placeholder adapter observed"
    return ""


def _escape_pipe(value: str | None) -> str:
    return (value or "").replace("|", "\\|")


def _format_counts(counts: dict[str, int]) -> str:
    if not counts:
        return ""
    return ", ".join(f"{key}={value}" for key, value in counts.items())


def _team_markdown(item: dict[str, Any]) -> str:
    lines = [f"# Search Cache: {item['analyst_id']}", ""]
    for source in item.get("sources", []):
        lines.extend(
            [
                f"## {source.get('id')}: {source.get('title', '')}",
                "",
                f"- url: {source.get('url', '')}",
                f"- source: {source.get('source', '')}",
                f"- source_type: {source.get('source_type', '')}",
                f"- published_at: {source.get('published_at') or ''}",
                f"- text_access: {source.get('text_access', '')}",
                f"- attribution_confidence: {source.get('attribution_confidence', '')}",
                "",
            ]
        )
    if not item.get("sources"):
        lines.append("No attributed in-window source candidates.")
        lines.append("")
    raw_hits = (item.get("raw_hits") or {}).get("primary", []) + (item.get("raw_hits") or {}).get("fallback", [])
    if raw_hits:
        lines.extend(["## Raw Hits", ""])
        for hit in raw_hits[:20]:
            lines.extend(
                [
                    f"- [{hit.get('source', 'unknown')}] {hit.get('title', '')}",
                    f"  - url: {hit.get('url', '')}",
                    f"  - published_at: {hit.get('published_at') or ''}",
                    f"  - adapter_mode: {hit.get('adapter_mode') or (hit.get('extra') or {}).get('adapter_mode', '')}",
                ]
            )
    return "\n".join(lines)
