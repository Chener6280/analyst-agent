from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDUSTRY_TERMS = REPO_ROOT / "data" / "industry_terms_sample.csv"
DEFAULT_COMPANIES = REPO_ROOT / "data" / "a_share_companies_sample.csv"


class EntityLinker:
    def __init__(
        self,
        industry_terms_path: str | Path = DEFAULT_INDUSTRY_TERMS,
        companies_path: str | Path = DEFAULT_COMPANIES,
        pending_path: str | Path = "~/macro-strategy/pending_vocab.jsonl",
    ) -> None:
        self.pending_path = Path(pending_path).expanduser()
        self.terms: dict[str, tuple[str, str | None]] = {}
        self._load_terms(industry_terms_path, has_dim_hint=True)
        self._load_terms(companies_path, has_dim_hint=False)

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

    def _load_terms(self, path: str | Path, *, has_dim_hint: bool) -> None:
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

    def _append_pending(self, tag: str, dim_key: str | None) -> None:
        self.pending_path.parent.mkdir(parents=True, exist_ok=True)
        record: dict[str, Any] = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "tag": tag,
            "dim_key": dim_key,
        }
        with self.pending_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
