"""Working memory: Redis-backed live incident context.

Key structure (SPEC.md Section 9):
  inc:{id}:meta        → JSON hash (status, started_at, title, ...)
  inc:{id}:events      → Redis list of JSON-serialised WorkingMemoryEvent
  inc:{id}:services    → Redis set of service names
  inc:{id}:hypotheses  → Redis list of JSON-serialised hypothesis strings
  inc:{id}:cue         → JSON serialised Cue

TTL: 72 h from the time of incident closure. Open incidents have no TTL.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis as redis_lib

from app.config import get_settings
from app.models import Cue, LiveContext, WorkingMemoryEvent

_TTL_SECONDS = 72 * 3600  # 72 hours


def _client() -> redis_lib.Redis:  # type: ignore[type-arg]
    settings = get_settings()
    return redis_lib.from_url(settings.REDIS_URL, decode_responses=True)


# ──────────────────────────────────────────────────────────────
# Key helpers
# ──────────────────────────────────────────────────────────────

def _key_meta(incident_id: str) -> str:
    return f"inc:{incident_id}:meta"


def _key_events(incident_id: str) -> str:
    return f"inc:{incident_id}:events"


def _key_services(incident_id: str) -> str:
    return f"inc:{incident_id}:services"


def _key_hypotheses(incident_id: str) -> str:
    return f"inc:{incident_id}:hypotheses"


def _key_cue(incident_id: str) -> str:
    return f"inc:{incident_id}:cue"


# ──────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────

def init_incident(
    incident_id: str,
    title: str,
    services: list[str],
    alert_text: str,
    *,
    r: redis_lib.Redis | None = None,  # type: ignore[type-arg]
) -> None:
    """Initialise Redis working memory for a new live incident."""
    rc = r or _client()
    meta = {
        "incident_id": incident_id,
        "title": title,
        "status": "open",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "alert_text": alert_text,
    }
    rc.set(_key_meta(incident_id), json.dumps(meta))
    if services:
        rc.sadd(_key_services(incident_id), *services)


def append_event(
    incident_id: str,
    kind: str,
    content: str,
    source: str = "system",
    *,
    r: redis_lib.Redis | None = None,  # type: ignore[type-arg]
) -> None:
    """Append a WorkingMemoryEvent to the incident event log."""
    rc = r or _client()
    event = WorkingMemoryEvent(
        kind=kind,
        content=content,
        source=source,
        ts=datetime.now(timezone.utc).isoformat(),
    )
    rc.rpush(_key_events(incident_id), event.model_dump_json())


def add_hypothesis(
    incident_id: str,
    hypothesis: str,
    *,
    r: redis_lib.Redis | None = None,  # type: ignore[type-arg]
) -> None:
    """Add an agent hypothesis to the working memory."""
    rc = r or _client()
    rc.rpush(_key_hypotheses(incident_id), hypothesis)


def set_cue(
    incident_id: str,
    cue: Cue,
    *,
    r: redis_lib.Redis | None = None,  # type: ignore[type-arg]
) -> None:
    """Store the normalised Cue for a live incident."""
    rc = r or _client()
    rc.set(_key_cue(incident_id), cue.model_dump_json())


def get_live_context(
    incident_id: str,
    *,
    r: redis_lib.Redis | None = None,  # type: ignore[type-arg]
) -> LiveContext | None:
    """Load full live context from Redis. Returns None if the incident is not found."""
    rc = r or _client()
    meta_raw = rc.get(_key_meta(incident_id))
    if meta_raw is None:
        return None
    meta: dict[str, Any] = json.loads(meta_raw)

    events_raw: list[str] = rc.lrange(_key_events(incident_id), 0, -1)
    events = [WorkingMemoryEvent(**json.loads(e)) for e in events_raw]

    services: list[str] = list(rc.smembers(_key_services(incident_id)))

    hyp_raw: list[str] = rc.lrange(_key_hypotheses(incident_id), 0, -1)

    cue_raw = rc.get(_key_cue(incident_id))
    cue = Cue(**json.loads(cue_raw)) if cue_raw else None

    return LiveContext(
        incident_id=incident_id,
        title=meta.get("title", ""),
        status=meta.get("status", "open"),
        started_at=meta.get("started_at", ""),
        services=services,
        events=events,
        hypotheses=hyp_raw,
        cue=cue,
    )


def close_incident(
    incident_id: str,
    resolution: str,
    *,
    r: redis_lib.Redis | None = None,  # type: ignore[type-arg]
) -> None:
    """Mark incident closed and schedule 72h TTL on all keys."""
    rc = r or _client()
    meta_raw = rc.get(_key_meta(incident_id))
    if meta_raw:
        meta: dict[str, Any] = json.loads(meta_raw)
        meta["status"] = "resolved"
        meta["resolved_at"] = datetime.now(timezone.utc).isoformat()
        meta["resolution"] = resolution
        rc.set(_key_meta(incident_id), json.dumps(meta))

    for keyfn in (_key_meta, _key_events, _key_services, _key_hypotheses, _key_cue):
        rc.expire(keyfn(incident_id), _TTL_SECONDS)
