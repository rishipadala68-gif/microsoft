import json
from typing import Any

from app.core.redact import redact
from app.models import Analysis, Runbook


def build_incident_started_blocks(live_id: str, title: str) -> list[dict[str, Any]]:
    """Header and ack blocks when an incident starts."""
    clean_title = redact(title)
    return [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"🚨 Incident Started: {live_id}",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Title:* {clean_title}\n*Status:* Open | Investigating precedents...",
            },
        },
    ]


def build_analysis_blocks(
    live_id: str,
    analysis: Analysis,
    suggestion_id: int | None = None,
) -> list[dict[str, Any]]:
    """
    Build Block Kit blocks for the analysis message:
    1. Header: summary plus a confidence badge.
    2. Section per hypothesis (max 3): cause, evidence bullets, steps.
    3. 'Similar past incidents' section: INC-0007: <one-line why> · differences: <...>.
    4. Buttons: Helpful, Not helpful, Investigate again, Mark resolved.
    """
    clean_summary = redact(analysis.summary)

    # Determine overall confidence badge from hypotheses or precedent strength
    if analysis.hypotheses:
        top_conf = analysis.hypotheses[0].confidence
    else:
        top_conf = "low"

    badge_map = {
        "high": "🟢 *[HIGH CONFIDENCE]*",
        "medium": "🟡 *[MEDIUM CONFIDENCE]*",
        "low": "🔴 *[LOW CONFIDENCE]*",
    }
    badge = badge_map.get(top_conf, "⚪ *[UNKNOWN CONFIDENCE]*")

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"{badge}\n*Analysis Summary:*\n{clean_summary}",
            },
        },
        {"type": "divider"},
    ]

    # Hypotheses sections (max 3)
    for hyp in analysis.hypotheses[:3]:
        cause = redact(hyp.cause)
        hyp_badge = badge_map.get(hyp.confidence, "")
        lines = [f"*Hypothesis #{hyp.rank}:* {cause} {hyp_badge}"]

        if hyp.evidence_for:
            lines.append("*Evidence For:*")
            for ev in hyp.evidence_for:
                lines.append(f"• {redact(ev)}")

        if hyp.evidence_against:
            lines.append("*Evidence Against:*")
            for ea in hyp.evidence_against:
                lines.append(f"• {redact(ea)}")

        if hyp.recommended_steps:
            lines.append("*Recommended Steps:*")
            for i, st in enumerate(hyp.recommended_steps, 1):
                lines.append(f"{i}. {redact(st)}")

        if hyp.runbook_id:
            lines.append(f"📖 *Runbook:* `{hyp.runbook_id}`")

        if hyp.risk_notes:
            lines.append(f"⚠️ *Risk Notes:* {redact(hyp.risk_notes)}")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(lines),
            },
        })

    # Similar past incidents section
    all_sims = []
    for hyp in analysis.hypotheses:
        for sim in hyp.similar_incidents:
            all_sims.append(sim)

    if all_sims:
        sim_lines = ["*Similar Past Incidents:*"]
        seen_sim_ids = set()
        for sim in all_sims:
            if sim.id not in seen_sim_ids:
                seen_sim_ids.add(sim.id)
                diff = redact(sim.differences) if sim.differences else "none noted"
                why = redact(sim.why_similar)
                sim_lines.append(f"• *{sim.id}*: {why} · *differences:* {diff}")

        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "\n".join(sim_lines),
            },
        })

    blocks.append({"type": "divider"})

    # Action buttons
    action_val = json.dumps({"live_id": live_id, "suggestion_id": suggestion_id})
    action_elements = [
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "👍 Helpful", "emoji": True},
            "action_id": "action_helpful",
            "value": action_val,
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "👎 Not helpful", "emoji": True},
            "action_id": "action_not_helpful",
            "value": action_val,
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "🔄 Investigate again", "emoji": True},
            "action_id": "action_investigate_again",
            "value": action_val,
        },
        {
            "type": "button",
            "text": {"type": "plain_text", "text": "✅ Mark resolved", "emoji": True},
            "style": "primary",
            "action_id": "action_mark_resolved",
            "value": action_val,
        },
    ]

    blocks.append({
        "type": "actions",
        "elements": action_elements,
    })

    return blocks


