import re
from typing import Any

from app.config import settings
from app.core.embeddings import get_embedder
from app.logging import logger
from app.memory.store import MemoryStore
from app.models import PRCheckResult, PRMatch


def parse_files_from_diff(diff_text: str) -> list[str]:
    """Extract changed file paths from a unified diff."""
    files = set()
    for line in diff_text.splitlines():
        # Match git diff headers: +++ b/path/to/file.py or diff --git a/path b/path
        m = re.match(r"^\+\+\+\s+b/(.*)$", line)
        if m:
            files.add(m.group(1).strip())
            continue
        m2 = re.match(r"^diff\s+--git\s+a/.*?\s+b/(.*?)$", line)
        if m2:
            files.add(m2.group(1).strip())
    return sorted(list(files))


def check_pr(
    files: list[str] | None = None,
    diff_text: str | None = None,
    summarize: bool = False,
    store: MemoryStore | None = None,
) -> PRCheckResult:
    """
    PR check:
    For each changed file, returns past incidents whose incident_files include it
    (ranked by weight and role: root_cause above involved), plus incidents linked
    to commits with emb similarity >= 0.8 to the diff.
    Output: a risk report with incident IDs, why they match, and 'what to double-check' bullets.
    """
    mem_store = store or MemoryStore()
    target_files = list(files) if files else []
    if diff_text and not target_files:
        target_files = parse_files_from_diff(diff_text)

    matches: list[PRMatch] = []
    seen_keys = set()

    # 1. Match by changed files
    if target_files:
        try:
            file_records = mem_store.get_incident_files_by_paths(target_files)
            for rec in file_records:
                key = (rec["incident_id"], rec["file_path"])
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                role = rec.get("role", "involved")
                role_desc = "caused the outage as ROOT CAUSE" if role == "root_cause" else "was involved in the outage"
                why = f"File '{rec['file_path']}' {role_desc} in incident {rec['incident_id']}."

                matches.append(PRMatch(
                    incident_id=rec["incident_id"],
                    incident_title=rec.get("title") or rec["incident_id"],
                    file_path=rec["file_path"],
                    role=role,
                    weight=float(rec.get("weight", 1.0)),
                    why_matched=why,
                    root_cause=rec.get("root_cause"),
                ))
        except Exception as e:
            logger.debug("pr_check_file_query_error", error=str(e))

    # 2. Match by diff embedding similarity (>= 0.8)
    if diff_text and diff_text.strip():
        try:
            embedder = get_embedder()
            diff_emb = embedder.embed_documents([diff_text[:2000]])[0]
            similar_commits = mem_store.find_code_changes_by_emb_similarity(diff_emb, threshold=0.8, limit=5)
            for sc in similar_commits:
                inc_id = sc.get("incident_id")
                if inc_id:
                    matched_file = sc.get("files", ["unknown"])[0] if sc.get("files") else "diff"
                    key = (inc_id, matched_file)
                    if key not in seen_keys:
                        seen_keys.add(key)
                        sim = float(sc.get("sim", 0.8))
                        why = f"Diff has {sim:.2f} semantic similarity to past outage commit {sc.get('commit_sha', '')[:8]} linked to {inc_id}."
                        matches.append(PRMatch(
                            incident_id=inc_id,
                            incident_title=sc.get("incident_title") or inc_id,
                            file_path=matched_file,
                            role=sc.get("link_type", "involved"),
                            weight=1.0,
                            why_matched=why,
                            root_cause=sc.get("root_cause"),
                        ))
        except Exception as e:
            logger.debug("pr_check_diff_sim_error", error=str(e))

    # Sort matches: root_cause first, then weight descending
    matches.sort(key=lambda m: (0 if m.role == "root_cause" else 1, -m.weight))

    # Determine risk level
    if any(m.role == "root_cause" for m in matches):
        risk_level = "high"
    elif matches:
        risk_level = "medium"
    else:
        risk_level = "low"

    # Generate "what to double-check" bullets
    what_to_double_check = []
    if risk_level == "high":
        for m in matches:
            if m.role == "root_cause":
                cause_detail = f" ({m.root_cause})" if m.root_cause else ""
                what_to_double_check.append(
                    f"CRITICAL: '{m.file_path}' was the root cause of {m.incident_id}{cause_detail}. Verify connection limits, timeouts, and error handling."
                )
    elif risk_level == "medium":
        for m in matches[:3]:
            what_to_double_check.append(
                f"REVIEW: '{m.file_path}' was previously involved in {m.incident_id}. Double-check edge-case handling and regression coverage."
            )
    else:
        what_to_double_check.append("No historical outage files or high-similarity regressions detected in this change.")

    # Generate summary
    if summarize and settings.ANTHROPIC_API_KEY and matches:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            resp = client.messages.create(
                model=settings.LLM_MODEL_FAST,
                max_tokens=200,
                system="Summarize the outage risk of this PR in 2 sentences with actionable guidance.",
                messages=[{"role": "user", "content": f"Matches: {[m.model_dump() for m in matches]}"}],
            )
            for c in resp.content:
                if c.type == "text":
                    summary = c.text.strip()
                    return PRCheckResult(
                        matches=matches,
                        risk_level=risk_level,
                        summary=summary,
                        what_to_double_check=what_to_double_check,
                    )
        except Exception:
            pass

    if risk_level == "high":
        summary = f"HIGH RISK: This PR touches code that previously caused {len([m for m in matches if m.role == 'root_cause'])} major outage(s)!"
    elif risk_level == "medium":
        summary = f"MEDIUM RISK: Changed files are linked to {len(matches)} historical incident(s)."
    else:
        summary = "LOW RISK: No past incident records match the files in this change."

    return PRCheckResult(
        matches=matches,
        risk_level=risk_level,
        summary=summary,
        what_to_double_check=what_to_double_check,
    )


def find_code_history(
    file_path: str,
    function_name: str | None = None,
    store: MemoryStore | None = None,
) -> dict[str, Any]:
    """
    Read-only tool adapter for the reasoning agent to investigate past incident history
    and commits associated with a given source file or function.
    """
    mem_store = store or MemoryStore()
    incidents = []
    try:
        records = mem_store.get_incident_files_by_paths([file_path])
        for r in records:
            incidents.append({
                "incident_id": r["incident_id"],
                "title": r.get("title"),
                "role": r.get("role"),
                "function": r.get("function_name"),
                "root_cause": r.get("root_cause"),
            })
    except Exception as e:
        logger.debug("find_code_history_error", error=str(e))

    return {
        "file_path": file_path,
        "function_name": function_name,
        "past_incidents": incidents,
        "has_outage_history": len(incidents) > 0,
    }
