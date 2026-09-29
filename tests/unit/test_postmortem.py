from app.agent.postmortem import confirm_postmortem, draft_postmortem, resolve_incident
from app.ingestion.pipeline import IngestionPipeline
from app.models import Incident, LiveIncident, Runbook


class MockPostmortemStore:
    def __init__(self):
        self.live_incidents: dict[str, LiveIncident] = {}
        self.incidents: dict[str, Incident] = {}
        self.runbooks: dict[str, Runbook] = {}
        self.incident_files: list[dict] = []
        self.code_links: list[dict] = []
        self._next_inc_id = 1

    def set_live_incident_resolution(self, live_id: str, resolution: dict) -> None:
        if live_id not in self.live_incidents:
            self.live_incidents[live_id] = LiveIncident(id=live_id, title="Test Incident")
        self.live_incidents[live_id].resolution = resolution
        self.live_incidents[live_id].status = "resolved"

    def get_live_incident(self, live_id: str) -> LiveIncident | None:
        return self.live_incidents.get(live_id)

    def set_live_incident_postmortem(self, live_id: str, postmortem: dict) -> None:
        if live_id in self.live_incidents:
            self.live_incidents[live_id].postmortem_draft = postmortem
            self.live_incidents[live_id].status = "postmortem_draft"

    def update_live_incident_status(self, live_id: str, status: str) -> None:
        if live_id in self.live_incidents:
            self.live_incidents[live_id].status = status

    def get_next_incident_id(self) -> str:
        res = f"INC-{self._next_inc_id:04d}"
        self._next_inc_id += 1
        return res

    def find_incident_by_doc_sha256(self, sha256_hash: str):
        return None

    def find_near_duplicate(self, emb_full, services, started_at):
        return None

    def insert_incident(self, inc: Incident) -> None:
        self.incidents[inc.id] = inc

    def get_incident(self, inc_id: str) -> Incident | None:
        return self.incidents.get(inc_id)

    def insert_incident_file(self, incident_id: str, file_path: str, function_name: str = "", role: str = "involved") -> None:
        self.incident_files.append({"incident_id": incident_id, "file_path": file_path, "role": role})

    def link_incident_code(self, incident_id: str, commit_sha: str, repo: str = "default", link_type: str = "caused_by") -> None:
        self.code_links.append({"incident_id": incident_id, "commit_sha": commit_sha, "link_type": link_type})

    def increment_runbook_stats(self, runbook_id: str, success: bool) -> None:
        if runbook_id in self.runbooks:
            if success:
                self.runbooks[runbook_id].success_count += 1
            else:
                self.runbooks[runbook_id].failure_count += 1

    def upsert_service(self, name: str, **kwargs):
        pass


def test_resolve_incident_flow():
    store = MockPostmortemStore()
    live_id = "LIVE-20260929-001"
    store.live_incidents[live_id] = LiveIncident(id=live_id, title="Checkout latency spike")

    res = resolve_incident(
        live_id=live_id,
        root_cause="Connection leak in checkout-api db pool",
        steps=["Restart pod", "Scale connection pool"],
        runbook_ids=["RB-db-pool-exhaustion"],
        worked=True,
        commit_or_deploy_ref="commit-xyz789",
        store=store,
    )

    assert res["root_cause"] == "Connection leak in checkout-api db pool"
    assert res["worked"] is True
    assert store.live_incidents[live_id].status == "resolved"


def test_draft_postmortem_human_fields_override():
    store = MockPostmortemStore()
    live_id = "LIVE-20260929-002"
    store.live_incidents[live_id] = LiveIncident(
        id=live_id,
        title="Payment gateway timeout",
        status="resolved",
        resolution={
            "root_cause": "HUMAN_SPECIFIED_ROOT_CAUSE: Third party TLS certificate expired",
            "steps": ["Renewed certificate via certbot", "Reloaded ingress proxy"],
            "runbook_ids": ["RB-cert-expiry"],
            "worked": True,
        },
    )

    draft = draft_postmortem(live_id=live_id, store=store)

    assert draft["root_cause"] == "HUMAN_SPECIFIED_ROOT_CAUSE: Third party TLS certificate expired"
    assert "Renewed certificate via certbot" in draft["what_worked"]
    assert "## Summary" in draft["markdown"]
    assert "## Root Cause" in draft["markdown"]
    assert store.live_incidents[live_id].status == "postmortem_draft"


def test_confirm_postmortem_writes_to_memory():
    store = MockPostmortemStore()
    store.runbooks["RB-db-pool-exhaustion"] = Runbook(
        id="RB-db-pool-exhaustion",
        title="DB Pool Exhaustion",
        body_md="",
        success_count=0,
        failure_count=0,
    )

    live_id = "LIVE-20260929-003"
    store.live_incidents[live_id] = LiveIncident(
        id=live_id,
        title="Database connection exhaustion in checkout-api",
        status="postmortem_draft",
        resolution={
            "root_cause": "Unclosed cursor in checkout transaction loop",
            "steps": ["Applied hotfix PR #42", "Rolled deployment"],
            "runbook_ids": ["RB-db-pool-exhaustion"],
            "worked": True,
            "commit_or_deploy_ref": "deadbeef123",
        },
        postmortem_draft={
            "summary": "Checkout API suffered connection pool exhaustion due to leaked connection cursors.",
            "markdown": "# Post-Mortem: Database connection exhaustion in checkout-api\n\n## Root Cause\nUnclosed cursor in checkout loop\n\ncheckout-api connection timeout",
        },
    )

    pipeline = IngestionPipeline(store=store)
    incident = confirm_postmortem(live_id=live_id, store=store, pipeline=pipeline)

    assert incident.id == "INC-0001"
    assert incident.title == "Database connection exhaustion in checkout-api"
    assert incident.root_cause == "Unclosed cursor in checkout transaction loop"
    assert store.live_incidents[live_id].status == "confirmed"

    # Verify code link was created for commit_or_deploy_ref
    assert len(store.code_links) == 1
    assert store.code_links[0]["commit_sha"] == "deadbeef123"
    assert store.code_links[0]["link_type"] == "fixed_by"

    # Verify runbook stats updated on resolve
    assert store.runbooks["RB-db-pool-exhaustion"].success_count == 1
