"""Idempotent run state in agent_runs/{run_id}.

Pub/Sub delivers at least once, so the same message can arrive twice (or concurrently).
`claim_run` decides atomically whether this delivery should do the work.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from google.cloud import firestore

from app.knowledge.store import get_db

logger = logging.getLogger("baton.pipeline.runs")
COLLECTION = "agent_runs"
STALE_AFTER = timedelta(minutes=5)

CLAIMED = "claimed"
ALREADY_DONE = "already_done"
IN_PROGRESS = "in_progress"


def decide(existing: Optional[dict], now: datetime, stale_after: timedelta = STALE_AFTER) -> str:
    """Pure decision: should this delivery run the work?"""
    if existing is None:
        return CLAIMED
    status = existing.get("status")
    if status in ("completed", "fallback"):
        return ALREADY_DONE
    if status == "running":
        started = existing.get("started_at")
        if started is not None and now - started < stale_after:
            return IN_PROGRESS
        return CLAIMED  # the earlier attempt crashed or hung: take over
    return CLAIMED  # failed: retry


@firestore.transactional
def _claim(txn, ref, now, trigger, handover_id, unit):
    snap = ref.get(transaction=txn)
    existing = snap.to_dict() if snap.exists else None
    outcome = decide(existing, now)
    if outcome == CLAIMED:
        attempts = (existing or {}).get("attempts", 0) + 1
        txn.set(ref, {
            "run_id": ref.id, "trigger": trigger, "handover_id": handover_id, "unit": unit,
            "status": "running", "started_at": now, "finished_at": None, "total_ms": None,
            "models_used": [], "guardrails_triggered": [], "attempts": attempts,
        })
    return outcome


def claim_run(run_id: str, handover_id: str, unit: str | None, trigger: str = "handover.synced") -> str:
    db = get_db()
    return _claim(db.transaction(), db.collection(COLLECTION).document(run_id),
                  datetime.now(timezone.utc), trigger, handover_id, unit)


def finish_run(run_id: str, status: str, started_at: datetime, models_used: list[str], error: str | None = None,
               extra: dict | None = None) -> None:
    now = datetime.now(timezone.utc)
    update = {"status": status, "finished_at": now, "total_ms": int((now - started_at).total_seconds() * 1000),
              "models_used": models_used, **(extra or {})}
    if error:
        update["error"] = error[:300]
    get_db().collection(COLLECTION).document(run_id).update(update)
