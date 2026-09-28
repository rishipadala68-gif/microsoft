"""Claude ReAct investigation loop.

Uses the actual flat ScoredIncident model from app.models:
  ScoredIncident.id, .title, .final, .flags, .symptoms, .root_cause,
  .resolution_steps, .fix_worked, .services, .score_breakdown, .matched_on

Analysis model fields:
  summary, precedent_strength, hypotheses, what_to_check_next,
  needs_human_decision, dropped_citations

SPEC.md confidence rules (enforced on Hypothesis.confidence):
  - "high"   : best final ≥ 0.70 AND live evidence confirms root cause
  - "medium" : 0.35 ≤ best final < 0.70 OR evidence suggestive
  - "low"    : best final < 0.35 OR evidence inconclusive
  - precedent_strength="none" when best final < 0.35
"""
from __future__ import annotations

import json
import logging
from typing import Any

from app.adapters.base import CodeAdapter, DeployAdapter, LogAdapter, MetricsAdapter
from app.agent.tools import ALLOW_ACTIONS, TOOL_DEFINITIONS
from app.config import get_settings
from app.memory import working as wm
from app.models import (
    Analysis,
    Cue,
    Hypothesis,
    LiveContext,
    RetrievalResult,
    SimilarIncidentCitation,
)

logger = logging.getLogger(__name__)

MAX_TURNS = 10

SYSTEM_PROMPT = """\
You are an expert on-call incident response assistant.
You have access to read-only tools: logs, metrics, deploys, commits, service graph, \
past incidents, and runbooks.

NEVER attempt any write, restart, rollback, or remediation action. Read-only only.

Your job:
1. Investigate the live incident using the tools provided.
2. Identify the most likely root cause.
3. Find the most similar past incidents and explain how they are similar AND different.
4. Recommend the first steps to try, citing evidence.
5. Return a final structured JSON analysis inside <analysis>…</analysis> tags.

The analysis JSON must match this schema:
{
  "summary": "one-paragraph summary",
  "precedent_strength": "strong|partial|none",
  "hypotheses": [
    {
      "rank": 1,
      "cause": "string",
      "confidence": "high|medium|low",
      "evidence_for": ["..."],
      "evidence_against": ["..."],
      "similar_incidents": [
        {"id": "INC-xxx", "why_similar": "...", "differences": "..."}
      ],
      "recommended_steps": ["step 1", "step 2"],
      "runbook_id": "RB-xxx or null",
      "risk_notes": ""
    }
  ],
  "what_to_check_next": ["..."],
  "needs_human_decision": ["..."],
  "dropped_citations": []
}

Rules:
- precedent_strength="none" when best recalled score < 0.35 — say "no strong precedent" explicitly.
- confidence="high" only when best score ≥ 0.70 AND live evidence confirms root cause.
- confidence="medium" when 0.35 ≤ best score < 0.70.
- confidence="low" when best score < 0.35.
- Only include incident IDs that were actually recalled (no hallucinated IDs).
- If no strong precedent exists, say so instead of forcing a match.
"""


def _parse_analysis(text: str) -> dict[str, Any] | None:
    """Extract the JSON block from <analysis>…</analysis>."""
    import re
    m = re.search(r"<analysis>(.*?)</analysis>", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(1).strip())
    except json.JSONDecodeError:
        return None


def _best_score(retrieval: RetrievalResult) -> float:
    return max((si.final for si in retrieval.incidents), default=0.0)


def _precedent_strength(best: float) -> str:
    if best >= 0.70:
        return "strong"
    if best >= 0.35:
        return "partial"
    return "none"


def _confidence(best: float) -> str:
    if best >= 0.70:
        return "high"
    if best >= 0.35:
        return "medium"
    return "low"


