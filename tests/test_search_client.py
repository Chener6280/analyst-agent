from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from core.retrieval.search_client import _dedupe_hits, _hit_to_dict, coarse_freshness


@dataclass
class FakeEnum:
    name: str
    value: str


@dataclass
class FakeHit:
    title: str = "title"
    url: str = "https://example.com/a"
    snippet: str = "snippet"
    source: str = "bocha"
    tier: FakeEnum = field(default_factory=lambda: FakeEnum("BROKER", "broker"))
    evidence_type: FakeEnum = field(default_factory=lambda: FakeEnum("BROKER_REPORT", "broker_report"))
    published_at: datetime | None = None
    fetched_at: datetime | None = None
    raw_score: float | None = 0.1
    found_by: list[str] = field(default_factory=lambda: ["bocha", "exa"])
    rank_score: float = 0.9
    canonical_url: str = "wechat:sn:abc"
    matched_entities: list[str] = field(default_factory=lambda: ["300750.SZ"])
    extra: dict = field(default_factory=dict)


def test_hit_to_dict_preserves_ir_search_evidence_fields() -> None:
    data = _hit_to_dict(FakeHit())

    assert data["canonical_url"] == "wechat:sn:abc"
    assert data["tier"] == "BROKER"
    assert data["evidence_type"] == "broker_report"
    assert data["matched_entities"] == ["300750.SZ"]
    assert data["found_by"] == ["bocha", "exa"]
    assert data["extra"]["canonical_url"] == "wechat:sn:abc"


def test_dedupe_hits_prefers_canonical_url() -> None:
    hits = [
        {"url": "https://mp.weixin.qq.com/s/a?chksm=1", "canonical_url": "wechat:sn:abc", "title": "a"},
        {"url": "https://mp.weixin.qq.com/s/a?from=timeline", "canonical_url": "wechat:sn:abc", "title": "a"},
    ]

    assert _dedupe_hits(hits) == [hits[0]]


def test_coarse_freshness_tracks_manual_window_span() -> None:
    assert coarse_freshness({"start_at": "2026-06-01T00:00:00", "end_at": "2026-06-07T23:59:59"}) == "oneWeek"
    assert coarse_freshness({"start_at": "2026-06-01T00:00:00", "end_at": "2026-06-21T23:59:59"}) == "oneMonth"
    assert coarse_freshness({"start_at": "2025-01-01T00:00:00", "end_at": "2026-06-21T23:59:59"}) == "noLimit"
