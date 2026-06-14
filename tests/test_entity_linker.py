from __future__ import annotations

from pathlib import Path

from core.vocab.entity_link import EntityLinker


def test_entity_linker_reads_ir_search_entity_schema(tmp_path: Path) -> None:
    entities = tmp_path / "entities"
    entities.mkdir()
    (entities / "a_share_companies.csv").write_text(
        "\n".join(
            [
                "canonical_id,names,aliases,codes,market,related_terms",
                "300750.SZ,宁德时代|CATL,宁德|时代新能源,300750|300750.SZ,A_SHARE,动力电池|储能",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (entities / "industry_terms.csv").write_text(
        "\n".join(
            [
                "canonical_id,names,aliases,codes,market,related_terms",
                "INDUSTRY:光模块,光模块|optical module,光通信模块|transceiver,,INDUSTRY,800G|CPO",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    linker = EntityLinker(ir_search_entities_dir=entities, pending_path=tmp_path / "pending.jsonl")

    assert linker.link("宁德时代") == "300750.SZ"
    assert linker.link("300750") == "300750.SZ"
    assert linker.link("动力电池") == "300750.SZ"
    assert linker.link("光通信模块", "sector") == "INDUSTRY:光模块"


def test_entity_linker_keeps_sample_terms_as_fallback(tmp_path: Path) -> None:
    entities = tmp_path / "entities"
    entities.mkdir()
    linker = EntityLinker(ir_search_entities_dir=entities, pending_path=tmp_path / "pending.jsonl")

    assert linker.link("电子", "sector") == "INDUSTRY:电子"
