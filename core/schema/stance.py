from __future__ import annotations

from pathlib import Path
from typing import Any

CONFIDENCE_VALUES = {"high", "med", "low"}
SCHEMA_VERSION = 1

MACRO_DIMENSIONS: dict[str, dict[str, Any]] = {
    "growth": {
        "name": "增长",
        "type": "ordinal",
        "axis": "增长改善为正",
        "values": {-2: "明显走弱", -1: "边际走弱", 0: "中性", 1: "边际改善", 2: "明显改善"},
    },
    "inflation": {
        "name": "通胀",
        "type": "ordinal",
        "axis": "通胀上行为正",
        "values": {-2: "明显下行", -1: "边际下行", 0: "中性", 1: "边际上行", 2: "明显上行"},
    },
    "monetary": {
        "name": "货币政策",
        "type": "ordinal",
        "axis": "宽松为正",
        "values": {-2: "明显收紧", -1: "边际收紧", 0: "中性", 1: "边际宽松", 2: "明显宽松"},
    },
    "fiscal": {
        "name": "财政政策",
        "type": "ordinal",
        "axis": "扩张为正",
        "values": {-2: "明显收缩", -1: "边际收缩", 0: "中性", 1: "边际扩张", 2: "明显扩张"},
    },
    "overseas": {
        "name": "海外环境",
        "type": "ordinal",
        "axis": "外部环境改善为正",
        "values": {-2: "明显恶化", -1: "边际恶化", 0: "中性", 1: "边际改善", 2: "明显改善"},
    },
}

STRATEGY_DIMENSIONS: dict[str, dict[str, Any]] = {
    "market_view": {
        "name": "市场整体观点",
        "type": "ordinal",
        "axis": "看多为正",
        "values": {-2: "明显看空", -1: "谨慎偏空", 0: "中性", 1: "谨慎偏多", 2: "明显看多"},
    },
    "sector": {"name": "板块配置", "type": "categorical", "axis": "推荐配置方向"},
    "style": {"name": "风格判断", "type": "categorical", "axis": "推荐风格方向"},
    "theme": {"name": "主题机会", "type": "categorical", "axis": "推荐主题方向"},
    "liquidity": {
        "name": "流动性",
        "type": "ordinal",
        "axis": "流动性改善为正",
        "values": {-2: "明显恶化", -1: "边际恶化", 0: "中性", 1: "边际改善", 2: "明显改善"},
    },
}


def dimensions_for_role(role: str) -> dict[str, dict[str, Any]]:
    if role == "macro":
        return MACRO_DIMENSIONS
    if role == "strategy":
        return STRATEGY_DIMENSIONS
    raise ValueError(f"unsupported role: {role}")


def validate_stance_document(doc: dict[str, Any], source_texts: dict[str, str] | None = None) -> list[str]:
    errors: list[str] = []
    required = [
        "scan_id",
        "schema_version",
        "model_version",
        "mode",
        "institution",
        "role",
        "analyst_id",
        "team_members",
        "window",
        "coverage",
        "text_access",
        "attribution_confidence",
        "dimensions",
        "selections",
        "intra_window_changes",
        "sources",
    ]
    for key in required:
        if key not in doc:
            errors.append(f"missing top-level field: {key}")
    if errors:
        return errors

    if doc["schema_version"] != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}")
    if doc["coverage"] not in {"covered", "partial"}:
        errors.append("coverage must be covered or partial for stance extraction")
    if doc["text_access"] not in {"full_text", "partial_text"}:
        errors.append("text_access must be full_text or partial_text")
    if doc["attribution_confidence"] not in {"high", "med"}:
        errors.append("attribution_confidence must be high or med")

    dim_defs = dimensions_for_role(str(doc["role"]))
    source_ids = {str(item.get("id")) for item in doc.get("sources", []) if item.get("id")}
    if set(doc["dimensions"].keys()) != set(dim_defs.keys()):
        errors.append("dimensions keys do not match role dimension definition")

    for dim_key, dim_def in dim_defs.items():
        item = doc["dimensions"].get(dim_key)
        if item is None:
            continue
        if item.get("type") != dim_def["type"]:
            errors.append(f"{dim_key}: type mismatch")
            continue
        if dim_def["type"] == "ordinal":
            errors.extend(_validate_ordinal_dimension(dim_key, item, dim_def, source_ids, source_texts))
        elif item.get("value") is not None:
            errors.append(f"{dim_key}: categorical dimensions must keep value=null")

    for idx, selection in enumerate(doc.get("selections", []), start=1):
        errors.extend(_validate_selection(idx, selection, dim_defs, source_ids, source_texts))

    return errors


def _validate_ordinal_dimension(
    dim_key: str,
    item: dict[str, Any],
    dim_def: dict[str, Any],
    source_ids: set[str],
    source_texts: dict[str, str] | None,
) -> list[str]:
    errors: list[str] = []
    value = item.get("value")
    if value is None:
        if item.get("label") is not None or item.get("confidence") is not None or item.get("evidence_ref") or item.get("verbatim") is not None:
            errors.append(f"{dim_key}: null value must have null label/confidence/verbatim and empty evidence_ref")
        return errors
    if value not in dim_def["values"]:
        errors.append(f"{dim_key}: invalid ordinal value {value}")
        return errors
    if item.get("label") != dim_def["values"][value]:
        errors.append(f"{dim_key}: label does not match value")
    errors.extend(_validate_evidence(dim_key, item, source_ids, source_texts))
    return errors


def _validate_selection(
    idx: int,
    selection: dict[str, Any],
    dim_defs: dict[str, dict[str, Any]],
    source_ids: set[str],
    source_texts: dict[str, str] | None,
) -> list[str]:
    label = f"selection[{idx}]"
    errors: list[str] = []
    dim_key = selection.get("dim_key")
    if dim_key not in dim_defs or dim_defs[dim_key]["type"] != "categorical":
        errors.append(f"{label}: invalid categorical dim_key")
    if not selection.get("tag"):
        errors.append(f"{label}: tag is required")
    if selection.get("lean") not in {-1, 0, 1}:
        errors.append(f"{label}: lean must be -1, 0, or 1")
    errors.extend(_validate_evidence(label, selection, source_ids, source_texts))
    return errors


def _validate_evidence(
    label: str,
    item: dict[str, Any],
    source_ids: set[str],
    source_texts: dict[str, str] | None,
) -> list[str]:
    errors: list[str] = []
    refs = item.get("evidence_ref") or []
    verbatim = item.get("verbatim")
    if not refs:
        errors.append(f"{label}: evidence_ref is required")
    if any(ref not in source_ids for ref in refs):
        errors.append(f"{label}: evidence_ref points to unknown source")
    if not verbatim:
        errors.append(f"{label}: verbatim is required")
    elif len(str(verbatim)) > 120:
        errors.append(f"{label}: verbatim must be <= 120 characters")
    elif source_texts is not None and not any(str(verbatim) in source_texts.get(ref, "") for ref in refs):
        errors.append(f"{label}: verbatim is not found in referenced source text")
    if item.get("confidence") is not None and item.get("confidence") not in CONFIDENCE_VALUES:
        errors.append(f"{label}: invalid confidence")
    return errors


def write_stance_json(path: str | Path, doc: dict[str, Any]) -> None:
    import json

    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
