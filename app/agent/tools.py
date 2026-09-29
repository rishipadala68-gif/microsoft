"""Read-only tool definitions for the Claude reasoning agent.

ALLOW_ACTIONS is a module-level constant that is always False.
No tool in this module may perform a write or state-changing action.
"""
from __future__ import annotations

from typing import Any

# ──────────────────────────────────────────────────────────────
# SAFETY CONSTANT — never change this to True
# ──────────────────────────────────────────────────────────────
ALLOW_ACTIONS: bool = False


# Anthropic tool_use schema definitions (passed to the Claude API)
TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "get_logs",
        "description": (
            "Fetch recent log lines for a service between two ISO timestamps. "
            "Returns a list of log entries. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Service name, e.g. 'payment-service'"},
                "start_iso": {"type": "string", "description": "ISO 8601 start time"},
                "end_iso": {"type": "string", "description": "ISO 8601 end time"},
                "filter_text": {"type": "string", "description": "Optional substring filter"},
                "limit": {"type": "integer", "description": "Max log lines to return (default 100)"},
            },
            "required": ["service", "start_iso", "end_iso"],
        },
    },
    {
        "name": "get_metrics",
        "description": (
            "Fetch a time-series metric for a service between two ISO timestamps. "
            "Returns [{ts, value}, ...]. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {"type": "string", "description": "Metric name, e.g. 'pg_connections_active'"},
                "start_iso": {"type": "string", "description": "ISO 8601 start time"},
                "end_iso": {"type": "string", "description": "ISO 8601 end time"},
                "step_seconds": {"type": "integer", "description": "Resolution in seconds (default 60)"},
            },
            "required": ["metric", "start_iso", "end_iso"],
        },
    },
    {
        "name": "get_recent_deploys",
        "description": (
            "List recent deployments for a service since a given timestamp. "
            "Returns [{service, version, commit, deployed_at, deployer, status}]. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "since_iso": {"type": "string", "description": "ISO 8601 lower bound"},
                "limit": {"type": "integer", "description": "Max records (default 10)"},
            },
            "required": ["service", "since_iso"],
        },
    },
    {
        "name": "get_commits_touching_files",
        "description": (
            "Find commits that modified specific file paths since a given timestamp. "
            "Useful for linking code changes to incidents. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "file_paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of file paths to check",
                },
                "since_iso": {"type": "string"},
                "limit": {"type": "integer"},
            },
            "required": ["file_paths", "since_iso"],
        },
    },
    {
        "name": "get_diff",
        "description": "Fetch the unified diff for a specific commit SHA. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "commit_sha": {"type": "string"},
                "file_path": {"type": "string", "description": "Optionally filter to one file"},
            },
            "required": ["commit_sha"],
        },
    },
    {
        "name": "get_service_dependencies",
        "description": (
            "Return the dependency graph for a service: "
            "its upstream and downstream services. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "depth": {"type": "integer", "description": "Graph depth (default 1)"},
            },
            "required": ["service"],
        },
    },
    {
        "name": "search_past_incidents",
        "description": (
            "Search the incident memory for past incidents similar to the given cue text. "
            "Returns top-k scored incidents. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "cue_text": {"type": "string", "description": "Free-text description of the symptoms"},
                "service": {"type": "string", "description": "Optional service filter"},
                "top_k": {"type": "integer", "description": "Number of results (default 5)"},
            },
            "required": ["cue_text"],
        },
    },
    {
        "name": "get_runbook",
        "description": "Fetch a specific runbook by its ID. Returns the runbook text. Read-only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "runbook_id": {"type": "string", "description": "Runbook ID, e.g. 'RB-db-pool-exhaustion'"},
            },
            "required": ["runbook_id"],
        },
    },
    {
        "name": "get_live_context",
        "description": (
            "Fetch the current live incident context from working memory (Redis), "
            "including timeline events, hypotheses, and services involved. Read-only."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "incident_id": {"type": "string"},
            },
            "required": ["incident_id"],
        },
    },
]
