import pytest

from app.memory.stats import (
    compute_smoothed_p,
    get_weak_runbooks,
    log_missed_runbook,
    record_feedback,
    record_resolution_stats,
)
from app.models import Runbook


class MockStatsStore:
    def __init__(self):
        self.runbooks: dict[str, Runbook] = {}
        self.feedback: list[dict] = []
        self.suggestions: dict[int, dict] = {}
        self._next_fb_id = 1

    def increment_runbook_stats(self, runbook_id: str, success: bool) -> None:
        if runbook_id in self.runbooks:
            rb = self.runbooks[runbook_id]
            if success:
                rb.success_count += 1
            else:
                rb.failure_count += 1

    def insert_feedback(self, suggestion_id, runbook_id, helpful, comment=None, user_ref=None) -> int:
        fb_id = self._next_fb_id
        self._next_fb_id += 1
        self.feedback.append({
            "id": fb_id,
            "suggestion_id": suggestion_id,
            "runbook_id": runbook_id,
            "helpful": helpful,
            "comment": comment,
            "user_ref": user_ref,
        })
        return fb_id

    def list_runbooks(self) -> list[Runbook]:
        return list(self.runbooks.values())

    def get_suggestion(self, suggestion_id: int):
        return self.suggestions.get(suggestion_id)

    def update_suggestion_response(self, suggestion_id: int, response: dict) -> None:
        if suggestion_id in self.suggestions:
            self.suggestions[suggestion_id]["response"] = response


def test_laplace_smoothed_probability():
    """Verify Laplace smoothing: p = (success + 1) / (success + failure + 2)."""
    # 0 observations -> uniform prior 0.5
    assert compute_smoothed_p(0, 0) == 0.5

    # 1 success, 0 failure -> 2/3
    assert pytest.approx(compute_smoothed_p(1, 0), rel=1e-3) == 2 / 3

    # 5 successes, 0 failures -> 6/7
    assert pytest.approx(compute_smoothed_p(5, 0), rel=1e-3) == 6 / 7

    # 0 successes, 5 failures -> 1/7
    assert pytest.approx(compute_smoothed_p(0, 5), rel=1e-3) == 1 / 7

    # 10 successes, 2 failures -> 11/14
    assert pytest.approx(compute_smoothed_p(10, 2), rel=1e-3) == 11 / 14


def test_record_feedback_updates_runbook_stats():
    store = MockStatsStore()
    store.runbooks["RB-test"] = Runbook(
        id="RB-test",
        title="Test Runbook",
        body_md="# Test",
        success_count=2,
        failure_count=1,
    )

    # Helpful feedback increments success_count
    fb_id_1 = record_feedback(
        suggestion_id=101,
        runbook_id="RB-test",
        helpful=True,
        store=store,
    )
    assert fb_id_1 == 1
    assert store.runbooks["RB-test"].success_count == 3
    assert store.runbooks["RB-test"].failure_count == 1
    assert len(store.feedback) == 1

    # Not helpful feedback increments failure_count
    fb_id_2 = record_feedback(
        suggestion_id=101,
        runbook_id="RB-test",
        helpful=False,
        store=store,
    )
    assert fb_id_2 == 2
    assert store.runbooks["RB-test"].success_count == 3
    assert store.runbooks["RB-test"].failure_count == 2


def test_record_resolution_stats():
    store = MockStatsStore()
    store.runbooks["RB-1"] = Runbook(id="RB-1", title="RB 1", body_md="", success_count=0, failure_count=0)
    store.runbooks["RB-2"] = Runbook(id="RB-2", title="RB 2", body_md="", success_count=0, failure_count=0)

    # Resolution worked -> success_count increments for each
    record_resolution_stats(["RB-1", "RB-2"], worked=True, store=store)
    assert store.runbooks["RB-1"].success_count == 1
    assert store.runbooks["RB-2"].success_count == 1

    # Resolution failed -> failure_count increments
    record_resolution_stats(["RB-1"], worked=False, store=store)
    assert store.runbooks["RB-1"].failure_count == 1
    assert store.runbooks["RB-2"].failure_count == 0


def test_get_weak_runbooks_threshold_and_samples():
    store = MockStatsStore()
    # 0 successes, 5 failures -> p = 1/7 = 0.143 (< 0.3) with 5 samples -> WEAK
    store.runbooks["RB-weak"] = Runbook(id="RB-weak", title="Weak RB", body_md="", success_count=0, failure_count=5)
    # 0 successes, 2 failures -> p = 1/4 = 0.25 (< 0.3), but only 2 samples (< 5) -> NOT in list
    store.runbooks["RB-few-samples"] = Runbook(id="RB-few-samples", title="Few Samples", body_md="", success_count=0, failure_count=2)
    # 5 successes, 1 failure -> p = 6/8 = 0.75 (>= 0.3) -> STRONG
    store.runbooks["RB-strong"] = Runbook(id="RB-strong", title="Strong RB", body_md="", success_count=5, failure_count=1)

    weak = get_weak_runbooks(min_samples=5, threshold=0.3, store=store)
    assert len(weak) == 1
    assert weak[0].id == "RB-weak"
    assert weak[0].p < 0.3


def test_log_missed_runbook():
    store = MockStatsStore()
    store.suggestions[1] = {
        "id": 1,
        "response": {"hypotheses": []},
    }

    # Recommended RB-1, but responders used RB-2 and it worked
    log_missed_runbook(
        suggestion_id=1,
        recommended_runbook_id="RB-1",
        used_runbook_ids=["RB-2"],
        worked=True,
        store=store,
    )

    resp = store.suggestions[1]["response"]
    assert "missed_runbooks" in resp
    assert len(resp["missed_runbooks"]) == 1
    assert resp["missed_runbooks"][0]["recommended"] == "RB-1"
    assert resp["missed_runbooks"][0]["used"] == ["RB-2"]
