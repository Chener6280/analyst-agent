from __future__ import annotations

import json
from pathlib import Path

from scripts.check_extract_accuracy import evaluate, load_gold, score_entry

GOLD = Path(__file__).resolve().parent / "gold" / "extraction_gold.jsonl"


def test_seed_gold_loads_and_skips_comment_lines() -> None:
    entries = load_gold(GOLD)
    assert entries
    assert all("expected" in entry for entry in entries)
    assert all("_comment" not in entry for entry in entries)


def test_harness_scores_correct_prediction_as_correct() -> None:
    entry = {
        "id": "t_dovish",
        "role": "macro",
        "analyst_id": "华创证券:macro",
        "institution": "华创证券",
        "account_name": "一瑜中的",
        "body": "文章提示央行态度已发生变化，后续关注银行间资金利率是否超预期波动。",
        "expected": {"monetary": -1, "growth": None},
    }

    result = score_entry(entry, None)
    checks = {check["dim"]: check for check in result["checks"]}

    assert checks["monetary"]["outcome"] == "correct"
    assert checks["growth"]["outcome"] == "correct"
    assert all(not check["flags"] for check in result["checks"])


def test_harness_flags_sign_reversal() -> None:
    entry = {
        "id": "t_reversal",
        "role": "macro",
        "analyst_id": "华创证券:macro",
        "institution": "华创证券",
        "account_name": "一瑜中的",
        "body": "文章提示央行态度已发生变化，后续关注银行间资金利率是否超预期波动。",
        "expected": {"monetary": 2},
    }

    result = score_entry(entry, None)

    assert "sign_reversal" in result["checks"][0]["flags"]


def test_gate_returns_not_ready_when_accuracy_below_threshold(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text(
        json.dumps(
            {
                "id": "x",
                "role": "macro",
                "analyst_id": "测试:macro",
                "institution": "测试",
                "body": "本周震荡为主。",
                "expected": {"monetary": 2},
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    result = evaluate(gold, min_accuracy=0.9, max_false_stance=0, model_version=None)

    assert result["ready"] is False
    assert result["ordinal_accuracy"] < 0.9
