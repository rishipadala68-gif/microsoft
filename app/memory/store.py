import json
from datetime import datetime
from typing import Any

from app.db import get_db_connection
from app.models import (
    CodeChangeRecord,
    FeedbackRecord,
    Incident,
    LiveIncident,
    Pattern,
    Runbook,
)


class MemoryStore:
    def __init__(self):
        pass

    # --- Services & Topology ---

    def upsert_service(self, name: str, owner_team: str = "", description: str = "", architecture_epoch: int = 1) -> int:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO services (name, owner_team, description, architecture_epoch)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (name) DO UPDATE
                    SET owner_team = EXCLUDED.owner_team,
                        description = EXCLUDED.description,
                        architecture_epoch = EXCLUDED.architecture_epoch
                    RETURNING id;
                    """,
                    (name, owner_team, description, architecture_epoch),
                )
                service_id = cur.fetchone()["id"]
                conn.commit()
                return service_id

    def add_service_dependency(self, service_name: str, depends_on_name: str) -> None:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM services WHERE name = %s;", (service_name,))
            s_row = cur.fetchone()
            cur.execute("SELECT id FROM services WHERE name = %s;", (depends_on_name,))
            d_row = cur.fetchone()
            if s_row and d_row:
                cur.execute(
                    """
                        INSERT INTO service_dependencies (service_id, depends_on_id)
                        VALUES (%s, %s)
                        ON CONFLICT DO NOTHING;
                        """,
                    (s_row["id"], d_row["id"]),
                )
                conn.commit()

    def get_service_dependencies(self, service_name: str) -> dict[str, list[str]]:
        """Returns upstream (services that depend on it) and downstream (services it depends on)."""
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT id FROM services WHERE name = %s;", (service_name,))
            row = cur.fetchone()
            if not row:
                return {"downstream": [], "upstream": []}
            svc_id = row["id"]

            # downstream: services this service depends on
            cur.execute(
                """
                    SELECT s.name FROM services s
                    JOIN service_dependencies d ON s.id = d.depends_on_id
                    WHERE d.service_id = %s;
                    """,
                (svc_id,),
            )
            downstream = [r["name"] for r in cur.fetchall()]

            # upstream: services that depend on this service
            cur.execute(
                """
                    SELECT s.name FROM services s
                    JOIN service_dependencies d ON s.id = d.service_id
                    WHERE d.depends_on_id = %s;
                    """,
                (svc_id,),
            )
            upstream = [r["name"] for r in cur.fetchall()]

            return {"downstream": downstream, "upstream": upstream}

    # --- Runbooks ---

    def upsert_runbook(self, rb: Runbook) -> None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                emb_val = rb.emb if rb.emb else None
                cur.execute(
                    """
                    INSERT INTO runbooks (id, title, body_md, services, emb, success_count, failure_count)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                    SET title = EXCLUDED.title,
                        body_md = EXCLUDED.body_md,
                        services = EXCLUDED.services,
                        emb = COALESCE(EXCLUDED.emb, runbooks.emb),
                        updated_at = now();
                    """,
                    (rb.id, rb.title, rb.body_md, rb.services, emb_val, rb.success_count, rb.failure_count),
                )
                conn.commit()

    def get_runbook(self, rb_id: str) -> Runbook | None:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM runbooks WHERE id = %s;", (rb_id,))
            row = cur.fetchone()
            if row:
                return Runbook(
                    id=row["id"],
                    title=row["title"],
                    body_md=row["body_md"],
                    services=row["services"] or [],
                    emb=list(row["emb"]) if row.get("emb") is not None else None,
                    success_count=row["success_count"],
                    failure_count=row["failure_count"],
                    updated_at=row["updated_at"],
                )
            return None

    def list_runbooks(self) -> list[Runbook]:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM runbooks ORDER BY id;")
            return [
                Runbook(
                    id=r["id"],
                    title=r["title"],
                    body_md=r["body_md"],
                    services=r["services"] or [],
                    emb=list(r["emb"]) if r.get("emb") is not None else None,
                    success_count=r["success_count"],
                    failure_count=r["failure_count"],
                    updated_at=r["updated_at"],
                )
                for r in cur.fetchall()
            ]

    # --- Incidents ---

    def get_next_incident_id(self) -> str:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM incidents WHERE id LIKE 'INC-%' ORDER BY id DESC LIMIT 1;")
                row = cur.fetchone()
                if row:
                    last_id = row["id"]
                    num = int(last_id.split("-")[1])
                    return f"INC-{num + 1:04d}"
                return "INC-0001"

    def find_incident_by_doc_sha256(self, sha256_hash: str) -> str | None:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                    SELECT id FROM incidents
                    WHERE source_docs @> %s::jsonb
                    LIMIT 1;
                    """,
                (json.dumps([{"sha256": sha256_hash}]),),
            )
            row = cur.fetchone()
            return row["id"] if row else None

    def find_near_duplicate(self, emb_full: list[float], services: list[str], started_at) -> tuple[str, float] | None:
        """Finds if an existing incident has cosine similarity >= 0.97 and matching services."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, 1 - (emb_full <=> %s::vector) AS sim, services, started_at
                    FROM incidents
                    WHERE services && %s::text[]
                    ORDER BY emb_full <=> %s::vector
                    LIMIT 1;
                    """,
                    (emb_full, services, emb_full),
                )
                row = cur.fetchone()
                if row and row["sim"] is not None and row["sim"] >= 0.97:
                    return row["id"], float(row["sim"])
                return None

    def insert_incident(self, inc: Incident) -> None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO incidents (
                        id, title, status, severity, started_at, resolved_at,
                        time_to_resolve_min, symptoms, error_messages, error_fingerprints,
                        services, trigger_type, trigger_ref, root_cause, root_cause_category,
                        resolution_steps, runbook_ids, fix_worked, lessons, source_docs,
                        symptom_text, full_text, emb_symptom, emb_full, weight, architecture_epoch
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    ) ON CONFLICT (id) DO UPDATE
                    SET title = EXCLUDED.title,
                        status = EXCLUDED.status,
                        severity = EXCLUDED.severity,
                        symptoms = EXCLUDED.symptoms,
                        error_messages = EXCLUDED.error_messages,
                        error_fingerprints = EXCLUDED.error_fingerprints,
                        services = EXCLUDED.services,
                        root_cause = EXCLUDED.root_cause,
                        resolution_steps = EXCLUDED.resolution_steps,
                        runbook_ids = EXCLUDED.runbook_ids,
                        symptom_text = EXCLUDED.symptom_text,
                        full_text = EXCLUDED.full_text,
                        emb_symptom = EXCLUDED.emb_symptom,
                        emb_full = EXCLUDED.emb_full,
                        updated_at = now();
                    """,
                    (
                        inc.id, inc.title, inc.status, inc.severity, inc.started_at, inc.resolved_at,
                        inc.time_to_resolve_min, inc.symptoms, inc.error_messages, inc.error_fingerprints,
                        inc.services, inc.trigger_type, inc.trigger_ref, inc.root_cause, inc.root_cause_category,
                        inc.resolution_steps, inc.runbook_ids, inc.fix_worked, inc.lessons, json.dumps(inc.source_docs),
                        inc.symptom_text, inc.full_text, inc.emb_symptom, inc.emb_full, inc.weight, inc.architecture_epoch,
                    ),
                )
                conn.commit()

    def merge_incident(self, existing_id: str, new_inc: Incident) -> None:
        """Merge an incident into an existing one: union arrays, keep longer root-cause text."""
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM incidents WHERE id = %s;", (existing_id,))
                row = cur.fetchone()
                if not row:
                    return

                new_symptoms = list(set((row["symptoms"] or []) + new_inc.symptoms))
                new_errors = list(set((row["error_messages"] or []) + new_inc.error_messages))
                new_fps = list(set((row["error_fingerprints"] or []) + new_inc.error_fingerprints))
                new_services = list(set((row["services"] or []) + new_inc.services))
                new_steps = list(set((row["resolution_steps"] or []) + new_inc.resolution_steps))
                new_runbooks = list(set((row["runbook_ids"] or []) + new_inc.runbook_ids))

                old_rc = row["root_cause"] or ""
                new_rc = new_inc.root_cause or ""
                chosen_rc = new_rc if len(new_rc) > len(old_rc) else old_rc

                existing_docs = row["source_docs"] if isinstance(row["source_docs"], list) else json.loads(row["source_docs"] or "[]")
                merged_docs = existing_docs + [d for d in new_inc.source_docs if d not in existing_docs]

                cur.execute(
                    """
                    UPDATE incidents
                    SET symptoms = %s,
                        error_messages = %s,
                        error_fingerprints = %s,
                        services = %s,
                        resolution_steps = %s,
                        runbook_ids = %s,
                        root_cause = %s,
                        source_docs = %s,
                        updated_at = now()
                    WHERE id = %s;
                    """,
                    (
                        new_symptoms, new_errors, new_fps, new_services,
                        new_steps, new_runbooks, chosen_rc, json.dumps(merged_docs), existing_id
                    ),
                )
                conn.commit()

    def get_incident(self, inc_id: str) -> Incident | None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM incidents WHERE id = %s;", (inc_id,))
                r = cur.fetchone()
                if not r:
                    return None
                return Incident(
                    id=r["id"],
                    title=r["title"],
                    status=r["status"],
                    severity=r["severity"],
                    started_at=r["started_at"],
                    resolved_at=r["resolved_at"],
                    time_to_resolve_min=r["time_to_resolve_min"],
                    symptoms=r["symptoms"] or [],
                    error_messages=r["error_messages"] or [],
                    error_fingerprints=r["error_fingerprints"] or [],
                    services=r["services"] or [],
                    trigger_type=r["trigger_type"],
                    trigger_ref=r["trigger_ref"],
                    root_cause=r["root_cause"],
                    root_cause_category=r["root_cause_category"],
                    resolution_steps=r["resolution_steps"] or [],
                    runbook_ids=r["runbook_ids"] or [],
                    fix_worked=r["fix_worked"],
                    lessons=r["lessons"],
                    source_docs=r["source_docs"] if isinstance(r["source_docs"], list) else json.loads(r["source_docs"] or "[]"),
                    symptom_text=r["symptom_text"],
                    full_text=r["full_text"],
                    emb_symptom=list(r["emb_symptom"]) if r.get("emb_symptom") is not None else [],
                    emb_full=list(r["emb_full"]) if r.get("emb_full") is not None else [],
                    weight=r["weight"],
                    architecture_epoch=r["architecture_epoch"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )

    def count_incidents(self) -> int:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM incidents;")
            return cur.fetchone()["count"]

    def insert_incident_file(self, incident_id: str, file_path: str, function_name: str = "", role: str = "involved") -> None:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO incident_files (incident_id, file_path, function_name, role)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT DO NOTHING;
                    """,
                    (incident_id, file_path, function_name, role),
                )
                conn.commit()

    # --- Patterns ---

    def upsert_pattern(self, pat: Pattern) -> int:
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                emb_val = pat.emb if pat.emb else None
                cur.execute(
                    """
                    INSERT INTO patterns (
                        title, rule_text, exceptions_text, trigger_signals,
                        recommended_checks, recommended_runbooks, member_incident_ids,
                        confidence, emb
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id;
                    """,
                    (
                        pat.title, pat.rule_text, pat.exceptions_text, pat.trigger_signals,
                        pat.recommended_checks, pat.recommended_runbooks, pat.member_incident_ids,
                        pat.confidence, emb_val,
                    ),
                )
                pat_id = cur.fetchone()["id"]
                conn.commit()
                return pat_id

    def list_patterns(self) -> list[Pattern]:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM patterns ORDER BY id DESC;")
            return [
                Pattern(
                    id=r["id"],
                    title=r["title"],
                    rule_text=r["rule_text"],
                    exceptions_text=r["exceptions_text"],
                    trigger_signals=r["trigger_signals"] or [],
                    recommended_checks=r["recommended_checks"] or [],
                    recommended_runbooks=r["recommended_runbooks"] or [],
                    member_incident_ids=r["member_incident_ids"] or [],
                    confidence=r["confidence"],
                    emb=list(r["emb"]) if r.get("emb") is not None else None,
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
                for r in cur.fetchall()
            ]

    # --- Runbook & Feedback Stats ---

    def increment_runbook_stats(self, runbook_id: str, success: bool) -> None:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE runbooks
                SET success_count = success_count + CASE WHEN %s THEN 1 ELSE 0 END,
                    failure_count = failure_count + CASE WHEN %s THEN 0 ELSE 1 END,
                    updated_at = now()
                WHERE id = %s;
                """,
                (success, success, runbook_id),
            )
            conn.commit()

    def insert_feedback(
        self,
        suggestion_id: int | None,
        runbook_id: str | None,
        helpful: bool,
        comment: str | None = None,
        user_ref: str | None = None,
    ) -> int:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO feedback (suggestion_id, runbook_id, helpful, comment, user_ref)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (suggestion_id, runbook_id, helpful, comment, user_ref),
            )
            fb_id = cur.fetchone()["id"]
            conn.commit()
            return fb_id

    def get_feedback_stats(self) -> dict[str, Any]:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    count(*) as total,
                    count(*) FILTER (WHERE helpful = true) as helpful_count,
                    count(*) FILTER (WHERE helpful = false) as not_helpful_count
                FROM feedback;
                """
            )
            row = cur.fetchone()
            total = row["total"] if row else 0
            helpful = row["helpful_count"] if row else 0
            not_helpful = row["not_helpful_count"] if row else 0
            ratio = (helpful / total) if total > 0 else 0.0
            return {
                "total": total,
                "helpful": helpful,
                "not_helpful": not_helpful,
                "satisfaction_ratio": ratio,
            }

    def list_feedback(self, limit: int = 100) -> list[FeedbackRecord]:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, suggestion_id, runbook_id, helpful, comment, user_ref, created_at
                FROM feedback
                ORDER BY id DESC
                LIMIT %s;
                """,
                (limit,),
            )
            return [
                FeedbackRecord(
                    id=r["id"],
                    suggestion_id=r["suggestion_id"],
                    runbook_id=r["runbook_id"],
                    helpful=r["helpful"],
                    comment=r["comment"],
                    user_ref=r["user_ref"],
                    created_at=r["created_at"],
                )
                for r in cur.fetchall()
            ]

    # --- Live Incidents ---

    def upsert_live_incident(
        self,
        live_id: str,
        title: str,
        slack_channel: str | None = None,
        slack_thread_ts: str | None = None,
    ) -> None:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO live_incidents (id, title, status, slack_channel, slack_thread_ts)
                VALUES (%s, %s, 'open', %s, %s)
                ON CONFLICT (id) DO UPDATE
                SET title = EXCLUDED.title,
                    slack_channel = COALESCE(EXCLUDED.slack_channel, live_incidents.slack_channel),
                    slack_thread_ts = COALESCE(EXCLUDED.slack_thread_ts, live_incidents.slack_thread_ts);
                """,
                (live_id, title, slack_channel, slack_thread_ts),
            )
            conn.commit()

    def get_live_incident(self, live_id: str) -> LiveIncident | None:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM live_incidents WHERE id = %s;", (live_id,))
            r = cur.fetchone()
            if not r:
                return None
            res = r["resolution"] if isinstance(r["resolution"], dict) else (json.loads(r["resolution"]) if r["resolution"] else None)
            draft = r["postmortem_draft"] if isinstance(r["postmortem_draft"], dict) else (json.loads(r["postmortem_draft"]) if r["postmortem_draft"] else None)
            return LiveIncident(
                id=r["id"],
                title=r["title"],
                status=r["status"],
                slack_channel=r["slack_channel"],
                slack_thread_ts=r["slack_thread_ts"],
                created_at=r["created_at"],
                resolved_at=r["resolved_at"],
                resolution=res,
                postmortem_draft=draft,
            )

    def set_live_incident_resolution(self, live_id: str, resolution: dict[str, Any]) -> None:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE live_incidents
                SET resolution = %s,
                    status = 'resolved',
                    resolved_at = now()
                WHERE id = %s;
                """,
                (json.dumps(resolution), live_id),
            )
            conn.commit()

    def set_live_incident_postmortem(self, live_id: str, postmortem: dict[str, Any]) -> None:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                UPDATE live_incidents
                SET postmortem_draft = %s,
                    status = 'postmortem_draft'
                WHERE id = %s;
                """,
                (json.dumps(postmortem), live_id),
            )
            conn.commit()

    def update_live_incident_status(self, live_id: str, status: str) -> None:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE live_incidents SET status = %s WHERE id = %s;",
                (status, live_id),
            )
            conn.commit()

    # --- Code Memory ---

    def upsert_code_change(
        self,
        repo: str,
        commit_sha: str,
        author: str | None = None,
        committed_at: datetime | None = None,
        message: str | None = None,
        files: list[str] | None = None,
        functions: list[str] | None = None,
        diff_summary: str | None = None,
        emb: list[float] | None = None,
    ) -> int:
        with get_db_connection() as conn, conn.cursor() as cur:
            emb_val = emb if emb else None
            cur.execute(
                """
                INSERT INTO code_changes (repo, commit_sha, author, committed_at, message, files, functions, diff_summary, emb)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (repo, commit_sha) DO UPDATE
                SET author = EXCLUDED.author,
                    committed_at = EXCLUDED.committed_at,
                    message = EXCLUDED.message,
                    files = EXCLUDED.files,
                    functions = EXCLUDED.functions,
                    diff_summary = COALESCE(EXCLUDED.diff_summary, code_changes.diff_summary),
                    emb = COALESCE(EXCLUDED.emb, code_changes.emb)
                RETURNING id;
                """,
                (repo, commit_sha, author, committed_at, message, files or [], functions or [], diff_summary, emb_val),
            )
            change_id = cur.fetchone()["id"]
            conn.commit()
            return change_id

    def get_code_change_by_sha(self, commit_sha: str, repo: str = "default") -> CodeChangeRecord | None:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM code_changes WHERE commit_sha = %s;", (commit_sha,))
            r = cur.fetchone()
            if not r:
                return None
            return CodeChangeRecord(
                id=r["id"],
                repo=r["repo"],
                commit_sha=r["commit_sha"],
                author=r["author"],
                committed_at=r["committed_at"],
                message=r["message"],
                files=r["files"] or [],
                functions=r["functions"] or [],
                diff_summary=r["diff_summary"],
                emb=list(r["emb"]) if r.get("emb") is not None else None,
            )

    def count_code_changes(self) -> int:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM code_changes;")
            return cur.fetchone()["count"]

    def link_incident_code(
        self,
        incident_id: str,
        commit_sha: str,
        repo: str = "default",
        link_type: str = "caused_by",
    ) -> None:
        with get_db_connection() as conn, conn.cursor() as cur:
            # Check or create code_change
            cur.execute("SELECT id FROM code_changes WHERE commit_sha = %s;", (commit_sha,))
            row = cur.fetchone()
            if not row:
                cur.execute(
                    """
                    INSERT INTO code_changes (repo, commit_sha, message)
                    VALUES (%s, %s, %s)
                    RETURNING id;
                    """,
                    (repo, commit_sha, f"Referenced in {incident_id}"),
                )
                code_change_id = cur.fetchone()["id"]
            else:
                code_change_id = row["id"]

            cur.execute(
                """
                INSERT INTO incident_code_links (incident_id, code_change_id, link_type)
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING;
                """,
                (incident_id, code_change_id, link_type),
            )
            conn.commit()

    def get_incident_files_by_paths(self, file_paths: list[str]) -> list[dict[str, Any]]:
        if not file_paths:
            return []
        basenames = [p.replace("\\", "/").split("/")[-1] for p in file_paths]
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT f.incident_id, f.file_path, f.function_name, f.role, i.title, i.weight, i.root_cause
                FROM incident_files f
                JOIN incidents i ON f.incident_id = i.id
                WHERE f.file_path = ANY(%s) OR substring(f.file_path from '[^/]+$') = ANY(%s)
                ORDER BY CASE WHEN f.role = 'root_cause' THEN 1 ELSE 2 END, i.weight DESC;
                """,
                (file_paths, basenames),
            )
            return [dict(r) for r in cur.fetchall()]

    def find_code_changes_by_emb_similarity(
        self,
        emb: list[float],
        threshold: float = 0.8,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.id, c.repo, c.commit_sha, c.message, c.files, 1 - (c.emb <=> %s::vector) AS sim,
                       l.incident_id, l.link_type, i.title as incident_title, i.root_cause
                FROM code_changes c
                LEFT JOIN incident_code_links l ON c.id = l.code_change_id
                LEFT JOIN incidents i ON l.incident_id = i.id
                WHERE c.emb IS NOT NULL AND (1 - (c.emb <=> %s::vector)) >= %s
                ORDER BY sim DESC
                LIMIT %s;
                """,
                (emb, emb, threshold, limit),
            )
            return [dict(r) for r in cur.fetchall()]

    # --- Suggestions ---

    def insert_suggestion(
        self,
        live_incident_id: str,
        query_text: str,
        retrieved: Any,
        response: Any,
        model: str = "",
        latency_ms: int = 0,
    ) -> int:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO suggestions (live_incident_id, query_text, retrieved, response, model, latency_ms)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id;
                """,
                (
                    live_incident_id,
                    query_text,
                    json.dumps(retrieved) if not isinstance(retrieved, str) else retrieved,
                    json.dumps(response) if not isinstance(response, str) else response,
                    model,
                    latency_ms,
                ),
            )
            sugg_id = cur.fetchone()["id"]
            conn.commit()
            return sugg_id

    def update_suggestion_response(self, suggestion_id: int, response: dict[str, Any]) -> None:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE suggestions SET response = %s WHERE id = %s;",
                (json.dumps(response), suggestion_id),
            )
            conn.commit()

    def get_suggestion(self, suggestion_id: int) -> dict[str, Any] | None:
        with get_db_connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM suggestions WHERE id = %s;", (suggestion_id,))
            r = cur.fetchone()
            if not r:
                return None
            res = r["response"] if isinstance(r["response"], dict) else (json.loads(r["response"]) if r["response"] else {})
            ret = r["retrieved"] if isinstance(r["retrieved"], (dict, list)) else (json.loads(r["retrieved"]) if r["retrieved"] else {})
            return {
                "id": r["id"],
                "live_incident_id": r["live_incident_id"],
                "created_at": r["created_at"],
                "query_text": r["query_text"],
                "retrieved": ret,
                "response": res,
                "model": r["model"],
                "latency_ms": r["latency_ms"],
            }
