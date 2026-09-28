# Architecture Decision Log

All decisions use the format: **Decision** → **Rationale** → **Trade-offs**.

---

## D-001 — Dual embedding strategy per incident

**Decision:** Store two embeddings per incident: `emb_symptom` (title + symptoms + errors + services) and `emb_full` (everything including root cause and fix).

**Rationale:** Retrieval queries match against `emb_symptom` because the query is a cue — we know symptoms but not root cause yet. Clustering and near-dup detection use `emb_full` to capture semantic similarity of the entire incident story.

**Trade-offs:** Doubles embedding storage (~3 KB/incident at 384d float32). Acceptable at the expected scale (tens of thousands of incidents).

---

## D-002 — Mock embedding fallback (no sentence-transformers)

**Decision:** `LocalBGEEmbedder._mock_embed()` generates a deterministic 384-dim embedding from SHA256 hash when `sentence-transformers` is not installed.

**Rationale:** The dev/CI environment has disk constraints that prevent installing PyTorch. The mock produces stable, reproducible embeddings so all tests pass without the real model.

**Trade-offs:** Mock embeddings have no semantic meaning, so retrieval quality tests are not meaningful in the mock regime. Marked clearly in test output. Real deployments must set `EMBED_PROVIDER=local` with the model installed.

---

## D-003 — Hybrid retrieval: weighted multi-modal scoring

**Decision:** Final score = `0.35×vec + 0.15×fts + 0.20×fp + 0.15×svc + 0.15×code`, multiplied by incident weight and runbook success probability. Fix-did-not-work penalty ×0.7.

**Rationale:** Pure vector search misses exact error-code matches (FTS strength). Pure FTS misses paraphrased descriptions (vector strength). Fingerprint matching catches identical stack traces across different wording. Code file overlap links incidents to the same root-cause area.

**Trade-offs:** Weights are manually tuned; an automatic learning-to-rank approach would be more optimal but requires labelled training data we don't have yet.

---

## D-004 — psycopg3 (not an ORM)

**Decision:** Use `psycopg[binary,pool]` v3 with plain SQL, not SQLAlchemy or another ORM.

**Rationale:** SPEC.md Section 0.8 explicitly requires plain SQL. psycopg3 supports pgvector natively via `register_vector`, has an async-compatible connection pool, and keeps the codebase readable.

**Trade-offs:** More boilerplate for CRUD operations. Offset by keeping models small and having the `MemoryStore` class as a thin wrapper.

---

## D-005 — Redis for working memory, Postgres for long-term memory

**Decision:** Live incident state (events, hypotheses, cue) lives in Redis with 72h TTL after close. Approved post-mortems are written to Postgres via the ingestion pipeline.

**Rationale:** Mirrors the hippocampal consolidation model: fast short-term buffer → reviewed → committed to long-term store. Redis TTL prevents indefinite growth. Human approval gate prevents bad information from poisoning memory.

**Trade-offs:** If Redis restarts during an active incident, working memory is lost. Mitigation: events are also appended to the `suggestions` table in Postgres during investigation.

---

## D-006 — Heuristic extraction fallback

**Decision:** When `ANTHROPIC_API_KEY` is absent or LLM extraction fails, `extract.py` falls back to regex heuristics for extracting services, errors, and root causes from raw text.

**Rationale:** Keeps the system usable in offline/dev environments and prevents a hard dependency on a paid API for ingestion.

**Trade-offs:** Heuristic extraction quality is lower. Fields may be incomplete. Incidents ingested via heuristic are tagged `extraction_confidence=low` and may be filtered out of eval sets.

---

## D-007 — ALLOW_ACTIONS = False (hard-coded safety constant)

**Decision:** `app/agent/tools.py` defines `ALLOW_ACTIONS: bool = False` as a module-level constant. The `investigate()` function asserts this at every tool dispatch.

**Rationale:** SPEC.md Section 15 prohibits any state-changing action by the agent. A hard-coded constant (not an env var) prevents accidental misconfiguration.

**Trade-offs:** Cannot be toggled at runtime. This is intentional — any future remediation feature must be a separate, explicitly-reviewed module.

---

## D-008 — AgglomerativeClustering for consolidation

**Decision:** Nightly consolidation uses `sklearn.cluster.AgglomerativeClustering` with cosine distance and `distance_threshold` (no fixed number of clusters). Falls back to root-cause-category grouping when embeddings are unavailable.

**Rationale:** The number of distinct failure patterns is unknown and grows over time. Threshold-based hierarchical clustering adapts automatically. The heuristic fallback ensures consolidation still runs in mock/test environments.

**Trade-offs:** Cosine AgglomerativeClustering is O(n²) memory. Capped at 2000 most recent incidents per run to avoid OOM. Older incidents are re-clustered when they fall within the window.
