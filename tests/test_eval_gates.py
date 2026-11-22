# -*- coding: utf-8 -*-
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from backend.eval_gates import (
    _evaluate_text_item,
    get_default_gold_dataset,
    init_eval_db,
    list_eval_runs,
    get_eval_run,
    run_evaluation,
)


def test_eval_text_item_scoring():
    item = {
        "id": "t1",
        "min_length": 20,
        "max_length": 200,
        "expected_keywords": ["liquidität", "kosten"],
        "forbidden_patterns": ["in today's fast-paced world"],
        "min_score": 70.0,
    }

    # Gute Antwort
    res_good = _evaluate_text_item(
        item,
        "Wir sichern die Liquidität und senken operative Kosten nachhaltig.",
        latency_ms=120.0,
        cost_usd=0.0001,
    )
    assert res_good["passed"] is True
    assert res_good["score"] >= 80.0
    assert not res_good["failures"]

    # Schlechte Antwort mit verbotenem Slop
    res_bad = _evaluate_text_item(
        item,
        "In today's fast-paced world we delve into solutions without detail.",
        latency_ms=100.0,
        cost_usd=0.0001,
    )
    assert res_bad["passed"] is False
    assert any("Slop-Treffer" in f for f in res_bad["failures"])


def test_eval_gates_db_persistence(tmp_path):
    db = str(tmp_path / "test_eval.db")
    init_eval_db(db)

    custom_dataset = [
        {
            "id": "c1",
            "prompt": "Test Frage",
            "min_length": 5,
            "max_length": 500,
            "expected_keywords": ["test"],
            "min_score": 60.0,
        }
    ]

    async def _mock_dispatch(**kwargs):
        return {
            "status": "success",
            "content": "Dies ist ein erfolgreicher Test für die Validierung.",
            "input_tokens": 10,
            "output_tokens": 15,
        }

    with patch("core_dispatcher.dispatch_to_omniroute_or_container", side_effect=_mock_dispatch):
        import asyncio
        res = asyncio.run(run_evaluation("profile", "test_agent", gold_dataset=custom_dataset, db_path=db))

    assert res["status"] == "success"
    assert res["passed"] is True
    assert res["overall_score"] >= 80.0
    eval_id = res["eval_id"]

    # Aus DB lesen
    run_obj = get_eval_run(eval_id, db_path=db)
    assert run_obj is not None
    assert run_obj["target_id"] == "test_agent"
    assert run_obj["passed"] is True

    runs = list_eval_runs(target_id="test_agent", db_path=db)
    assert len(runs) >= 1
    assert runs[0]["id"] == eval_id
