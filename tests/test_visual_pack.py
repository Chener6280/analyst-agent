from __future__ import annotations

import json
from pathlib import Path

from core.history.timeseries import build_history_readiness
from core.store.db import ingest_scan
from core.store.queries import build_cross_section
from core.visual.charts import build_visual_pack, render_macro_consensus_svg, render_strategy_sector_svg
from scripts.export_history_readiness import render_markdown as render_history_markdown
from scripts.export_visual_pack import render_markdown
from scripts.generate_weekly_brief import build_brief
from tests.test_aggregation import write_scan


def prepare_visual_inputs(tmp_path: Path) -> tuple[str, Path, Path]:
    scan_id = "manual-2026-06-01-2026-06-07-v1"
    output_root = tmp_path / "out"
    scan_dir = output_root / "scans" / scan_id
    reports_dir = scan_dir / "reports"
    diagnostics_dir = output_root / "diagnostics"
    write_scan(scan_dir)
    db_path = tmp_path / "views.db"
    ingest_scan(scan_dir, db_path=db_path)

    reports_dir.mkdir(parents=True)
    cross_section = build_cross_section(scan_id, db_path=str(db_path))
    (reports_dir / "weekly_cross_section.json").write_text(json.dumps(cross_section, ensure_ascii=False), encoding="utf-8")
    (reports_dir / "weekly_cross_section.md").write_text("# cross section\n", encoding="utf-8")
    diagnostics_dir.mkdir(parents=True)
    (diagnostics_dir / f"{scan_id}__mvp_acceptance.json").write_text(
        json.dumps({"passed": True, "quality_warnings": []}),
        encoding="utf-8",
    )
    brief = build_brief(scan_dir, diagnostics_dir=diagnostics_dir)
    (reports_dir / "weekly_brief.json").write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")
    (reports_dir / "weekly_brief.md").write_text("# brief\n", encoding="utf-8")
    history = build_history_readiness(scan_id, db_path=db_path)
    (reports_dir / "history_readiness.json").write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")
    (reports_dir / "history_readiness.md").write_text(render_history_markdown(history), encoding="utf-8")
    return scan_id, output_root, db_path


def test_visual_pack_writes_svg_assets_and_markdown_index(tmp_path: Path) -> None:
    scan_id, output_root, db_path = prepare_visual_inputs(tmp_path)

    pack = build_visual_pack(scan_id, output_root=output_root, db_path=db_path)
    text = render_markdown(pack)

    assert pack["status"] == "ready"
    assert pack["history_status"] == "insufficient_history"
    assert len(pack["visuals"]) == 3
    assert "## Visuals" in text
    for item in pack["visuals"]:
        path = Path(item["path"])
        assert path.exists()
        assert path.read_text(encoding="utf-8").startswith("<svg")


def test_svg_renderers_escape_text_and_handle_empty_inputs() -> None:
    macro_svg = render_macro_consensus_svg([{"name": "增长<&", "n_non_null": 0, "n_teams": 1, "summary": "无"}])
    sector_svg = render_strategy_sector_svg([])

    assert "增长&lt;&amp;" in macro_svg
    assert "no sector tags" in sector_svg
