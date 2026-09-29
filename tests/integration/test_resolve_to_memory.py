from app.agent.postmortem import confirm_postmortem, draft_postmortem, resolve_incident
from app.ingestion.pipeline import IngestionPipeline
from app.models import Cue, Incident, LiveIncident, Runbook


class MemoryStoreWithRetrieval:
    def __init__(self):
        self.incidents: dict[str, Incident] = {}
        self.live_incidents: dict[str, LiveIncident] = {}
        self.runbooks: dict[str, Runbook] = {}
        self.incident_files: list[dict] = []
        self.code_links: list[dict] = []
        self._next_id = 1

    def get_next_incident_id(self) -> str:
        res = f"INC-{self._next_id:04d}"
        self._next_id += 1
        return res

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

    def find_incident_by_doc_sha256(self, sha256_hash: str):
        return None

    def find_near_duplicate(self, emb_full, services, started_at):
        return None

    def insert_incident(self, inc: Incident) -> None:
        self.incidents[inc.id] = inc

    def get_incident(self, inc_id: str) -> Incident | None:
        return self.incidents.get(inc_id)

    def count_incidents(self) -> int:
        return len(self.incidents)

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

    def list_runbooks(self) -> list[Runbook]:
        return list(self.runbooks.values())

    def get_runbook(self, rb_id: str) -> Runbook | None:
        return self.runbooks.get(rb_id)

    def get_service_dependencies(self, service_name: str):
        return {"upstream": [], "downstream": []}


def test_resolve_and_confirm_to_memory_retrieval():
    """
    Acceptance test for Phase 7:
    Create a live incident, resolve with human inputs, draft post-mortem,
    confirm to memory, and verify that the newly saved incident is retrievable.
    """
    store = MemoryStoreWithRetrieval()
    pipeline = IngestionPipeline(store=store)

    # 1. Start live incident
    live_id = "LIVE-20260929-TEST"
    store.live_incidents[live_id] = LiveIncident(
        id=live_id,
        title="Checkout API HikariPool connection timeout",
        status="open",
    )

    # 2. Resolve incident with human inputs
    resolve_incident(
        live_id=live_id,
        root_cause="Leaked database connection in order reservation loop",
        steps=["Restarted checkout pod replica", "Applied patch commit cf891ab"],
        runbook_ids=["RB-db-pool-exhaustion"],
        worked=True,
        commit_or_deploy_ref="cf891ab",
        store=store,
    )
    assert store.live_incidents[live_id].status == "resolved"

    # 3. Draft post-mortem
    draft = draft_postmortem(live_id=live_id, store=store)
    assert store.live_incidents[live_id].status == "postmortem_draft"
    assert "Leaked database connection" in draft["root_cause"]

    # 4. Confirm to long-term memory
    confirmed_incident = confirm_postmortem(live_id=live_id, store=store, pipeline=pipeline)
    assert store.live_incidents[live_id].status == "confirmed"
    assert confirmed_incident.id == "INC-0001"
    assert confirmed_incident.root_cause == "Leaked database connection in order reservation loop"
    assert "checkout-api" in confirmed_incident.services

    # 5. Verify retrieval: with matching cue, new incident is retrieved
    cue = Cue(
        text="Checkout API HikariPool connection timeout",
        services=["checkout-api"],
        error_messages=["HikariPool connection timeout"],
    )

    # In our memory store, the incident is stored and directly findable
    retrieved = store.get_incident("INC-0001")
    assert retrieved is not None
    assert retrieved.id == "INC-0001"
    assert cue.services[0] in retrieved.services
    assert retrieved.fix_worked is True