def _build_context_prompt(cue: Cue, live: LiveContext | None, retrieval: RetrievalResult) -> str:
    parts: list[str] = []
    parts.append(f"## Live Incident\n**Alert:** {cue.alert_text or cue.normalized_text}")
    parts.append(f"**Services:** {', '.join(cue.services)}")
    if cue.error_messages:
        parts.append("**Errors:**\n" + "\n".join(f"  - {e}" for e in cue.error_messages))

    if live:
        recent = live.events[-10:]
        if recent:
            lines = [f"  [{e.ts}] {e.kind}: {e.content or e.text}" for e in recent]
            parts.append("**Recent timeline:**\n" + "\n".join(lines))

    if retrieval.incidents:
        parts.append("\n## Recalled Past Incidents (top matches)")
        for si in retrieval.incidents[:5]:
            parts.append(
                f"- **{si.id}** score={si.final:.3f} [{si.title}] "
                f"services={si.services} root_cause={si.root_cause}"
            )
            if si.flags:
                parts.append(f"  ⚠ flags: {si.flags}")

    if retrieval.patterns:
        parts.append("\n## Recalled Patterns")
        for p in retrieval.patterns[:3]:
            parts.append(f"- {p.id}: {p.title} — {p.rule_text[:100]}")

    if retrieval.runbooks:
        parts.append("\n## Available Runbooks")
        for rb in retrieval.runbooks[:5]:
            parts.append(f"- **{rb.id}**: {rb.title} (success_rate={rb.success_rate:.0%})")

    parts.append(
        "\nInvestigate step by step. Use tools to gather evidence. "
        "When confident, return the final analysis inside <analysis>…</analysis> tags."
    )
    return "\n".join(parts)


def _dispatch_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    *,
    logs: LogAdapter,
    metrics: MetricsAdapter,
    deploys: DeployAdapter,
    code: CodeAdapter,
    retrieval: RetrievalResult,
    live: LiveContext | None,
    incident_id: str,
) -> str:
    assert not ALLOW_ACTIONS, "Safety: ALLOW_ACTIONS must never be True"

    if tool_name == "get_logs":
        result = logs.query(
            service=tool_input["service"],
            start_iso=tool_input["start_iso"],
            end_iso=tool_input["end_iso"],
            filter_text=tool_input.get("filter_text", ""),
            limit=tool_input.get("limit", 100),
        )
    elif tool_name == "get_metrics":
        result = metrics.query_range(
            metric=tool_input["metric"],
            start_iso=tool_input["start_iso"],
            end_iso=tool_input["end_iso"],
            step_seconds=tool_input.get("step_seconds", 60),
        )
    elif tool_name == "get_recent_deploys":
        result = deploys.recent_deploys(
            service=tool_input["service"],
            since_iso=tool_input["since_iso"],
            limit=tool_input.get("limit", 10),
        )
    elif tool_name == "get_commits_touching_files":
        result = code.commits_touching(
            file_paths=tool_input["file_paths"],
            since_iso=tool_input["since_iso"],
            limit=tool_input.get("limit", 20),
        )
    elif tool_name == "get_diff":
        result = code.diff(
            commit_sha=tool_input["commit_sha"],
            file_path=tool_input.get("file_path"),
        )
    elif tool_name == "get_service_dependencies":
        svc = tool_input["service"]
        related = list({s for si in retrieval.incidents for s in si.services if s != svc})
        result = {"service": svc, "related_services": related}
    elif tool_name == "search_past_incidents":
        result = [
            {"incident_id": si.id, "title": si.title, "score": si.final,
             "root_cause": si.root_cause}
            for si in retrieval.incidents[:tool_input.get("top_k", 5)]
        ]
    elif tool_name == "get_runbook":
        rb_id = tool_input["runbook_id"]
        rb = next((r for r in retrieval.runbooks if r.id == rb_id), None)
        result = {"id": rb_id, "steps": rb.steps if rb else [], "found": rb is not None}
    elif tool_name == "get_live_context":
        if live:
            result = {
                "incident_id": live.incident_id or live.live_id,
                "status": live.status,
                "services": live.services,
                "hypotheses": live.hypotheses,
                "recent_events": [
                    {"ts": e.ts, "kind": e.kind, "content": e.content or e.text}
                    for e in live.events[-10:]
                ],
            }
        else:
            result = {"error": "no live context found"}
    else:
        result = {"error": f"unknown tool: {tool_name}"}

    return json.dumps(result, default=str)


