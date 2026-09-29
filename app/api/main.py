"""FastAPI application — REST API for the Incident Response Agent.

Routes (SPEC.md Section 10.9):
  GET  /healthz                     — health check
  POST /webhooks/alertmanager       — Alertmanager webhook
  POST /webhooks/pagerduty          — PagerDuty webhook
  POST /incidents                   — create live incident manually
  GET  /incidents/{id}              — get live incident context
  POST /incidents/{id}/events       — append event to working memory
  POST /incidents/{id}/investigate  — trigger investigation
  GET  /incidents/{id}/analysis     — get latest analysis
  POST /incidents/{id}/resolve      — resolve and write to long-term memory
  GET  /incidents/{id}/postmortem   — get post-mortem draft
  GET  /memory/search               — search past incidents
  GET  /runbooks/{id}               — get a runbook

Authentication: X-API-Key header required on all non-health routes.
"""
from __future__ import annotations

import uuid
from typing import Any

import redis
from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request, status
from pydantic import BaseModel

from app.config import get_settings
from app.db import get_pool
from app.logging import logger, setup_logging
from app.memory import working as wm
from app.models import Cue

setup_logging()

app = FastAPI(
    title="Incident Response Agent",
    description="Brain-inspired memory incident response assistant",
    version="0.2.0",
)

# ──────────────────────────────────────────────────────────────
# Auth middleware
# ──────────────────────────────────────────────────────────────

async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    settings = get_settings()
    if not x_api_key or x_api_key != settings.API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
        )


# ──────────────────────────────────────────────────────────────
# Pydantic request/response bodies
# ──────────────────────────────────────────────────────────────

class CreateIncidentRequest(BaseModel):
    title: str
    alert_text: str
    services: list[str] = []


class AppendEventRequest(BaseModel):
    kind: str = "note"
    content: str
    source: str = "human"


class ResolveRequest(BaseModel):
    root_cause: str
    steps_taken: list[str] = []
    runbook_worked: bool | None = None
    runbook_id: str | None = None


# ──────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────

def _make_incident_id() -> str:
    return f"INC-{uuid.uuid4().hex[:8].upper()}"


def _get_adapters() -> dict[str, Any]:
    settings = get_settings()
    if settings.ADAPTER_MODE == "mock":
        from app.adapters.mock import (
            MockCodeAdapter,
            MockDeployAdapter,
            MockLogAdapter,
            MockMetricsAdapter,
        )
        return {
            "logs": MockLogAdapter(),
            "metrics": MockMetricsAdapter(),
            "deploys": MockDeployAdapter(),
            "code": MockCodeAdapter(),
        }
    # Real adapters — stubs only; users extend these
    from app.adapters.mock import (
        MockCodeAdapter,
        MockDeployAdapter,
        MockLogAdapter,
        MockMetricsAdapter,
    )
    return {
        "logs": MockLogAdapter(),
        "metrics": MockMetricsAdapter(),
        "deploys": MockDeployAdapter(),
        "code": MockCodeAdapter(),
    }


def _run_investigation(incident_id: str, cue: Cue) -> None:
    """Background task: run the investigation agent and store the analysis."""
    from app.agent.investigate import investigate
    from app.memory.retrieval import HybridRetrievalEngine

    settings = get_settings()
    adapters = _get_adapters()

    engine = HybridRetrievalEngine()
    try:
        retrieval = engine.recall(cue)
    except Exception as exc:
        logger.warning("retrieval_failed", incident_id=incident_id, error=str(exc))
        from app.models import RetrievalResult
        retrieval = RetrievalResult(incidents=[], patterns=[], runbooks=[])

    llm_client = None
    if settings.ANTHROPIC_API_KEY:
        try:
            import anthropic
            llm_client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        except Exception:
            pass

    analysis = investigate(
        incident_id=incident_id,
        cue=cue,
        retrieval=retrieval,
        logs=adapters["logs"],
        metrics=adapters["metrics"],
        deploys=adapters["deploys"],
        code=adapters["code"],
        llm_client=llm_client,
    )

    # Store analysis in working memory as an event
    import json
    wm.append_event(
        incident_id,
        "suggestion",
        json.dumps(analysis.model_dump()),
        source="agent",
    )


