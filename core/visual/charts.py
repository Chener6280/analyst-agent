from __future__ import annotations

import json
from html import escape
from pathlib import Path
from typing import Any

from core.history.timeseries import build_consensus_series

VISUAL_PACK_VERSION = 1


def build_visual_pack(
    scan_id: str,
    *,
    output_root: str | Path = "~/macro-strategy",
    db_path: str | Path = "~/macro-strategy/analyst_views.db",
) -> dict[str, Any]:
    output_dir = Path(output_root).expanduser()
    scan_dir = output_dir / "scans" / scan_id
    reports_dir = scan_dir / "reports"
    charts_dir = reports_dir / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)

    brief = read_required_json(reports_dir / "weekly_brief.json")
    history = read_required_json(reports_dir / "history_readiness.json")
    growth_series = build_consensus_series("macro", "growth", db_path=db_path)

    visuals = [
        write_visual(
            charts_dir / "macro_consensus.svg",
            render_macro_consensus_svg(brief.get("macro", [])),
            title="Macro Consensus",
            source="weekly_brief.json",
        ),
        write_visual(
            charts_dir / "strategy_sector_tags.svg",
            render_strategy_sector_svg((brief.get("strategy") or {}).get("categories", [])),
            title="Strategy Sector Tags",
            source="weekly_brief.json",
        ),
        write_visual(
            charts_dir / "growth_history_series.svg",
            render_growth_series_svg(growth_series),
            title="Growth History Series",
            source="SQLite consensus-series",
        ),
    ]
    return {
        "visual_pack_version": VISUAL_PACK_VERSION,
        "scan_id": scan_id,
        "status": "ready" if all(item["bytes"] > 0 for item in visuals) else "incomplete",
        "charts_dir": str(charts_dir),
        "history_status": history.get("status"),
        "visuals": visuals,
        "notes": visual_notes(history),
    }


def write_visual(path: Path, svg: str, *, title: str, source: str) -> dict[str, Any]:
    path.write_text(svg, encoding="utf-8")
    return {"title": title, "path": str(path), "source": source, "bytes": path.stat().st_size}