def build_resolve_modal(live_id: str, runbooks: list[Runbook]) -> dict[str, Any]:
    """
    Build the resolve modal view:
    - Root cause (multi-line)
    - Steps taken (multi-line)
    - Runbooks used (multi-select)
    - 'Did the suggested fix work?' (radio: yes/partly/no)
    """
    rb_options = []
    for rb in runbooks[:20]:
        rb_options.append({
            "text": {"type": "plain_text", "text": f"{rb.id} ({rb.title[:30]})"},
            "value": rb.id,
        })

    view: dict[str, Any] = {
        "type": "modal",
        "callback_id": "resolve_modal_view",
        "title": {"type": "plain_text", "text": "Mark Incident Resolved"},
        "submit": {"type": "plain_text", "text": "Submit Resolution"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps({"live_id": live_id}),
        "blocks": [
            {
                "type": "input",
                "block_id": "root_cause_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "root_cause_input",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "Describe the root cause of the incident..."},
                },
                "label": {"type": "plain_text", "text": "Root Cause"},
            },
            {
                "type": "input",
                "block_id": "steps_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "steps_input",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "List the actual steps taken to mitigate and resolve..."},
                },
                "label": {"type": "plain_text", "text": "Steps Taken"},
            },
        ],
    }

    if rb_options:
        view["blocks"].append({
            "type": "input",
            "block_id": "runbooks_block",
            "optional": True,
            "element": {
                "type": "multi_static_select",
                "action_id": "runbooks_input",
                "placeholder": {"type": "plain_text", "text": "Select runbooks executed..."},
                "options": rb_options,
            },
            "label": {"type": "plain_text", "text": "Runbooks Used"},
        })

    view["blocks"].append({
        "type": "input",
        "block_id": "fix_worked_block",
        "element": {
            "type": "radio_buttons",
            "action_id": "fix_worked_input",
            "initial_option": {
                "text": {"type": "plain_text", "text": "Yes, completely"},
                "value": "yes",
            },
            "options": [
                {
                    "text": {"type": "plain_text", "text": "Yes, completely"},
                    "value": "yes",
                },
                {
                    "text": {"type": "plain_text", "text": "Partly"},
                    "value": "partly",
                },
                {
                    "text": {"type": "plain_text", "text": "No, had to do something else"},
                    "value": "no",
                },
            ],
        },
        "label": {"type": "plain_text", "text": "Did the suggested fix work?"},
    })

    return view


def build_postmortem_draft_blocks(live_id: str, draft: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Post-mortem draft block kit message with:
    - Summary & Root cause
    - Action buttons: 'Approve & save to memory' and 'Edit'
    """
    summary = redact(draft.get("summary", ""))
    root_cause = redact(draft.get("root_cause", ""))
    val = json.dumps({"live_id": live_id})

    blocks: list[dict[str, Any]] = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"📝 Post-Mortem Draft ({live_id})",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Summary:* {summary}\n*Root Cause:* {root_cause}",
            },
        },
        {"type": "divider"},
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "💾 Approve & save to memory", "emoji": True},
                    "style": "primary",
                    "action_id": "btn_approve_postmortem",
                    "value": val,
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "✏️ Edit Draft", "emoji": True},
                    "action_id": "btn_edit_postmortem",
                    "value": val,
                },
            ],
        },
    ]
    return blocks


def build_edit_postmortem_modal(live_id: str, markdown_text: str) -> dict[str, Any]:
    """Modal to edit post-mortem markdown before saving."""
    return {
        "type": "modal",
        "callback_id": "edit_postmortem_modal_view",
        "title": {"type": "plain_text", "text": "Edit Post-Mortem"},
        "submit": {"type": "plain_text", "text": "Approve & Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "private_metadata": json.dumps({"live_id": live_id}),
        "blocks": [
            {
                "type": "input",
                "block_id": "markdown_block",
                "element": {
                    "type": "plain_text_input",
                    "action_id": "markdown_input",
                    "multiline": True,
                    "initial_value": markdown_text[:3000],
                },
                "label": {"type": "plain_text", "text": "Post-Mortem Markdown"},
            }
        ],
    }
