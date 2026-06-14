from __future__ import annotations

import csv
import os
import json
from importlib import resources
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDUSTRY_TERMS = REPO_ROOT / "data" / "industry_terms_sample.csv"
DEFAULT_COMPANIES = REPO_ROOT / "data" / "a_share_companies_sample.csv"
IR_SEARCH_ENTITY_FILES = ("industry_terms.csv", "a_share_companies.csv")


class EntityLinker:
    def __init__(
        self,
        industry_terms_path: str | Path = DEFAULT_INDUSTRY_TERMS,
        companies_path: str | Path = DEFAULT_COMPANIES,
        ir_search_entities_dir: str | Path | None = None,
        pending_path: str | Path = "~/macro-strategy/pending_vocab.jsonl",
    ) -> None:
        self.pending_path = Path(pending_path).expanduser()
        self.terms: dict[str, tuple[str, str | None]] = {}
        self._load_legacy_terms(industry_terms_path, has_dim_hint=True)
        self._load_legacy_terms(companies_path, has_dim_hint=False)
        self._load_ir_search_entities(ir_search_entities_dir)

    def link(self, tag: str, dim_key: str | None = None) -> str | None:
        clean = tag.strip()
        if not clean:
            return None
        matched = self.terms.get(clean)
        if matched:
            canonical_id, dim_hint = matched
            if dim_key is None or dim_hint is None or dim_key == dim_hint:
                return canonical_id
        self._append_pending(clean, dim_key)
        return None

    def _load_legacy_terms(self, path: str | Path, *, has_dim_hint: bool) -> None:
        source = Path(path)
        if not source.exists():
            return
        with source.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                tag = (row.get("tag") or "").strip()
                canonical_id = (row.get("canonical_id") or "").strip()
                if not tag or not canonical_id:
                    continue
                self.terms[tag] = (canonical_id, (row.get("dim_hint") or "").strip() or None if has_dim_hint else None)

    def _load_ir_search_entities(self, entities_dir: str | Path | None) -> None:
        root = resolve_ir_search_entities_dir(entities_dir)
        if not root:
            return
        for filename in IR_SEARCH_ENTITY_FILES:
            path = root / filename
            if path.exists():
                self._load_ir_search_entity_file(path)

    def _load_ir_search_entity_file(self, path: Path) -> None:
        with path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                canonical_id = (row.get("canonical_id") or "").strip()
                if not canonical_id:
                    continue
                dim_hint = _dim_hint_for_ir_search_row(row)
                for tag in _ir_search_tags(row):
                    self.terms[tag] = (canonical_id, dim_hint)

    def _append_pending(self, tag: str, dim_key: str | None) -> None:
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "tag": tag,
            "dim_key": dim_key,
        }
        with self.pending_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def resolve_ir_search_entities_dir(entities_dir: str | Path | None = None) -> Path | None:
    if entities_dir:
        return Path(entities_dir).expanduser()
    configured = os.environ.get("IR_SEARCH_ENTITIES_DIR")
    if configured:
        return Path(configured).expanduser()
    try:
        return Path(resources.files("ir_search") / "entities")
    except Exception:
        return None


def _ir_search_tags(row: dict[str, str]) -> list[str]:
    values: list[str] = []
    for key in ["names", "aliases", "codes", "related_terms"]:
        values.extend(_split_pipe_cell(row.get(key) or ""))
    return _dedupe([item for item in values if item])


def _split_pipe_cell(value: str) -> list[str]:
    return [item.strip() for item in value.split("|") if item.strip()]


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _dim_hint_for_ir_search_row(row: dict[str, str]) -> str | None:
    market = (row.get("market") or "").strip()
    canonical_id = (row.get("canonical_id") or "").strip()
    if market == "INDUSTRY" or canonical_id.startswith("INDUSTRY:"):
        return None
    return None
