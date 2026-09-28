"""Tests for the evaluation harness and ablation metrics."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from app.eval.harness import load_cases, recall_at_k, run_eval


def test_recall_at_k_calculation() -> None:
    # 2 hits out of 2 expected in top 3
    assert recall_at_k(["A", "B", "C"], ["A", "B"], k=3) == 1.0
    # 1 hit out of 2 expected in top 2
    assert recall_at_k(["A", "C"], ["A", "B"], k=2) == 0.5
    # 0 hits
    assert recall_at_k(["X", "Y"], ["A", "B"], k=2) == 0.0
    # empty expected
    assert recall_at_k(["A"], [], k=1) == 1.0


def test_load_cases(tmp_path: Path) -> None:
    cases_file = tmp_path / "cases.jsonl"
    cases_file.write_text(
        json.dumps({"query": "q1", "expected_ids": ["INC-1"], "services": ["s1"]}) + "\n"
        + json.dumps({"query": "q2", "expected_ids": ["INC-2"], "services": []}) + "\n"
    )
    cases = load_cases(cases_file)
    assert len(cases) == 2
    assert cases[0]["query"] == "q1"
    assert cases[1]["expected_ids"] == ["INC-2"]


def test_load_cases_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist.jsonl"
    cases = load_cases(missing)
    assert cases == []


def test_run_eval_empty_cases() -> None:
    res = run_eval(cases=[], k=3, ablation=False)
    assert "error" in res
    assert res["n_cases"] == 0


def test_run_eval_mocked_engine() -> None:
    mock_case = [{"query": "database error", "expected_ids": ["INC-001"], "services": ["db"]}]

    mock_incident = MagicMock()
    mock_incident.id = "INC-001"
    mock_result = MagicMock()
    mock_result.incidents = [mock_incident]

    with patch("app.eval.harness.HybridRetrievalEngine") as mock_engine_cls:
        engine_instance = mock_engine_cls.return_value
        engine_instance.recall.return_value = mock_result

        res = run_eval(cases=mock_case, k=3, ablation=True)
        assert res["pass"] is True
        assert res["hybrid"]["recall@3"] == 1.0
        assert "vector_only" in res
        assert "fts_only" in res
