import re
from typing import Any

from app.config import settings
from app.core.embeddings import get_embedder
from app.core.fingerprint import fingerprints
from app.core.normalize import normalize_text
from app.db import get_db_connection
from app.logging import logger
from app.memory.store import MemoryStore
from app.models import Cue, Pattern, RetrievalResult, ScoredIncident

STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "as", "at", "be", "because", "been", "before", "being", "below",
    "between", "both", "but", "by", "could", "did", "do", "does", "doing", "down",
    "during", "each", "few", "for", "from", "further", "had", "has", "have", "having",
    "he", "her", "here", "hers", "herself", "him", "himself", "his", "how", "i", "if",
    "in", "into", "is", "it", "its", "itself", "me", "more", "most", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought",
    "our", "ours", "ourselves", "out", "over", "own", "same", "she", "should", "so",
    "some", "such", "than", "that", "the", "their", "theirs", "them", "themselves",
    "then", "there", "these", "they", "this", "those", "through", "to", "too", "under",
    "until", "up", "very", "was", "we", "were", "what", "when", "where", "which",
    "while", "who", "whom", "why", "with", "would", "you", "your", "yours", "yourself",
}


def compute_final_score(
    vec: float,
    fts: float,
    fp: float,
    svc: float,
    code: float,
    incident_weight: float = 1.0,
    runbook_p: float = 0.5,
    fix_worked: bool | None = True,
    w_vec: float | None = None,
    w_fts: float | None = None,
    w_fp: float | None = None,
    w_svc: float | None = None,
    w_code: float | None = None,
) -> tuple[float, list[str]]:
    """
    Computes base and final score according to SPEC.md Section 10.6:
    base = W_VEC*vec + W_FTS*fts + W_FP*fp + W_SVC*svc + W_CODE*code
    final = base * incident.weight * (0.85 + 0.30 * runbook_p)
    If fix_worked is False: final *= 0.7 and add flag 'fix_did_not_work'.
    """
    wv = settings.W_VEC if w_vec is None else w_vec
    wf = settings.W_FTS if w_fts is None else w_fts
    wp = settings.W_FP if w_fp is None else w_fp
    ws = settings.W_SVC if w_svc is None else w_svc
    wc = settings.W_CODE if w_code is None else w_code

    base = (wv * vec) + (wf * fts) + (wp * fp) + (ws * svc) + (wc * code)
    final = base * incident_weight * (0.85 + 0.30 * runbook_p)

    flags = []
    if fix_worked is False:
        final *= 0.7
        flags.append("fix_did_not_work")

    return max(0.0, min(1.0, final)), flags


def compute_mismatch_flags(
    cue: Cue,
    inc_services: list[str],
    inc_trigger_type: str | None,
    inc_epoch: int,
    inc_weight: float,
    service_epochs: dict[str, int] | None = None,
) -> list[str]:
    """Computes deterministic mismatch flags (pattern separation)."""
    flags = []

    # 1. service_mismatch: no overlap with cue services
    if cue.services and inc_services:
        if not any(s in inc_services for s in cue.services):
            flags.append("service_mismatch")

    # 2. trigger_mismatch: both trigger types known and different
    if cue.trigger_type and inc_trigger_type:
        if cue.trigger_type.lower() != inc_trigger_type.lower():
            flags.append("trigger_mismatch")

    # 3. stale_architecture: incident epoch is below a cue service's current epoch
    if service_epochs and cue.services:
        for s in cue.services:
            current_epoch = service_epochs.get(s, 1)
            if inc_epoch < current_epoch:
                flags.append("stale_architecture")
                break

    # 4. old: recency weight below 0.6
    if inc_weight < 0.6:
        flags.append("old")

    return flags


def extract_distinctive_tokens(text: str, max_tokens: int = 12) -> list[str]:
    """Extracts distinctive tokens for full-text search, dropping placeholders and stop words."""
    cleaned = re.sub(r"<[a-zA-Z0-9_]+>", " ", text)
    tokens = re.findall(r"\b[a-zA-Z]{3,}\b", cleaned.lower())
    distinctive = [t for t in tokens if t not in STOP_WORDS]
    # Unique tokens preserving order
    return list(dict.fromkeys(distinctive))[:max_tokens]


