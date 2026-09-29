import tempfile

import git

from app.code_memory.git_indexer import extract_touched_functions, index_repo
from app.models import CodeChangeRecord


class MockGitStore:
    def __init__(self):
        self.code_changes: list[CodeChangeRecord] = []

    def upsert_code_change(
        self, repo, commit_sha, author=None, committed_at=None,
        message=None, files=None, functions=None, diff_summary=None, emb=None,
    ) -> int:
        idx = len(self.code_changes) + 1
        self.code_changes.append(CodeChangeRecord(
            id=idx,
            repo=repo,
            commit_sha=commit_sha,
            author=author,
            committed_at=committed_at,
            message=message,
            files=files or [],
            functions=functions or [],
            diff_summary=diff_summary,
            emb=emb,
        ))
        return idx


def test_extract_touched_functions_from_hunk_headers():
    diff_sample = """
@@ -10,6 +10,8 @@ def handle_checkout(order_id: str):
     logger.info("checking out")
@@ -45,3 +47,6 @@ async def process_payment(amount: float):
     return True
@@ -102 +105,4 @@ class OrderProcessor:
     pass
"""
    funcs = extract_touched_functions(diff_sample)
    assert "handle_checkout" in funcs
    assert "process_payment" in funcs
    assert "OrderProcessor" in funcs


def test_index_repo_commits():
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Initialize temp git repo
        repo = git.Repo.init(tmp_dir)

        # Commit 1
        file1 = f"{tmp_dir}/service.py"
        with open(file1, "w", encoding="utf-8") as f:
            f.write("def initialize_db():\n    pass\n")
        repo.index.add([file1])
        c1 = repo.index.commit("feat: initial db setup")

        # Commit 2
        with open(file1, "a", encoding="utf-8") as f:
            f.write("\ndef query_users():\n    return []\n")
        repo.index.add([file1])
        c2 = repo.index.commit("feat: add query_users")
        repo.close()

        store = MockGitStore()
        indexed = index_repo(repo_path=tmp_dir, store=store)

        assert indexed >= 2
        shas = [cc.commit_sha for cc in store.code_changes]
        assert c1.hexsha in shas
        assert c2.hexsha in shas

        # Verify functions were extracted from diff
        user_commit = next(cc for cc in store.code_changes if cc.commit_sha == c2.hexsha)
        assert "query_users" in user_commit.functions
        assert "service.py" in user_commit.files
