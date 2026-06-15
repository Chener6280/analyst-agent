from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from types import SimpleNamespace

from core.retrieval.search_client import _dedupe_hits, _hit_to_dict, _run_wechat_accounts, coarse_freshness


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


def test_run_wechat_accounts_calls_gzh_fetch_with_explicit_account(monkeypatch) -> None:
    calls = []

    def fake_run(cmd, check, capture_output, text, timeout):
        calls.append(cmd)
        return SimpleNamespace(
            stdout=(
                '[{"title":"本周观点","url":"https://mp.weixin.qq.com/s/x",'
                '"published_at":"2026-06-14 12:00","account_name":"一瑜中的",'
                '"content":"' + ("正文" * 700) + '"}]'
            )
        )

    monkeypatch.setenv("WECHAT_OPENCLI_COMMAND", "python3 /tmp/gzh_fetch.py --accounts /tmp/accounts.json --opencli")
    monkeypatch.setattr("subprocess.run", fake_run)

    result = _run_wechat_accounts(
        {"official_accounts": ["一瑜中的"]},
        {"start": "2026-06-08", "end": "2026-06-14"},
    )

    assert result is not None
    assert result["diagnostics"][0]["ok"] is True
    assert result["hits"][0]["extra"]["account_name"] == "一瑜中的"
    assert len(result["hits"][0]["extra"]["content"]) >= 1200
    assert "--account" in calls[0]
    assert "一瑜中的" in calls[0]
    assert "--fulltext" in calls[0]


def test_run_wechat_accounts_rejects_non_gzh_command(monkeypatch) -> None:
    monkeypatch.setenv("WECHAT_OPENCLI_COMMAND", "python3 /tmp/not_fetch.py")

    result = _run_wechat_accounts(
        {"official_accounts": ["一瑜中的"]},
        {"start": "2026-06-08", "end": "2026-06-14"},
    )

    assert result is not None
    assert result["hits"] == []
    assert "must invoke gzh_fetch.py" in result["diagnostics"][0]["error"]


def test_run_wechat_accounts_reports_bad_timeout(monkeypatch) -> None:
    monkeypatch.setenv("WECHAT_OPENCLI_COMMAND", "python3 /tmp/gzh_fetch.py")
    monkeypatch.setenv("WECHAT_OPENCLI_TIMEOUT", "slow")

    result = _run_wechat_accounts(
        {"official_accounts": ["一瑜中的"]},
        {"start": "2026-06-08", "end": "2026-06-14"},
    )

    assert result is not None
    assert result["hits"] == []
    assert "WECHAT_OPENCLI_TIMEOUT must be an integer" in result["diagnostics"][0]["error"]
