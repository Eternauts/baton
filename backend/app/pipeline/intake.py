"""Intake: load a synced handover, store its capsules, chunk, embed and write knowledge chunks."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.config import get_settings
from app.knowledge.handover_chunker import chunk_handover
from app.knowledge.store import get_db, upsert_chunks
from app.knowledge.tags import normalize_unit

logger = logging.getLogger("baton.pipeline.intake")
EVENTS_COLLECTION = "batch_sync_events"
CAPSULES_COLLECTION = "handover_capsules"


class HandoverNotFound(Exception):
    """The event document is not there (yet). Retryable: Pub/Sub will redeliver."""


def _ts(value) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def run_intake(handover_id: str) -> dict:
    db = get_db()
    snap = db.collection(EVENTS_COLLECTION).document(handover_id).get()
    if not snap.exists:
        raise HandoverNotFound(handover_id)
    event = snap.to_dict()
    capsules = event.get("capsules") or []

    # Capsule records keyed by their client UUID, so a redelivery overwrites the same documents.
    batch = db.batch()
    for c in capsules:
        batch.set(db.collection(CAPSULES_COLLECTION).document(c["uuid"]), {
            **c, "handover_id": handover_id, "unit_name": event.get("unit_name"),
            "shift_name": event.get("shift_name"), "operator_id": event.get("operator_id"),
            "device_id": event.get("device_id"), "created_at": _ts(c.get("timestamp")) or datetime.now(timezone.utc),
            "seeded": False})
    if capsules:
        batch.commit()

    # Remember which unit this device reports for, so GET /devices/{id}/updates can find its updates.
    if event.get("device_id"):
        db.collection("devices").document(event["device_id"]).set(
            {"device_id": event["device_id"], "unit": normalize_unit(event.get("unit_name")), "last_sync": datetime.now(timezone.utc)},
            merge=True)

    chunks = chunk_handover(handover_id, capsules, unit_name=event.get("unit_name"),
                            shift_name=event.get("shift_name"), operator_id=event.get("operator_id"))
    n = upsert_chunks(chunks)
    logger.info("intake handover=%s capsules=%d chunks=%d", handover_id, len(capsules), n)
    return {"capsules": len(capsules), "chunks": n, "unit": event.get("unit_name"),
            "models_used": [get_settings().embedding_model]}
