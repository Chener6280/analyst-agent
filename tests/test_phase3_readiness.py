from __future__ import annotations

import json
from pathlib import Path

from scripts.check_phase3_readiness import build_readiness, duplicate_values
from tests.test_store import make_doc


SCAN_ID = "manual-2026-06-01-2026-06-07-v1"


def write_phase3_scan(scan_dir: Path, *, extraction_scan_id: str = SCAN_ID, doc_scan_id: str = SCAN_ID) -> None:
    extracted = scan_dir / "extracted"
    extracted.mkdir(parents=True)
    article_path = scan_dir / "source.md"
    article_path.write_text(
        "\n".join(
            [
                "---",
                'title: "测试来源"',
                'url: "https://example.com/source"',
                'published_at: "2026-06-02"',
                'account_name: "广发证券"',
                'institution: "广发证券"',
                'role: "macro"',
                'analyst_id: "广发证券:macro"',
                "team_members:",
                '  - "测试"',
                "---",
                "",
                "测试证据",
                "",
            ]
        ),
        encoding="utf-8",
    )
    doc = make_doc(analyst_id="广发证券:macro", institution="广发证券", role="macro", dim_values={"growth": 1})
    doc["scan_id"] = doc_scan_id
    (extracted / "macro_001_广发证券.stance.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    (extracted / "extraction_summary.json").write_text(
        json.dumps({"scan_id": extraction_scan_id, "passed": True}, ensure_ascii=False),
        encoding="utf-8",
    )
    (scan_dir / "coverage_summary.json").write_text(
        json.dumps(
            {
                "scan_id": SCAN_ID,
                "teams": [
                    {
                        "analyst_id": "广发证券:macro",
                        "coverage": "covered",
                        "text_access": "partial_text",
                        "attribution_confidence": "med",
                        "sources": [
                            {
                                "id": "s1",
                                "source": "manual_wechat",
                                "content_path": str(article_path),
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_duplicate_values() -> None:
    assert duplicate_values(["a", "b", "a", None, None]) == ["None", "a"]


def test_phase3_readiness_passes_matching_scan_ids(tmp_path: Path) -> None:
    write_phase3_scan(tmp_path)

    result = build_readiness(tmp_path)

    assert result["ready"] is True
    assert result["global_errors"] == []


def test_phase3_readiness_fails_extraction_summary_scan_mismatch(tmp_path: Path) -> None:
    write_phase3_scan(tmp_path, extraction_scan_id="other")

    result = build_readiness(tmp_path)

    assert result["ready"] is False
    assert "extraction_summary scan_id does not match coverage scan_id" in result["global_errors"]


def test_phase3_readiness_fails_stance_doc_scan_mismatch(tmp_path: Path) -> None:
    write_phase3_scan(tmp_path, doc_scan_id="other")

    result = build_readiness(tmp_path)

    assert result["ready"] is False
    assert any("stance JSON scan_id mismatch" in error for error in result["global_errors"])


def test_phase3_readiness_fails_duplicate_analyst_docs(tmp_path: Path) -> None:
    write_phase3_scan(tmp_path)
    first = tmp_path / "extracted" / "macro_001_广发证券.stance.json"
    duplicate = tmp_path / "extracted" / "macro_999_广发证券.stance.json"
    duplicate.write_text(first.read_text(encoding="utf-8"), encoding="utf-8")

    result = build_readiness(tmp_path)

    assert result["ready"] is False
    assert "duplicate stance JSON analyst_id: 广发证券:macro" in result["global_errors"]
