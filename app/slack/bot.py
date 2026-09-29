import json
import uuid
from datetime import datetime, timezone

import redis
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from app.agent.postmortem import confirm_postmortem, draft_postmortem, resolve_incident
from app.config import settings
from app.core.redact import redact
from app.logging import logger
from app.memory.retrieval import HybridRetrievalEngine
from app.memory.stats import record_feedback
from app.memory.store import MemoryStore
from app.models import Analysis, Cue, Hypothesis, SimilarIncidentCitation
from app.slack.blocks import (
    build_analysis_blocks,
    build_edit_postmortem_modal,
    build_incident_started_blocks,
    build_postmortem_draft_blocks,
    build_resolve_modal,
)

app = App(token=settings.SLACK_BOT_TOKEN)


def _generate_retrieval_analysis(live_id: str, query_text: str, store: MemoryStore) -> tuple[Analysis, int]:
    """Fallback investigation analysis based on HybridRetrievalEngine if agent is pending."""
    retriever = HybridRetrievalEngine(store=store)
    cue = Cue(text=query_text, error_messages=[query_text])
    result = retriever.recall(cue, top_k=3)

    hypotheses = []
    dropped_citations = []

    for idx, inc in enumerate(result.incidents, 1):
        # Validate citation exists in store
        p_inc = store.get_incident(inc.id)
        if not p_inc:
            dropped_citations.append(inc.id)
            continue

        hypotheses.append(Hypothesis(
            rank=idx,
            cause=inc.root_cause or inc.title,
            confidence="high" if inc.final >= 0.75 else ("medium" if inc.final >= 0.4 else "low"),
            evidence_for=[f"Past incident {inc.id} matched on: {', '.join(inc.matched_on)}"],
            evidence_against=[],
            similar_incidents=[SimilarIncidentCitation(
                id=inc.id,
                why_similar=f"Matched symptoms and keywords with score {inc.final:.2f}",
                differences=", ".join(inc.flags) if inc.flags else "No significant mismatches",
            )],
            recommended_steps=inc.resolution_steps or ["Verify application health and logs"],
            runbook_id=inc.runbook_ids[0] if inc.runbook_ids else None,
            risk_notes="Ensure changes are validated before destructive rollback",
        ))

    analysis = Analysis(
        summary=f"Incident investigation based on precedent recall for query: {query_text[:120]}",
        precedent_strength="strong" if any(h.confidence == "high" for h in hypotheses) else "partial",
        hypotheses=hypotheses,
        what_to_check_next=["Review error rate metrics", "Check recent deployment logs"],
        needs_human_decision=["Confirm remediation actions with on-call lead"],
        dropped_citations=dropped_citations,
    )

    sugg_id = store.insert_suggestion(
        live_incident_id=live_id,
        query_text=query_text,
        retrieved=[inc.model_dump() for inc in result.incidents],
        response=analysis.model_dump(),
        model="hybrid-retriever",
    )
    return analysis, sugg_id


@app.event("app_mention")
def handle_app_mention(body, say, client):
    """Handle @IncidentBot mentions to start an incident."""
    event = body.get("event", {})
    if event.get("bot_id"):
        return  # Ignore messages from bots

    text = event.get("text", "")
    channel = event.get("channel")
    thread_ts = event.get("thread_ts") or event.get("ts")

    # Redact input text
    clean_text = redact(text)
    live_id = f"LIVE-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{str(uuid.uuid4())[:4].upper()}"

    store = MemoryStore()
    store.upsert_live_incident(live_id=live_id, title=clean_text[:100], slack_channel=channel, slack_thread_ts=thread_ts)

    # Reply in thread
    started_blocks = build_incident_started_blocks(live_id, clean_text[:100])
    say(blocks=started_blocks, thread_ts=thread_ts)

    # Perform analysis
    analysis, sugg_id = _generate_retrieval_analysis(live_id, clean_text, store)
    analysis_blocks = build_analysis_blocks(live_id, analysis, suggestion_id=sugg_id)
    say(blocks=analysis_blocks, thread_ts=thread_ts)


