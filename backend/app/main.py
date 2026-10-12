from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import asyncio
import time
import os
import secrets
import hashlib
import logging
import threading
from contextlib import asynccontextmanager
from dotenv import load_dotenv

# Load local environment variables from .env if present
load_dotenv()

from collections import deque
import pathlib
from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Header
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech
from google.cloud import logging as cloud_logging
from google.genai import types as genai_types
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)  # keep request URLs out of the logs
logger = logging.getLogger(__name__)



from app.models import (
    HandoverRequest, HandoverSession, HandoverBrief,
    SafetyConflict, GapQuestion, Fact, Severity,
    Capsule, CapsuleBatchSyncRequest, CapsuleBatchSyncResponse
)
from app.rules import SafetyRulesEngine
from app.agents import GeminiAgentService
from app.plant_data import MOCK_ACTIVE_PERMITS, MOCK_DCS_TELEMETRY
from app.safety import evaluate_capsules, facts_from_capsules
from app.config import get_settings, validate_startup
from app.llm import generate as llm_generate
from app.pipeline.publisher import publish_handover_synced, run_id_for

@asynccontextmanager
async def lifespan(_: FastAPI):
    for problem in validate_startup():
        logger.error("Config problem: %s", problem)

    def _warm():   # importing ADK takes a few seconds; do it now so the first question does not pay for it
        try:
            import app.agents.ask  # noqa: F401
        except Exception as err:  # noqa: BLE001
            logger.warning("ask warm-up failed: %s", type(err).__name__)
    threading.Thread(target=_warm, daemon=True).start()
    yield


app = FastAPI(
    title="Baton MVP - Shift-Handover Guardian",
    description="Safety Rule Engine + Gemini AI Multi-Agent Handover Platform",
    version="1.0.0",
    lifespan=lifespan,
)


def require_aegis_key(provided: Optional[str]) -> None:
    """Reject the request unless it carries the configured X-Aegis-Key. Fails closed if none is configured."""
    expected = get_settings().aegis_api_key
    if not expected or not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid or missing X-Aegis-Key"}})

