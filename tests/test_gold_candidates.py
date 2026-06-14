from __future__ import annotations

import json
from pathlib import Path

from core.schema.stance import dimensions_for_role


def test_gold_candidates_are_inactive_and_schema_aligned() -> None:
    path = Path("tests/gold/extraction_gold_candidates_2026w24.jsonl")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    candidates = [row for row in rows if "_comment" not in row]

    assert len(candidates) == 5
    for row in candidates:
        assert "expected" not in row
        assert row["status"] == "candidate_needs_human_labels"
        ordinal_keys = {
            key
            for key, dim in dimensions_for_role(row["role"]).items()
            if dim["type"] == "ordinal"
        }
        assert set(row["expected_template"]) == ordinal_keys
