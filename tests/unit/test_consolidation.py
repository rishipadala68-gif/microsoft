"""Tests for the nightly consolidation job."""
from __future__ import annotations

from app.jobs.consolidate import (
    cluster_incidents,
    recall_at_k_helper,
)

# ── cluster_incidents ─────────────────────────────────────────

def test_cluster_no_embeddings_groups_by_category() -> None:
    incidents = [
        {"id": "INC-001", "root_cause_category": "db", "emb_full": None},
        {"id": "INC-002", "root_cause_category": "db", "emb_full": None},
        {"id": "INC-003", "root_cause_category": "db", "emb_full": None},
        {"id": "INC-004", "root_cause_category": "network", "emb_full": None},
        {"id": "INC-005", "root_cause_category": "network", "emb_full": None},
        {"id": "INC-006", "root_cause_category": "network", "emb_full": None},
    ]
    clusters = cluster_incidents(incidents, distance_threshold=0.25, min_cluster=3)
    assert len(clusters) >= 2
    all_ids = {i for c in clusters for i in c}
    # All 6 incidents should appear in clusters (3 per category meets min_cluster=3)
    assert "INC-001" in all_ids
    assert "INC-004" in all_ids


def test_cluster_small_category_excluded() -> None:
    incidents = [
        {"id": "INC-001", "root_cause_category": "db", "emb_full": None},
        {"id": "INC-002", "root_cause_category": "db", "emb_full": None},
        {"id": "INC-003", "root_cause_category": "db", "emb_full": None},
        {"id": "INC-004", "root_cause_category": "rare", "emb_full": None},
        {"id": "INC-005", "root_cause_category": "rare", "emb_full": None},
        # only 2 in "rare" — below min_cluster=3
    ]
    clusters = cluster_incidents(incidents, min_cluster=3)
    all_ids = {i for c in clusters for i in c}
    assert "INC-001" in all_ids  # db cluster included
    assert "INC-004" not in all_ids  # rare cluster excluded


def test_cluster_with_embeddings() -> None:
    """Two tight groups via simple embeddings."""
    def _emb(val: float) -> list[float]:
        return [val] + [0.0] * 383

    incidents = [
        {"id": f"INC-A{i}", "root_cause_category": "a", "emb_full": _emb(1.0)} for i in range(4)
    ] + [
        {"id": f"INC-B{i}", "root_cause_category": "b", "emb_full": _emb(-1.0)} for i in range(4)
    ]
    clusters = cluster_incidents(incidents, distance_threshold=0.5, min_cluster=3)
    assert len(clusters) >= 1


# ── recall_at_k_helper ────────────────────────────────────────

def test_recall_at_k_perfect() -> None:
    assert recall_at_k_helper(["A", "B", "C"], ["A", "B"], k=3) == 1.0


def test_recall_at_k_partial() -> None:
    assert recall_at_k_helper(["A", "X", "Y"], ["A", "B"], k=3) == 0.5


def test_recall_at_k_none_found() -> None:
    assert recall_at_k_helper(["X", "Y"], ["A", "B"], k=3) == 0.0


def test_recall_at_k_empty_expected() -> None:
    assert recall_at_k_helper(["A", "B"], [], k=3) == 1.0


def test_recall_at_k_cutoff_respected() -> None:
    # Expected is at position 4, which is beyond k=3 — not counted
    assert recall_at_k_helper(["X", "Y", "Z", "A"], ["A"], k=3) == 0.0
