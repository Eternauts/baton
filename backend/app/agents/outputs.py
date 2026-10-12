"""Persist pipeline results: the brief for the dashboard and the small update for devices."""
from __future__ import annotations

from datetime import datetime, timezone

from app.knowledge.store import get_db


def save_brief(handover_id: str, doc: dict) -> None:
    get_db().collection("handover_briefs").document(handover_id).set({**doc, "created_at": datetime.now(timezone.utc)})


def save_device_update(update: dict) -> None:
    get_db().collection("device_updates").document(update["update_id"]).set({**update, "created_at": datetime.now(timezone.utc)})
