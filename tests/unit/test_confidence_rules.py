"""Tests for confidence rules and precedent_strength enforcement."""
from __future__ import annotations

from app.models import Cue, RetrievalResult, ScoredIncident


def _make_si(inc_id: str, final_score: float) -> ScoredIncident:
    return ScoredIncident(
        id=inc_id,
        title=f"Incident {inc_id}",
        final=final_score,
        score_breakdown={"vec": final_score, "fts": 0.0, "fp": 0.0, "svc": 0.0, "code": 0.0},
        matched_on=["vec"],
        flags=[],
        symptoms=["error"],
        root_cause="unknown cause",
        resolution_steps=["check logs"],
        fix_worked=None,
        time_to_resolve_min=None,
        services=["svc-a"],
    )


def _make_retrieval(scores: list[float]) -> RetrievalResult:
    return RetrievalResult(
        incidents=[_make_si(f"INC-{i:03d}", s) for i, s in enumerate(scores)],
        patterns=[],
        runbooks=[],
    )


# ── _apply_confidence_rules ───────────────────────────────────

def test_confidence_rules_high_score_preserved() -> None:
    from app.agent.investigate import _apply_confidence_rules

    retrieval = _make_retrieval([0.80, 0.72])
    raw: dict = {"hypotheses": [{"confidence": "high"}], "dropped_citations": []}
    out = _apply_confidence_rules(raw, retrieval)
    assert out["precedent_strength"] == "strong"
    assert out["hypotheses"][0]["confidence"] == "high"


def test_confidence_rules_high_capped_to_medium_on_partial() -> None:
    from app.agent.investigate import _apply_confidence_rules

    retrieval = _make_retrieval([0.55])
    raw: dict = {"hypotheses": [{"confidence": "high"}], "dropped_citations": []}
    out = _apply_confidence_rules(raw, retrieval)
    assert out["precedent_strength"] == "partial"
    assert out["hypotheses"][0]["confidence"] == "medium"


def test_confidence_rules_none_on_low_score() -> None:
    from app.agent.investigate import _apply_confidence_rules

    retrieval = _make_retrieval([0.20])
    raw: dict = {"hypotheses": [{"confidence": "high"}], "dropped_citations": []}
    out = _apply_confidence_rules(raw, retrieval)
    assert out["precedent_strength"] == "none"
    assert out["hypotheses"][0]["confidence"] == "low"


def test_confidence_rules_none_when_no_incidents() -> None:
    from app.agent.investigate import _apply_confidence_rules

    retrieval = _make_retrieval([])
    raw: dict = {"hypotheses": [{"confidence": "medium"}], "dropped_citations": []}
    out = _apply_confidence_rules(raw, retrieval)
    assert out["precedent_strength"] == "none"


# ── Heuristic fallback analysis ───────────────────────────────

def test_heuristic_fallback_high_confidence_for_strong_match() -> None:
    from app.adapters.mock import MockCodeAdapter, MockDeployAdapter, MockLogAdapter, MockMetricsAdapter
    from app.agent.investigate import investigate

    cue = Cue(
        normalized_text="db pool exhausted",
        alert_text="db pool exhausted",
        services=["payment-service"],
        error_messages=["pool exhausted"],
    )
    retrieval = _make_retrieval([0.85, 0.75])

    analysis = investigate(
        "INC-TEST-001", cue, retrieval,
        logs=MockLogAdapter(), metrics=MockMetricsAdapter(),
        deploys=MockDeployAdapter(), code=MockCodeAdapter(),
        llm_client=None,
    )
    assert analysis.precedent_strength == "strong"
    assert analysis.hypotheses[0].confidence == "high"


def test_heuristic_fallback_low_confidence_for_novel() -> None:
    from app.adapters.mock import MockCodeAdapter, MockDeployAdapter, MockLogAdapter, MockMetricsAdapter
    from app.agent.investigate import investigate

    cue = Cue(
        normalized_text="weird flapping",
        alert_text="weird flapping",
        services=["unknown-service"],
        error_messages=[],
    )
    retrieval = _make_retrieval([0.10])

    analysis = investigate(
        "INC-TEST-002", cue, retrieval,
        logs=MockLogAdapter(), metrics=MockMetricsAdapter(),
        deploys=MockDeployAdapter(), code=MockCodeAdapter(),
        llm_client=None,
    )
    assert analysis.precedent_strength == "none"
    assert analysis.hypotheses[0].confidence == "low"
