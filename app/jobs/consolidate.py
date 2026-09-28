"""Nightly consolidation job.

Responsibilities (SPEC.md Section 10.10):
1. Cluster incidents by emb_full similarity → upsert `patterns` table.
2. Apply age/architecture decay to incident weights.
3. Report weak runbooks (success_rate < 0.3 with ≥ 5 uses).
4. Log consolidation stats.

Uses scikit-learn AgglomerativeClustering with cosine affinity.
Falls back to heuristic grouping when embeddings are not populated.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.db import get_pool
from app.logging import logger

# ──────────────────────────────────────────────────────────────
# Decay
# ──────────────────────────────────────────────────────────────

def apply_decay(conn: Any, half_life_days: int = 365) -> int:
    """Exponential decay on incident weights based on age. Returns rows updated."""
    sql = """
        UPDATE incidents
        SET weight = weight * pow(0.5, EXTRACT(EPOCH FROM (NOW() - started_at)) / (%(half_life_seconds)s))
        WHERE weight > 0.01
        RETURNING id
    """
    half_life_seconds = half_life_days * 86400
    with conn.cursor() as cur:
        cur.execute(sql, {"half_life_seconds": half_life_seconds})
        rows = cur.fetchall()
    return len(rows)


def recall_at_k_helper(returned_ids: list[str], expected_ids: list[str], k: int) -> float:
    """Recall@k = |returned[:k] ∩ expected| / |expected|. Exported for tests."""
    if not expected_ids:
        return 1.0
    top_k = set(returned_ids[:k])
    return len(top_k & set(expected_ids)) / len(expected_ids)


# ──────────────────────────────────────────────────────────────
# Clustering
# ──────────────────────────────────────────────────────────────

def _fetch_incidents_for_clustering(conn: Any, limit: int = 2000) -> list[dict[str, Any]]:
    sql = """
        SELECT id, title, services, root_cause_category,
               emb_full, weight, started_at
        FROM incidents
        WHERE emb_full IS NOT NULL
        ORDER BY started_at DESC
        LIMIT %(limit)s
    """
    with conn.cursor(row_factory=None) as cur:  # type: ignore[call-arg]
        cur.execute(sql, {"limit": limit})
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def _cosine_sim(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def cluster_incidents(
    incidents: list[dict[str, Any]],
    distance_threshold: float = 0.25,
    min_cluster: int = 3,
) -> list[list[str]]:
    """
    Group incidents into clusters using greedy cosine similarity.
    Returns list of clusters (each cluster = list of incident IDs).
    Falls back to category grouping when embeddings missing.
    """
    # Try scikit-learn first
    embeddings = []
    ids = []
    for inc in incidents:
        emb = inc.get("emb_full")
        if emb and len(emb) > 0:
            embeddings.append(emb)
            ids.append(inc["id"])

    if len(embeddings) >= min_cluster:
        try:
            import numpy as np
            from sklearn.cluster import AgglomerativeClustering

            X = np.array(embeddings, dtype=float)
            # Normalise rows for cosine distance
            norms = np.linalg.norm(X, axis=1, keepdims=True)
            norms[norms == 0] = 1.0
            X = X / norms

            model = AgglomerativeClustering(
                n_clusters=None,
                distance_threshold=distance_threshold,
                metric="cosine",
                linkage="average",
            )
            labels = model.fit_predict(X)

            cluster_map: dict[int, list[str]] = defaultdict(list)
            for inc_id, label in zip(ids, labels):
                cluster_map[int(label)].append(inc_id)

            return [members for members in cluster_map.values() if len(members) >= min_cluster]
        except ImportError:
            pass  # fall through to heuristic

    # Heuristic: group by root_cause_category
    cat_map: dict[str, list[str]] = defaultdict(list)
    for inc in incidents:
        cat = inc.get("root_cause_category") or "unknown"
        cat_map[cat].append(inc["id"])
    return [members for members in cat_map.values() if len(members) >= min_cluster]


def upsert_patterns(conn: Any, clusters: list[list[str]]) -> int:
    """Write cluster summaries into the patterns table. Returns count upserted."""
    if not clusters:
        return 0

    upserted = 0
    for members in clusters:
        # Fetch titles and root causes for summary
        placeholders = ",".join([f"'{m}'" for m in members[:50]])
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT title, root_cause_category, services FROM incidents WHERE id IN ({placeholders})"
            )
            rows = cur.fetchall()

        titles = [r[0] for r in rows if r[0]]
        categories = list({r[1] for r in rows if r[1]})
        services: list[str] = []
        for r in rows:
            if r[2]:
                services.extend(r[2])
        services = list(set(services))

        name = categories[0] if categories else "Unknown Pattern"
        rule_text = (
            f"Cluster of {len(members)} incidents in {', '.join(categories[:3])}. "
            f"Matching: {'; '.join(titles[:3])}" + (" ..." if len(titles) > 3 else "")
        )

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO patterns (title, rule_text, member_incident_ids, created_at, updated_at)
                VALUES (%(title)s, %(rule_text)s, %(members)s, NOW(), NOW())
                ON CONFLICT DO NOTHING
                """,
                {
                    "title": name[:200],
                    "rule_text": rule_text[:500],
                    "members": members,
                },
            )
        upserted += 1

    return upserted


