from __future__ import annotations

import os
import hashlib
from datetime import date, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from core.retrieval.source_whitelist import is_official_account, load_source_whitelist

REQUIRED_FIELDS = ["title", "url", "published_at", "account_name", "institution", "role", "analyst_id"]


def search_manual_wechat(team: dict[str, Any], window: dict[str, Any], query: str, root: str | Path | None = None) -> dict[str, Any]:
    configured_root = root or os.environ.get("MANUAL_WECHAT_ROOT")
    article_root = Path(configured_root).expanduser() if configured_root else Path("~/macro-strategy/manual_wechat_articles").expanduser()
    week_dir = article_root / f"{window['iso_year']}-W{int(window['iso_week']):02d}"
    diagnostics = [
        {
            "source": "manual_wechat",
            "ok": week_dir.exists(),
            "adapter_mode": "live",
            "error": None if week_dir.exists() else f"manual_wechat directory not found: {week_dir}",
            "n_results": 0,
        }
    ]
    if not week_dir.exists():
        return {"hits": [], "diagnostics": diagnostics}

    hits: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in iter_article_files(week_dir):
        try:
            article = parse_manual_wechat_article(path)
        except ValueError as exc:
            errors.append(f"{path.name}: {exc}")
            continue
        if not article_matches_team(article, team):
            continue
        if not article_matches_query(article, query):
            continue
        if not in_window(article["metadata"]["published_at"], window):
            continue
        hits.append(article_to_hit(article, path, team))

    diagnostics[0]["n_results"] = len(hits)
    if errors:
        diagnostics.append(
            {
                "source": "manual_wechat",
                "ok": False,
                "adapter_mode": "live",
                "error": "; ".join(errors[:5]),
                "n_results": 0,
            }
        )
    return {"hits": hits, "diagnostics": diagnostics}


def iter_article_files(week_dir: Path) -> list[Path]:
    return [path for path in sorted(week_dir.glob("*.md")) if not path.name.startswith("README")]


def parse_manual_wechat_article(path: str | Path) -> dict[str, Any]:
    text = Path(path).read_text(encoding="utf-8")
    metadata, body = parse_front_matter(text)
    missing = [field for field in REQUIRED_FIELDS if not metadata.get(field)]
    if missing:
        raise ValueError(f"missing required front matter fields: {', '.join(missing)}")
    if not body.strip():
        raise ValueError("body is empty")
    return {"metadata": metadata, "body": body.strip()}


def parse_front_matter(text: str) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("missing YAML front matter")

    end_idx = None
    for idx, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            end_idx = idx
            break
    if end_idx is None:
        raise ValueError("front matter is not closed")

    metadata = parse_simple_yaml(lines[1:end_idx])
    body = "\n".join(lines[end_idx + 1 :])
    return metadata, body


def parse_simple_yaml(lines: list[str]) -> dict[str, Any]:
    data: dict[str, Any] = {}
    current_list_key: str | None = None
    for raw in lines:
        if not raw.strip():
            continue
        if raw.startswith("  - ") and current_list_key:
            data.setdefault(current_list_key, []).append(clean_scalar(raw[4:]))
            continue
        if ":" not in raw:
            raise ValueError(f"invalid front matter line: {raw}")
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if not value:
            data[key] = []
            current_list_key = key
        else:
            data[key] = clean_scalar(value)
            current_list_key = None
    return data


def clean_scalar(value: str) -> str:
    text = value.strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    return text


def article_matches_team(article: dict[str, Any], team: dict[str, Any]) -> bool:
    meta = article["metadata"]
    if meta.get("analyst_id") == team.get("analyst_id"):
        return True
    if meta.get("institution") == team.get("institution") and meta.get("role") == team.get("role"):
        return True
    accounts = set(team.get("official_accounts", []))
    return bool(meta.get("account_name") in accounts)


def article_matches_query(article: dict[str, Any], query: str) -> bool:
    meta = article["metadata"]
    body = article["body"]
    haystack = " ".join(
        [
            str(meta.get("title", "")),
            str(meta.get("url", "")),
            str(meta.get("account_name", "")),
            str(meta.get("institution", "")),
            str(meta.get("analyst_id", "")),
            body[:1000],
        ]
    )
    return any(token and token in haystack for token in query.split())


