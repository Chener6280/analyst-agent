from __future__ import annotations

import json
from pathlib import Path

from core.retrieval.extract import document_summary, extract_team_stance, find_evidence, run_extraction
from core.schema.stance import validate_stance_document


def write_manual_article(path: Path, *, role: str, analyst_id: str, institution: str, account_name: str, body: str) -> None:
    member = "郭磊" if role == "macro" else "牟一凌"
    path.write_text(
        "\n".join(
            [
                "---",
                f'title: "{institution}测试观点"',
                f'url: "https://example.com/{analyst_id}"',
                'published_at: "2026-06-02"',
                f'account_name: "{account_name}"',
                f'institution: "{institution}"',
                f'role: "{role}"',
                f'analyst_id: "{analyst_id}"',
                "team_members:",
                f'  - "{member}"',
                "---",
                "",
                body,
                "",
            ]
        ),
        encoding="utf-8",
    )


def team_record(path: Path, *, role: str, analyst_id: str, institution: str) -> dict:
    member = "郭磊" if role == "macro" else "牟一凌"
    return {
        "scan_id": "manual-2026-06-01-2026-06-07-v1",
        "mode": "manual",
        "window": {"start": "2026-06-01", "end": "2026-06-07", "iso_year": 2026, "iso_week": 23},
        "institution": institution,
        "role": role,
        "analyst_id": analyst_id,
        "team_members": [member],
        "coverage": "covered",
        "text_access": "partial_text",
        "attribution_confidence": "med",
        "sources": [
            {
                "id": "s1",
                "title": f"{institution}测试观点",
                "url": f"https://example.com/{analyst_id}",
                "source": "manual_wechat",
                "source_type": "official_wechat",
                "published_at": "2026-06-02",
                "adapter_mode": "live",
                "content_path": str(path),
            }
        ],
    }


def test_macro_extraction_uses_null_for_unmentioned_dimensions(tmp_path: Path) -> None:
    article = tmp_path / "macro.md"
    write_manual_article(
        article,
        role="macro",
        analyst_id="华创证券:macro",
        institution="华创证券",
        account_name="一瑜中的",
        body="文章提示央行态度已发生变化，后续关注银行间资金利率是否超预期波动。",
    )
    doc, source_texts = extract_team_stance(
        "manual-2026-06-01-2026-06-07-v1",
        team_record(article, role="macro", analyst_id="华创证券:macro", institution="华创证券"),
    )
    assert doc["dimensions"]["monetary"]["value"] == -1
    assert doc["dimensions"]["growth"]["value"] is None
    assert doc["dimensions"]["growth"]["label"] is None
    assert validate_stance_document(doc, source_texts) == []


def test_strategy_extraction_links_selections_and_evidence(tmp_path: Path) -> None:
    article = tmp_path / "strategy.md"
    write_manual_article(
        article,
        role="strategy",
        analyst_id="国金证券:strategy",
        institution="国金证券",
        account_name="一凌策略研究",
        body="北上资金与公募基金阶段成为市场的主要边际增量。两融主要净买入电子、通信等板块，主要净卖出食品饮料等板块。个人投资者的净买入幅度进一步放缓。",
    )
    doc, source_texts = extract_team_stance(
        "manual-2026-06-01-2026-06-07-v1",
        team_record(article, role="strategy", analyst_id="国金证券:strategy", institution="国金证券"),
    )
    assert doc["dimensions"]["market_view"]["value"] == 1
    assert doc["dimensions"]["liquidity"]["value"] == -1
    by_tag = {item["tag"]: item for item in doc["selections"]}
    assert by_tag["电子"]["tag_canonical_id"] == "INDUSTRY:电子"
    assert by_tag["食品饮料"]["lean"] == -1
    summary = document_summary(doc, tmp_path / "strategy.stance.json")
    assert summary["selection_counts_by_dim"]["sector"] == 3
    assert summary["selection_counts_by_dim"]["theme"] == 3
    assert validate_stance_document(doc, source_texts) == []