class HybridRetrievalEngine:
    def __init__(self, store: MemoryStore | None = None):
        self.store = store or MemoryStore()
        self.embedder = get_embedder()

    def recall(
        self,
        cue: Cue,
        top_k: int = 3,
        candidates_limit: int = 20,
        mode: str = "hybrid",  # "hybrid" | "vector" | "keyword"
    ) -> RetrievalResult:
        """
        Recall past incidents, patterns, and runbooks matching the cue.
        Supports ablation modes: 'hybrid', 'vector', and 'keyword'.
        """
        # 1. Build normalized cue text & fingerprints
        norm_text = normalize_text(cue.text)
        all_fps = []
        for em in cue.error_messages:
            all_fps.extend(fingerprints(em))
        for st in cue.stack_traces:
            all_fps.extend(fingerprints(st))
        cue_fps = list(dict.fromkeys(all_fps))

        cue_emb = self.embedder.embed_query(norm_text if norm_text else "system incident outage")

        # 2. Candidate generation
        candidates: dict[str, dict[str, Any]] = {}

        try:
            with get_db_connection() as conn, conn.cursor() as cur:
                # Set ef_search for HNSW
                try:
                    cur.execute("SET LOCAL hnsw.ef_search = 100;")
                except Exception:
                    pass

                exclude_filter = "AND id <> ALL(%s)" if cue.exclude_ids else ""
                exclude_arg = [cue.exclude_ids] if cue.exclude_ids else []

                # A. Vector search (emb_symptom)
                if mode in ["hybrid", "vector"]:
                    cur.execute(
                        f"""
                        SELECT id, 1 - (emb_symptom <=> %s::vector) AS sim
                        FROM incidents
                        WHERE 1=1 {exclude_filter}
                        ORDER BY emb_symptom <=> %s::vector
                        LIMIT %s;
                        """,
                        [cue_emb] + exclude_arg + [cue_emb, candidates_limit],
                    )
                    for r in cur.fetchall():
                        cid = r["id"]
                        candidates.setdefault(cid, {})["vec"] = max(0.0, min(1.0, float(r["sim"])))

                # B. Full-text search (ts_rank_cd)
                if mode in ["hybrid", "keyword"]:
                    tokens = extract_distinctive_tokens(norm_text)
                    if tokens:
                        fts_query_str = " | ".join(tokens)
                        cur.execute(
                            f"""
                            SELECT id, ts_rank_cd(tsv, to_tsquery('english', %s)) AS rank
                            FROM incidents
                            WHERE tsv @@ to_tsquery('english', %s) {exclude_filter}
                            ORDER BY rank DESC
                            LIMIT %s;
                            """,
                            [fts_query_str, fts_query_str] + exclude_arg + [candidates_limit],
                        )
                        fts_rows = cur.fetchall()
                        max_fts = max([float(r["rank"]) for r in fts_rows], default=0.0)
                        for r in fts_rows:
                            cid = r["id"]
                            val = float(r["rank"]) / max_fts if max_fts > 0 else 0.0
                            candidates.setdefault(cid, {})["fts"] = val

                # C. Fingerprint exact match
                if mode == "hybrid" and cue_fps:
                    cur.execute(
                        f"""
                        SELECT id FROM incidents
                        WHERE error_fingerprints && %s::text[] {exclude_filter}
                        LIMIT %s;
                        """,
                        [cue_fps] + exclude_arg + [candidates_limit],
                    )
                    for r in cur.fetchall():
                        candidates.setdefault(r["id"], {})["fp"] = 1.0

                # D. Service Graph expansion
                if mode == "hybrid" and cue.services:
                    # 1-hop neighbors
                    cur.execute(
                        """
                        SELECT s2.name AS neighbor FROM services s1
                        JOIN service_dependencies d ON (s1.id = d.service_id AND s2.id = d.depends_on_id)
                                                    OR (s1.id = d.depends_on_id AND s2.id = d.service_id)
                        JOIN services s2 ON 1=1
                        WHERE s1.name = ANY(%s);
                        """,
                        (cue.services,),
                    )
                    neighbor_services = [r["neighbor"] for r in cur.fetchall()]

                    cur.execute(
                        f"""
                        SELECT id, services FROM incidents
                        WHERE (services && %s::text[] OR services && %s::text[]) {exclude_filter}
                        LIMIT %s;
                        """,
                        [cue.services, neighbor_services] + exclude_arg + [candidates_limit],
                    )
                    for r in cur.fetchall():
                        cid = r["id"]
                        svc_list = r["services"] or []
                        if any(s in svc_list for s in cue.services):
                            candidates.setdefault(cid, {})["svc"] = 1.0
                        else:
                            candidates.setdefault(cid, {})["svc"] = 0.5

                # E. Code / File match
                if mode == "hybrid" and cue.files:
                    cur.execute(
                        """
                        SELECT DISTINCT incident_id FROM incident_files
                        WHERE file_path = ANY(%s)
                        LIMIT %s;
                        """,
                        (cue.files, candidates_limit),
                    )
                    for r in cur.fetchall():
                        candidates.setdefault(r["incident_id"], {})["code"] = 1.0

                # Fetch full data for candidate incidents
                if not candidates:
                    return RetrievalResult(incidents=[], patterns=[], runbooks=[])

                cur.execute(
                    """
                    SELECT * FROM incidents WHERE id = ANY(%s);
                    """,
                    (list(candidates.keys()),),
                )
                inc_rows = {r["id"]: r for r in cur.fetchall()}

                # Fetch service epochs
                cur.execute("SELECT name, architecture_epoch FROM services;")
                svc_epochs = {r["name"]: r["architecture_epoch"] for r in cur.fetchall()}

        except Exception as e:
            logger.warn("retrieval_db_fallback", error=str(e))
            inc_rows = {}
            svc_epochs = {}

        # 3. Score and merge candidates
        scored_list: list[ScoredIncident] = []

        w_v = 1.0 if mode == "vector" else (0.0 if mode == "keyword" else None)
        w_f = 1.0 if mode == "keyword" else (0.0 if mode == "vector" else None)
        w_other = 0.0 if mode in ["vector", "keyword"] else None

        for cid, scores in candidates.items():
            inc_data = inc_rows.get(cid)
            if not inc_data:
                continue

            vec_s = scores.get("vec", 0.0)
            fts_s = scores.get("fts", 0.0)
            fp_s = scores.get("fp", 0.0)
            svc_s = scores.get("svc", 0.0)
            code_s = scores.get("code", 0.0)

            # Smoothed runbook probability (default 0.5)
            runbook_p = 0.5
            fix_worked = inc_data.get("fix_worked")
            weight = inc_data.get("weight", 1.0)

            final_score, fix_flags = compute_final_score(
                vec=vec_s,
                fts=fts_s,
                fp=fp_s,
                svc=svc_s,
                code=code_s,
                incident_weight=weight,
                runbook_p=runbook_p,
                fix_worked=fix_worked,
                w_vec=w_v,
                w_fts=w_f,
                w_fp=w_other,
                w_svc=w_other,
                w_code=w_other,
            )

            mismatch_flags = compute_mismatch_flags(
                cue=cue,
                inc_services=inc_data.get("services") or [],
                inc_trigger_type=inc_data.get("trigger_type"),
                inc_epoch=inc_data.get("architecture_epoch", 1),
                inc_weight=weight,
                service_epochs=svc_epochs,
            )
            all_flags = list(set(fix_flags + mismatch_flags))

            matched_on = []
            if vec_s >= 0.3:
                matched_on.append("vec")
            if fts_s >= 0.3:
                matched_on.append("fts")
            if fp_s >= 0.3:
                matched_on.append("fp")
            if svc_s >= 0.3:
                matched_on.append("svc")
            if code_s >= 0.3:
                matched_on.append("code")

            scored_list.append(ScoredIncident(
                id=cid,
                title=inc_data["title"],
                final=round(final_score, 4),
                score_breakdown={
                    "vec": round(vec_s, 4),
                    "fts": round(fts_s, 4),
                    "fp": round(fp_s, 4),
                    "svc": round(svc_s, 4),
                    "code": round(code_s, 4),
                },
                matched_on=matched_on,
                flags=all_flags,
                symptoms=inc_data.get("symptoms") or [],
                root_cause=inc_data.get("root_cause"),
                resolution_steps=inc_data.get("resolution_steps") or [],
                fix_worked=fix_worked,
                time_to_resolve_min=inc_data.get("time_to_resolve_min"),
                services=inc_data.get("services") or [],
            ))

        # Sort by final score descending
        scored_list.sort(key=lambda x: x.final, reverse=True)
        top_incidents = scored_list[:top_k]

        # 4. Patterns recall (similarity >= 0.60)
        recalled_patterns = []
        try:
            with get_db_connection() as conn, conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, title, rule_text, exceptions_text, trigger_signals,
                           recommended_checks, recommended_runbooks, member_incident_ids,
                           confidence, 1 - (emb <=> %s::vector) AS sim
                    FROM patterns
                    WHERE emb IS NOT NULL
                    ORDER BY emb <=> %s::vector
                    LIMIT 3;
                    """,
                    (cue_emb, cue_emb),
                )
                for r in cur.fetchall():
                    if r["sim"] is not None and float(r["sim"]) >= 0.60:
                        recalled_patterns.append(Pattern(
                            id=r["id"],
                            title=r["title"],
                            rule_text=r["rule_text"],
                            exceptions_text=r["exceptions_text"],
                            trigger_signals=r["trigger_signals"] or [],
                            recommended_checks=r["recommended_checks"] or [],
                            recommended_runbooks=r["recommended_runbooks"] or [],
                            member_incident_ids=r["member_incident_ids"] or [],
                            confidence=float(r["confidence"]) if r["confidence"] else None,
                        ))
        except Exception:
            pass

        # 5. Runbooks recall (from incidents, patterns, + top 2 direct emb similarity)
        runbook_ids = set()
        for inc in top_incidents:
            inc_row = inc_rows.get(inc.id)
            if inc_row and inc_row.get("runbook_ids"):
                runbook_ids.update(inc_row["runbook_ids"])
        for p in recalled_patterns:
            runbook_ids.update(p.recommended_runbooks)

        recalled_runbooks = []
        for rbid in runbook_ids:
            rb = self.store.get_runbook(rbid)
            if rb:
                recalled_runbooks.append(rb)

        return RetrievalResult(
            incidents=top_incidents,
            patterns=recalled_patterns,
            runbooks=recalled_runbooks,
        )
