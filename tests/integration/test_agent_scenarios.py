"""Integration tests: agent returns sensible heuristic analyses for all four mock scenarios."""
from __future__ import annotations

import pytest

from app.adapters.mock import MockCodeAdapter, MockDeployAdapter, MockLogAdapter, MockMetricsAdapter
from app.agent.investigate import _validate_citations, investigate
from app.models import Cue, RetrievalResult, ScoredIncident


def _make_si(inc_id: str, score: float, title: str = "Test", root_cause: str = "unknown",
             services: list[str] | None = None) -> ScoredIncident:
    return ScoredIncident(
        id=inc_id,
        title=title,
        final=score,
        score_breakdown={"vec": score, "fts": 0.0, "fp": 0.0, "svc": 0.0, "code": 0.0},
        matched_on=["vec"],
        flags=[],
        symptoms=["error"],
        root_cause=root_cause,
        resolution_steps=["check logs"],
        fix_worked=None,
        time_to_resolve_min=None,
        services=services or ["svc-a"],
    )


@pytest.mark.parametrize("scenario", [
    "A_pool_exhaustion",
    "B_cert_expiry",
    "C_novel",
    "D_lookalike_dns",
])
def test_scenario_returns_analysis(scenario: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MOCK_SCENARIO", scenario)
    from app.config import get_settings
    get_settings.cache_clear()

    retrieval = RetrievalResult(
        incidents=[
            _make_si("INC-001", 0.75, "DB pool exhausted", "Connection leak", ["payment-service"]),
            _make_si("INC-002", 0.55, "DNS failure", "kube-dns crash", ["order-service"]),
        ],
        patterns=[],
        runbooks=[],
    )
    cue = Cue(
        normalized_text="service degraded",
        alert_text="service degraded",
        services=["payment-service"],
        error_messages=["could not connect"],
    )
    analysis = investigate(
        f"INC-TEST-{scenario}", cue, retrieval,
        logs=MockLogAdapter(), metrics=MockMetricsAdapter(),
        deploys=MockDeployAdapter(), code=MockCodeAdapter(),
        llm_client=None,
    )
    assert analysis.summary
    assert analysis.precedent_strength in ("strong", "partial", "none")
    assert len(analysis.hypotheses) >= 1
    assert analysis.hypotheses[0].confidence in ("high", "medium", "low")


def test_scenario_c_novel_gets_no_precedent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Scenario C has no good precedents — precedent_strength must be none."""
    monkeypatch.setenv("MOCK_SCENARIO", "C_novel")
    from app.config import get_settings
    get_settings.cache_clear()

    retrieval = RetrievalResult(incidents=[], patterns=[], runbooks=[])
    cue = Cue(
        normalized_text="unknown latency spike",
        alert_text="recommendation-engine p99 jumped 10x",
        services=["recommendation-engine"],
        error_messages=["context deadline exceeded"],
    )
    analysis = investigate(
        "INC-TEST-C", cue, retrieval,
        logs=MockLogAdapter(), metrics=MockMetricsAdapter(),
        deploys=MockDeployAdapter(), code=MockCodeAdapter(),
        llm_client=None,
    )
    assert analysis.precedent_strength == "none"
    assert analysis.hypotheses[0].confidence == "low"
    # No citations when no incidents were recalled
    for h in analysis.hypotheses:
        assert h.similar_incidents == []


def test_no_hallucinated_citations() -> None:
    """Citations must only reference IDs present in retrieval."""
    retrieval = RetrievalResult(
        incidents=[_make_si("INC-REAL", 0.80)],
        patterns=[],
        runbooks=[],
    )
    raw = {
        "hypotheses": [
            {
                "similar_incidents": [
                    {"id": "INC-REAL", "why_similar": "x", "differences": "y"},
                    {"id": "INC-FAKE-HALLUCINATED", "why_similar": "z", "differences": ""},
                ],
                "runbook_id": "RB-ghost",
            }
        ],
        "dropped_citations": [],
    }
    out = _validate_citations(raw, retrieval)
    ids = [c["id"] for c in out["hypotheses"][0]["similar_incidents"]]
    assert "INC-REAL" in ids
    assert "INC-FAKE-HALLUCINATED" not in ids
    assert out["hypotheses"][0]["runbook_id"] is None
    assert "INC-FAKE-HALLUCINATED" in out["dropped_citations"]
    assert "RB-ghost" in out["dropped_citations"]
