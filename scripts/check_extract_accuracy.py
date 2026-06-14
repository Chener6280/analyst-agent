#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.retrieval.extract import extract_team_stance
from scripts.diagnostic_io import write_diagnostic_pair

DEFAULT_GOLD = REPO_ROOT / "tests" / "gold" / "extraction_gold.jsonl"


def load_gold(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        row = json.loads(line)
        if "_comment" in row or "expected" not in row:
            continue
        entries.append(row)
    return entries


def write_manual_article(path: Path, entry: dict[str, Any]) -> None:
    member = entry.get("primary_member") or ("郭磊" if entry["role"] == "macro" else "牟一凌")
    path.write_text(
        "\n".join(
            [
                "---",
                f'title: "{entry["institution"]}观点"',
                f'url: "https://example.com/{entry["id"]}"',
                'published_at: "2026-06-02"',
                f'account_name: "{entry.get("account_name", "测试号")}"',
                f'institution: "{entry["institution"]}"',
                f'role: "{entry["role"]}"',
                f'analyst_id: "{entry["analyst_id"]}"',
                "team_members:",
                f'  - "{member}"',
                "---",
                "",
                entry["body"],
                "",
            ]
        ),
        encoding="utf-8",
    )


def team_record(content_path: Path, entry: dict[str, Any]) -> dict[str, Any]:
    member = entry.get("primary_member") or ("郭磊" if entry["role"] == "macro" else "牟一凌")
    return {
        "scan_id": "gold-eval",
        "mode": "manual",
        "window": {"start": "2026-06-01", "end": "2026-06-07", "iso_year": 2026, "iso_week": 23},
        "institution": entry["institution"],
        "role": entry["role"],
        "analyst_id": entry["analyst_id"],
        "team_members": [member],
        "coverage": "covered",
        "text_access": "full_text",
        "attribution_confidence": "high",
        "sources": [
            {
                "id": "s1",
                "title": f'{entry["institution"]}观点',
                "url": f'https://example.com/{entry["id"]}',
                "source": "manual_wechat",
                "source_type": "official_wechat",
                "published_at": "2026-06-02",
                "adapter_mode": "live",
                "content_path": str(content_path),
            }
        ],
    }


def sign(value: int | None) -> int | None:
    if value is None:
        return None
    return (value > 0) - (value < 0)


def score_entry(entry: dict[str, Any], model_version: str | None) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        article = Path(tmp) / f'{entry["id"]}.md'
        write_manual_article(article, entry)
        kwargs = {"model_version": model_version} if model_version else {}
        doc, _ = extract_team_stance("gold-eval", team_record(article, entry), **kwargs)

    dims = doc.get("dimensions", {})
    checks: list[dict[str, Any]] = []
    for dim_key, gold_value in entry["expected"].items():
        produced = dims.get(dim_key, {}).get("value") if dim_key in dims else "MISSING_DIM"
        flags: list[str] = []
        if produced != "MISSING_DIM":
            gold_sign = sign(gold_value)
            produced_sign = sign(produced if isinstance(produced, int) else None)
            if gold_sign is not None and produced_sign is not None and gold_sign != 0 and produced_sign != 0 and gold_sign != produced_sign:
                flags.append("sign_reversal")
            if gold_value is None and produced is not None:
                flags.append("false_stance")
            if gold_value is not None and produced is None:
                flags.append("missed_stance")
        checks.append(
            {
                "dim": dim_key,
                "gold": gold_value,
                "produced": produced,
                "outcome": "correct" if produced == gold_value else "wrong",
                "flags": flags,
            }
        )
    return {"id": entry["id"], "role": entry["role"], "model_version": doc.get("model_version"), "checks": checks}


def evaluate(
    gold_path: Path,
    *,
    min_accuracy: float,
    max_false_stance: int,
    model_version: str | None,
) -> dict[str, Any]:
    entries = load_gold(gold_path)
    results = [score_entry(entry, model_version) for entry in entries]
    flat = [check for result in results for check in result["checks"]]
    total = len(flat)
    correct = sum(1 for check in flat if check["outcome"] == "correct")
    sign_reversals = sum(1 for check in flat if "sign_reversal" in check["flags"])
    false_stance = sum(1 for check in flat if "false_stance" in check["flags"])
    missed_stance = sum(1 for check in flat if "missed_stance" in check["flags"])
    accuracy = correct / total if total else 0.0
    seen_model = next((result["model_version"] for result in results if result["model_version"]), model_version)
    ready = total > 0 and accuracy >= min_accuracy and sign_reversals == 0 and false_stance <= max_false_stance
    return {
        "scan_id": None,
        "gold_path": str(gold_path),
        "model_version": seen_model,
        "annotated_dimensions": total,
        "ordinal_accuracy": round(accuracy, 4),
        "sign_reversals": sign_reversals,
        "false_stance": false_stance,
        "missed_stance": missed_stance,
        "thresholds": {
            "min_accuracy": min_accuracy,
            "max_false_stance": max_false_stance,
            "sign_reversals": 0,
        },
        "ready": ready,
        "results": results,
    }


def render_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Extract Accuracy Gate",
        "",
        f"- model_version: `{result['model_version']}`",
        f"- annotated_dimensions: {result['annotated_dimensions']}",
        f"- ordinal_accuracy: {result['ordinal_accuracy']} (threshold {result['thresholds']['min_accuracy']})",
        f"- sign_reversals: {result['sign_reversals']} (threshold 0)",
        f"- false_stance: {result['false_stance']} (threshold {result['thresholds']['max_false_stance']})",
        f"- missed_stance: {result['missed_stance']}",
        f"- ready: **{result['ready']}**",
        "",
        "| id | dim | gold | produced | flags |",
        "|---|---|---|---|---|",
    ]
    for result_item in result["results"]:
        for check in result_item["checks"]:
            lines.append(
                f"| {result_item['id']} | {check['dim']} | {check['gold']} | {check['produced']} | {','.join(check['flags']) or '-'} |"
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    args = parse_args()
    result = evaluate(
        Path(args.gold).expanduser(),
        min_accuracy=args.min_accuracy,
        max_false_stance=args.max_false_stance,
        model_version=args.model_version,
    )
    json_path, md_path, _, _ = write_diagnostic_pair(
        Path(args.diagnostics_dir).expanduser(),
        stem="extract_accuracy",
        scan_id=None,
        data=result,
        markdown=render_markdown(result),
    )
    print(f"extract_accuracy={md_path}")
    print(f"json={json_path}")
    print(f"ordinal_accuracy={result['ordinal_accuracy']} sign_reversals={result['sign_reversals']}")
    print(f"ready={result['ready']}")
    return 0 if result["ready"] else 1


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check ordinal extraction accuracy against a human gold set.")
    parser.add_argument("--gold", default=str(DEFAULT_GOLD))
    parser.add_argument("--diagnostics-dir", default="outputs/diagnostics")
    parser.add_argument("--min-accuracy", type=float, default=0.9)
    parser.add_argument("--max-false-stance", type=int, default=0)
    parser.add_argument("--model-version", default=None, help="Override extraction model_version for boundary checks.")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
