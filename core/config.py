from __future__ import annotations

from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

VALID_ROLES = {"macro", "strategy"}


def resolve_window(
    mode: str,
    start: str | None = None,
    end: str | None = None,
    tz: str = "Asia/Shanghai",
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    if mode not in {"weekly", "manual"}:
        raise ValueError("mode must be weekly or manual")

    zone = ZoneInfo(tz)
    if mode == "manual":
        if not start or not end:
            raise ValueError("manual mode requires start and end")
        start_date = _parse_date(start, "start")
        end_date = _parse_date(end, "end")
        if start_date > end_date:
            raise ValueError("start must be on or before end")
        iso = start_date.isocalendar()
        return _window_dict(start_date, end_date, tz, iso.year, iso.week)

    anchor = now.astimezone(zone) if now else datetime.now(zone)
    this_week_monday = anchor.date() - timedelta(days=anchor.isoweekday() - 1)
    start_date = this_week_monday - timedelta(days=7)
    end_date = this_week_monday - timedelta(days=1)
    iso = start_date.isocalendar()
    return _window_dict(start_date, end_date, tz, iso.year, iso.week)


def make_scan_id(window: dict[str, Any], mode: str, run_version: str) -> str:
    if mode == "weekly":
        return f"{window['iso_year']}-W{int(window['iso_week']):02d}-{run_version}"
    if mode == "manual":
        return f"manual-{window['start']}-{window['end']}-{run_version}"
    raise ValueError("mode must be weekly or manual")


def load_analyst_list(path: str | Path) -> list[dict[str, Any]]:
    rows = _read_markdown_table(Path(path))
    seen_ids: set[str] = set()
    analysts: list[dict[str, Any]] = []

    for row in rows:
        institution = row.get("institution", "").strip()
        role = row.get("role", "").strip()
        analyst_id = row.get("analyst_id", "").strip()
        if role not in VALID_ROLES:
            raise ValueError(f"invalid role for {analyst_id or institution}: {role}")
        if analyst_id != f"{institution}:{role}":
            raise ValueError(f"analyst_id must be institution:role for {institution}")
        if analyst_id in seen_ids:
            raise ValueError(f"duplicate analyst_id: {analyst_id}")
        seen_ids.add(analyst_id)

        analysts.append(
            {
                "institution": institution,
                "role": role,
                "analyst_id": analyst_id,
                "team_members": _split_cell(row.get("team_members", "")),
                "official_accounts": _split_cell(row.get("official_accounts", "")),
                "active": row.get("active", "").strip() == "1",
            }
        )
    return analysts


def _window_dict(start_date: date, end_date: date, tz: str, iso_year: int, iso_week: int) -> dict[str, Any]:
    start_at = datetime.combine(start_date, time.min).isoformat()
    end_at = datetime.combine(end_date, time(23, 59, 59)).isoformat()
    return {
        "start": start_date.isoformat(),
        "end": end_date.isoformat(),
        "start_at": start_at,
        "end_at": end_at,
        "timezone": tz,
        "iso_year": iso_year,
        "iso_week": iso_week,
    }


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must use YYYY-MM-DD") from exc


def _read_markdown_table(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)

    table_lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip().startswith("|")]
    if len(table_lines) < 3:
        raise ValueError(f"no markdown table found in {path}")

    headers = [_clean_cell(cell) for cell in table_lines[0].strip("|").split("|")]
    rows: list[dict[str, str]] = []
    for line in table_lines[2:]:
        cells = [_clean_cell(cell) for cell in line.strip("|").split("|")]
        if len(cells) != len(headers):
            raise ValueError(f"table row has {len(cells)} cells but expected {len(headers)}: {line}")
        rows.append(dict(zip(headers, cells)))
    return rows


def _clean_cell(value: str) -> str:
    return value.strip().replace("<br>", ",")


def _split_cell(value: str) -> list[str]:
    return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
