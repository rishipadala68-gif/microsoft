"""Mock adapters that read pre-canned data from data/mock_env/scenarios/<MOCK_SCENARIO>/.

Each scenario directory must contain:
  alert.json   — the triggering alert
  deploys.json — list of recent deploys
  logs.jsonl   — one log entry per line (newline-delimited JSON)
  metrics.json — dict of metric_name → [{ts, value}, ...]
  commits.json — list of commits
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import get_settings


def _scenario_dir() -> Path:
    settings = get_settings()
    base = Path(settings.MOCK_SCENARIO_DIR)
    return base / settings.MOCK_SCENARIO


class MockLogAdapter:
    """Returns log lines from logs.jsonl, filtered by service and text."""

    def query(
        self,
        service: str,
        start_iso: str,
        end_iso: str,
        filter_text: str = "",
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        path = _scenario_dir() / "logs.jsonl"
        if not path.exists():
            return []
        results: list[dict[str, Any]] = []
        with path.open() as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                svc = entry.get("service", entry.get("svc", ""))
                if service and svc and service not in svc:
                    continue
                if filter_text and filter_text.lower() not in json.dumps(entry).lower():
                    continue
                results.append(entry)
                if len(results) >= limit:
                    break
        return results


class MockMetricsAdapter:
    """Returns metrics from metrics.json."""

    def _load(self) -> dict[str, list[dict[str, Any]]]:
        path = _scenario_dir() / "metrics.json"
        if not path.exists():
            return {}
        with path.open() as fh:
            return json.load(fh)

    def query_range(
        self,
        metric: str,
        start_iso: str,
        end_iso: str,
        step_seconds: int = 60,
    ) -> list[dict[str, Any]]:
        data = self._load()
        return data.get(metric, [])

    def instant_query(self, metric: str, at_iso: str) -> float | None:
        data = self._load()
        samples = data.get(metric, [])
        if samples:
            return float(samples[-1].get("value", 0))
        return None


class MockDeployAdapter:
    """Returns deploys from deploys.json."""

    def recent_deploys(
        self,
        service: str,
        since_iso: str,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        path = _scenario_dir() / "deploys.json"
        if not path.exists():
            return []
        with path.open() as fh:
            deploys: list[dict[str, Any]] = json.load(fh)
        if service:
            deploys = [d for d in deploys if service in d.get("service", "")]
        return deploys[:limit]


class MockCodeAdapter:
    """Returns commit data from commits.json."""

    def _load(self) -> list[dict[str, Any]]:
        path = _scenario_dir() / "commits.json"
        if not path.exists():
            return []
        with path.open() as fh:
            return json.load(fh)

    def commits_touching(
        self,
        file_paths: list[str],
        since_iso: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        commits = self._load()
        if not file_paths:
            return commits[:limit]
        results = []
        for c in commits:
            changed = c.get("changed_files", [])
            if any(fp in changed for fp in file_paths):
                results.append(c)
            if len(results) >= limit:
                break
        return results

    def blame(self, file_path: str, line_start: int, line_end: int) -> list[dict[str, Any]]:
        commits = self._load()
        return [{"file": file_path, "lines": f"{line_start}-{line_end}", "commit": c} for c in commits[:3]]

    def diff(self, commit_sha: str, file_path: str | None = None) -> str:
        commits = self._load()
        for c in commits:
            if c.get("sha", "").startswith(commit_sha[:7]):
                return c.get("diff", f"# No diff stored for {commit_sha}")
        return f"# commit {commit_sha} not found in mock data"
