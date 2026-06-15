from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from core.config import load_analyst_list, make_scan_id, resolve_window


def test_manual_window_and_scan_id() -> None:
    window = resolve_window("manual", "2026-06-01", "2026-06-07")
    assert window["start"] == "2026-06-01"
    assert window["end"] == "2026-06-07"
    assert make_scan_id(window, "manual", "v1") == "manual-2026-06-01-2026-06-07-v1"


def test_weekly_window_handles_cross_year_iso_week() -> None:
    now = datetime(2026, 1, 1, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    window = resolve_window("weekly", tz="Asia/Shanghai", now=now)
    assert window["start"] == "2025-12-22"
    assert window["end"] == "2025-12-28"
    assert window["iso_year"] == 2025
    assert window["iso_week"] == 52
    assert make_scan_id(window, "weekly", "v1") == "2025-W52-v1"


def test_weekly_window_can_use_explicit_dates_for_backfill() -> None:
    window = resolve_window("weekly", "2026-06-08", "2026-06-14")
    assert window["start"] == "2026-06-08"
    assert window["end"] == "2026-06-14"
    assert window["iso_year"] == 2026
    assert window["iso_week"] == 24
    assert make_scan_id(window, "weekly", "v1") == "2026-W24-v1"


def test_load_analyst_list() -> None:
    teams = load_analyst_list("data/analyst-list.md")
    assert teams[0]["analyst_id"] == "广发证券:macro"
    assert teams[0]["team_members"] == ["郭磊"]
    assert teams[2]["role"] == "strategy"
    assert all(team["active"] for team in teams)


def test_load_analyst_list_rejects_duplicate_id(tmp_path: Path) -> None:
    path = tmp_path / "analysts.md"
    path.write_text(
        """# Analyst List

| institution | role | analyst_id | team_members | official_accounts | active |
|---|---|---|---|---|---|
| 广发证券 | macro | 广发证券:macro | 郭磊 | 郭磊宏观茶座 | 1 |
| 广发证券 | macro | 广发证券:macro | 郭磊 | 郭磊宏观茶座 | 1 |
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate analyst_id"):
        load_analyst_list(path)


def test_load_analyst_list_rejects_bad_role(tmp_path: Path) -> None:
    path = tmp_path / "analysts.md"
    path.write_text(
        """# Analyst List

| institution | role | analyst_id | team_members | official_accounts | active |
|---|---|---|---|---|---|
| 广发证券 | credit | 广发证券:credit | 郭磊 | 郭磊宏观茶座 | 1 |
""",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="invalid role"):
        load_analyst_list(path)