# ──────────────────────────────────────────────────────────────
# Routes
# ──────────────────────────────────────────────────────────────

@app.get("/healthz", status_code=status.HTTP_200_OK)
def healthz() -> dict[str, Any]:
    settings = get_settings()
    db_ok = False
    redis_ok = False
    errors: list[str] = []

    try:
        pool = get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                res = cur.fetchone()
                if res:
                    db_ok = True
    except Exception as e:
        errors.append(f"postgres: {e!s}")

    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        if r.ping():
            redis_ok = True
    except Exception as e:
        errors.append(f"redis: {e!s}")

    if not db_ok or not redis_ok:
        logger.error("healthz_failed", postgres=db_ok, redis=redis_ok, errors=errors)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"postgres": db_ok, "redis": redis_ok, "errors": errors},
        )
    return {"status": "ok", "postgres": "healthy", "redis": "healthy"}


@app.post("/incidents", status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_api_key)])
def create_incident(
    body: CreateIncidentRequest,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    incident_id = _make_incident_id()
    wm.init_incident(
        incident_id,
        title=body.title,
        services=body.services,
        alert_text=body.alert_text,
    )
    cue = Cue(
        normalized_text=body.alert_text,
        alert_text=body.alert_text,
        services=body.services,
        error_messages=[],
    )
    wm.set_cue(incident_id, cue)
    background_tasks.add_task(_run_investigation, incident_id, cue)
    logger.info("incident_created", incident_id=incident_id, title=body.title)
    return {"incident_id": incident_id, "status": "open", "investigation": "started"}


@app.get("/incidents/{incident_id}", dependencies=[Depends(require_api_key)])
def get_incident(incident_id: str) -> dict[str, Any]:
    ctx = wm.get_live_context(incident_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found in working memory")
    return ctx.model_dump()


@app.post("/incidents/{incident_id}/events", dependencies=[Depends(require_api_key)])
def append_event(incident_id: str, body: AppendEventRequest) -> dict[str, str]:
    ctx = wm.get_live_context(incident_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    wm.append_event(incident_id, kind=body.kind, content=body.content, source=body.source)
    return {"status": "appended"}


@app.post("/incidents/{incident_id}/investigate", dependencies=[Depends(require_api_key)])
def trigger_investigation(incident_id: str, background_tasks: BackgroundTasks) -> dict[str, str]:
    ctx = wm.get_live_context(incident_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    if ctx.cue is None:
        raise HTTPException(status_code=400, detail="No cue set for this incident — cannot investigate")
    background_tasks.add_task(_run_investigation, incident_id, ctx.cue)
    return {"status": "investigation_started"}


@app.get("/incidents/{incident_id}/analysis", dependencies=[Depends(require_api_key)])
def get_analysis(incident_id: str) -> dict[str, Any]:
    import json

    ctx = wm.get_live_context(incident_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    # Find the latest "suggestion" event that contains valid JSON
    for event in reversed(ctx.events):
        if event.kind == "suggestion":
            content = event.content or event.text
            try:
                data = json.loads(content)
                if "summary" in data:
                    return data
            except json.JSONDecodeError:
                continue
    return {"status": "no_analysis_yet"}


@app.post("/incidents/{incident_id}/resolve", dependencies=[Depends(require_api_key)])
def resolve_incident(incident_id: str, body: ResolveRequest) -> dict[str, str]:
    ctx = wm.get_live_context(incident_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    resolution = body.root_cause
    wm.append_event(incident_id, "resolve", f"Root cause: {resolution}", source="human")
    wm.close_incident(incident_id, resolution)
    logger.info("incident_resolved", incident_id=incident_id, root_cause=resolution)
    return {"status": "resolved", "note": "Post-mortem ingestion requires approval via /postmortem"}


@app.get("/incidents/{incident_id}/postmortem", dependencies=[Depends(require_api_key)])
def get_postmortem(incident_id: str) -> dict[str, Any]:
    ctx = wm.get_live_context(incident_id)
    if ctx is None:
        raise HTTPException(status_code=404, detail=f"Incident {incident_id} not found")
    events_text = "\n".join(
        f"[{e.ts}] {e.kind}: {e.content or e.text}" for e in ctx.events
    )
    return {
        "incident_id": incident_id,
        "title": ctx.title,
        "status": ctx.status,
        "draft": (
            f"# Post-Mortem: {ctx.title}\n\n"
            f"## Timeline\n{events_text}\n\n"
            f"## Root Cause\n{ctx.hypotheses[-1] if ctx.hypotheses else 'TBD'}\n\n"
            f"## Action Items\n- [ ] Review and complete this post-mortem\n"
        ),
        "approved": False,
    }


@app.get("/memory/search", dependencies=[Depends(require_api_key)])
def memory_search(q: str, service: str = "", top_k: int = 5) -> dict[str, Any]:
    from app.core.normalize import normalize_text
    from app.memory.retrieval import HybridRetrievalEngine

    cue = Cue(
        normalized_text=normalize_text(q),
        alert_text=q,
        services=[service] if service else [],
        error_messages=[],
    )
    engine = HybridRetrievalEngine()
    try:
        result = engine.recall(cue, top_k=top_k)
        return {
            "incidents": [
                {
                    "id": si.id,
                    "title": si.title,
                    "score": si.final,
                    "score_breakdown": si.score_breakdown,
                }
                for si in result.incidents
            ],
            "patterns": [{"id": p.id, "name": p.name} for p in result.patterns],
            "runbooks": [{"id": rb.id, "title": rb.title} for rb in result.runbooks],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/runbooks/{runbook_id}", dependencies=[Depends(require_api_key)])
def get_runbook(runbook_id: str) -> dict[str, Any]:
    from app.memory.store import MemoryStore

    try:
        store = MemoryStore()
        rb = store.get_runbook(runbook_id)
        if rb is None:
            raise HTTPException(status_code=404, detail=f"Runbook {runbook_id} not found")
        return rb.model_dump()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ──────────────────────────────────────────────────────────────
# Webhooks
# ──────────────────────────────────────────────────────────────

@app.post("/webhooks/alertmanager", status_code=status.HTTP_202_ACCEPTED)
async def alertmanager_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Receive Alertmanager webhook payload and create a live incident."""
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    alerts = payload.get("alerts", [payload])
    created: list[str] = []
    for alert in alerts:
        if alert.get("status") != "firing" and alert.get("status") != "FIRING":
            # Skip resolved/pending
            if alert.get("status") in ("resolved", "inactive"):
                continue
        labels = alert.get("labels", alert.get("annotations", {}))
        title = labels.get("alertname", alert.get("alertname", "Unknown Alert"))
        service = labels.get("service", labels.get("job", "unknown"))
        description = labels.get("description", alert.get("description", alert.get("summary", "")))

        incident_id = _make_incident_id()
        wm.init_incident(incident_id, title=title, services=[service], alert_text=description)
        cue = Cue(
            normalized_text=description,
            alert_text=description,
            services=[service],
            error_messages=[],
        )
        wm.set_cue(incident_id, cue)
        background_tasks.add_task(_run_investigation, incident_id, cue)
        created.append(incident_id)

    return {"accepted": len(created), "incident_ids": created}


@app.post("/webhooks/pagerduty", status_code=status.HTTP_202_ACCEPTED)
async def pagerduty_webhook(request: Request, background_tasks: BackgroundTasks) -> dict[str, Any]:
    """Receive PagerDuty webhook payload."""
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    messages = payload.get("messages", [payload])
    created: list[str] = []
    for msg in messages:
        incident_data = msg.get("incident", msg)
        title = incident_data.get("title", "PagerDuty Alert")
        service_data = incident_data.get("service", {})
        service = service_data.get("name", "unknown") if isinstance(service_data, dict) else str(service_data)
        description = incident_data.get("body", {}).get("cef_details", {}).get("description", title)

        incident_id = _make_incident_id()
        wm.init_incident(incident_id, title=title, services=[service], alert_text=description)
        cue = Cue(
            normalized_text=description,
            alert_text=description,
            services=[service],
            error_messages=[],
        )
        wm.set_cue(incident_id, cue)
        background_tasks.add_task(_run_investigation, incident_id, cue)
        created.append(incident_id)

    return {"accepted": len(created), "incident_ids": created}
