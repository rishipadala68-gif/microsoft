from app.ingestion.pipeline import IngestionPipeline
from app.models import Incident, RawDoc


class InMemoryStore:
    """Lightweight in-memory store for integration testing pipeline idempotency."""
    def __init__(self):
        self.incidents: dict[str, Incident] = {}
        self.services: set[str] = set()
        self.files: list[dict] = []
        self._next_id = 1

    def get_next_incident_id(self) -> str:
        res = f"INC-{self._next_id:04d}"
        self._next_id += 1
        return res

    def find_incident_by_doc_sha256(self, sha256_hash: str) -> str | None:
        for inc_id, inc in self.incidents.items():
            for doc in inc.source_docs:
                if doc.get("sha256") == sha256_hash:
                    return inc_id
        return None

    def find_near_duplicate(self, emb_full, services, started_at):
        return None

    def insert_incident(self, inc: Incident) -> None:
        self.incidents[inc.id] = inc

    def merge_incident(self, existing_id: str, new_inc: Incident) -> None:
        pass

    def insert_incident_file(self, incident_id: str, file_path: str, function_name: str = "", role: str = "involved") -> None:
        self.files.append({"incident_id": incident_id, "file_path": file_path})

    def upsert_service(self, name: str, **kwargs):
        self.services.add(name)

    def count_incidents(self) -> int:
        return len(self.incidents)


def test_ingest_idempotency():
    store = InMemoryStore()
    pipeline = IngestionPipeline(store=store, review_queue_dir="/tmp/test_review_queue")

    doc1 = RawDoc(
        source_type="postmortem",
        source_id="test_inc_1",
        text="# Incident: Database connection leak in checkout-api\n\nSymptoms: 503s\nError: HikariPool connection timeout\nRoot Cause: pool exhaustion",
    )

    # First ingestion
    id1 = pipeline.ingest_doc(doc1)
    assert id1 == "INC-0001"
    assert store.count_incidents() == 1

    # Second ingestion with identical document
    id2 = pipeline.ingest_doc(doc1)
    assert id2 == "INC-0001"
    # Count must remain unchanged
    assert store.count_incidents() == 1
