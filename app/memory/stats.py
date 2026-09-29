from typing import Any

from app.memory.store import MemoryStore
from app.models import RunbookStats


def compute_smoothed_p(success_count: int, failure_count: int) -> float:
    """Laplace-smoothed runbook success probability: p = (success_count + 1) / (success_count + failure_count + 2)."""
    return (success_count + 1) / (success_count + failure_count + 2)


def record_feedback(
    suggestion_id: int | None,
    runbook_id: str | None,
    helpful: bool,
    comment: str | None = None,
    user_ref: str | None = None,
    store: MemoryStore | None = None,
) -> int:
    """
    Record user feedback for a suggestion.
    On Helpful: increments runbook.success_count.
    On Not helpful: increments runbook.failure_count.
    Stores a row in feedback table.
    """
    mem_store = store or MemoryStore()

    if runbook_id:
        try:
            mem_store.increment_runbook_stats(runbook_id, success=helpful)
        except Exception:
            pass

    fb_id = mem_store.insert_feedback(
        suggestion_id=suggestion_id,
        runbook_id=runbook_id,
        helpful=helpful,
        comment=comment,
        user_ref=user_ref,
    )
    return fb_id


def record_resolution_stats(
    runbook_ids: list[str],
    worked: bool,
    store: MemoryStore | None = None,
) -> None:
    """
    On incident resolve:
    If worked=True: increment success_count for each runbook used.
    If worked=False: increment failure_count for each runbook used.
    """
    if not runbook_ids:
        return
    mem_store = store or MemoryStore()
    for rb_id in runbook_ids:
        try:
            mem_store.increment_runbook_stats(rb_id, success=worked)
        except Exception:
            pass


def log_missed_runbook(
    suggestion_id: int,
    recommended_runbook_id: str | None,
    used_runbook_ids: list[str],
    worked: bool,
    store: MemoryStore | None = None,
) -> None:
    """
    If the agent recommended runbook R but the responders used a different one
    and it worked, log a missed_runbook record (in suggestions.response JSON)
    for the evaluation report.
    """
    if not worked or not recommended_runbook_id:
        return
    if recommended_runbook_id in used_runbook_ids or not used_runbook_ids:
        return

    mem_store = store or MemoryStore()
    sugg = mem_store.get_suggestion(suggestion_id)
    if not sugg:
        return

    resp = sugg.get("response") or {}
    missed_records = resp.get("missed_runbooks", [])
    missed_records.append({
        "recommended": recommended_runbook_id,
        "used": used_runbook_ids,
    })
    resp["missed_runbooks"] = missed_records
    mem_store.update_suggestion_response(suggestion_id, resp)


def get_weak_runbooks(
    min_samples: int = 5,
    threshold: float = 0.3,
    store: MemoryStore | None = None,
) -> list[RunbookStats]:
    """List runbooks with smoothed success probability p < threshold and at least min_samples samples."""
    mem_store = store or MemoryStore()
    try:
        runbooks = mem_store.list_runbooks()
    except Exception:
        runbooks = []

    weak: list[RunbookStats] = []
    for rb in runbooks:
        samples = rb.success_count + rb.failure_count
        if samples >= min_samples:
            p = compute_smoothed_p(rb.success_count, rb.failure_count)
            if p < threshold:
                weak.append(RunbookStats(
                    id=rb.id,
                    title=rb.title,
                    success_count=rb.success_count,
                    failure_count=rb.failure_count,
                    p=round(p, 4),
                ))
    return weak


def get_memory_stats(store: MemoryStore | None = None) -> dict[str, Any]:
    """Aggregate statistics for cli stats."""
    mem_store = store or MemoryStore()
    try:
        incident_count = mem_store.count_incidents()
    except Exception:
        incident_count = 0

    try:
        runbooks = mem_store.list_runbooks()
        runbook_count = len(runbooks)
    except Exception:
        runbook_count = 0

    weak = get_weak_runbooks(min_samples=5, threshold=0.3, store=mem_store)

    try:
        feedback_stats = mem_store.get_feedback_stats()
    except Exception:
        feedback_stats = {"total": 0, "helpful": 0, "not_helpful": 0, "satisfaction_ratio": 0.0}

    try:
        code_changes_count = mem_store.count_code_changes()
    except Exception:
        code_changes_count = 0

    return {
        "incident_count": incident_count,
        "runbook_count": runbook_count,
        "weak_runbooks": [w.model_dump() for w in weak],
        "feedback": feedback_stats,
        "code_changes_count": code_changes_count,
    }
