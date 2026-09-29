from app.code_memory.pr_check import check_pr, find_code_history, parse_files_from_diff


class MockPRCheckStore:
    def __init__(self):
        self.incident_files = [
            {
                "incident_id": "INC-0007",
                "file_path": "services/checkout/pool.py",
                "function_name": "get_connection",
                "role": "root_cause",
                "title": "Database connection pool exhaustion in checkout",
                "weight": 1.0,
                "root_cause": "Unreleased database connection in error block",
            },
            {
                "incident_id": "INC-0012",
                "file_path": "services/common/http_client.py",
                "function_name": "build_client",
                "role": "involved",
                "title": "TLS certificate expired",
                "weight": 0.8,
                "root_cause": "Expired SSL cert",
            },
        ]

    def get_incident_files_by_paths(self, file_paths: list[str]) -> list[dict]:
        results = []
        for rec in self.incident_files:
            for p in file_paths:
                if p == rec["file_path"] or p.split("/")[-1] == rec["file_path"].split("/")[-1]:
                    results.append(rec)
        return results

    def find_code_changes_by_emb_similarity(self, emb, threshold=0.8, limit=10):
        return []


def test_parse_files_from_diff():
    diff_text = """diff --git a/services/checkout/pool.py b/services/checkout/pool.py
--- a/services/checkout/pool.py
+++ b/services/checkout/pool.py
@@ -10,3 +10,4 @@
+    pass
diff --git a/config/settings.yaml b/config/settings.yaml
--- a/config/settings.yaml
+++ b/config/settings.yaml
"""
    files = parse_files_from_diff(diff_text)
    assert "services/checkout/pool.py" in files
    assert "config/settings.yaml" in files


def test_pr_check_root_cause_high_risk():
    store = MockPRCheckStore()

    # Touching pool.py which was the root cause of INC-0007
    result = check_pr(files=["services/checkout/pool.py"], store=store)

    assert result.risk_level == "high"
    assert len(result.matches) == 1
    assert result.matches[0].incident_id == "INC-0007"
    assert result.matches[0].role == "root_cause"
    assert any("CRITICAL" in check for check in result.what_to_double_check)


def test_pr_check_involved_medium_risk():
    store = MockPRCheckStore()

    # Touching http_client.py which was merely 'involved' in INC-0012
    result = check_pr(files=["services/common/http_client.py"], store=store)

    assert result.risk_level == "medium"
    assert len(result.matches) == 1
    assert result.matches[0].incident_id == "INC-0012"
    assert result.matches[0].role == "involved"


def test_pr_check_safe_low_risk():
    store = MockPRCheckStore()

    result = check_pr(files=["docs/architecture.md", "README.md"], store=store)

    assert result.risk_level == "low"
    assert len(result.matches) == 0


def test_find_code_history_tool():
    store = MockPRCheckStore()

    history = find_code_history("services/checkout/pool.py", store=store)

    assert history["has_outage_history"] is True
    assert len(history["past_incidents"]) == 1
    assert history["past_incidents"][0]["incident_id"] == "INC-0007"
    assert history["past_incidents"][0]["role"] == "root_cause"