def render_macro_consensus_svg(items: list[dict[str, Any]]) -> str:
    width = 900
    row_h = 64
    top = 92
    height = top + max(len(items), 1) * row_h + 44
    axis_x = 360
    axis_w = 360
    center_x = axis_x + axis_w / 2
    lines = svg_header(width, height, "Macro Consensus")
    lines.append(text(32, 40, "宏观共识：当前维度表态", size=24, weight=700, fill="#172026"))
    lines.append(text(32, 68, "横轴为 stance 值（-2 到 +2）；灰色代表本周无有效表态。", size=14, fill="#667085"))
    lines.append(line(axis_x, top - 22, axis_x + axis_w, top - 22, "#D0D5DD", 2))
    for value in range(-2, 3):
        x = center_x + value * axis_w / 4
        lines.append(line(x, top - 28, x, height - 54, "#EAECF0", 1))
        lines.append(text(x, top - 34, str(value), size=12, fill="#667085", anchor="middle"))

    for idx, item in enumerate(items):
        y = top + idx * row_h
        median = item.get("median")
        n_non_null = int(item.get("n_non_null") or 0)
        n_teams = int(item.get("n_teams") or 0)
        name = str(item.get("name") or item.get("dim_key") or "")
        summary = str(item.get("summary") or "")
        lines.append(text(32, y + 8, name, size=16, weight=700, fill="#172026"))
        lines.append(text(32, y + 31, f"{n_non_null}/{n_teams} | {summary}", size=13, fill="#667085"))
        if median is None:
            lines.append(rect(axis_x, y - 5, axis_w, 22, "#F2F4F7", "#D0D5DD"))
            lines.append(text(center_x, y + 11, "no signal", size=12, fill="#98A2B3", anchor="middle"))
            continue
        value = clamp(float(median), -2, 2)
        x = center_x + value * axis_w / 4
        bar_x = min(center_x, x)
        bar_w = abs(x - center_x)
        color = "#1677FF" if value >= 0 else "#D92D20"
        lines.append(rect(bar_x, y - 5, max(bar_w, 3), 22, color, color))
        lines.append(circle(x, y + 6, 8, color))
        lines.append(text(axis_x + axis_w + 20, y + 10, f"median {median}", size=13, fill="#344054"))
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def render_strategy_sector_svg(categories: list[dict[str, Any]]) -> str:
    sector = next((item for item in categories if item.get("dim_key") == "sector"), {})
    positive = sector.get("top_positive_tags") or []
    negative = sector.get("top_negative_tags") or []
    tags = [("positive", tag) for tag in positive[:5]] + [("negative", tag) for tag in negative[:5]]
    width = 900
    row_h = 42
    top = 86
    height = top + max(len(tags), 1) * row_h + 48
    label_x = 210
    bar_x = 300
    max_count = max([int(tag.get("positive_count") or tag.get("negative_count") or 0) for _, tag in tags] or [1])
    lines = svg_header(width, height, "Strategy Sector Tags")
    lines.append(text(32, 40, "策略板块标签：正负方向", size=24, weight=700, fill="#172026"))
    lines.append(text(32, 68, "蓝色为正向配置，红色为负向配置；长度为提及次数。", size=14, fill="#667085"))
    if not tags:
        lines.append(text(width / 2, height / 2, "no sector tags", size=18, fill="#98A2B3", anchor="middle"))
    for idx, (direction, tag) in enumerate(tags):
        y = top + idx * row_h
        count_key = "positive_count" if direction == "positive" else "negative_count"
        count = int(tag.get(count_key) or 0)
        bar_w = 420 * count / max_count if max_count else 0
        color = "#1677FF" if direction == "positive" else "#D92D20"
        sign = "+" if direction == "positive" else "-"
        lines.append(text(32, y + 16, f"{sign} {tag.get('tag')}", size=15, weight=700, fill="#172026"))
        lines.append(rect(bar_x, y, max(bar_w, 3), 22, color, color))
        lines.append(text(bar_x + bar_w + 14, y + 16, str(count), size=13, fill="#344054"))
        lines.append(text(label_x, y + 16, str(tag.get("tag_canonical_id") or ""), size=12, fill="#667085"))
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def render_growth_series_svg(series: dict[str, Any]) -> str:
    points = series.get("points") or []
    width = 900
    height = 320
    left = 72
    right = 44
    top = 72
    bottom = 64
    chart_w = width - left - right
    chart_h = height - top - bottom
    lines = svg_header(width, height, "Growth History Series")
    lines.append(text(32, 40, "增长共识序列", size=24, weight=700, fill="#172026"))
    lines.append(text(32, 66, "展示已入库 scan 的 median；历史不足时仅作点位展示，不解释趋势。", size=14, fill="#667085"))
    for value in range(-2, 3):
        y = value_to_y(value, top, chart_h)
        lines.append(line(left, y, width - right, y, "#EAECF0", 1))
        lines.append(text(left - 18, y + 4, str(value), size=12, fill="#667085", anchor="end"))
    lines.append(line(left, top, left, top + chart_h, "#D0D5DD", 1.5))
    lines.append(line(left, top + chart_h, width - right, top + chart_h, "#D0D5DD", 1.5))

    plotted = []
    for idx, point in enumerate(points):
        median = point.get("median")
        if median is None:
            continue
        x = left + (chart_w * idx / max(len(points) - 1, 1) if len(points) > 1 else chart_w / 2)
        y = value_to_y(float(median), top, chart_h)
        plotted.append((x, y, point))
    if len(plotted) > 1:
        coords = " ".join(f"{x:.1f},{y:.1f}" for x, y, _ in plotted)
        lines.append(f'<polyline points="{coords}" fill="none" stroke="#1677FF" stroke-width="3"/>')
    if not plotted:
        lines.append(text(width / 2, height / 2, "no non-null growth series", size=18, fill="#98A2B3", anchor="middle"))
    for x, y, point in plotted:
        lines.append(circle(x, y, 7, "#1677FF"))
        label = f"W{point.get('iso_week')} {point.get('mode_label') or ''}".strip()
        lines.append(text(x, top + chart_h + 24, label, size=12, fill="#667085", anchor="middle"))
        lines.append(text(x, y - 12, str(point.get("median")), size=12, fill="#344054", anchor="middle"))
    lines.append("</svg>")
    return "\n".join(lines) + "\n"


def svg_header(width: int, height: int, title: str) -> list[str]:
    return [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">',
        f"<title>{escape(title)}</title>",
        f'<rect width="{width}" height="{height}" fill="#FFFFFF"/>',
    ]


def text(
    x: float,
    y: float,
    value: str,
    *,
    size: int,
    fill: str,
    weight: int | None = None,
    anchor: str | None = None,
) -> str:
    attrs = [f'x="{x:.1f}"', f'y="{y:.1f}"', f'font-size="{size}"', f'fill="{fill}"', 'font-family="Arial, sans-serif"']
    if weight:
        attrs.append(f'font-weight="{weight}"')
    if anchor:
        attrs.append(f'text-anchor="{anchor}"')
    return f"<text {' '.join(attrs)}>{escape(str(value))}</text>"


def rect(x: float, y: float, width: float, height: float, fill: str, stroke: str | None = None) -> str:
    stroke_attr = f' stroke="{stroke}"' if stroke else ""
    return f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{height:.1f}" rx="4" fill="{fill}"{stroke_attr}/>'


def line(x1: float, y1: float, x2: float, y2: float, stroke: str, width: float) -> str:
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" stroke="{stroke}" stroke-width="{width}"/>'


def circle(cx: float, cy: float, r: float, fill: str) -> str:
    return f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="{fill}"/>'


def value_to_y(value: float, top: float, chart_h: float) -> float:
    return top + (2 - clamp(value, -2, 2)) * chart_h / 4


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def visual_notes(history: dict[str, Any]) -> list[str]:
    notes = ["SVG charts are deterministic and generated from local JSON/SQLite artifacts."]
    if history.get("status") == "insufficient_history":
        notes.append("History chart is a readiness preview; do not interpret it as a trend until more real scans exist.")
    return notes


def read_required_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"missing required P7 input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
