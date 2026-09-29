import re
from pathlib import Path

import git

from app.config import settings
from app.core.embeddings import get_embedder
from app.logging import logger
from app.memory.store import MemoryStore


def extract_touched_functions(diff_text: str) -> list[str]:
    """Parse @@ ... @@ <function context> hunk headers and touched functions from git diff -U0."""
    functions = set()
    for line in diff_text.splitlines():
        if line.startswith("@@"):
            match = re.search(
                r"@@\s+-[0-9,]+\s+\+[0-9,]+\s+@@\s*(?:def\s+|async\s+def\s+|class\s+|function\s+)?([a-zA-Z_][a-zA-Z0-9_]*)",
                line,
            )
            if match:
                fn = match.group(1).strip()
                if fn and fn not in {"def", "class", "async", "function"}:
                    functions.add(fn)
        elif line.startswith("+") or line.startswith("-"):
            match = re.search(
                r"^[+-]\s*(?:def\s+|async\s+def\s+|class\s+|function\s+)([a-zA-Z_][a-zA-Z0-9_]*)",
                line,
            )
            if match:
                fn = match.group(1).strip()
                if fn and fn not in {"def", "class", "async", "function"}:
                    functions.add(fn)
    return sorted(list(functions))


def generate_diff_summary(diff_text: str, commit_message: str) -> str:
    """Generate concise diff summary (max 60 words, LLM_MODEL_FAST) if LLM available."""
    if not diff_text.strip():
        return commit_message[:200]

    if settings.ANTHROPIC_API_KEY:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            resp = client.messages.create(
                model=settings.LLM_MODEL_FAST,
                max_tokens=150,
                system="Summarize the core technical impact and risk of this git commit diff in at most 60 words.",
                messages=[{"role": "user", "content": f"Commit: {commit_message}\n\nDiff:\n{diff_text[:3000]}"}],
            )
            for c in resp.content:
                if c.type == "text":
                    words = c.text.strip().split()
                    return " ".join(words[:60])
        except Exception:
            pass

    # Deterministic fallback summary
    first_lines = [line.strip() for line in diff_text.splitlines() if line.startswith("+") and not line.startswith("+++")]
    sample_changes = "; ".join(first_lines[:3]) if first_lines else "Code modification"
    summary = f"{commit_message.splitlines()[0]}: {sample_changes}"
    return " ".join(summary.split()[:60])


def index_repo(
    repo_path: str = ".",
    since: str | None = None,
    repo_name: str | None = None,
    generate_summaries: bool = False,
    store: MemoryStore | None = None,
) -> int:
    """
    Reads git log with --numstat and diffs, storing per commit:
    sha, author, date, message, changed files, touched function names.
    Embeds message + files.
    Diff summaries generated only when requested or linked.
    """
    mem_store = store or MemoryStore()
    embedder = get_embedder()
    resolved_path = Path(repo_path).resolve()
    name = repo_name or resolved_path.name

    try:
        repo = git.Repo(str(resolved_path))
    except Exception as e:
        logger.error("git_repo_open_failed", path=str(resolved_path), error=str(e))
        return 0

    rev = f"HEAD --since={since}" if since else "HEAD"
    try:
        commits = list(repo.iter_commits(rev=rev))
    except Exception:
        commits = list(repo.iter_commits())

    indexed_count = 0
    try:
        for commit in commits:
            sha = commit.hexsha
            author = f"{commit.author.name} <{commit.author.email}>" if commit.author else "Unknown"
            committed_at = commit.committed_datetime
            message = commit.message.strip()

            # Extract changed files
            files = list(commit.stats.files.keys())

            # Extract touched function names from diff
            functions = []
            diff_text = ""
            try:
                parent = commit.parents[0] if commit.parents else None
                if parent:
                    diffs = parent.diff(commit, create_patch=True, unified=0)
                else:
                    diffs = commit.diff(git.NULL_TREE, create_patch=True, unified=0)
                diff_patches = []
                for d in diffs:
                    if d.diff:
                        patch = d.diff.decode("utf-8", errors="replace") if isinstance(d.diff, bytes) else str(d.diff)
                        diff_patches.append(patch)
                diff_text = "\n".join(diff_patches)
                functions = extract_touched_functions(diff_text)
            except Exception:
                pass

            # Diff summary
            diff_summary = None
            if generate_summaries and diff_text:
                diff_summary = generate_diff_summary(diff_text, message)

            # Embed message + files
            embed_content = f"{message}\nFiles: {' '.join(files)}"
            emb = embedder.embed_documents([embed_content])[0]

            mem_store.upsert_code_change(
                repo=name,
                commit_sha=sha,
                author=author,
                committed_at=committed_at,
                message=message,
                files=files,
                functions=functions,
                diff_summary=diff_summary,
                emb=emb,
            )
            indexed_count += 1
    finally:
        repo.close()

    logger.info("indexed_repo_commits", repo=name, count=indexed_count)
    return indexed_count


def link_incident_to_code(
    incident_id: str,
    commit_sha: str,
    repo_name: str = "default",
    link_type: str = "caused_by",
    store: MemoryStore | None = None,
) -> None:
    """Link an incident to a commit sha."""
    mem_store = store or MemoryStore()
    mem_store.link_incident_code(incident_id, commit_sha, repo=repo_name, link_type=link_type)
