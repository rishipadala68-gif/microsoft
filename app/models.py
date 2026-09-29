from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# --- Ingestion & Extraction Models ---

class FileMention(BaseModel):
    path: str
    function: str = ""


class ExtractedIncident(BaseModel):
    title: str
    severity: Literal["sev1", "sev2", "sev3", "sev4", "unknown"] = "unknown"
    started_at: datetime | None = None
    resolved_at: datetime | None = None
    symptoms: list[str] = Field(default_factory=list)
    error_messages: list[str] = Field(default_factory=list)
    stack_traces: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    trigger_type: str | None = None
    trigger_ref: str | None = None
    root_cause: str | None = None
    root_cause_category: str | None = None
    resolution_steps: list[str] = Field(default_factory=list)
    runbooks_mentioned: list[str] = Field(default_factory=list)
    fix_worked: bool | None = None
    lessons: str | None = None
    files_mentioned: list[FileMention] = Field(default_factory=list)
    extraction_confidence: Literal["low", "medium", "high"] = "medium"
    missing_fields: list[str] = Field(default_factory=list)


class RawDoc(BaseModel):
    source_type: str
    source_id: str
    text: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# --- Core Memory Models ---

class Incident(BaseModel):
    id: str
    title: str
    status: str = "confirmed"
    severity: str | None = "unknown"
    started_at: datetime | None = None
    resolved_at: datetime | None = None
    time_to_resolve_min: int | None = None
    symptoms: list[str] = Field(default_factory=list)
    error_messages: list[str] = Field(default_factory=list)
    error_fingerprints: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    trigger_type: str | None = None
    trigger_ref: str | None = None
    root_cause: str | None = None
    root_cause_category: str | None = None
    resolution_steps: list[str] = Field(default_factory=list)
    runbook_ids: list[str] = Field(default_factory=list)
    fix_worked: bool | None = None
    lessons: str | None = None
    source_docs: list[dict[str, Any]] = Field(default_factory=list)
    symptom_text: str = ""
    full_text: str = ""
    emb_symptom: list[float] = Field(default_factory=list)
    emb_full: list[float] = Field(default_factory=list)
    weight: float = 1.0
    architecture_epoch: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


class Runbook(BaseModel):
    id: str
    title: str
    body_md: str
    services: list[str] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    emb: list[float] | None = None
    success_count: int = 0
    failure_count: int = 0
    updated_at: datetime | None = None

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.failure_count
        return self.success_count / total if total > 0 else 0.5


class Pattern(BaseModel):
    id: int | None = None
    title: str
    rule_text: str
    exceptions_text: str | None = None
    trigger_signals: list[str] = Field(default_factory=list)
    recommended_checks: list[str] = Field(default_factory=list)
    recommended_runbooks: list[str] = Field(default_factory=list)
    member_incident_ids: list[str] = Field(default_factory=list)
    confidence: float | None = None
    emb: list[float] | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


# --- Retrieval Models ---

class Cue(BaseModel):
    text: str = ""
    error_messages: list[str] = Field(default_factory=list)
    stack_traces: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    files: list[str] = Field(default_factory=list)
    commit_refs: list[str] = Field(default_factory=list)
    trigger_type: str | None = None
    exclude_ids: list[str] = Field(default_factory=list)


class ScoredIncident(BaseModel):
    id: str
    title: str
    final: float
    score_breakdown: dict[str, float]
    matched_on: list[str]
    flags: list[str]
    symptoms: list[str]
    root_cause: str | None
    resolution_steps: list[str]
    fix_worked: bool | None
    time_to_resolve_min: int | None
    services: list[str]


class RetrievalResult(BaseModel):
    incidents: list[ScoredIncident] = Field(default_factory=list)
    patterns: list[Pattern] = Field(default_factory=list)
    runbooks: list[Runbook] = Field(default_factory=list)


# --- Reasoning & Agent Analysis Models ---

