import json

from app.db import get_db_connection
from app.models import Incident, Pattern, Runbook


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
