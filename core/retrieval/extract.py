from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from core.retrieval.manual_wechat import parse_manual_wechat_article
from core.schema.stance import dimensions_for_role, validate_stance_document
from core.vocab.entity_link import EntityLinker

MODEL_VERSION_RULES = "rules-mvp-v1"


def run_extraction(
    scan_dir: str | Path,
    *,
    model_version: str = MODEL_VERSION_RULES,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    scan_path = Path(scan_dir).expanduser()
    coverage_path = scan_path / "coverage_summary.json"
    if not coverage_path.exists():
        raise FileNotFoundError(f"coverage_summary.json not found: {coverage_path}")
    coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
    extracted_dir = Path(output_dir).expanduser() if output_dir else scan_path / "extracted"
    extracted_dir.mkdir(parents=True, exist_ok=True)
    purge_stance_outputs(extracted_dir)

    docs: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for idx, team in enumerate(coverage.get("teams", []), start=1):
        if not is_eligible_team(team):
            continue
        try:
            doc, source_texts = extract_team_stance(coverage["scan_id"], team, model_version=model_version)
            errors = validate_stance_document(doc, source_texts=source_texts)
            if errors:
                failures.append({"analyst_id": team.get("analyst_id"), "errors": errors})
                continue
            out_path = extracted_dir / stance_filename(team, idx)
            out_path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            docs.append(document_summary(doc, out_path))
        except Exception as exc:  # pragma: no cover - surfaced in command output
            failures.append({"analyst_id": team.get("analyst_id"), "errors": [str(exc)]})

    summary = {
        "scan_id": coverage.get("scan_id"),
        "extracted_dir": str(extracted_dir),
        "eligible_count": sum(1 for team in coverage.get("teams", []) if is_eligible_team(team)),
        "written_count": len(docs),
        "failed_count": len(failures),
        "passed": not failures and bool(docs),
        "documents": docs,
        "quality": summarize_extraction_quality(docs),
        "failures": failures,
    }
    (extracted_dir / "extraction_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (extracted_dir / "extraction_report.md").write_text(render_extraction_report(summary), encoding="utf-8")
    return summary


def purge_stance_outputs(extracted_dir: Path) -> None:
    for path in extracted_dir.glob("*.stance.json"):
        path.unlink()


def is_eligible_team(team: dict[str, Any]) -> bool:
    return (
        team.get("coverage") in {"covered", "partial"}
        and team.get("text_access") in {"full_text", "partial_text"}
        and team.get("attribution_confidence") in {"high", "med"}
    )


def extract_team_stance(scan_id: str, team: dict[str, Any], *, model_version: str = MODEL_VERSION_RULES) -> tuple[dict[str, Any], dict[str, str]]:
    source_texts: dict[str, str] = {}
    sources: list[dict[str, Any]] = []
    for source in team.get("sources", []):
        if not is_extractable_source(source):
            continue
        content_path = source.get("content_path")
        if not content_path:
            continue
        article = parse_manual_wechat_article(content_path)
        text = article["body"]
        source_id = source["id"]
        source_texts[source_id] = text
        sources.append(
            {
                "id": source_id,
                "title": source.get("title") or article["metadata"].get("title"),
                "date": source.get("published_at") or article["metadata"].get("published_at"),
                "source": source.get("source"),
                "source_type": source.get("source_type"),
                "canonical_url": source.get("canonical_url"),
                "tier": source.get("tier"),
                "evidence_type": source.get("evidence_type"),
                "matched_entities": source.get("matched_entities", []),
                "found_by": source.get("found_by", []),
                "url": source.get("url") or article["metadata"].get("url"),
                "adapter_mode": source.get("adapter_mode"),
            }
        )

    combined_text = "\n".join(source_texts.values())
    doc = {
        "scan_id": scan_id,
        "schema_version": 1,
        "model_version": model_version,
        "mode": team.get("mode"),
        "institution": team.get("institution"),
        "role": team.get("role"),
        "analyst_id": team.get("analyst_id"),
        "team_members": team.get("team_members", []),
        "window": team.get("window"),
        "coverage": team.get("coverage"),
        "text_access": team.get("text_access"),
        "attribution_confidence": team.get("attribution_confidence"),
        "dimensions": extract_dimensions(team.get("role"), combined_text, source_texts),
        "selections": extract_selections(team.get("role"), combined_text, source_texts),
        "intra_window_changes": [],
        "sources": sources,
    }
    return doc, source_texts


def is_extractable_source(source: dict[str, Any]) -> bool:
    text_access = source.get("text_access")
    return text_access in {None, "", "full_text", "partial_text"}


def extract_dimensions(role: str, text: str, source_texts: dict[str, str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for dim_key, dim_def in dimensions_for_role(role).items():
        base = {
            "type": dim_def["type"],
            "axis": dim_def["axis"],
            "value": None,
            "label": None,
            "confidence": None,
            "evidence_ref": [],
            "verbatim": None,
        }
        if dim_def["type"] == "ordinal":
            stance = infer_ordinal(role, dim_key, text, source_texts)
            if stance:
                value, evidence_ref, verbatim, confidence, evidence_span = stance
                base.update(
                    {
                        "value": value,
                        "label": dim_def["values"][value],
                        "confidence": confidence,
                        "evidence_ref": [evidence_ref],
                        "verbatim": verbatim,
                        "evidence_span": evidence_span,
                    }
                )
        out[dim_key] = base
    return out


def infer_ordinal(role: str, dim_key: str, text: str, source_texts: dict[str, str]) -> tuple[int, str, str, str, dict[str, Any]] | None:
    if role == "macro":
        rules = {
            "growth": [
                (0, ["大致中性", "中性"], "med"),
                (1, ["景气度触底", "边际改善", "改善", "修复", "复苏", "创年内新高"], "med"),
                (-1, ["回落", "放缓", "走弱", "下探"], "med"),
            ],
            "inflation": [
                (1, ["PPI回升", "PPI快速上行", "通胀再临", "价格抬升", "通胀上行", "价格上行"], "med"),
                (-1, ["PPI回落", "价格回落", "通胀下行"], "med"),
            ],
            "monetary": [
                (-1, ["投放收敛", "利率是否超预期波动", "央行态度已发生变化", "删掉降准降息"], "med"),
                (1, ["流动性双宽松", "适度宽松", "降准", "降息"], "med"),
            ],
            "fiscal": [
                (1, ["财政发力", "政策性金融工具", "扩内需", "结构性工具"], "med"),
                (-1, ["财政收缩", "财政换挡", "支出放缓"], "med"),
            ],
            "overseas": [
                (-1, ["外部环境短期变化超预期", "地缘政治风险", "海外风险"], "low"),
                (1, ["外部环境改善", "海外缓和"], "low"),
            ],
        }
    else:
        rules = {
            "market_view": [
                (1, ["主要边际增量", "市场交易热度回升", "北上重新净买入"], "med"),
                (-1, ["交易扰动", "卖出力量", "谨慎偏空"], "med"),
                (0, ["中性"], "med"),
            ],
            "liquidity": [
                (-1, ["净买入幅度进一步放缓", "继续放缓", "净赎回"], "med"),
                (1, ["活跃度回升", "净流入", "净买入"], "med"),
                (0, ["中性"], "med"),
            ],
        }
    for value, phrases, confidence in rules.get(dim_key, []):
        found = find_evidence(phrases, source_texts)
        if found:
            source_id, verbatim, span = found
            return value, source_id, verbatim, confidence, span
    return None


def extract_selections(role: str, text: str, source_texts: dict[str, str]) -> list[dict[str, Any]]:
    if role != "strategy":
        return []
    linker = EntityLinker()
    selections: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for dim_key, tags in {
        "sector": ["电新", "电子", "通信", "公用事业", "军工", "食品饮料", "计算机", "医药", "有色", "石油石化"],
        "style": ["红利", "中证A500", "科创创业50", "沪深300", "创业板指", "中证500"],
        "theme": ["北上资金", "公募基金", "股票ETF", "两融"],
    }.items():
        for tag in tags:
            if tag not in text:
                continue
            lean = infer_selection_lean(tag, text)
            key = (dim_key, tag)
            if key in seen:
                continue
            seen.add(key)
            found = find_evidence([tag], source_texts)
            if not found:
                continue
            source_id, verbatim, span = found
            selections.append(
                {
                    "dim_key": dim_key,
                    "tag": tag,
                    "tag_canonical_id": linker.link(tag, dim_key),
                    "lean": lean,
                    "evidence_ref": [source_id],
                    "verbatim": verbatim,
                    "evidence_span": span,
                }
            )
    return selections


def infer_selection_lean(tag: str, text: str) -> int:
    positive_cues = ["净买入", "加仓", "被上调", "净申购", "回升", "增量"]
    negative_cues = ["净卖出", "减仓", "净赎回", "卖出力量"]
    for clause in split_clauses(text):
        if tag not in clause:
            continue
        idx = clause.index(tag)
        prefix = clause[:idx]
        suffix = clause[idx : idx + 40]
        positive_before = max(prefix.rfind(token) for token in positive_cues)
        negative_before = max(prefix.rfind(token) for token in negative_cues)
        if positive_before > negative_before and positive_before != -1:
            return 1
        if negative_before > positive_before and negative_before != -1:
            return -1
        if any(token in suffix for token in positive_cues):
            return 1
        if any(token in suffix for token in negative_cues):
            return -1
        if any(token in clause for token in ["交易热度", "活跃度"]) and any(token in clause for token in ["回升", "90%分位数", "相对较高"]):
            return 1
    return 0


def find_evidence(phrases: list[str], source_texts: dict[str, str]) -> tuple[str, str, dict[str, Any]] | None:
    for phrase in phrases:
        for source_id, text in source_texts.items():
            idx = text.find(phrase)
            if idx != -1:
                start, end = sentence_bounds(text, idx)
                sentence = text[start:end].strip()
                if len(sentence) > 120:
                    local_start = max(start, idx - 45)
                    local_end = min(end, idx + len(phrase) + 45)
                    sentence = text[local_start:local_end].strip()
                    start, end = local_start, local_end
                return source_id, sentence, {"source_id": source_id, "start": start, "end": end}
    return None


def sentence_bounds(text: str, idx: int) -> tuple[int, int]:
    left_marks = "。！？\n"
    right_marks = "。！？\n"
    start = idx
    while start > 0 and text[start - 1] not in left_marks:
        start -= 1
    end = idx
    while end < len(text) and text[end] not in right_marks:
        end += 1
    if end < len(text):
        end += 1
    return start, end


def split_sentences(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"[。！？\n]+", text) if item.strip()]


def split_clauses(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"[。！？；;，,\n]+", text) if item.strip()]


def stance_filename(team: dict[str, Any], index: int) -> str:
    return f"{team.get('role')}_{index:03d}_{team.get('institution')}.stance.json"


def count_non_null_dimensions(doc: dict[str, Any]) -> int:
    return sum(1 for item in doc.get("dimensions", {}).values() if item.get("value") is not None)


def non_null_dimension_keys(doc: dict[str, Any]) -> list[str]:
    return [key for key, item in doc.get("dimensions", {}).items() if item.get("value") is not None]


def document_summary(doc: dict[str, Any], path: Path) -> dict[str, Any]:
    return {
        "analyst_id": doc.get("analyst_id"),
        "role": doc.get("role"),
        "path": str(path),
        "text_access": doc.get("text_access"),
        "attribution_confidence": doc.get("attribution_confidence"),
        "source_types": sorted({source.get("source_type") or "unknown" for source in doc.get("sources", [])}),
        "dimensions_non_null": count_non_null_dimensions(doc),
        "non_null_dimensions": non_null_dimension_keys(doc),
        "selections": len(doc.get("selections", [])),
        "selection_counts_by_dim": selection_counts_by_dim(doc),
    }


def selection_counts_by_dim(doc: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for selection in doc.get("selections", []):
        dim_key = str(selection.get("dim_key") or "")
        if dim_key:
            counts[dim_key] = counts.get(dim_key, 0) + 1
    return dict(sorted(counts.items()))


def summarize_extraction_quality(documents: list[dict[str, Any]]) -> dict[str, Any]:
    zero_signal = [
        item["analyst_id"]
        for item in documents
        if int(item.get("dimensions_non_null") or 0) == 0 and int(item.get("selections") or 0) == 0
    ]
    dimension_counts: dict[str, dict[str, int]] = {}
    categorical_counts: dict[str, dict[str, int]] = {}
    for role in ["macro", "strategy"]:
        dim_defs = dimensions_for_role(role)
        dimension_counts[role] = {key: 0 for key, dim_def in dim_defs.items() if dim_def["type"] == "ordinal"}
        categorical_counts[role] = {key: 0 for key, dim_def in dim_defs.items() if dim_def["type"] == "categorical"}

    source_type_counts: dict[str, int] = {}
    for item in documents:
        role = str(item.get("role") or "")
        if role in dimension_counts:
            for dim_key in item.get("non_null_dimensions", []):
                dimension_counts[role][dim_key] = dimension_counts[role].get(dim_key, 0) + 1
        if role in categorical_counts:
            for dim_key, count in (item.get("selection_counts_by_dim") or {}).items():
                if dim_key in categorical_counts[role]:
                    categorical_counts[role][dim_key] = categorical_counts[role].get(dim_key, 0) + int(count)
        for source_type in item.get("source_types", []) or ["unknown"]:
            source_type_counts[source_type] = source_type_counts.get(source_type, 0) + 1

    return {
        "documents_with_any_signal": len(documents) - len(zero_signal),
        "zero_signal_documents": zero_signal,
        "dimension_non_null_counts": dimension_counts,
        "categorical_selection_counts": categorical_counts,
        "source_type_counts": dict(sorted(source_type_counts.items())),
    }


def render_extraction_report(summary: dict[str, Any]) -> str:
    quality = summary.get("quality", {})
    lines = [
        f"# Extraction Report: {summary['scan_id']}",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| eligible_count | {summary['eligible_count']} |",
        f"| written_count | {summary['written_count']} |",
        f"| failed_count | {summary['failed_count']} |",
        f"| documents_with_any_signal | {quality.get('documents_with_any_signal', 0)} |",
        f"| passed | {'yes' if summary['passed'] else 'no'} |",
        "",
        "## Quality Summary",
        "",
        f"- 零抽取样本：{', '.join(quality.get('zero_signal_documents') or []) if quality.get('zero_signal_documents') else '无'}",
        f"- 来源类型分布：{format_count_map(quality.get('source_type_counts') or {}) or '无'}",
        "- ordinal 非空维度覆盖：",
    ]
    for role, counts in (quality.get("dimension_non_null_counts") or {}).items():
        lines.append(f"  - {role}: {format_count_map(counts)}")
    lines.append("- categorical selection 覆盖：")
    for role, counts in (quality.get("categorical_selection_counts") or {}).items():
        lines.append(f"  - {role}: {format_count_map(counts) or '无'}")
    lines.extend(
        [
        "",
        "## Documents",
        "",
        "| analyst_id | role | text_access | source_types | non_null_dimensions | selections | path |",
        "|---|---|---|---|---|---:|---|",
        ]
    )
    for item in summary["documents"]:
        lines.append(
            "| {analyst_id} | {role} | {text_access} | {source_types} | {dims} | {selections} | {path} |".format(
                analyst_id=item["analyst_id"],
                role=item.get("role") or "",
                text_access=item.get("text_access") or "",
                source_types=", ".join(item.get("source_types") or []),
                dims=", ".join(item.get("non_null_dimensions") or []) or "无",
                selections=item["selections"],
                path=item["path"],
            )
        )
    if not summary["documents"]:
        lines.append("|  |  |  |  |  |  |  |")
    if summary["failures"]:
        lines.extend(["", "## Failures", ""])
        for failure in summary["failures"]:
            lines.append(f"- {failure['analyst_id']}: {'; '.join(failure['errors'])}")
    return "\n".join(lines) + "\n"


def format_count_map(counts: dict[str, int]) -> str:
    return ", ".join(f"{key}={value}" for key, value in counts.items())