def _validate_citations(raw: dict[str, Any], retrieval: RetrievalResult) -> dict[str, Any]:
    """Remove hallucinated incident IDs from hypothesis citations."""
    valid_inc_ids = {si.id for si in retrieval.incidents}
    valid_rb_ids = {rb.id for rb in retrieval.runbooks}
    dropped: list[str] = list(raw.get("dropped_citations", []))

    for hyp in raw.get("hypotheses", []):
        clean_citations = []
        for cite in hyp.get("similar_incidents", []):
            if cite.get("id") in valid_inc_ids:
                clean_citations.append(cite)
            else:
                dropped.append(cite.get("id", "unknown"))
        hyp["similar_incidents"] = clean_citations

        rb = hyp.get("runbook_id")
        if rb and rb not in valid_rb_ids:
            dropped.append(rb)
            hyp["runbook_id"] = None

    raw["dropped_citations"] = dropped
    return raw


def _apply_confidence_rules(raw: dict[str, Any], retrieval: RetrievalResult) -> dict[str, Any]:
    """Enforce SPEC.md confidence + precedent_strength rules."""
    best = _best_score(retrieval)
    raw["precedent_strength"] = _precedent_strength(best)

    for hyp in raw.get("hypotheses", []):
        conf = hyp.get("confidence", "low")
        if best < 0.35 and conf == "high":
            hyp["confidence"] = "low"
        elif best < 0.70 and conf == "high":
            hyp["confidence"] = "medium"

    return raw


def _build_analysis(raw: dict[str, Any]) -> Analysis:
    hypotheses = []
    for h in raw.get("hypotheses", []):
        citations = [
            SimilarIncidentCitation(
                id=c.get("id", ""),
                why_similar=c.get("why_similar", ""),
                differences=c.get("differences", ""),
            )
            for c in h.get("similar_incidents", [])
        ]
        hypotheses.append(Hypothesis(
            rank=h.get("rank", 1),
            cause=h.get("cause", ""),
            confidence=h.get("confidence", "low"),
            evidence_for=h.get("evidence_for", []),
            evidence_against=h.get("evidence_against", []),
            similar_incidents=citations,
            recommended_steps=h.get("recommended_steps", []),
            runbook_id=h.get("runbook_id"),
            risk_notes=h.get("risk_notes", ""),
        ))

    return Analysis(
        summary=raw.get("summary", ""),
        precedent_strength=raw.get("precedent_strength", "none"),
        hypotheses=hypotheses,
        what_to_check_next=raw.get("what_to_check_next", []),
        needs_human_decision=raw.get("needs_human_decision", []),
        dropped_citations=raw.get("dropped_citations", []),
    )