def test_run_extraction_writes_valid_json(tmp_path: Path) -> None:
    article = tmp_path / "macro.md"
    write_manual_article(
        article,
        role="macro",
        analyst_id="广发证券:macro",
        institution="广发证券",
        account_name="郭磊宏观茶座",
        body="5月经济表现大致中性，建筑业景气度触底。",
    )
    scan_dir = tmp_path / "scan"
    scan_dir.mkdir()
    coverage = {
        "scan_id": "manual-2026-06-01-2026-06-07-v1",
        "summary": {},
        "teams": [team_record(article, role="macro", analyst_id="广发证券:macro", institution="广发证券")],
    }
    (scan_dir / "coverage_summary.json").write_text(json.dumps(coverage, ensure_ascii=False), encoding="utf-8")
    summary = run_extraction(scan_dir)
    assert summary["passed"] is True
    out_path = Path(summary["documents"][0]["path"])
    assert out_path.exists()
    written = json.loads(out_path.read_text(encoding="utf-8"))
    assert written["dimensions"]["growth"]["value"] == 0
    assert written["sources"][0]["source_type"] == "official_wechat"
    assert summary["quality"]["documents_with_any_signal"] == 1
    assert summary["quality"]["source_type_counts"] == {"official_wechat": 1}
    report = (scan_dir / "extracted" / "extraction_report.md").read_text(encoding="utf-8")
    assert "## Quality Summary" in report
    assert "source_types" in report


def test_extraction_skips_non_text_sources_without_front_matter(tmp_path: Path) -> None:
    article = tmp_path / "macro.md"
    cache_summary = tmp_path / "team_cache.md"
    write_manual_article(
        article,
        role="macro",
        analyst_id="兴业证券:macro",
        institution="兴业证券",
        account_name="段超宏观研究",
        body="信贷延续较弱，等待政策呵护。后续财政发力。",
    )
    cache_summary.write_text("# Search Cache\n\n- metadata-only row\n", encoding="utf-8")
    team = team_record(article, role="macro", analyst_id="兴业证券:macro", institution="兴业证券")
    team["text_access"] = "full_text"
    team["attribution_confidence"] = "high"
    team["sources"].append(
        {
            "id": "s2",
            "title": "只有元数据的文章",
            "url": "https://example.com/meta",
            "source": "wechat_opencli",
            "source_type": "official_wechat",
            "published_at": "2026-06-02",
            "adapter_mode": "live",
            "text_access": "metadata_only",
            "content_path": str(cache_summary),
        }
    )

    doc, source_texts = extract_team_stance("2026-W24-full-v2", team)

    assert list(source_texts) == ["s1"]
    assert [source["id"] for source in doc["sources"]] == ["s1"]
    assert doc["dimensions"]["fiscal"]["value"] == 1


def test_run_extraction_removes_stale_stance_json(tmp_path: Path) -> None:
    article = tmp_path / "macro.md"
    write_manual_article(
        article,
        role="macro",
        analyst_id="广发证券:macro",
        institution="广发证券",
        account_name="郭磊宏观茶座",
        body="5月经济表现大致中性，建筑业景气度触底。",
    )
    scan_dir = tmp_path / "scan"
    extracted_dir = scan_dir / "extracted"
    extracted_dir.mkdir(parents=True)
    stale_path = extracted_dir / "strategy_999_旧样本.stance.json"
    stale_path.write_text('{"scan_id": "old"}', encoding="utf-8")
    coverage = {
        "scan_id": "manual-2026-06-01-2026-06-07-v1",
        "summary": {},
        "teams": [team_record(article, role="macro", analyst_id="广发证券:macro", institution="广发证券")],
    }
    (scan_dir / "coverage_summary.json").write_text(json.dumps(coverage, ensure_ascii=False), encoding="utf-8")

    summary = run_extraction(scan_dir)

    assert summary["written_count"] == 1
    assert not stale_path.exists()
    stance_paths = sorted(extracted_dir.glob("*.stance.json"))
    assert len(stance_paths) == 1
    assert "广发证券" in stance_paths[0].name


def test_find_evidence_returns_sentence_span_not_keyword_only() -> None:
    text = "前文。5月PMI环比回升，显示生产和需求均有边际改善。后文。"
    found = find_evidence(["边际改善"], {"s1": text})

    assert found is not None
    source_id, verbatim, span = found
    assert source_id == "s1"
    assert "5月PMI环比回升" in verbatim
    assert verbatim != "边际改善"
    assert text[span["start"] : span["end"]].strip() == verbatim