# ──────────────────────────────────────────────────────────────
# Weak runbook report
# ──────────────────────────────────────────────────────────────

def report_weak_runbooks(conn: Any, min_uses: int = 5, threshold: float = 0.3) -> list[dict[str, Any]]:
    """Return runbooks with low success rate that have been used enough to matter."""
    sql = """
        SELECT id, title, success_count, failure_count
        FROM runbooks
        WHERE (success_count + failure_count) >= %(min_uses)s
          AND success_count::float / NULLIF(success_count + failure_count, 0) < %(threshold)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"min_uses": min_uses, "threshold": threshold})
        rows = cur.fetchall()

    weak = []
    for row in rows:
        rb_id, title, sc, fc = row[0], row[1], row[2], row[3]
        rate = sc / (sc + fc) if (sc + fc) > 0 else 0.0
        weak.append({"id": rb_id, "title": title, "success_rate": rate, "uses": sc + fc})
        logger.warning("weak_runbook", runbook_id=rb_id, success_rate=rate)
    return weak


# ──────────────────────────────────────────────────────────────
# Main entry point
# ──────────────────────────────────────────────────────────────

def run_consolidation(
    *,
    pool: Any = None,
    distance_threshold: float | None = None,
    min_cluster: int | None = None,
    half_life_days: int | None = None,
) -> dict[str, Any]:
    """Run the full nightly consolidation job. Returns a stats dict."""
    settings = get_settings()
    pool = pool or get_pool()
    dt = distance_threshold if distance_threshold is not None else settings.PATTERN_DISTANCE_THRESHOLD
    mc = min_cluster if min_cluster is not None else settings.PATTERN_MIN_CLUSTER
    hl = half_life_days if half_life_days is not None else settings.DECAY_HALF_LIFE_DAYS

    stats: dict[str, Any] = {
        "run_at": datetime.now(timezone.utc).isoformat(),
        "incidents_decayed": 0,
        "clusters_found": 0,
        "patterns_upserted": 0,
        "weak_runbooks": [],
    }

    try:
        with pool.connection() as conn:
            # 1. Decay
            stats["incidents_decayed"] = apply_decay(conn, half_life_days=hl)

            # 2. Cluster
            incidents = _fetch_incidents_for_clustering(conn)
            clusters = cluster_incidents(incidents, distance_threshold=dt, min_cluster=mc)
            stats["clusters_found"] = len(clusters)

            # 3. Upsert patterns
            stats["patterns_upserted"] = upsert_patterns(conn, clusters)

            # 4. Weak runbooks
            stats["weak_runbooks"] = report_weak_runbooks(conn)

            conn.commit()

    except Exception as exc:
        logger.error("consolidation_failed", error=str(exc))
        stats["error"] = str(exc)

    logger.info("consolidation_complete", **{k: v for k, v in stats.items() if k != "weak_runbooks"})
    return stats
