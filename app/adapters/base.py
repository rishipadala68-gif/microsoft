"""Base protocols for read-only external adapters.

All adapters are strictly read-only. No state-changing actions are permitted
(see SPEC.md Section 15 and the ALLOW_ACTIONS constant in tools.py).
"""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class LogAdapter(Protocol):
    """Fetch log lines from an observability backend (Loki, CloudWatch, etc.)."""

    def query(
        self,
        service: str,
        start_iso: str,
        end_iso: str,
        filter_text: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """Return log entries as list of {ts, level, msg, ...} dicts."""
        ...


@runtime_checkable
class MetricsAdapter(Protocol):
    """Fetch time-series metrics (Prometheus, Datadog, etc.)."""

    def query_range(
        self,
        metric: str,
        start_iso: str,
        end_iso: str,
        step_seconds: int = 60,
    ) -> list[dict[str, Any]]:
        """Return [{ts, value}, ...] samples."""
        ...

    def instant_query(self, metric: str, at_iso: str) -> float | None:
        """Return a single scalar value at a point in time."""
        ...


@runtime_checkable
class DeployAdapter(Protocol):
    """Fetch deployment records (ArgoCD, Spinnaker, CI/CD systems)."""

    def recent_deploys(
        self,
        service: str,
        since_iso: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Return [{service, version, commit, deployed_at, deployer, status}, ...]."""
        ...


@runtime_checkable
class CodeAdapter(Protocol):
    """Fetch code change history (GitHub, GitLab, Bitbucket)."""

    def commits_touching(
        self,
        file_paths: list[str],
        since_iso: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return commits that touched any of the given file paths."""
        ...

    def blame(self, file_path: str, line_start: int, line_end: int) -> list[dict[str, Any]]:
        """Return git blame entries for a line range."""
        ...

    def diff(self, commit_sha: str, file_path: str | None = None) -> str:
        """Return unified diff for a commit, optionally filtered to one file."""
        ...
