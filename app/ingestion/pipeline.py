import hashlib
from pathlib import Path

from app.core.embeddings import get_embedder
from app.core.fingerprint import fingerprints, parse_stack_trace
from app.core.normalize import normalize_text
from app.core.redact import redact
from app.ingestion.extract import extract_incident
from app.logging import logger
from app.memory.store import MemoryStore
from app.models import Incident, RawDoc


class IngestionPipeline:
    def __init__(self, store: MemoryStore | None = None, review_queue_dir: str = "data/review_queue"):
        self.store = store or MemoryStore()
        self.embedder = get_embedder()
        self.review_queue_dir = Path(review_queue_dir)
        self.review_queue_dir.mkdir(parents=True, exist_ok=True)

    def ingest_doc(self, doc: RawDoc, accept_low: bool = False) -> str | None:
        """Processes a single RawDoc and returns the incident ID or None."""
        text_sha256 = hashlib.sha256(doc.text.encode("utf-8")).hexdigest()

        # 1. Idempotency check via source_docs SHA256
        existing_id = self.store.find_incident_by_doc_sha256(text_sha256)
        if existing_id:
            logger.info("doc_already_ingested", source_id=doc.source_id, incident_id=existing_id)
            return existing_id

        # 2. Redact then extract
        redacted_text = redact(doc.text)
        extracted = extract_incident(RawDoc(
            source_type=doc.source_type,
            source_id=doc.source_id,
            text=redacted_text,
            metadata=doc.metadata,
        ))

        # 3. Apply human-prefilled fields if present
        prefilled = doc.metadata.get("prefilled", {})
        if prefilled:
            if prefilled.get("title"):
                extracted.title = prefilled["title"]
            if prefilled.get("root_cause"):
                extracted.root_cause = prefilled["root_cause"]
            if prefilled.get("resolution_steps"):
                extracted.resolution_steps = prefilled["resolution_steps"]
            if prefilled.get("runbooks_mentioned"):
                extracted.runbooks_mentioned = prefilled["runbooks_mentioned"]
            if prefilled.get("fix_worked") is not None:
                extracted.fix_worked = prefilled["fix_worked"]
            if prefilled.get("trigger_ref"):
                extracted.trigger_ref = prefilled["trigger_ref"]
            if prefilled.get("services"):
                extracted.services = prefilled["services"]
            extracted.extraction_confidence = "high"

        # 4. Handle low confidence
        if doc.source_type != "postmortem" and extracted.extraction_confidence == "low" and not accept_low:
            queue_file = self.review_queue_dir / f"{text_sha256[:12]}.json"
            queue_file.write_text(extracted.model_dump_json(indent=2), encoding="utf-8")
            logger.warn("low_confidence_queued", source_id=doc.source_id, path=str(queue_file))
            return None

        # 4. Normalize error messages and compute fingerprints
        norm_errors = [normalize_text(e) for e in extracted.error_messages if e]
        all_fps = []
        for em in extracted.error_messages:
            all_fps.extend(fingerprints(em))
        for st in extracted.stack_traces:
            all_fps.extend(fingerprints(st))
        unique_fps = list(dict.fromkeys(all_fps))

        # 5. Build symptom_text and full_text
        symptom_components = [
            extracted.title,
            " ".join(extracted.symptoms),
            " ".join(norm_errors),
            " ".join(extracted.services),
            extracted.trigger_type or "",
        ]
        symptom_text = " ".join([c for c in symptom_components if c]).strip()

        full_components = [
            symptom_text,
            extracted.root_cause or "",
            " ".join(extracted.resolution_steps),
            extracted.lessons or "",
        ]
        full_text = " ".join([c for c in full_components if c]).strip()

        # 6. Embed both texts
        embs = self.embedder.embed_documents([symptom_text, full_text])
        emb_symptom = embs[0]
        emb_full = embs[1]

        # 7. Dedupe: check for near duplicate
        near_dup = self.store.find_near_duplicate(emb_full, extracted.services, extracted.started_at)
        source_doc_entry = {
            "type": doc.source_type,
            "id": doc.source_id,
            "sha256": text_sha256,
        }

        if near_dup:
            dup_id, sim = near_dup
            logger.info("dedupe_merged_incident", duplicate_of=dup_id, similarity=sim)
            incident_obj = Incident(
                id=dup_id,
                title=extracted.title,
                symptoms=extracted.symptoms,
                error_messages=norm_errors,
                error_fingerprints=unique_fps,
                services=extracted.services,
                root_cause=extracted.root_cause,
                resolution_steps=extracted.resolution_steps,
                runbook_ids=extracted.runbooks_mentioned,
                source_docs=[source_doc_entry],
                symptom_text=symptom_text,
                full_text=full_text,
                emb_symptom=emb_symptom,
                emb_full=emb_full,
            )
            self.store.merge_incident(dup_id, incident_obj)
            return dup_id

        # 8. Insert new incident
        inc_id = self.store.get_next_incident_id()
        incident_obj = Incident(
            id=inc_id,
            title=extracted.title,
            status="confirmed",
            severity=extracted.severity,
            started_at=extracted.started_at,
            resolved_at=extracted.resolved_at,
            symptoms=extracted.symptoms,
            error_messages=norm_errors,
            error_fingerprints=unique_fps,
            services=extracted.services,
            trigger_type=extracted.trigger_type,
            trigger_ref=extracted.trigger_ref,
            root_cause=extracted.root_cause,
            root_cause_category=extracted.root_cause_category,
            resolution_steps=extracted.resolution_steps,
            runbook_ids=extracted.runbooks_mentioned,
            fix_worked=extracted.fix_worked,
            lessons=extracted.lessons,
            source_docs=[source_doc_entry],
            symptom_text=symptom_text,
            full_text=full_text,
            emb_symptom=emb_symptom,
            emb_full=emb_full,
            weight=1.0,
            architecture_epoch=1,
        )
        self.store.insert_incident(incident_obj)

        # 9. Link files mentioned and stack trace frames
        for fm in extracted.files_mentioned:
            self.store.insert_incident_file(inc_id, fm.path, fm.function, role="involved")

        for st in extracted.stack_traces:
            _, frames = parse_stack_trace(st)
            for fr in frames:
                if fr.is_app:
                    self.store.insert_incident_file(inc_id, fr.file, fr.function, role="involved")

        # 10. Upsert services
        for svc in extracted.services:
            self.store.upsert_service(svc)

        logger.info("ingested_new_incident", incident_id=inc_id, title=extracted.title)
        return inc_id