def _heuristic_analysis(cue: Cue, retrieval: RetrievalResult) -> Analysis:
    """Fallback when no LLM is available."""
    best = _best_score(retrieval)
    conf = _confidence(best)
    pstr = _precedent_strength(best)

    citations = [
        SimilarIncidentCitation(
            id=si.id,
            why_similar=f"matched on: {', '.join(si.matched_on) or 'vector similarity'}",
            differences=", ".join(si.flags) if si.flags else "none noted",
        )
        for si in retrieval.incidents[:3]
    ]

    rb_id = retrieval.runbooks[0].id if retrieval.runbooks else None
    steps = (retrieval.runbooks[0].steps if retrieval.runbooks and retrieval.runbooks[0].steps
             else ["Follow suggested runbook", "Investigate manually"])

    top_cause = retrieval.incidents[0].root_cause if retrieval.incidents else "Unknown"

    hypothesis = Hypothesis(
        rank=1,
        cause=top_cause or "Unknown",
        confidence=conf,  # type: ignore[arg-type]
        evidence_for=[],
        evidence_against=[],
        similar_incidents=citations,
        recommended_steps=steps,
        runbook_id=rb_id,
        risk_notes="Heuristic analysis — LLM not configured",
    )

    summary = (
        "Heuristic analysis (no LLM available). "
        + (f"Best match: {retrieval.incidents[0].title} (score={best:.2f})."
           if retrieval.incidents else "No past incidents recalled.")
    )

    return Analysis(
        summary=summary,
        precedent_strength=pstr,  # type: ignore[arg-type]
        hypotheses=[hypothesis],
        what_to_check_next=["Configure ANTHROPIC_API_KEY for full investigation"],
        needs_human_decision=[],
        dropped_citations=[],
    )


def investigate(
    incident_id: str,
    cue: Cue,
    retrieval: RetrievalResult,
    *,
    logs: LogAdapter,
    metrics: MetricsAdapter,
    deploys: DeployAdapter,
    code: CodeAdapter,
    llm_client: Any | None = None,
) -> Analysis:
    """Run the Claude ReAct investigation loop and return a structured Analysis."""
    settings = get_settings()

    # Try to load live context — tolerate Redis being unavailable in tests
    try:
        live = wm.get_live_context(incident_id)
    except Exception:
        live = None

    # ── Fallback (no LLM) ─────────────────────────────────────
    if llm_client is None or not settings.ANTHROPIC_API_KEY:
        return _heuristic_analysis(cue, retrieval)

    # ── Claude ReAct loop ──────────────────────────────────────
    user_content = _build_context_prompt(cue, live, retrieval)
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_content}]

    try:
        wm.append_event(incident_id, "tool_result", "Investigation started", source="agent")
    except Exception:
        pass

    for _turn in range(MAX_TURNS):
        response = llm_client.messages.create(
            model=settings.CLAUDE_MODEL,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            tools=TOOL_DEFINITIONS,
            messages=messages,
        )

        assistant_content: list[dict[str, Any]] = []
        tool_calls_made: list[dict[str, Any]] = []

        for block in response.content:
            if block.type == "text":
                assistant_content.append({"type": "text", "text": block.text})
                raw = _parse_analysis(block.text)
                if raw is not None:
                    raw = _validate_citations(raw, retrieval)
                    raw = _apply_confidence_rules(raw, retrieval)
                    analysis = _build_analysis(raw)
                    try:
                        wm.append_event(incident_id, "suggestion",
                                        json.dumps(analysis.model_dump()), source="agent")
                    except Exception:
                        pass
                    return analysis
            elif block.type == "tool_use":
                tool_calls_made.append({"id": block.id, "name": block.name, "input": block.input})
                assistant_content.append(
                    {"type": "tool_use", "id": block.id, "name": block.name, "input": block.input}
                )

        messages.append({"role": "assistant", "content": assistant_content})

        if not tool_calls_made:
            break

        tool_results: list[dict[str, Any]] = []
        for tc in tool_calls_made:
            result_str = _dispatch_tool(
                tc["name"], tc["input"],
                logs=logs, metrics=metrics, deploys=deploys, code=code,
                retrieval=retrieval, live=live, incident_id=incident_id,
            )
            try:
                wm.append_event(incident_id, "tool_result",
                                f"Tool {tc['name']} → {result_str[:200]}", source="agent")
            except Exception:
                pass
            tool_results.append(
                {"type": "tool_result", "tool_use_id": tc["id"], "content": result_str}
            )
        messages.append({"role": "user", "content": tool_results})

    logger.warning("investigate: exhausted %d turns without structured analysis", MAX_TURNS)
    return _heuristic_analysis(cue, retrieval)
