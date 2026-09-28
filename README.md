# Incident Response Agent with Brain-Inspired Memory

An AI-powered assistant for on-call engineers inspired by the human brain's memory systems (working memory in Redis, episodic memory in Postgres with `pgvector`, pattern separation, consolidation into semantic patterns, procedural runbook stats, and code memory).

---

## Team Division & Branch Strategy

The project is divided into **5 distinct parts**, each assigned to a dedicated branch for individual team members:

| Part / Person | Branch Name | Scope & Phases Covered | Key Responsibilities |
|---|---|---|---|
| **Person 1 / Part 1** | `person-1/part-1-foundation-and-memory` | **Phase 0, 1, 2** (Scaffold, Core Utilities, Episodic Ingestion) | Docker Compose, DB schema (pgvector), text normalisation, redaction, stack-trace fingerprinting, BGE-small embeddings, data loaders, extraction pipeline, synthetic seed data & runbooks |
| **Person 2 / Part 2** | `person-2/part-2-hybrid-retrieval` | **Phase 3** (The Hippocampus — Hybrid Retrieval Engine) | Multi-modal candidate retrieval (Vector HNSW + FTS + Fingerprint + Graph + Code), weighted fusion scoring, pattern separation mismatch flags, and `cli ask` breakdown table |
| **Person 3 / Part 3** | `person-3/part-3-reasoning-agent` | **Phase 4, 5** (Working Memory, Reasoning Agent & REST API) | Redis working memory manager, read-only observability adapters (Mock scenarios A–D + Prometheus/Loki/GitHub), Claude ReAct loop, anti-hallucination citation validation, FastAPI REST API & webhooks |
| **Person 4 / Part 4** | `person-4/part-4-interfaces-and-learning` | **Phase 6, 7, 8** (Slack Bot, Post-Mortem Writeback & Code Memory) | Slack Bolt Socket Mode bot (Block Kit UI), resolve & post-mortem draft generation, human approval flow, writeback to long-term memory, Laplace-smoothed runbook stats, Git indexer & `cli pr-check` |
| **Person 5 / Part 5** | `person-5/part-5-consolidation-and-eval` | **Phase 9, 10, 11** (Consolidation, Scientific Evaluation & Hardening) | Nightly semantic clustering (`AgglomerativeClustering`), rule induction, recency decay, evaluation harness (`eval/cases.jsonl`), keyword vs. vector vs. hybrid ablation report, system stats, CI/CD & documentation |

---

## 5-Part Architectural Mapping

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ PART 1: Foundation & Long-Term Memory (Person 1)                            │
│  • Scaffold, DB (pgvector), Redis, Core utilities, Embeddings, Ingestion   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
┌──────────────────────────────────────▼──────────────────────────────────────┐
│ PART 2: The Hippocampus — Hybrid Retrieval Engine (Person 2)                 │
│  • Multi-modal candidate retrieval, scoring, mismatch flags, `cli ask`     │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
┌──────────────────────────────────────▼──────────────────────────────────────┐
│ PART 3: Working Memory & Live Reasoning Agent (Person 3)                    │
│  • Redis working memory, mock adapters (A–D), tool loop, REST API, webhooks │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
┌──────────────────────────────────────▼──────────────────────────────────────┐
│ PART 4: Closed-Loop Learning, Slack & Code Memory (Person 4)                │
│  • Slack Socket Mode bot, resolve & post-mortem writeback, Git PR check     │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
┌──────────────────────────────────────▼──────────────────────────────────────┐
│ PART 5: Consolidation, Scientific Evaluation & Hardening (Person 5)         │
│  • Pattern clustering, ablation benchmark, CI/CD, docs & demo readiness    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Specification

Please see [SPEC.md](SPEC.md) for the complete, authoritative specification and working agreement.