def require_app_key(provided: Optional[str]) -> None:
    """The key a shipped app (including the public web app) may hold: the supervisor key, or the separate demo key.
    The demo key opens the app endpoints only. Supervisor actions (acknowledge an alert, read agent traces) still
    need the supervisor key through require_aegis_key, so a key visible in a web page cannot reach them."""
    s = get_settings()
    ok = bool(provided) and any(k and secrets.compare_digest(provided, k) for k in (s.aegis_api_key, s.aegis_demo_key))
    if not ok:
        raise HTTPException(status_code=401, detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid or missing X-Aegis-Key"}})


# The website's JavaScript and WebAssembly are several MB: compress them (Cloud Run does not).
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Enable CORS for local development and Firebase Hosting frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage repository for MVP (transits to Firestore on GCP)
sessions_db: Dict[str, HandoverSession] = {}
firestore_db = None
try:
    from google.cloud import firestore
    firestore_project = os.getenv("GOOGLE_CLOUD_PROJECT", "ai-builder-cup-2026-509818")
    firestore_db = firestore.Client(project=firestore_project)
    logger.info(f"Initialized Firestore Client for project: {firestore_project}")
except Exception as e:
    firestore_db = None
    logger.warning(f"Firestore Client could not be initialized: {e}. Running in in-memory fallback mode.")


def save_handover_session(session: HandoverSession):
    """Save handover session to in-memory cache and asynchronously persist to Firestore."""
    sessions_db[session.id] = session
    if firestore_db:
        try:
            firestore_db.collection("handover_sessions").document(session.id).set(session.model_dump())
        except Exception as e:
            logger.warning(f"Failed to persist session {session.id} to Firestore: {e}")


def get_handover_session(session_id: str) -> Optional[HandoverSession]:
    """Retrieve handover session from in-memory cache, or hydrate from Firestore."""
    if session_id in sessions_db:
        return sessions_db[session_id]
    if firestore_db:
        try:
            doc = firestore_db.collection("handover_sessions").document(session_id).get()
            if doc.exists:
                session = HandoverSession(**doc.to_dict())
                sessions_db[session_id] = session
                return session
        except Exception as e:
            logger.warning(f"Failed to fetch session {session_id} from Firestore: {e}")
    return None


def _batch_id(device_id: Optional[str], uuids: List[str]) -> str:
    """Stable handover id for a set of capsules: the same device and capsule UUIDs always give the same id."""
    raw = (device_id or "") + "|" + "|".join(sorted(uuids))
    return "batch-" + hashlib.sha256(raw.encode()).hexdigest()[:8]


def _find_batch_event(batch_id: str) -> Optional[Dict[str, Any]]:
    """A previously recorded sync event: this instance's memory first, then the Firestore ledger. Blocking."""
    for e in list(dashboard_telemetry_stream):
        if e.get("id") == batch_id:
            return dict(e)
    if firestore_db:
        try:
            snap = firestore_db.collection("batch_sync_events").document(batch_id).get()
            if snap.exists:
                return snap.to_dict()
        except Exception as e:  # noqa: BLE001 - a failed lookup must never block a real sync
            logger.warning("batch lookup failed: %s", type(e).__name__)
    return None


def save_batch_sync_event(event_dict: Dict[str, Any]):
    """Persist batch sync event to Firestore batch_sync_events collection."""
    if firestore_db:
        try:
            firestore_db.collection("batch_sync_events").document(event_dict["id"]).set(event_dict)
        except Exception as e:
            logger.warning(f"Failed to persist batch event {event_dict.get('id')} to Firestore: {e}")


_ledger_cache: Dict[str, Any] = {"at": 0.0, "n": None}


def get_firestore_ledger_count() -> int:
    """Number of persisted audit documents. Uses one aggregation query and caches it for 15 s: the dashboard polls
    every 2 s, and listing up to 100 documents on every poll cost about 100 reads per second per open dashboard."""
    now = time.time()
    if _ledger_cache["n"] is not None and now - _ledger_cache["at"] < 15:
        return _ledger_cache["n"]
    if firestore_db:
        try:
            n = int(firestore_db.collection("batch_sync_events").count().get()[0][0].value)
            _ledger_cache.update(at=now, n=n)
            return n
        except Exception:
            if _ledger_cache["n"] is not None:
                return _ledger_cache["n"]
    return len(dashboard_telemetry_stream)


def hydrate_telemetry_from_firestore():
    """Hydrate in-memory telemetry stream from Firestore on container cold start."""
    if not firestore_db:
        return
    try:
        docs = list(
            firestore_db.collection("batch_sync_events")
            .order_by("timestamp", direction=firestore.Query.DESCENDING)
            .limit(15)
            .stream()
        )
        if docs:
            dashboard_telemetry_stream.clear()
            for d in docs:
                dashboard_telemetry_stream.append(d.to_dict())
            logger.info(f"Hydrated {len(docs)} batch sync events from Firestore.")
    except Exception as e:
        logger.warning(f"Could not hydrate telemetry from Firestore: {e}")


rules_engine = SafetyRulesEngine()
agent_service = GeminiAgentService()

# Simulated plant feed and permits live in app/plant_data.py (shared with the background pipeline).

# In-memory circular buffer for Cloud Control Room live dashboard (stores last 20 events)
dashboard_telemetry_stream: deque = deque(maxlen=20)
DASHBOARD_HTML_PATH = pathlib.Path(__file__).parent / "static" / "dashboard.html"

# GCP Cloud Logging Client & In-Memory Real-Time Activity Log
gcp_project = os.getenv("GOOGLE_CLOUD_PROJECT", "ai-builder-cup-2026-509818")
try:
    cloud_log_client = cloud_logging.Client(project=gcp_project)
except Exception as e:
    logger.warning(f"Failed to init cloud logging client: {e}")
    cloud_log_client = None

cloud_activity_log: deque = deque(maxlen=50)
_cached_cloud_logs: List[Dict[str, Any]] = []
_last_cloud_log_fetch: float = 0.0


def fetch_and_parse_cloud_logs(max_entries: int = 50) -> List[Dict[str, Any]]:
    """
    Parses live Google Cloud Run logs, filtering out frequent polling noise
    (/api/v1/dashboard/stream, /api/health) to highlight substantive API calls:
    - Audio Transcriptions (latencies, languages, sizes)
    - Anomalies & Incidents (4xx, 500 errors, bad requests)
    - Shift Handover Syncs
    """
    global _cached_cloud_logs, _last_cloud_log_fetch
    now = time.time()
    if _cached_cloud_logs and (now - _last_cloud_log_fetch < 5.0):
        return _cached_cloud_logs

    if not cloud_log_client:
        return list(cloud_activity_log)

    try:
        project_id = os.getenv("GOOGLE_CLOUD_PROJECT", "ai-builder-cup-2026-509818")
        filter_expr = (
            'resource.type="cloud_run_revision" AND '
            'resource.labels.service_name="baton-api" AND '
            f'logName="projects/{project_id}/logs/run.googleapis.com%2Frequests" AND '
            'NOT httpRequest.requestUrl:"dashboard" AND '
            'NOT httpRequest.requestUrl:"health" AND '
            'NOT httpRequest.requestUrl:"favicon.ico" AND '
            'NOT httpRequest.requestUrl:"/agents/"'      # the dashboard's own trace polling is not a substantive request
        )
        entries = list(cloud_log_client.list_entries(
            filter_=filter_expr,
            order_by=cloud_logging.DESCENDING,
            page_size=max_entries,
            max_results=max_entries
        ))

        parsed: List[Dict[str, Any]] = []
        for e in entries:
            req = e.http_request or {}
            status = req.get("status", 200)
            url = req.get("requestUrl", "")
            method = req.get("requestMethod", "POST")
            user_agent = req.get("userAgent", "Client")
            latency = req.get("latency", "0.2s")
            remote_ip = req.get("remoteIp", "unknown")
            text = str(e.payload) if e.payload else ""

            path = url.split("run.app")[-1] if "run.app" in url else url
            if not path and method:
                path = "/api/transcribe" if "transcribe" in text.lower() else "/"

            is_anomaly = (status and status >= 400) or e.severity in ["WARNING", "ERROR", "CRITICAL"]
            is_transcribe = "/api/transcribe" in url or "transcribe" in text.lower()
            is_sync = "/batch_sync" in url or "batch" in text.lower()

            if is_anomaly:
                cat = "ANOMALY"
                summary = f"Incident: HTTP {status} on {path} ({user_agent})"
            elif is_transcribe:
                cat = "TRANSCRIBE"
                summary = f"Audio Transcription ({latency}) from {user_agent}"
            elif is_sync:
                cat = "BATCH_SYNC"
                summary = f"Handover Batch Sync ({latency}) from {user_agent}"
            else:
                cat = "SYSTEM"
                summary = f"{method} {path} - HTTP {status}"

            parsed.append({
                "id": str(getattr(e, "insert_id", uuid.uuid4().hex[:8])),
                "timestamp": e.timestamp.isoformat() if hasattr(e.timestamp, "isoformat") else str(e.timestamp),
                "category": cat,
                "status": status,
                "severity": "ERROR" if is_anomaly else "INFO",
                "method": method,
                "path": path,
                "url": url,
                "ip": remote_ip,
                "user_agent": user_agent,
                "latency": latency,
                "summary": summary
            })

        _cached_cloud_logs = parsed
        _last_cloud_log_fetch = now
        return parsed
    except Exception as err:
        logger.warning(f"Error fetching cloud run logs: {err}")
        return list(cloud_activity_log)

# Pre-populate with initial baseline event so judges immediately see live UI on boot
dashboard_telemetry_stream.appendleft({
    "id": "batch-init-001",
    "device_id": "pixel7-edge-unit1",
    "operator_id": "TECH-ARUN-42",
    "shift_name": "NIGHT-SHIFT-A",
    "unit_name": "HYDROCRACKER-01",
    "timestamp": datetime.now(timezone.utc).isoformat(),
    "capsules": [
        {
            "uuid": "capsule-init-001",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": "ISOLATION",
            "asset_tag": "P-201B",
            "asserted_state": "ISOLATED",
            "text_transcript": "Pump P-201B isolated and lock applied at 10:30 by Arun",
            "intent_severity": "CRITICAL"
        }
    ],
    "synced_count": 1,
    "sync_status": "CONFLICT_DETECTED",
    "has_critical_conflict": True,
    "conflicts": [
        {
            "id": "CONF-R1-1",
            "rule_id": "R1",
            "title": "Isolation Mismatch: P-201B",
            "description": "Log/capsule asserts 'Asset P-201B asserted as ISOLATED', but live DCS state for P-201B is physically 'OPEN' (telemetry: {'status': 'OPEN', 'pressure': 12.4, 'temp_c': 64.2}).",
            "severity": "CRITICAL",
            "evidence_ids": ["capsule-init-001", "DCS-P-201B"],
            "status": "OPEN",
            "mitigation_notes": None
        }
    ],
    "summary": "Pump P-201B requires immediate attention due to an active Isolation Mismatch against live SCADA telemetry. Gating shift handover transfer.",
    "processed_at": datetime.now(timezone.utc).isoformat()
})

# Hydrate in-memory telemetry stream from persistent Firestore ledger on boot
hydrate_telemetry_from_firestore()




# ==========================================
# V1 Edge / Offline-First Endpoints (Flutter)
# ==========================================

@app.get("/api/v1/health")
@app.get("/v1/health")
@app.get("/health")
async def health_v1():
    """
    Lightweight health/connectivity check pinged every 5s by the Flutter mobile app
    to detect network restoration from airplane mode and trigger batch flush.
    """
    return {
        "status": "online",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


@app.post("/api/v1/handover/batch_sync", response_model=CapsuleBatchSyncResponse)
@app.post("/v1/handover/batch_sync", response_model=CapsuleBatchSyncResponse)
async def batch_sync_capsules(req: CapsuleBatchSyncRequest):
    """
    Batch synchronization endpoint for offline Gemma E4B capsules from Flutter edge devices.
    Executes deterministic safety checks against DCS telemetry and generates an AI summary.
    Returns HTTP 200 with conflict payload so edge clients never crash on 4xx/5xx network errors.
    """
    sync_started = time.time()
    now_utc = datetime.now(timezone.utc).isoformat()

    # Idempotent by capsule: the same device re-sending the same capsules is the same handover. A retry, a
    # double tap or an app that re-sends a pending queue must not create another event, another set of
    # conflicts and another agent run.
    session_id = _batch_id(req.device_id, [c.uuid for c in req.capsules])
    replay = await asyncio.to_thread(_find_batch_event, session_id)
    if replay is not None:
        logger.info("batch_sync replay: %s already recorded, nothing re-run", session_id)
        stored = [SafetyConflict(**c) for c in replay.get("conflicts", [])]
        critical = any(c.rule_id in ["R1", "R2"] or c.severity == Severity.CRITICAL for c in stored)
        return CapsuleBatchSyncResponse(
            sync_status="CONFLICT_DETECTED" if critical else "SUCCESS",   # an acknowledged conflict is still a conflict
            synced_count=len(req.capsules), has_critical_conflict=critical, conflicts=stored,
            summary=replay.get("summary") or "", processed_at=replay.get("processed_at") or now_utc,
            pipeline_run_id=run_id_for(session_id), handover_id=session_id)

    # 1-2. Capsules to facts, then the deterministic rules (shared with the background pipeline).
    capsule_dicts = [c.model_dump(mode="json") for c in req.capsules]
    facts: List[Fact] = facts_from_capsules(capsule_dicts)
    conflicts = evaluate_capsules(capsule_dicts)

    # 3. Check for critical rule violations (R1: Isolation Mismatch, R2: SIMOPS Conflict)
    has_critical_conflict = any(
        c.rule_id in ["R1", "R2"] or c.severity == Severity.CRITICAL
        for c in conflicts
    )

    sync_status = "CONFLICT_DETECTED" if has_critical_conflict else "SUCCESS"

    # 4. Executive summary. While LEGACY_BRIEF_INLINE is on, Gemini writes it inside the request;
    #    otherwise the rule-based text is used and the pipeline's briefing agent owns the real brief.
    if os.getenv("LEGACY_BRIEF_INLINE", "true").strip().lower() == "true":
        summary_task = agent_service.generate_batch_summary(req.capsules, conflicts)
        summary_results = await asyncio.gather(summary_task, return_exceptions=True)

        if isinstance(summary_results[0], Exception):
            logger.error(f"Error generating batch summary: {summary_results[0]}")
            summary = (
                f"Batch sync processed {len(req.capsules)} logs. "
                f"{'CRITICAL safety conflicts detected!' if has_critical_conflict else 'All logs verified.'}"
            )
        else:
            summary = summary_results[0]
    else:
        summary = agent_service.deterministic_batch_summary(req.capsules, conflicts)

    # 5. Record session in memory & persist to Firestore for supervisor audit
    session = HandoverSession(
        id=session_id,
        unit_name=req.unit_name or "UNIT-01",
        shift_name=req.shift_name or "SHIFT-A",
        outgoing_operator=req.operator_id or "TECH-OFFLINE",
        status="NEEDS_CLARIFICATION" if has_critical_conflict else "READY_FOR_BRIEF",
        facts=facts,
        conflicts=conflicts,
        questions=[],
        brief=None,
        created_at=now_utc
    )
    save_handover_session(session)

    # 6. Push to real-time dashboard telemetry stream & persist to Firestore event ledger
    event_dict = {
        "id": session_id,
        "device_id": req.device_id or "pixel7-edge-unit1",
        "operator_id": req.operator_id or "TECH-OFFLINE",
        "shift_name": req.shift_name or "SHIFT-A",
        "unit_name": req.unit_name or "HYDROCRACKER-01",
        "timestamp": now_utc,
        "capsules": [c.model_dump() for c in req.capsules],
        "synced_count": len(req.capsules),
        "sync_status": sync_status,
        "has_critical_conflict": has_critical_conflict,
        "conflicts": [c.model_dump() for c in conflicts],
        "summary": summary,
        "processed_at": now_utc
    }
    dashboard_telemetry_stream.appendleft(event_dict)
    save_batch_sync_event(event_dict)

    # Push to in-memory cloud activity log
    cloud_activity_log.appendleft({
        "id": session_id,
        "timestamp": now_utc,
        "category": "BATCH_SYNC",
        "status": 200,
        "severity": "WARNING" if has_critical_conflict else "INFO",
        "method": "POST",
        "url": "/api/v1/handover/batch_sync",
        "ip": req.device_id,
        "user_agent": req.operator_id or "Flutter",
        "latency": f"{int((time.time() - sync_started) * 1000)}ms",
        "summary": f"Batch Sync: {len(req.capsules)} capsules | Status: {sync_status} (Critical Conflict: {has_critical_conflict})"
    })

    # 7. Queue the background pipeline (embedding, agents). A failure here never fails the sync.
    pipeline_run_id = None
    try:
        queued = await asyncio.wait_for(
            asyncio.to_thread(publish_handover_synced, session_id, [c.uuid for c in req.capsules],
                              req.unit_name, req.device_id),
            timeout=5.0)
        pipeline_run_id = run_id_for(session_id) if queued else None
    except Exception as err:  # noqa: BLE001
        logger.warning("pipeline publish skipped: %s", type(err).__name__)

    # 8. Return 200 OK wrapper response
    return CapsuleBatchSyncResponse(
        sync_status=sync_status,
        synced_count=len(req.capsules),
        has_critical_conflict=has_critical_conflict,
        conflicts=conflicts,
        summary=summary,
        processed_at=now_utc,
        pipeline_run_id=pipeline_run_id,
        handover_id=session_id
    )


# ==========================================
# Realtime Dashboard Endpoints
# ==========================================

_brief_cache: Dict[str, Any] = {}     # handover_id -> (fetched_at, brief dict or None)
_BRIEF_FIELDS = ("headline", "items", "citation_details", "model", "guardrail_status", "guardrails", "run_id", "created_at")


def _fetch_briefs(ids: List[str]) -> Dict[str, Optional[dict]]:
    """Pipeline briefs for recent events. A found brief is cached 30 s; a missing one is re-checked every 2 s."""
    out, now, missing = {}, time.time(), []
    for i in ids:
        hit = _brief_cache.get(i)
        if hit and (now - hit[0] < (30 if hit[1] else 2)):
            out[i] = hit[1]
        else:
            missing.append(i)
    if missing and firestore_db:
        try:
            for snap in firestore_db.get_all([firestore_db.collection("handover_briefs").document(i) for i in missing]):
                doc = snap.to_dict() if snap.exists else None
                _brief_cache[snap.id] = (now, doc)
                out[snap.id] = doc
        except Exception as err:  # noqa: BLE001 - the brief is an enhancement; the stream must still work
            logger.warning("brief lookup failed: %s", type(err).__name__)
    return out


@app.get("/api/v1/dashboard/stream")
async def get_dashboard_stream():
    """
    Returns the real-time stream of parsed Cloud Run logs,
    filtering out noise (2s polling) to highlight:
    - Audio Transcriptions (latencies, languages, sizes)
    - Anomalies & 500 Incidents (such as recent Dart/3.13 500 errors)
    - Shift Handover Syncs
    - Animated Cloud Resource Topology Flow
    """
    # blocking Google API calls run in a worker thread so they never stall other requests on the event loop
    cloud_logs = await asyncio.to_thread(fetch_and_parse_cloud_logs, 40)
    ledger_count = await asyncio.to_thread(get_firestore_ledger_count)

    # Merge in-memory activity with cloud logs
    merged_ids = set()
    combined_logs = []
    for log in list(cloud_activity_log) + cloud_logs:
        log_id = log.get("id") or log.get("timestamp")
        if log_id not in merged_ids:
            merged_ids.add(log_id)
            combined_logs.append(log)

    # Sort descending by timestamp
    combined_logs.sort(key=lambda x: str(x.get("timestamp", "")), reverse=True)

    anomalies = [l for l in combined_logs if l.get("category") == "ANOMALY" or (l.get("status") and l.get("status") >= 400)]
    transcriptions = [l for l in combined_logs if l.get("category") == "TRANSCRIBE"]
    syncs = [l for l in combined_logs if l.get("category") == "BATCH_SYNC"]

    cloud_flow = {
        "edge": {
            "status": "online",
            "name": "Mobile Edge (Gemma E4B / Flutter)",
            "client_ua": "Dart/3.13 (dart:io)",
            "active_transcriptions": len(transcriptions),
            "recent_syncs": len(syncs)
        },
        "cloud_run": {
            "status": "healthy" if len(anomalies) < 10 else "degraded",
            "service": "baton-api",
            "region": "asia-southeast1",
            "active_revision": os.getenv("K_REVISION", "local"),
            "anomalies_detected": len(anomalies),
            "recent_calls": len(combined_logs)
        },
        "vertex_ai": {
            "status": "active",
            "model": get_settings().gemini_model,
            "location": get_settings().gemini_location,
            "fast_model": get_settings().gemini_fast_model,
            "fast_location": get_settings().gemini_fast_location,
            "embedding_model": get_settings().embedding_model,
            "audio_engine": get_settings().transcribe_engine
        },
        "pipeline": {
            "topic": "baton-handover-events",
            "worker": "baton-agents",
            "region": "asia-southeast1",
            "brief_source": "adk-pipeline" if os.getenv("LEGACY_BRIEF_INLINE", "true").strip().lower() != "true" else "inline-gemini",
        },
        "safety_engine": {
            "status": "enforcing",
            "rules": ["R1 Isolation Mismatch", "R2 SIMOPS", "R3 Interlock Bypass", "R4 Expired Permit"]
        },
        "firestore": {
            "status": "persisted" if firestore_db else "in_memory",
            "database": "(default)",
            "location": "asia-southeast1",
            "ledger_count": ledger_count
        }
    }

    events = [dict(e) for e in dashboard_telemetry_stream]
    briefs = await asyncio.to_thread(_fetch_briefs, [e["id"] for e in events[:5] if e.get("id")])
    for e in events:
        b = briefs.get(e.get("id"))
        if b:
            e["brief"] = {k: b.get(k) for k in _BRIEF_FIELDS}
            if e.get("sync_status") != "ACKNOWLEDGED":     # an acknowledged event keeps its acknowledgement text
                e["summary"] = b.get("headline") or e.get("summary")

    return {
        "events": events,
        "cloud_logs": combined_logs[:30],
        "anomalies": anomalies[:10],
        "transcriptions": transcriptions[:15],
        "cloud_flow": cloud_flow,
        "stats": {
            "total_transcriptions": len(transcriptions),
            "total_anomalies": len(anomalies),
            "total_syncs": len(syncs),
            "total_substantive": len(combined_logs),
            "firestore_ledger_count": ledger_count
        },
        "total_events": len(dashboard_telemetry_stream),
        "server_time": datetime.now(timezone.utc).isoformat(),
        "dcs_telemetry": MOCK_DCS_TELEMETRY,
        "active_permits": MOCK_ACTIVE_PERMITS,
        "model": get_settings().gemini_model
    }


@app.post("/api/v1/dashboard/clear_alert")
async def clear_dashboard_alert(x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
    """
    Clears the active R1 conflict alert from the telemetry stream,
    transitioning the safety engine node to nominal state. Requires X-Aegis-Key.
    """
    require_aegis_key(x_aegis_key)
    if dashboard_telemetry_stream:
        latest = dashboard_telemetry_stream[0]
        latest["has_critical_conflict"] = False
        latest["sync_status"] = "ACKNOWLEDGED"
        latest["summary"] = "Supervisor acknowledged the active isolation alert. The conflict stays open until the equipment is re-verified in the field."
        if "conflicts" in latest:
            for c in latest["conflicts"]:
                c["status"] = "ACKNOWLEDGED"   # acknowledged is not resolved
        save_batch_sync_event(latest)
    return {"status": "ACKNOWLEDGED", "message": "Alert acknowledged by supervisor. The underlying conflict remains open until re-verified."}


@app.get("/dashboard", response_class=HTMLResponse)
async def serve_dashboard():
    """Serves the Baton Cloud Control Room UI dashboard."""
    if DASHBOARD_HTML_PATH.exists():
        return HTMLResponse(content=DASHBOARD_HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Baton Control Room</h1><p>dashboard.html not found</p>", status_code=404)


@app.get("/", response_class=HTMLResponse)
async def serve_root_dashboard():
    """Direct landing page to Cloud Control Room for judge convenience."""
    if DASHBOARD_HTML_PATH.exists():
        return HTMLResponse(content=DASHBOARD_HTML_PATH.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Baton API</h1><p><a href='/dashboard'>Go to Cloud Control Room</a></p>")



# ==========================================
# Legacy / Full Handover Endpoints
# ==========================================

@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "Baton MVP", "timestamp": datetime.now(timezone.utc).isoformat()}



def _distinct_conflicts(conflicts: List[SafetyConflict]) -> List[SafetyConflict]:
    """One entry per (rule, title): the same conflict raised by the log and by a voice note is one conflict."""
    seen, out = set(), []
    for c in conflicts:
        k = (c.rule_id, c.title)
        if k not in seen:
            seen.add(k)
            out.append(c)
    return out


@app.post("/api/handover/start", response_model=HandoverSession)
def start_handover(req: HandoverRequest, x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
    require_app_key(x_aegis_key)
    session_id = f"session-{uuid.uuid4().hex[:8]}"

    # 1. Gemini Agent: Fact Extraction
    facts = agent_service.extract_facts(req.log_text, req.voice_transcripts)

    # 2. Deterministic Safety Rules Engine Evaluation. The plant state and permits are the server's own feed:
    #    a caller must not be able to decide the verdict by sending the state it wants (req fields are ignored).
    conflicts = _distinct_conflicts(rules_engine.evaluate(facts, MOCK_DCS_TELEMETRY, MOCK_ACTIVE_PERMITS))

    # 3. Gap questions (one per distinct conflict)
    questions = agent_service.generate_gap_questions(conflicts, facts, req.target_language)

    # 4. Determine initial status
    status = "NEEDS_CLARIFICATION" if questions else "READY_FOR_BRIEF"

    brief = None
    if status == "READY_FOR_BRIEF":
        brief = agent_service.compose_brief(conflicts, facts, req.target_language)

    session = HandoverSession(
        id=session_id,
        unit_name=req.unit_name,
        shift_name=req.shift_name,
        outgoing_operator=req.outgoing_operator,
        status=status,
        facts=facts,
        conflicts=conflicts,
        questions=questions,
        brief=brief,
        created_at=datetime.utcnow().isoformat()
    )

    save_handover_session(session)
    return session


@app.get("/api/handover/{session_id}", response_model=HandoverSession)
def get_session(session_id: str, x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
    require_app_key(x_aegis_key)
    session = get_handover_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Handover session not found")
    return session


@app.post("/api/handover/{session_id}/interview", response_model=HandoverSession)
def start_interview(session_id: str, language: str = "en", x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
    """Interview step for a handover created by batch_sync: the outgoing operator is asked about each distinct
    open conflict. Idempotent: asking again returns the same questions."""
    require_app_key(x_aegis_key)
    session = get_handover_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Handover session not found")
    if session.status == "COMPLETED":
        return session
    if not session.questions:
        lang = language if language in ("en", "ta", "ms", "zh") else "en"
        session.questions = agent_service.generate_gap_questions(_distinct_conflicts(session.conflicts), session.facts, lang)
    if session.questions and not all(q.answered for q in session.questions):
        session.status = "NEEDS_CLARIFICATION"
    elif session.brief is None:
        session.brief = agent_service.compose_brief(_distinct_conflicts(session.conflicts), session.facts, "en")
        session.status = "READY_FOR_BRIEF"
    save_handover_session(session)
    return session


@app.get("/api/handover/{session_id}/brief")
async def get_pipeline_brief(session_id: str, x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
    """The agent pipeline's cited brief for this handover, once it is ready (it is written about 10 to 20 s after a sync)."""
    require_app_key(x_aegis_key)
    got = await asyncio.to_thread(_fetch_briefs, [session_id])
    b = got.get(session_id)
    if not b:
        return {"ready": False, "brief": None}
    return {"ready": True, "brief": {k: b.get(k) for k in _BRIEF_FIELDS}}


class AnswerPayload(BaseModel):
    answers: Dict[str, str]  # question_id -> answer text


@app.post("/api/handover/{session_id}/answer", response_model=HandoverSession)
def submit_answers(session_id: str, payload: AnswerPayload, x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
    require_app_key(x_aegis_key)
    session = get_handover_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Handover session not found")

    # Process answers and convert to facts
    for q in session.questions:
        text = (payload.answers.get(q.id) or "").strip()[:500]
        if text and not q.answered:
            q.answer_text = text
            q.answered = True
            session.facts.append(
                Fact(
                    id=f"FACT-ANS-{q.id}",
                    text=f"Operator Verified: {text}",
                    category="OPERATOR_CLARIFICATION",
                    source_type="OPERATOR_ANSWER",
                    source_id=q.id
                )
            )

    # An answer is a statement, not a verdict: the rules are not re-run and no conflict changes status here.
    # The brief is only released once every question has an answer.
    if all(q.answered for q in session.questions):
        session.brief = agent_service.compose_brief(_distinct_conflicts(session.conflicts), session.facts, "en")
        session.status = "READY_FOR_BRIEF"
    else:
        session.status = "NEEDS_CLARIFICATION"
    save_handover_session(session)

    return session


class AcknowledgePayload(BaseModel):
    item_id: str
    readback_text: str
    supervisor: str


@app.post("/api/handover/{session_id}/acknowledge", response_model=HandoverSession)
def acknowledge_item(session_id: str, payload: AcknowledgePayload, x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
    require_app_key(x_aegis_key)
    session = get_handover_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Handover session not found")

    if not session.brief:
        raise HTTPException(status_code=400, detail="Brief not generated yet")

    supervisor = payload.supervisor.strip()
    readback = " ".join(payload.readback_text.split())
    if not (1 <= len(supervisor) <= 60):
        raise HTTPException(status_code=422, detail="The incoming supervisor's name is required.")
    if len(readback.split()) < 3 or len(readback) > 500:
        raise HTTPException(status_code=422, detail="A read-back must say the item back in your own words (at least 3 words).")

    for item in session.brief.items:
        if item.id == payload.item_id:
            if not item.acknowledged:                       # idempotent: a repeat does not overwrite who read it back
                item.acknowledged = True
                item.readback_text = readback
                item.acknowledged_by = supervisor
                item.acknowledged_at = datetime.now(timezone.utc).isoformat()
            break
    else:
        raise HTTPException(status_code=404, detail="Brief item not found")

    save_handover_session(session)
    return session


@app.post("/api/handover/{session_id}/complete")
def complete_handover(session_id: str, x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
    require_app_key(x_aegis_key)
    session = get_handover_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Handover session not found")

    if not session.brief:
        raise HTTPException(status_code=400, detail="Brief not available")

    # Gate: Check if all critical items are acknowledged
    unack_critical = [
        item for item in session.brief.items
        if item.severity == "CRITICAL" and not item.acknowledged
    ]

    if unack_critical:
        raise HTTPException(
            status_code=409,
            detail=f"Handover gated: {len(unack_critical)} CRITICAL safety item(s) require read-back acknowledgment before transfer."
        )

    names = [i.acknowledged_by for i in session.brief.items if i.acknowledged_by]
    session.status = "COMPLETED"
    session.brief.completion_status = "COMPLETED"
    session.brief.incoming_supervisor = names[-1] if names else session.brief.incoming_supervisor
    save_handover_session(session)

    # Transferring responsibility is not resolving: every conflict keeps its status.
    still_open = sum(1 for c in _distinct_conflicts(session.conflicts) if c.status != "RESOLVED")
    return {"status": "COMPLETED", "message": "Handover responsibility transferred.", "incoming_supervisor": session.brief.incoming_supervisor,
            "open_conflicts": still_open}


# Rate Limiter setup
rate_limit_db: Dict[str, List[float]] = {}
RATE_LIMIT_MAX = 30
RATE_LIMIT_WINDOW = 60.0

def check_rate_limit(client_ip: str) -> bool:
    now = time.time()
    if client_ip not in rate_limit_db:
        rate_limit_db[client_ip] = []
    
    # Clean up old
    rate_limit_db[client_ip] = [t for t in rate_limit_db[client_ip] if now - t < RATE_LIMIT_WINDOW]
    
    if len(rate_limit_db[client_ip]) >= RATE_LIMIT_MAX:
        return False
        
    rate_limit_db[client_ip].append(now)
    return True

def _asset_hint_sentence(asset_hints: Optional[str]) -> str:
    """Tell the model which equipment tags exist so it writes them exactly (hyphens and letters included)."""
    tags = [h.strip() for h in (asset_hints or "").split(",") if h.strip()][:50]
    if not tags:
        return ""
    return (" Equipment tags in this plant are written exactly like these, with the hyphen and the final letter: "
            + ", ".join(tags) + ". Whenever the speaker names one of them, write it in exactly that form.")


@app.post("/api/transcribe")
@app.post("/transcribe")
async def transcribe_audio(
    request: Request,
    audio: UploadFile = File(...),
    languages: Optional[str] = Form(None),
    asset_hints: Optional[str] = Form(None),
    client_request_id: Optional[str] = Form(None),
    x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")
):
    start_time = time.time()
    client_ip = request.client.host if request.client else "unknown"
    
    # 1. Auth check (app scope: the web app transcribes too)
    require_app_key(x_aegis_key)
        
    # 2. Rate Limit
    if not check_rate_limit(client_ip):
        raise HTTPException(status_code=429, detail={"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "Too many requests"}})
        
    # 3. Read and check file size
    audio_content = await audio.read()
    byte_size = len(audio_content)
    if byte_size > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail={"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Audio file exceeds 10MB limit"}})
        
    if byte_size == 0:
        raise HTTPException(status_code=400, detail={"error": {"code": "BAD_REQUEST", "message": "Audio file is empty"}})

    # 4. Engine selection
    settings = get_settings()
    engine = settings.transcribe_engine
    project_id = settings.project or "test-project"
    model_used = None  # set to the model that actually answered
    
    transcript_text = ""
    detected_lang = None
    no_speech = False
    english_text = None
    
    # Calculate approx audio length for logs (assume 16kHz, 16bit mono = 32kB/s)
    audio_seconds = byte_size / 32000.0 
    
    try:
        if engine == "gemini":
            # Robust audio mime type detection using magic bytes and headers
            mime = "audio/mp4"
            if audio_content.startswith(b"RIFF"):
                mime = "audio/wav"
            elif audio_content.startswith(b"ID3") or audio_content[:2] in [b"\xff\xfb", b"\xff\xf3"]:
                mime = "audio/mp3"
            elif audio_content.startswith(b"OggS"):
                mime = "audio/ogg"
            elif audio_content.startswith(b"\x1aE\xdf\xa3"):
                mime = "audio/webm"
            elif b"ftyp" in audio_content[:32]:
                mime = "audio/mp4"
            elif audio.content_type and audio.content_type.startswith("audio/"):
                mime = audio.content_type

            response = await asyncio.to_thread(
                llm_generate,
                "transcribe",
                [
                    genai_types.Part.from_bytes(data=audio_content, mime_type=mime),
                    "Transcribe the following audio accurately. If it is in a non-English language (such as Tamil or Malay), output the original transcription, and on a new line prefixed with 'TRANSLATION: ', output the English translation keeping asset tags (like P-201B) unchanged. If already English, just output the transcription."
                    + _asset_hint_sentence(asset_hints)
                ],
                max_output_tokens=4096,
                timeout_s=60,
            )
            model_used = response.model
            raw_text = response.text
            if not raw_text:
                no_speech = True
            elif "TRANSLATION:" in raw_text:
                parts = raw_text.split("TRANSLATION:", 1)
                transcript_text = parts[0].strip()
                english_text = parts[1].strip()
                detected_lang = "non-en"
            else:
                transcript_text = raw_text
                detected_lang = "en"
        else:
            engine = "chirp3"

            speech_location = os.environ.get("SPEECH_LOCATION", "us")
            speech_client = SpeechClient(client_options={"api_endpoint": f"{speech_location}-speech.googleapis.com"})
            
            # Setup language codes
            lang_codes = ["auto"]
            if languages:
                lang_codes = [l.strip() for l in languages.split(",") if l.strip()]

            # Adaptation
            adaptation = None
            if asset_hints:
                phrases = [h.strip() for h in asset_hints.split(",") if h.strip()][:50]
                if phrases:
                    adaptation = cloud_speech.SpeechAdaptation(
                        phrase_sets=[
                            cloud_speech.SpeechAdaptation.AdaptationPhraseSet(
                                inline_phrase_set=cloud_speech.PhraseSet(
                                    phrases=[cloud_speech.PhraseSet.Phrase(value=p) for p in phrases]
                                )
                            )
                        ]
                    )

            config = cloud_speech.RecognitionConfig(
                auto_decoding_config=cloud_speech.AutoDetectDecodingConfig(),
                language_codes=lang_codes,
                model="chirp_3",
                adaptation=adaptation
            )
            
            req = cloud_speech.RecognizeRequest(
                recognizer=f"projects/{project_id}/locations/{speech_location}/recognizers/_",
                config=config,
                content=audio_content
            )
            
            try:
                response = speech_client.recognize(request=req, timeout=20.0)
            except GoogleAPICallError as e:
                if adaptation and ("not found" in str(e).lower() or "not supported" in str(e).lower() or "invalid argument" in str(e).lower()):
                    logger.warning("Speech adaptation phrase set not supported by model/recognizer in this region; retrying without adaptation.")
                    config.adaptation = None
                    req.config = config
                    response = speech_client.recognize(request=req, timeout=20.0)
                else:
                    raise
            
            if not response.results:
                no_speech = True
            else:
                transcript_text = response.results[0].alternatives[0].transcript
                detected_lang = response.results[0].language_code

    except (GoogleAPICallError, RetryError) as e:
        status_code = 504 if "Deadline Exceeded" in str(e) or "Timeout" in str(e) else 502
        cloud_activity_log.appendleft({
            "id": f"err-transcribe-{uuid.uuid4().hex[:6]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": "ANOMALY",
            "status": status_code,
            "severity": "ERROR",
            "method": "POST",
            "url": "/api/transcribe",
            "ip": client_ip,
            "user_agent": request.headers.get("user-agent", "unknown"),
            "latency": f"{int((time.time() - start_time) * 1000)}ms",
            "summary": f"Transcribe Upstream Error: {str(e)[:120]}"
        })
        raise HTTPException(status_code=status_code, detail={"error": {"code": "UPSTREAM_ERROR", "message": str(e)}})
    except Exception as e:
        logger.error(f"Transcribe error: {e}", exc_info=True)
        cloud_activity_log.appendleft({
            "id": f"err-transcribe-{uuid.uuid4().hex[:6]}",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": "ANOMALY",
            "status": 500,
            "severity": "ERROR",
            "method": "POST",
            "url": "/api/transcribe",
            "ip": client_ip,
            "user_agent": request.headers.get("user-agent", "unknown"),
            "latency": f"{int((time.time() - start_time) * 1000)}ms",
            "summary": f"Transcribe 500 Error: {str(e)[:120]}"
        })
        if "duration" in str(e).lower() or "too long" in str(e).lower():
            raise HTTPException(status_code=413, detail={"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Audio duration too long"}})
        raise HTTPException(status_code=500, detail={"error": {"code": "INTERNAL_ERROR", "message": str(e)}})

    # 5. Translation step if not English (if not already populated)
    if not english_text and not no_speech and detected_lang and not detected_lang.startswith("en"):
        try:
            prompt = (
                "Translate the following transcript to English. "
                "Keep asset tags (like P-201B) unchanged. Return ONLY the plain English text.\n\n"
                f"{transcript_text}"
            )
            
            if asset_hints:
                prompt += f"\n\nContext/Hints for proper nouns: {asset_hints}"
                
            res = await asyncio.to_thread(llm_generate, "translate", prompt, max_output_tokens=2048, timeout_s=30)
            english_text = res.text or None
        except Exception as e:
            logger.error(f"Translation failed: {e}")
            english_text = None

    latency_ms = int((time.time() - start_time) * 1000)
    if engine == "chirp3":
        model_used = "chirp_3"

    print(
        f"Transcribe request_id={client_request_id} size={byte_size} "
        f"audio_s={audio_seconds:.1f} lang={detected_lang} "
        f"engine={engine} lat_ms={latency_ms} status=200"
    )

    # Record successful transcription to in-memory cloud activity log
    cloud_activity_log.appendleft({
        "id": f"transcribe-{client_request_id or uuid.uuid4().hex[:6]}",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "category": "TRANSCRIBE",
        "status": 200,
        "severity": "INFO",
        "method": "POST",
        "url": "/api/transcribe",
        "ip": client_ip,
        "user_agent": request.headers.get("user-agent", "unknown"),
        "latency": f"{latency_ms}ms",
        "summary": f"Voice Note: '{transcript_text[:65]}' (Lang: {detected_lang or 'en'}, {audio_seconds:.1f}s, {model_used})"
    })

    return {
        "request_id": client_request_id or "",
        "text": transcript_text,
        "language": detected_lang,
        "english_text": english_text,
        "engine": engine,
        "model": model_used,
        "audio_seconds": audio_seconds,
        "latency_ms": latency_ms,
        "no_speech": no_speech
    }


# New v1 endpoints (Ask the logs, device updates). Registered last so they can reuse auth and the rate limiter.
from app.api_v1 import create_router  # noqa: E402
app.include_router(create_router(require_aegis_key, check_rate_limit, require_app_key))

