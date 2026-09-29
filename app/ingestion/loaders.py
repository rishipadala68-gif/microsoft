import json
from collections.abc import Generator
from pathlib import Path

from app.models import RawDoc


def load_folder(folder_path: str) -> Generator[RawDoc, None, None]:
    """Loads all .md, .txt, and .json files in a directory recursively."""
    path = Path(folder_path)
    if not path.exists():
        return

    for file_path in path.rglob("*"):
        if file_path.is_file() and file_path.suffix.lower() in [".md", ".txt", ".json"]:
            if file_path.name.startswith("_"):
                continue  # skip metadata labels like _labels.json
            try:
                content = file_path.read_text(encoding="utf-8")
                yield RawDoc(
                    source_type="file",
                    source_id=str(file_path),
                    text=content,
                    metadata={"filename": file_path.name, "path": str(file_path)},
                )
            except Exception:
                continue


def load_jira_export(file_path: str) -> Generator[RawDoc, None, None]:
    """Loads JIRA JSON export: one doc per ticket, including comments."""
    path = Path(file_path)
    if not path.exists():
        return

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        issues = data.get("issues", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
        for issue in issues:
            key = issue.get("key", "UNKNOWN-JIRA")
            summary = issue.get("fields", {}).get("summary", "")
            description = issue.get("fields", {}).get("description", "")
            comments_data = issue.get("fields", {}).get("comment", {}).get("comments", [])
            comments = "\n".join([f"Comment by {c.get('author', {}).get('displayName', 'User')}: {c.get('body', '')}" for c in comments_data])

            doc_text = f"JIRA Issue: {key}\nSummary: {summary}\n\nDescription:\n{description}\n\nComments:\n{comments}"
            yield RawDoc(
                source_type="jira",
                source_id=key,
                text=doc_text,
                metadata={"key": key, "summary": summary},
            )
    except Exception:
        return


def load_slack_export(file_path_or_dir: str) -> Generator[RawDoc, None, None]:
    """Groups Slack messages into threads; yields one doc per incident thread."""
    path = Path(file_path_or_dir)
    files = [path] if path.is_file() else list(path.rglob("*.json"))

    for f in files:
        try:
            messages = json.loads(f.read_text(encoding="utf-8"))
            if not isinstance(messages, list):
                continue

            # Group messages by thread_ts
            threads: dict[str, list[dict]] = {}
            for msg in messages:
                thread_ts = msg.get("thread_ts", msg.get("ts", ""))
                threads.setdefault(thread_ts, []).append(msg)

            for thread_ts, thread_msgs in threads.items():
                thread_text = "\n".join([f"[{m.get('user', 'user')}]: {m.get('text', '')}" for m in thread_msgs])
                lower = thread_text.lower()
                if any(kw in lower for kw in ["incident", "outage", "sev", "down", "503", "hikari"]):
                    yield RawDoc(
                        source_type="slack",
                        source_id=f"slack-{thread_ts}",
                        text=thread_text,
                        metadata={"thread_ts": thread_ts, "channel": f.stem},
                    )
        except Exception:
            continue


def load_notion_confluence_md(file_path_or_dir: str) -> Generator[RawDoc, None, None]:
    """Loads exported Notion or Confluence markdown files."""
    path = Path(file_path_or_dir)
    files = [path] if path.is_file() else list(path.rglob("*.md"))

    for f in files:
        try:
            content = f.read_text(encoding="utf-8")
            yield RawDoc(
                source_type="confluence_notion",
                source_id=str(f),
                text=content,
                metadata={"filename": f.name},
            )
        except Exception:
            continue
