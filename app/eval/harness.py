"""Evaluation harness: Recall@k and hybrid vs vector-only vs FTS-only ablation.

SPEC.md Section 13:
  - Recall@3 ≥ 0.80 on the seed eval set
  - Hybrid retrieval must beat both vector-only and keyword-only
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.core.normalize import normalize_text
from app.logging import logger
from app.memory.retrieval import HybridRetrievalEngine
from app.models import Cue

EVAL_CASES_PATH = Path(__file__).parent.parent.parent / "eval" / "cases.jsonl"


# ──────────────────────────────────────────────────────────────
# Load eval cases
# ──────────────────────────────────────────────────────────────

def load_cases(path: Path | None = None) -> list[dict[str, Any]]:
    """Load evaluation cases from cases.jsonl.

    Each line: {"query": "...", "expected_ids": ["INC-xxx", ...], "services": [...]}
    """
    p = path or EVAL_CASES_PATH
    if not p.exists():
        logger.warning("eval_cases_not_found", path=str(p))
        return []
    cases = []
    with p.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


# ──────────────────────────────────────────────────────────────
# Recall@k metric
# ──────────────────────────────────────────────────────────────

def recall_at_k(returned_ids: list[str], expected_ids: list[str], k: int) -> float:
    """Recall@k = |returned[:k] ∩ expected| / |expected|."""
    if not expected_ids:
        return 1.0
    top_k = set(returned_ids[:k])
    expected = set(expected_ids)
    return len(top_k & expected) / len(expected)


# ──────────────────────────────────────────────────────────────
# Run evaluation
# ──────────────────────────────────────────────────────────────

def run_eval(
    cases: list[dict[str, Any]] | None = None,
    k: int = 3,
    ablation: bool = True,
) -> dict[str, Any]:
    """
    Run retrieval evaluation and optional ablation.

    Returns:
      {
        "hybrid": {"recall@k": 0.85, "per_case": [...]},
        "vector_only": {"recall@k": 0.70},   # only if ablation=True
        "fts_only":    {"recall@k": 0.62},   # only if ablation=True
        "beats_vector": True,
        "beats_fts":    True,
        "k": 3,
        "n_cases": 12,
      }
    """
    if cases is None:
        cases = load_cases()

    if not cases:
        return {"error": "no eval cases found", "k": k, "n_cases": 0}

    engine = HybridRetrievalEngine()

    def _score_mode(mode: str) -> tuple[float, list[dict[str, Any]]]:
        scores = []
        per_case = []
        for case in cases:
            query = case["query"]
            expected = case.get("expected_ids", [])
            services = case.get("services", [])

            cue = Cue(
                normalized_text=normalize_text(query),
                alert_text=query,
                services=services,
                error_messages=[],
            )
            try:
                result = engine.recall(cue, top_k=k, ablation_mode=mode if mode != "hybrid" else None)
                returned = [si.id for si in result.incidents]
            except Exception as exc:
                logger.warning("eval_recall_failed", mode=mode, error=str(exc))
                returned = []

            r = recall_at_k(returned, expected, k)
            scores.append(r)
            per_case.append({
                "query": query[:80],
                "expected": expected,
                "returned": returned,
                f"recall@{k}": r,
            })
        avg = sum(scores) / len(scores) if scores else 0.0
        return avg, per_case

    hybrid_score, hybrid_per = _score_mode("hybrid")
    result: dict[str, Any] = {
        "k": k,
        "n_cases": len(cases),
        "hybrid": {f"recall@{k}": round(hybrid_score, 4), "per_case": hybrid_per},
    }

    if ablation:
        vec_score, _ = _score_mode("vector")
        fts_score, _ = _score_mode("fts")
        result["vector_only"] = {f"recall@{k}": round(vec_score, 4)}
        result["fts_only"] = {f"recall@{k}": round(fts_score, 4)}
        result["beats_vector"] = hybrid_score > vec_score
        result["beats_fts"] = hybrid_score > fts_score

    result["pass"] = hybrid_score >= 0.80
    logger.info(
        "eval_complete",
        hybrid_recall=hybrid_score,
        k=k,
        n_cases=len(cases),
        passed=result["pass"],
    )
    return result
