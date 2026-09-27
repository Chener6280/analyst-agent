from __future__ import annotations

import json
import re
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any


def export_scan_to_obsidian(
    scan_id: str,
    *,
    output_root: str | Path,
    vault_path: str | Path,
    obsidian_root: str = "Analyst Agent",
) -> dict[str, Any]:
    output_dir = Path(output_root).expanduser()
    scan_dir = output_dir / "scans" / scan_id
    reports_dir = scan_dir / "reports"
    diagnostics_dir = output_dir / "diagnostics"
    vault = Path(vault_path).expanduser()
    root = vault / obsidian_root
    week_label = week_from_scan(scan_id, scan_dir)
    week_dir = root / "Weekly" / week_label
    institution_dir = root / "Institutions"
    topic_dir = root / "Topics"
    chart_dir = week_dir / "charts"

    brief = read_required_json(reports_dir / "weekly_brief.json")
    cross_section = read_required_json(reports_dir / "weekly_cross_section.json")
    source_links = read_json(scan_dir / "source_links.json").get("links") or []
    config = read_json(scan_dir / "config.json")
    window = config.get("window") or infer_window(brief, cross_section)

    for directory in [week_dir, institution_dir, topic_dir, chart_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    copied_charts = copy_charts(reports_dir / "charts", chart_dir)
    stances = read_stances(scan_dir / "extracted")

    write(root / "Analyst Agent Home.md", render_home(week_label))
    write(week_dir / f"{week_label} 周报.md", render_weekly_note(brief, scan_dir, week_label, window))
    write(week_dir / f"{week_label} 机构观点索引.md", render_institution_index(stances, week_label, scan_id))
    write(week_dir / f"{week_label} 主题索引.md", render_topic_index(brief, cross_section, topic_dir, week_label))
    write(week_dir / f"{week_label} 来源链接.md", render_source_links(source_links, week_label))
    write(
        week_dir / f"{week_label} 数据质量.md",
        render_quality_note(brief, scan_dir, reports_dir, diagnostics_dir, week_label),
    )
    write_raw_reports(scan_dir, reports_dir, week_dir, week_label)

    institution_notes = 0
    for stance in stances:
        note_name = f"机构 - {stance.get('institution', '')} {stance.get('role', '')}"
        write(institution_dir / f"{safe_name(note_name)}.md", render_institution_note(stance, week_label))
        institution_notes += 1

    topic_notes = write_topic_notes(brief, cross_section, topic_dir, week_label)

    manifest = {
        "scan_id": scan_id,
        "week": week_label,
        "vault_path": str(vault),
        "obsidian_root": str(root),
        "weekly_dir": str(week_dir),
        "entry_note": str(week_dir / f"{week_label} 周报.md"),
        "home_note": str(root / "Analyst Agent Home.md"),
        "institution_notes": institution_notes,
        "topic_notes": topic_notes,
        "source_links": len(source_links),
        "charts": copied_charts,
    }
    manifest_path = reports_dir / "obsidian_export.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write(week_dir / f"{week_label} Obsidian Export Manifest.md", render_manifest(manifest))
    return manifest


def render_weekly_note(brief: dict[str, Any], scan_dir: Path, week_label: str, window: dict[str, Any]) -> str:
    macro_rows = [
        f"| {wikilink('主题 - ' + item['name'], item['name'])} | {item.get('n_non_null')}/{item.get('n_teams')} | "
        f"{item.get('mode_label') or 'n/a'} | {format_value(item.get('median'))} | "
        f"{format_value(item.get('dispersion_range'))} | {item.get('summary')} |"
        for item in brief.get("macro", [])
    ]
    strategy_rows = [
        f"| {wikilink('主题 - ' + item['name'], item['name'])} | {item.get('n_non_null')}/{item.get('n_teams')} | "
        f"{item.get('mode_label') or 'n/a'} | {format_value(item.get('median'))} | "
        f"{format_value(item.get('dispersion_range'))} | {item.get('summary')} |"
        for item in brief.get("strategy", {}).get("ordinals", [])
    ]
    category_lines = [
        f"- {item.get('name')}: {format_category_tags(item, links=True)}"
        for item in brief.get("strategy", {}).get("categories", [])
    ]
    quality_lines = render_quality_lines(brief.get("quality") or {})
    evidence_rows = []
    for row in brief.get("evidence", []):
        institution = row.get("institution") or row.get("analyst_id") or ""
        role = row.get("role") or ""
        dim_name = row.get("dim_name") or row.get("dim_key") or ""
        label = row.get("tag") or row.get("label") or "n/a"
        evidence_rows.append(
            f"| {role} | {wikilink('主题 - ' + dim_name, dim_name)} | "
            f"{wikilink('机构 - ' + institution + ' ' + role, institution + ':' + role)} | "
            f"{escape_table(label)} | {escape_table(row.get('verbatim'))} | {format_source(row.get('source_url'))} |"
        )

    start = window.get("start") or ""
    end = window.get("end") or ""
    return f"""---
type: weekly_report
project: analyst-agent
scan_id: {brief.get("scan_id")}
week: {week_label}
window_start: {start}
window_end: {end}
tags: [analyst-agent, weekly, macro-strategy]
---

# {week_label} 宏观策略周报

> 原始扫描：`{scan_dir}`  
> 周期：{start} 至 {end}  
> 关联：{wikilink(week_label + " 机构观点索引")} · {wikilink(week_label + " 主题索引")} · {wikilink(week_label + " 来源链接")} · {wikilink(week_label + " 数据质量")}

## 本周结论

{brief.get("headline")}

## 图表

![[charts/macro_consensus.svg]]

![[charts/strategy_sector_tags.svg]]

## 宏观观点

| 维度 | 样本 | 众数 | 中位数 | 分歧 | 摘要 |
|---|---:|---|---:|---:|---|
{chr(10).join(macro_rows)}

## 策略观点

| 维度 | 样本 | 众数 | 中位数 | 分歧 | 摘要 |
|---|---:|---|---:|---:|---|
{chr(10).join(strategy_rows)}

### 配置与主题

{chr(10).join(category_lines)}

## 数据质量速览

{chr(10).join(quality_lines)}

## 证据摘录

| 角色 | 维度 | 机构 | 观点/标签 | 原文摘录 | 来源 |
|---|---|---|---|---|---|
{chr(10).join(evidence_rows)}

## 原始报告

- {wikilink(week_label + " 原始 weekly_brief")}
- {wikilink(week_label + " 原始 weekly_cross_section")}
"""


def render_institution_index(stances: list[dict[str, Any]], week_label: str, scan_id: str) -> str:
    rows = []
    for stance in stances:
        institution = stance.get("institution") or ""
        role = stance.get("role") or ""
        team = "；".join(stance.get("team_members") or [])
        key_labels = []
        for key, value in (stance.get("dimensions") or {}).items():
            if isinstance(value, dict) and value.get("label"):
                key_labels.append(f"{key}:{value['label']}")
        rows.append(
            f"| {wikilink('机构 - ' + institution + ' ' + role, institution + ':' + role)} | "
            f"{escape_table(team)} | {stance.get('coverage')} | {stance.get('text_access')} | "
            f"{escape_table('; '.join(key_labels[:4]))} | {len(stance.get('sources') or [])} |"
        )
    return f"""---
type: institution_index
scan_id: {scan_id}
week: {week_label}
tags: [analyst-agent, institution-index]
---

# {week_label} 机构观点索引

返回：{wikilink(week_label + " 周报")}

| 机构/角色 | 分析师 | 覆盖 | 正文 | 关键观点 | 来源数 |
|---|---|---|---|---|---:|
{chr(10).join(rows)}
"""


def render_institution_note(stance: dict[str, Any], week_label: str) -> str:
    institution = stance.get("institution") or ""
    role = stance.get("role") or ""
    team_members = stance.get("team_members") or []
    dim_sections = []
    for key, value in (stance.get("dimensions") or {}).items():
        if not isinstance(value, dict):
            continue
        dim_sections.append(
            f"### {key}\n\n"
            f"- 观点：{value.get('label') or '未提取'}\n"
            f"- 置信度：{value.get('confidence') or ''}\n"
            f"- 摘录：{value.get('verbatim') or ''}\n"
        )
    source_rows = []
    for source in (stance.get("sources") or [])[:50]:
        source_rows.append(
            f"| {escape_table(source.get('date'))} | {escape_table(source.get('title'))} | "
            f"{escape_table(source.get('source_type'))} | {format_source(source.get('url'))} |"
        )
    return f"""---
type: institution_view
scan_id: {stance.get("scan_id")}
week: {week_label}
institution: {institution}
role: {role}
analyst_id: {stance.get("analyst_id")}
team_members: {yaml_inline_list(team_members)}
tags: [analyst-agent, institution, {role}]
---

# {institution} {role}

返回：{wikilink(week_label + " 机构观点索引")} · {wikilink(week_label + " 周报")}

- 分析师/团队：{"；".join(team_members) if team_members else "未记录"}
- 覆盖状态：{stance.get("coverage")}
- 正文状态：{stance.get("text_access")}
- 归因置信度：{stance.get("attribution_confidence")}

## 本周提取观点

{chr(10).join(dim_sections)}

## 来源链接

| 日期 | 标题 | 来源类型 | 链接 |
|---|---|---|---|
{chr(10).join(source_rows)}
"""


def render_topic_index(brief: dict[str, Any], cross_section: dict[str, Any], topic_dir: Path, week_label: str) -> str:
    lines = [
        "---",
        "type: topic_index",
        f"scan_id: {brief.get('scan_id')}",
        f"week: {week_label}",
        "tags: [analyst-agent, topic-index]",
        "---",
        "",
        f"# {week_label} 主题索引",
        "",
        f"返回：{wikilink(week_label + ' 周报')}",
        "",
    ]
    evidence_by_dim = defaultdict(list)
    for row in brief.get("evidence", []):
        evidence_by_dim[row.get("dim_name") or row.get("dim_key")].append(row)
    for dim_name, rows in sorted(evidence_by_dim.items()):
        lines.append(f"- {wikilink('主题 - ' + dim_name, dim_name)}：{len(rows)} 条证据")
    lines.append("")
    lines.append("## 配置/行业/风格实体")
    lines.append("")
    for entity in cross_section.get("entities") or []:
        tag = entity.get("tag") or entity.get("entity")
        lines.append(
            f"- {wikilink('主题 - ' + tag, tag)}：+{entity.get('positive')} / "
            f"-{entity.get('negative')} / neutral {entity.get('neutral')}"
        )
    return "\n".join(lines) + "\n"


def write_topic_notes(brief: dict[str, Any], cross_section: dict[str, Any], topic_dir: Path, week_label: str) -> int:
    count = 0
    evidence_by_dim = defaultdict(list)
    for row in brief.get("evidence", []):
        evidence_by_dim[row.get("dim_name") or row.get("dim_key")].append(row)
    for dim_name, rows in evidence_by_dim.items():
        table_rows = []
        for row in rows:
            institution = row.get("institution") or ""
            role = row.get("role") or ""
            table_rows.append(
                f"| {role} | {wikilink('机构 - ' + institution + ' ' + role, institution + ':' + role)} | "
                f"{escape_table(row.get('tag') or row.get('label'))} | {escape_table(row.get('verbatim'))} | "
                f"{format_source(row.get('source_url'))} |"
            )
        write(
            topic_dir / f"{safe_name('主题 - ' + dim_name)}.md",
            render_topic_note(week_label, dim_name, "topic", "\n".join(table_rows)),
        )
        count += 1
    for entity in cross_section.get("entities") or []:
        tag = entity.get("tag") or entity.get("entity")
        teams = []
        for team in (entity.get("teams") or [])[:60]:
            institution, _, role = team.partition(":")
            teams.append(f"- {wikilink('机构 - ' + institution + ' ' + role, team)}")
        text = f"""---
type: topic_entity
week: {week_label}
entity: {entity.get("entity")}
topic: {tag}
tags: [analyst-agent, topic, entity]
---

# {tag}

返回：{wikilink(week_label + " 主题索引")} · {wikilink(week_label + " 周报")}

- canonical_id: `{entity.get("entity")}`
- positive: {entity.get("positive")}
- negative: {entity.get("negative")}
- neutral: {entity.get("neutral")}

## 提及团队

{chr(10).join(teams)}
"""
        write(topic_dir / f"{safe_name('主题 - ' + tag)}.md", text)
        count += 1
    return count


def render_topic_note(week_label: str, topic: str, note_type: str, table_rows: str) -> str:
    return f"""---
type: {note_type}
week: {week_label}
topic: {topic}
tags: [analyst-agent, topic]
---

# {topic}

返回：{wikilink(week_label + " 主题索引")} · {wikilink(week_label + " 周报")}

| 角色 | 机构 | 观点/标签 | 摘录 | 来源 |
|---|---|---|---|---|
{table_rows}
"""


def render_source_links(source_links: list[dict[str, Any]], week_label: str) -> str:
    rows = []
    for link in source_links:
        institution = link.get("institution") or ""
        role = link.get("role") or ""
        rows.append(
            f"| {escape_table(link.get('published_at'))} | "
            f"{wikilink('机构 - ' + institution + ' ' + role, institution + ':' + role)} | "
            f"{escape_table(link.get('account_name'))} | {escape_table(link.get('title'))} | "
            f"{escape_table(link.get('text_access'))} | {format_source(link.get('url'))} |"
        )
    return f"""---
type: source_links
week: {week_label}
tags: [analyst-agent, sources]
---

# {week_label} 来源链接

返回：{wikilink(week_label + " 周报")}

| 日期 | 机构/角色 | 账号 | 标题 | 正文 | 链接 |
|---|---|---|---|---|---|
{chr(10).join(rows)}
"""


def render_quality_note(
    brief: dict[str, Any],
    scan_dir: Path,
    reports_dir: Path,
    diagnostics_dir: Path,
    week_label: str,
) -> str:
    scan_id = brief.get("scan_id") or scan_dir.name
    parts = [
        "---",
        "type: data_quality",
        f"scan_id: {scan_id}",
        f"week: {week_label}",
        "tags: [analyst-agent, quality]",
        "---",
        "",
        f"# {week_label} 数据质量",
        "",
        f"返回：{wikilink(week_label + ' 周报')}",
        "",
        "## Weekly Brief Quality",
        "",
        "\n".join(render_quality_lines(brief.get("quality") or {})),
    ]
    for title, path in [
        ("Coverage Report", scan_dir / "coverage_report.md"),
        ("Extraction Report", scan_dir / "extracted" / "extraction_report.md"),
        ("History Readiness", reports_dir / "history_readiness.md"),
        ("Acceptance", diagnostics_dir / f"{scan_id}__mvp_acceptance.md"),
    ]:
        if path.exists():
            parts.extend(["", f"## {title}", "", path.read_text(encoding="utf-8")])
    return "\n".join(parts) + "\n"


def render_home(week_label: str) -> str:
    return f"""---
type: project_home
project: analyst-agent
tags: [analyst-agent]
---

# Analyst Agent

## 周报

- {wikilink(week_label + " 周报", week_label + " 宏观策略周报")}

## 最新索引

- {wikilink(week_label + " 机构观点索引")}
- {wikilink(week_label + " 主题索引")}
- {wikilink(week_label + " 来源链接")}
- {wikilink(week_label + " 数据质量")}

## 说明

本目录由本地 analyst-agent 输出生成。抓取、抽取和质量校验仍以项目原始输出为准；Obsidian 用于复盘、链接和长期沉淀。
"""


def render_manifest(manifest: dict[str, Any]) -> str:
    rows = [f"| {key} | `{value}` |" for key, value in manifest.items()]
    return "# Obsidian Export Manifest\n\n| Key | Value |\n|---|---|\n" + "\n".join(rows) + "\n"


def write_raw_reports(scan_dir: Path, reports_dir: Path, week_dir: Path, week_label: str) -> None:
    raw_files = [
        (reports_dir / "weekly_brief.md", f"{week_label} 原始 weekly_brief.md"),
        (reports_dir / "weekly_cross_section.md", f"{week_label} 原始 weekly_cross_section.md"),
        (scan_dir / "source_links.md", f"{week_label} 原始 source_links.md"),
    ]
    for source, name in raw_files:
        if source.exists():
            write(week_dir / name, source.read_text(encoding="utf-8"))


def copy_charts(source_dir: Path, target_dir: Path) -> list[str]:
    copied = []
    if not source_dir.exists():
        return copied
    for source in sorted(source_dir.glob("*.svg")):
        target = target_dir / source.name
        shutil.copy2(source, target)
        copied.append(str(target))
    return copied


def read_stances(extracted_dir: Path) -> list[dict[str, Any]]:
    stances = []
    if not extracted_dir.exists():
        return stances
    for path in sorted(extracted_dir.glob("*.stance.json")):
        stances.append(read_required_json(path))
    return stances


def render_quality_lines(quality: dict[str, Any]) -> list[str]:
    lines = []
    for key, value in quality.items():
        if key == "quality_warnings":
            continue
        lines.append(f"- {key}: {value}")
    for warning in quality.get("quality_warnings") or []:
        lines.append(f"- quality_warning: {warning}")
    return lines


def format_category_tags(item: dict[str, Any], *, links: bool = False) -> str:
    def fmt(bucket: str, sign: str, count_key: str) -> list[str]:
        out = []
        for tag in item.get(bucket) or []:
            name = tag.get("tag")
            if not name:
                continue
            display = wikilink("主题 - " + name, name) if links else name
            out.append(f"{sign}{display}({tag.get(count_key, 0)})")
        return out

    parts = []
    positive = fmt("top_positive_tags", "+", "positive_count")
    negative = fmt("top_negative_tags", "-", "negative_count")
    disputed = [tag.get("tag") for tag in item.get("disputed_tags") or [] if tag.get("tag")]
    if positive:
        parts.append(", ".join(positive))
    if negative:
        parts.append(", ".join(negative))
    if disputed:
        parts.append("分歧: " + ", ".join(disputed))
    return "; ".join(parts) if parts else f"提及 {item.get('n_mentions', 0)} 次"


def format_source(url: str | None) -> str:
    if not url:
        return "n/a"
    return f"[原文]({url})"


def format_value(value: Any) -> str:
    return "n/a" if value is None else str(value)


def wikilink(name: str, label: str | None = None) -> str:
    safe = safe_name(name)
    if label and label != safe:
        return f"[[{safe}|{label}]]"
    return f"[[{safe}]]"


def safe_name(value: str) -> str:
    text = re.sub(r'[\\/:*?"<>|#^\\[\\]]+', " ", str(value)).strip()
    return re.sub(r"\s+", " ", text)


def escape_table(value: Any) -> str:
    return str(value or "").replace("\n", " ").replace("|", "\\|")


def yaml_inline_list(values: list[Any]) -> str:
    if not values:
        return "[]"
    escaped = [str(value).replace('"', '\\"') for value in values]
    return "[" + ", ".join(f'"{value}"' for value in escaped) + "]"


def week_from_scan(scan_id: str, scan_dir: Path) -> str:
    config = read_json(scan_dir / "config.json")
    window = config.get("window") or {}
    iso_year = window.get("iso_year")
    iso_week = window.get("iso_week")
    if iso_year and iso_week:
        return f"{iso_year}-W{int(iso_week):02d}"
    match = re.search(r"(\d{4}-W\d{2})", scan_id)
    if match:
        return match.group(1)
    return scan_id


def infer_window(*objects: dict[str, Any]) -> dict[str, Any]:
    for obj in objects:
        for key in ["window", "date_window"]:
            if isinstance(obj.get(key), dict):
                return obj[key]
    return {}


def read_required_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ValueError(f"missing required input: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
