from app.models import Analysis, Hypothesis, Runbook, SimilarIncidentCitation
from app.slack.blocks import (
    build_analysis_blocks,
    build_edit_postmortem_modal,
    build_incident_started_blocks,
    build_postmortem_draft_blocks,
    build_resolve_modal,
)


def test_build_incident_started_blocks():
    blocks = build_incident_started_blocks("LIVE-001", "Database connection pool timeout in api")
    assert len(blocks) == 2
    assert blocks[0]["type"] == "header"
    assert "LIVE-001" in blocks[0]["text"]["text"]
    assert "Database connection pool timeout" in blocks[1]["text"]["text"]


def test_build_analysis_blocks():
    hyp = Hypothesis(
        rank=1,
        cause="HikariCP connection pool exhausted",
        confidence="high",
        evidence_for=["503 error rate spike", "HikariPool timeout logs"],
        evidence_against=[],
        similar_incidents=[
            SimilarIncidentCitation(
                id="INC-0007",
                why_similar="Same connection timeout error message",
                differences="Traffic spike was absent this time",
            )
        ],
        recommended_steps=["Check active db connections", "Restart leaking replica pod"],
        runbook_id="RB-db-pool-exhaustion",
        risk_notes="Ensure read replicas are synced before restart",
    )
    analysis = Analysis(
        summary="High likelihood of db pool exhaustion caused by connection leak.",
        precedent_strength="strong",
        hypotheses=[hyp],
        what_to_check_next=["Check postgres pg_stat_activity"],
        needs_human_decision=[],
    )

    blocks = build_analysis_blocks(live_id="LIVE-001", analysis=analysis, suggestion_id=42)

    # Check for confidence badge and summary
    assert any("[HIGH CONFIDENCE]" in b.get("text", {}).get("text", "") for b in blocks if "text" in b)
    # Check for hypothesis details
    assert any("HikariCP connection pool exhausted" in b.get("text", {}).get("text", "") for b in blocks if "text" in b)
    # Check for similar incidents differences
    assert any("INC-0007" in b.get("text", {}).get("text", "") for b in blocks if "text" in b)
    assert any("differences:" in b.get("text", {}).get("text", "") for b in blocks if "text" in b)

    # Check for action buttons
    action_block = next(b for b in blocks if b["type"] == "actions")
    action_ids = [el["action_id"] for el in action_block["elements"]]
    assert "action_helpful" in action_ids
    assert "action_not_helpful" in action_ids
    assert "action_investigate_again" in action_ids
    assert "action_mark_resolved" in action_ids


def test_build_resolve_modal():
    runbooks = [Runbook(id="RB-1", title="Runbook 1", body_md="")]
    modal = build_resolve_modal("LIVE-001", runbooks)

    assert modal["type"] == "modal"
    assert modal["callback_id"] == "resolve_modal_view"
    block_ids = [b["block_id"] for b in modal["blocks"]]
    assert "root_cause_block" in block_ids
    assert "steps_block" in block_ids
    assert "runbooks_block" in block_ids
    assert "fix_worked_block" in block_ids


def test_build_postmortem_draft_blocks():
    draft = {
        "summary": "Summary of incident",
        "root_cause": "Database connection exhaustion",
    }
    blocks = build_postmortem_draft_blocks("LIVE-001", draft)
    action_block = next(b for b in blocks if b["type"] == "actions")
    action_ids = [el["action_id"] for el in action_block["elements"]]
    assert "btn_approve_postmortem" in action_ids
    assert "btn_edit_postmortem" in action_ids


def test_build_edit_postmortem_modal():
    modal = build_edit_postmortem_modal("LIVE-001", "# Post-Mortem\n\nContent")
    assert modal["callback_id"] == "edit_postmortem_modal_view"
    assert modal["blocks"][0]["element"]["initial_value"] == "# Post-Mortem\n\nContent"