def in_window(value: str, window: dict[str, Any]) -> bool:
    published = parse_date(value)
    return date.fromisoformat(window["start"]) <= published <= date.fromisoformat(window["end"])


def parse_date(value: str) -> date:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return date.fromisoformat(value[:10])


def article_to_hit(article: dict[str, Any], path: Path, team: dict[str, Any]) -> dict[str, Any]:
    meta = article["metadata"]
    body = article["body"]
    whitelist = load_source_whitelist()
    official_match = is_official_account(team["analyst_id"], meta.get("account_name"), meta.get("url"), whitelist)
    source_completeness = str(meta.get("source_completeness") or infer_source_completeness(body))
    source_origin = str(meta.get("source_origin") or infer_source_origin(meta, official_match))
    source_type = classify_manual_source_type(meta, source_origin, official_match)
    text_access = classify_manual_text_access(body, source_completeness)
    attribution = attribution_confidence(meta, team)
    return {
        "title": meta["title"],
        "url": meta["url"],
        "snippet": body[:500],
        "source": "manual_wechat",
        "published_at": parse_date(meta["published_at"]).isoformat(),
        "fetched_at": None,
        "raw_score": None,
        "rank_score": None,
        "adapter_mode": "live",
        "extra": {
            "account_name": meta["account_name"],
            "content": body,
            "content_path": str(path),
            "institution": meta["institution"],
            "role": meta["role"],
            "analyst_id": meta["analyst_id"],
            "team_members": meta.get("team_members", []),
            "source_note": meta.get("source_note"),
            "source_type": source_type,
            "source_origin": source_origin,
            "source_completeness": source_completeness,
            "original_url": meta.get("original_url") or meta.get("url"),
            "copied_at": meta.get("copied_at"),
            "content_length_chars": len(body),
            "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "official_account_match": official_match,
            "text_access": text_access,
            "attribution_confidence": attribution,
            "adapter_mode": "live",
        },
    }


def infer_source_completeness(body: str) -> str:
    return "full_article" if len(body) >= 1200 else "excerpt"


def infer_source_origin(meta: dict[str, Any], official_match: bool) -> str:
    if official_match:
        return "official_wechat"
    host = urlparse(str(meta.get("url") or "")).netloc.lower()
    if any(token in host for token in ["sina", "163", "qq.com", "eastmoney", "stcn", "cnstock", "yicai"]):
        return "financial_media"
    if any(token in host for token in ["wind", "choice", "research", "glybw", "sohu"]):
        return "research_platform"
    return "manual_note"


def classify_manual_source_type(meta: dict[str, Any], source_origin: str, official_match: bool) -> str:
    explicit = meta.get("source_type")
    if explicit and explicit != "official_wechat":
        return str(explicit)
    if source_origin == "official_wechat" and official_match:
        return "official_wechat"
    if source_origin in {"broker_official", "research_platform", "financial_media", "aggregator", "manual_note"}:
        return source_origin
    return "unknown"


def classify_manual_text_access(body: str, source_completeness: str) -> str:
    body_len = len(body)
    if source_completeness == "full_article" and body_len >= 1200:
        return "full_text"
    if source_completeness == "snippet" or body_len < 300:
        return "snippet_only"
    if source_completeness == "full_article" and body_len >= 500:
        return "partial_text"
    if source_completeness == "excerpt":
        return "partial_text"
    if body_len >= 500:
        return "partial_text"
    return "metadata_only"


def attribution_confidence(meta: dict[str, Any], team: dict[str, Any]) -> str:
    if (
        meta.get("analyst_id") == team.get("analyst_id")
        and meta.get("institution") == team.get("institution")
        and meta.get("account_name") in set(team.get("official_accounts", []))
    ):
        return "high"
    if meta.get("institution") == team.get("institution") or meta.get("account_name") in set(team.get("official_accounts", [])):
        return "med"
    if any(member and member in str(meta.get("title", "")) for member in team.get("team_members", [])):
        return "low"
    return "none"