@app.command("/incident")
def handle_incident_command(ack, body, say, client):
    """Handle /incident start <title> slash command."""
    ack()
    text = body.get("text", "").strip()
    channel = body.get("channel_id")

    if text.startswith("start"):
        title = text.replace("start", "", 1).strip() or "Untitled Incident"
        clean_title = redact(title)
        live_id = f"LIVE-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{str(uuid.uuid4())[:4].upper()}"

        store = MemoryStore()
        store.upsert_live_incident(live_id=live_id, title=clean_title, slack_channel=channel)

        started_blocks = build_incident_started_blocks(live_id, clean_title)
        say(blocks=started_blocks, channel=channel)


@app.event("message")
def handle_thread_message(body, say, client):
    """Append messages in an incident thread to Redis working memory, handle /reinvestigate."""
    event = body.get("event", {})
    if event.get("bot_id") or not event.get("thread_ts"):
        return

    text = event.get("text", "")
    thread_ts = event.get("thread_ts")
    user = event.get("user", "user")

    # Record message event in Redis
    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        ev_data = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "kind": "message",
            "source": user,
            "text": redact(text),
        }
        r.rpush(f"live:{thread_ts}:events", json.dumps(ev_data))
    except Exception:
        pass

    if "/reinvestigate" in text:
        store = MemoryStore()
        live_id = f"LIVE-{thread_ts}"
        analysis, sugg_id = _generate_retrieval_analysis(live_id, text, store)
        blocks = build_analysis_blocks(live_id, analysis, suggestion_id=sugg_id)
        say(blocks=blocks, thread_ts=thread_ts)


# --- Action Handlers ---

@app.action("action_helpful")
def handle_action_helpful(ack, body, client):
    ack()
    val_str = body.get("actions", [{}])[0].get("value")
    data = json.loads(val_str) if val_str else {}
    sugg_id = data.get("suggestion_id")
    record_feedback(suggestion_id=sugg_id, runbook_id=None, helpful=True, user_ref=body.get("user", {}).get("id"))


@app.action("action_not_helpful")
def handle_action_not_helpful(ack, body, client):
    ack()
    val_str = body.get("actions", [{}])[0].get("value")
    data = json.loads(val_str) if val_str else {}
    sugg_id = data.get("suggestion_id")
    record_feedback(suggestion_id=sugg_id, runbook_id=None, helpful=False, user_ref=body.get("user", {}).get("id"))


@app.action("action_investigate_again")
def handle_action_investigate_again(ack, body, say, client):
    ack()
    val_str = body.get("actions", [{}])[0].get("value")
    data = json.loads(val_str) if val_str else {}
    live_id = data.get("live_id", "LIVE-UNKNOWN")
    thread_ts = body.get("container", {}).get("thread_ts")

    store = MemoryStore()
    analysis, sugg_id = _generate_retrieval_analysis(live_id, "Re-investigation requested", store)
    blocks = build_analysis_blocks(live_id, analysis, suggestion_id=sugg_id)
    say(blocks=blocks, thread_ts=thread_ts)


@app.action("action_mark_resolved")
def handle_action_mark_resolved(ack, body, client):
    ack()
    val_str = body.get("actions", [{}])[0].get("value")
    data = json.loads(val_str) if val_str else {}
    live_id = data.get("live_id", "LIVE-UNKNOWN")

    store = MemoryStore()
    runbooks = store.list_runbooks()
    modal = build_resolve_modal(live_id, runbooks)

    client.views_open(
        trigger_id=body["trigger_id"],
        view=modal,
    )


# --- View Submission Handlers ---

