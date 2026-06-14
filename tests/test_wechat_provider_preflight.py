from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace

from core.retrieval.wechat_provider_preflight import (
    build_wechat_provider_preflight,
    check_dajiala,
    check_wewe,
    render_wechat_provider_preflight,
    resolve_accounts_path,
)
from scripts.run_coverage_check import should_run_wechat_provider_preflight


class FakeGzhFetch:
    DAJIALA_MAX_PAGES = 3

    @staticmethod
    def fetch_dajiala(cfg, account, start, end):
        return [
            SimpleNamespace(
                title=f"{account} 最新文章",
                published_at=datetime(2026, 6, 14, 12, 0),
            )
        ]


class FakeResponse:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def test_check_dajiala_reports_missing_name() -> None:
    result = check_dajiala(FakeGzhFetch, "一瑜中的", {}, datetime(2026, 6, 8).date(), datetime(2026, 6, 14).date(), max_pages=1)

    assert result["configured"] is False
    assert result["error"] == "dajiala.name missing"


def test_check_dajiala_counts_window_articles() -> None:
    result = check_dajiala(
        FakeGzhFetch,
        "一瑜中的",
        {"name": "一瑜中的"},
        datetime(2026, 6, 8).date(),
        datetime(2026, 6, 14).date(),
        max_pages=1,
    )

    assert result["ok"] is True
    assert result["in_window_count"] == 1
    assert result["latest_title"] == "一瑜中的 最新文章"
    assert FakeGzhFetch.DAJIALA_MAX_PAGES == 3


def test_check_wewe_distinguishes_empty_feed(monkeypatch) -> None:
    def fake_urlopen(url, timeout):
        return FakeResponse({"title": "一瑜中的", "items": []})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = check_wewe(
        "一瑜中的",
        {"mp_id": "MP_WXS_1"},
        datetime(2026, 6, 8).date(),
        datetime(2026, 6, 14).date(),
        base_url="http://localhost:4001",
        timeout=1,
    )

    assert result["ok"] is True
    assert result["item_count"] == 0
    assert result["in_window_count"] == 0


def test_build_preflight_marks_ready_from_dajiala_and_warns_empty_wewe(tmp_path, monkeypatch) -> None:
    accounts = {
        "一瑜中的": {
            "dajiala": {"name": "一瑜中的"},
            "wewe": {"mp_id": "MP_WXS_1"},
        }
    }
    accounts_path = tmp_path / "accounts.json"
    accounts_path.write_text(json.dumps(accounts, ensure_ascii=False), encoding="utf-8")

    def fake_urlopen(url, timeout):
        return FakeResponse({"title": "一瑜中的", "items": []})

    monkeypatch.setattr("core.retrieval.wechat_provider_preflight.load_gzh_fetch", lambda: FakeGzhFetch)
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    result = build_wechat_provider_preflight(
        [{"analyst_id": "华创证券:macro", "official_accounts": ["华创证券研究", "一瑜中的"]}],
        {"start": "2026-06-08", "end": "2026-06-14", "iso_year": 2026, "iso_week": 24},
        accounts_path=accounts_path,
    )

    by_account = {row["account"]: row for row in result["accounts"]}
    assert by_account["一瑜中的"]["ready"] is True
    assert by_account["一瑜中的"]["dajiala"]["in_window_count"] == 1
    assert "wewe_no_window_articles" in by_account["一瑜中的"]["issues"]
    assert by_account["华创证券研究"]["ready"] is False
    assert result["summary"]["team_ready"] == 1
    assert result["summary"]["team_not_ready"] == 0
    assert "一瑜中的" in render_wechat_provider_preflight(result)


def test_resolve_accounts_path_prefers_ir_search_path_over_stale_command(tmp_path, monkeypatch) -> None:
    ir_root = tmp_path / "ir"
    ir_root.mkdir()
    accounts = ir_root / "accounts.json"
    accounts.write_text("{}", encoding="utf-8")
    stale = tmp_path / "stale.json"
    stale.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("IR_SEARCH_PATH", str(ir_root))
    monkeypatch.setenv("WECHAT_OPENCLI_COMMAND", f"python gzh_fetch.py --accounts {stale} --opencli")

    assert resolve_accounts_path() == accounts


def test_should_run_wechat_provider_preflight_only_for_wechat_opencli() -> None:
    assert should_run_wechat_provider_preflight(["wechat_opencli"], skip=False) is True
    assert should_run_wechat_provider_preflight(["bocha"], skip=False) is False
    assert should_run_wechat_provider_preflight(["wechat_opencli"], skip=True) is False
