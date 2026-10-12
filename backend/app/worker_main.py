"""baton-agents: Pub/Sub push worker. Same image as baton-api, different start command:
    uvicorn app.worker_main:app --host 0.0.0.0 --port 8080
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Request

from app.pipeline import intake, runs
from app.pipeline.auth import PushAuthError, verify_push_request
from app.pipeline.publisher import run_id_for

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger("baton.worker")

app = FastAPI(title="Baton agents worker")


@app.get("/health")
def health():
    return {"status": "ok"}


def _decode(body: dict[str, Any]) -> dict:
    try:
        raw = base64.b64decode(body["message"]["data"])
        msg = json.loads(raw)
    except (KeyError, TypeError, ValueError, binascii.Error) as err:
        raise HTTPException(status_code=400, detail="malformed push message") from err
    if msg.get("type") != "handover.synced" or not msg.get("handover_id"):
        raise HTTPException(status_code=400, detail="unsupported message")
    return msg


@app.post("/pubsub/handover")
def pubsub_handover(request: Request, body: dict[str, Any] = Body(...)):
    """Return 2xx to ack, 5xx to have Pub/Sub retry (and dead-letter after the configured attempts)."""
    try:
        verify_push_request(request.headers.get("authorization"))
    except PushAuthError as err:
        logger.warning("push rejected: %s", err)
        raise HTTPException(status_code=401, detail="unauthorized")

    msg = _decode(body)
    handover_id = msg["handover_id"]
    run_id = run_id_for(handover_id)
    attempt = body.get("deliveryAttempt")

    outcome = runs.claim_run(run_id, handover_id, msg.get("unit"))
    if outcome != runs.CLAIMED:
        logger.info("skip run=%s reason=%s delivery_attempt=%s", run_id, outcome, attempt)
        return {"status": "skipped", "reason": outcome, "run_id": run_id}

    started = datetime.now(timezone.utc)
    agents_on = os.getenv("PIPELINE_AGENTS_ENABLED", "true").strip().lower() == "true"
    try:
        if agents_on:
            from app.agents.pipeline import run_handover_pipeline   # imported lazily: the ADK stack is heavy
            result = run_handover_pipeline(handover_id, run_id)
        else:
            result = intake.run_intake(handover_id)
            result["status"] = "completed"
    except intake.HandoverNotFound:
        runs.finish_run(run_id, "failed", started, [], "handover not found")
        logger.warning("run=%s handover not found, will retry (delivery_attempt=%s)", run_id, attempt)
        raise HTTPException(status_code=503, detail="handover not found yet")
    except Exception as err:  # noqa: BLE001 - infrastructure failure before/after the agents: retryable
        runs.finish_run(run_id, "failed", started, [], type(err).__name__)
        logger.error("run=%s failed: %s (delivery_attempt=%s)", run_id, type(err).__name__, attempt)
        raise HTTPException(status_code=500, detail="pipeline failed")

    status = result.get("status", "completed")
    extra = {"tokens": result.get("tokens", {}),
             "guardrails_triggered": [f"{t['agent']}:{t['guardrail']}" for t in result.get("guardrails_triggered", [])]}
    runs.finish_run(run_id, status, started, result.get("models_used", []), extra=extra)
    logger.info("run=%s %s total_ms=%s guardrails=%d", run_id, status, result.get("total_ms"), len(extra["guardrails_triggered"]))
    return {"status": status, "run_id": run_id}
