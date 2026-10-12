"""Publish `handover.synced` events. Never raises: the sync must not fail because of the pipeline."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from functools import lru_cache

from app.config import get_settings

logger = logging.getLogger("baton.pipeline.publisher")
PUBLISH_TIMEOUT_S = 3.0


def run_id_for(handover_id: str) -> str:
    """One pipeline run per handover, so redelivered messages map to the same run."""
    return f"run-{handover_id}"


@lru_cache(maxsize=1)
def _client():
    from google.cloud import pubsub_v1
    return pubsub_v1.PublisherClient()


def _topic_path() -> str | None:
    s = get_settings()
    if not s.pubsub_topic:
        return None
    return s.pubsub_topic if s.pubsub_topic.startswith("projects/") else f"projects/{s.project}/topics/{s.pubsub_topic}"


def build_message(handover_id: str, event_ids: list[str], unit: str | None, device_id: str | None) -> dict:
    """The message carries IDs only, never transcripts."""
    return {
        "type": "handover.synced",
        "handover_id": handover_id,
        "event_ids": event_ids,
        "unit": unit,
        "device_id": device_id,
        "published_at": datetime.now(timezone.utc).isoformat(),
    }


def publish_handover_synced(handover_id: str, event_ids: list[str], unit: str | None, device_id: str | None) -> bool:
    """Blocking publish (call from a thread). Returns True only if Pub/Sub accepted the message."""
    topic = _topic_path()
    if not topic:
        logger.info("pipeline disabled: PUBSUB_TOPIC not set")
        return False
    try:
        data = json.dumps(build_message(handover_id, event_ids, unit, device_id)).encode("utf-8")
        message_id = _client().publish(topic, data=data).result(timeout=PUBLISH_TIMEOUT_S)
        logger.info("published handover=%s events=%d message_id=%s", handover_id, len(event_ids), message_id)
        return True
    except Exception as err:  # noqa: BLE001 - publishing must never break the sync
        logger.warning("publish failed handover=%s error=%s", handover_id, type(err).__name__)
        return False