@app.view("resolve_modal_view")
def handle_resolve_submission(ack, body, say, client):
    ack()
    view = body.get("view", {})
    meta = json.loads(view.get("private_metadata", "{}"))
    live_id = meta.get("live_id")

    values = view.get("state", {}).get("values", {})
    root_cause = values.get("root_cause_block", {}).get("root_cause_input", {}).get("value", "")
    steps_raw = values.get("steps_block", {}).get("steps_input", {}).get("value", "")
    steps = [s.strip() for s in steps_raw.splitlines() if s.strip()]

    selected_rbs = []
    if "runbooks_block" in values:
        selected_options = values["runbooks_block"].get("runbooks_input", {}).get("selected_options") or []
        selected_rbs = [opt["value"] for opt in selected_options]

    fix_worked_opt = values.get("fix_worked_block", {}).get("fix_worked_input", {}).get("selected_option", {}).get("value", "yes")
    worked = fix_worked_opt in {"yes", "partly"}

    store = MemoryStore()
    resolve_incident(
        live_id=live_id,
        root_cause=root_cause,
        steps=steps,
        runbook_ids=selected_rbs,
        worked=worked,
        user_ref=body.get("user", {}).get("id"),
        store=store,
    )

    draft = draft_postmortem(live_id=live_id, store=store)
    live_inc = store.get_live_incident(live_id)
    if live_inc and live_inc.slack_channel:
        pm_blocks = build_postmortem_draft_blocks(live_id, draft)
        client.chat_postMessage(
            channel=live_inc.slack_channel,
            thread_ts=live_inc.slack_thread_ts,
            blocks=pm_blocks,
            text=f"Post-Mortem Draft for {live_id}",
        )


@app.action("btn_approve_postmortem")
def handle_approve_postmortem(ack, body, client):
    ack()
    val_str = body.get("actions", [{}])[0].get("value")
    data = json.loads(val_str) if val_str else {}
    live_id = data.get("live_id")

    store = MemoryStore()
    new_inc = confirm_postmortem(live_id=live_id, store=store)
    channel = body.get("channel", {}).get("id")
    thread_ts = body.get("container", {}).get("thread_ts")

    if channel:
        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            text=f"✅ Post-Mortem approved and saved to long-term memory as *{new_inc.id}* ({new_inc.title}).",
        )


@app.action("btn_edit_postmortem")
def handle_edit_postmortem(ack, body, client):
    ack()
    val_str = body.get("actions", [{}])[0].get("value")
    data = json.loads(val_str) if val_str else {}
    live_id = data.get("live_id")

    store = MemoryStore()
    live_inc = store.get_live_incident(live_id)
    draft = live_inc.postmortem_draft if live_inc else {}
    md = draft.get("markdown", "# Post-Mortem Draft\n\nRoot Cause: ...")

    modal = build_edit_postmortem_modal(live_id, md)
    client.views_open(trigger_id=body["trigger_id"], view=modal)


@app.view("edit_postmortem_modal_view")
def handle_edit_submission(ack, body, client):
    ack()
    view = body.get("view", {})
    meta = json.loads(view.get("private_metadata", "{}"))
    live_id = meta.get("live_id")

    edited_md = view.get("state", {}).get("values", {}).get("markdown_block", {}).get("markdown_input", {}).get("value", "")

    store = MemoryStore()
    new_inc = confirm_postmortem(live_id=live_id, markdown_override=edited_md, store=store)
    live_inc = store.get_live_incident(live_id)
    if live_inc and live_inc.slack_channel:
        client.chat_postMessage(
            channel=live_inc.slack_channel,
            thread_ts=live_inc.slack_thread_ts,
            text=f"✅ Edited post-mortem approved and saved to long-term memory as *{new_inc.id}*.",
        )


def start_slack_bot():
    """Start Slack Bolt app in Socket Mode."""
    if not settings.SLACK_BOT_TOKEN or not settings.SLACK_APP_TOKEN:
        logger.warn("slack_tokens_missing", msg="SLACK_BOT_TOKEN or SLACK_APP_TOKEN not set. Slack bot cannot start.")
        return
    handler = SocketModeHandler(app, settings.SLACK_APP_TOKEN)
    logger.info("slack_bot_starting_socket_mode")
    handler.start()