class SimilarIncidentCitation(BaseModel):
    id: str
    why_similar: str
    differences: str


class Hypothesis(BaseModel):
    rank: int
    cause: str
    confidence: Literal["low", "medium", "high"]
    evidence_for: list[str] = Field(default_factory=list)
    evidence_against: list[str] = Field(default_factory=list)
    similar_incidents: list[SimilarIncidentCitation] = Field(default_factory=list)
    recommended_steps: list[str] = Field(default_factory=list)
    runbook_id: str | None = None
    risk_notes: str = ""


class Analysis(BaseModel):
    summary: str
    precedent_strength: Literal["strong", "partial", "none"]
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    what_to_check_next: list[str] = Field(default_factory=list)
    needs_human_decision: list[str] = Field(default_factory=list)
    dropped_citations: list[str] = Field(default_factory=list)


# --- Working Memory Event Models ---

class WorkingMemoryEvent(BaseModel):
    ts: str
    kind: str  # "alert", "log", "deploy", "message", "tool_result", "suggestion", "note", "resolve"
    source: str
    content: str = ""  # primary field used by working.py
    text: str = ""  # backwards-compat alias
    data: dict[str, Any] = Field(default_factory=dict)


class LiveContext(BaseModel):
    incident_id: str = ""
    live_id: str = ""  # backwards-compat alias
    title: str
    status: str = "open"
    started_at: str = ""
    services: list[str]
    events: list[WorkingMemoryEvent]
    hypotheses: list[str] = Field(default_factory=list)
    cue: "Cue | None" = None


# --- Feedback & Stats Models ---

class FeedbackCreate(BaseModel):
    suggestion_id: int | None = None
    runbook_id: str | None = None
    helpful: bool
    comment: str | None = None
    user_ref: str | None = None


class FeedbackRecord(BaseModel):
    id: int
    suggestion_id: int | None = None
    runbook_id: str | None = None
    helpful: bool
    comment: str | None = None
    user_ref: str | None = None
    created_at: datetime | None = None


class RunbookStats(BaseModel):
    id: str
    title: str
    success_count: int
    failure_count: int
    p: float


# --- Post-Mortem & Resolution Models ---

class IncidentResolution(BaseModel):
    root_cause: str
    steps: list[str] = Field(default_factory=list)
    runbook_ids: list[str] = Field(default_factory=list)
    worked: bool = True
    commit_or_deploy_ref: str | None = None
    user_ref: str | None = None


class PostmortemDraft(BaseModel):
    summary: str
    impact: str
    timeline: list[dict[str, str]] = Field(default_factory=list)
    root_cause: str
    contributing_factors: list[str] = Field(default_factory=list)
    what_worked: list[str] = Field(default_factory=list)
    what_did_not_work: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    markdown: str


class LiveIncident(BaseModel):
    id: str
    title: str
    status: Literal["open", "resolved", "postmortem_draft", "confirmed"] = "open"
    slack_channel: str | None = None
    slack_thread_ts: str | None = None
    created_at: datetime | None = None
    resolved_at: datetime | None = None
    resolution: dict[str, Any] | None = None
    postmortem_draft: dict[str, Any] | None = None


# --- Code Memory Models ---

class CodeChangeRecord(BaseModel):
    id: int | None = None
    repo: str
    commit_sha: str
    author: str | None = None
    committed_at: datetime | None = None
    message: str | None = None
    files: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    diff_summary: str | None = None
    emb: list[float] | None = None


class PRMatch(BaseModel):
    incident_id: str
    incident_title: str
    file_path: str
    role: str = "involved"
    weight: float = 1.0
    why_matched: str
    root_cause: str | None = None


class PRCheckResult(BaseModel):
    matches: list[PRMatch] = Field(default_factory=list)
    risk_level: Literal["high", "medium", "low"]
    summary: str
    what_to_double_check: list[str] = Field(default_factory=list)

