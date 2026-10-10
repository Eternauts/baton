from __future__ import annotations
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import asyncio
import time
import os
import secrets
import logging
from dotenv import load_dotenv

# Load local environment variables from .env if present
load_dotenv()

from fastapi import FastAPI, HTTPException, Request, UploadFile, File, Form, Header
from fastapi.middleware.cors import CORSMiddleware
from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.cloud.speech_v2 import SpeechClient
from google.cloud.speech_v2.types import cloud_speech
from google import genai
from pydantic import BaseModel

logger = logging.getLogger(__name__)

from app.models import (
    HandoverRequest, HandoverSession, HandoverBrief,
    SafetyConflict, GapQuestion, Fact, Severity,
    Capsule, CapsuleBatchSyncRequest, CapsuleBatchSyncResponse
)
from app.rules import SafetyRulesEngine
from app.agents import GeminiAgentService

app = FastAPI(
    title="Baton MVP - Shift-Handover Guardian",
    description="Safety Rule Engine + Gemini AI Multi-Agent Handover Platform",
    version="1.0.0"
)

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

rules_engine = SafetyRulesEngine()
agent_service = GeminiAgentService()

# Mock DCS Plant Telemetry for live cross-verification of edge-asserted states
MOCK_DCS_TELEMETRY: Dict[str, Any] = {
    "P-201B": {"status": "OPEN", "pressure": 12.4, "temp_c": 64.2},
    "V-102": {"status": "CLOSED", "flow_rate": 0.0},
    "ESDV-301": {"status": "BYPASS", "active": True},
    "TK-501": {"status": "ACTIVE", "level_pct": 82.5},
}

# Mock Active Work Permits (including hot work and maintenance)
MOCK_ACTIVE_PERMITS: List[Dict[str, Any]] = [
    {"id": "PERMIT-HW-409", "type": "HOT_WORK", "title": "Unit 3 Flare Line Welding", "status": "OPEN"},
    {"id": "PERMIT-M-102", "type": "MAINTENANCE", "title": "Pump Gasket Replacement", "status": "EXPIRED", "expired": True}
]


# ==========================================
# V1 Edge / Offline-First Endpoints (Flutter)
# ==========================================

@app.get("/api/v1/health")
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
async def batch_sync_capsules(req: CapsuleBatchSyncRequest):
    """
    Batch synchronization endpoint for offline Gemma E4B capsules from Flutter edge devices.
    Executes deterministic safety checks against DCS telemetry and generates an AI summary.
    Returns HTTP 200 with conflict payload so edge clients never crash on 4xx/5xx network errors.
    """
    now_utc = datetime.now(timezone.utc).isoformat()

    # 1. Map incoming capsules to structured Facts
    facts: List[Fact] = []
    for c in req.capsules:
        # Build composite fact text ensuring tag and asserted state are present for deterministic engine
        fact_text = f"Asset {c.asset_tag} asserted as {c.asserted_state}. {c.text_transcript}".strip()
        facts.append(
            Fact(
                id=c.uuid,
                text=fact_text,
                category=c.category.upper(),
                source_type="ON_DEVICE_GEMMA",
                source_id=c.uuid
            )
        )

    # 2. Evaluate against live DCS telemetry and active permits using deterministic rules
    conflicts = rules_engine.evaluate(facts, MOCK_DCS_TELEMETRY, MOCK_ACTIVE_PERMITS)

    # 3. Check for critical rule violations (R1: Isolation Mismatch, R2: SIMOPS Conflict)
    has_critical_conflict = any(
        c.rule_id in ["R1", "R2"] or c.severity == Severity.CRITICAL
        for c in conflicts
    )

    sync_status = "CONFLICT_DETECTED" if has_critical_conflict else "SUCCESS"

    # 4. Generate AI Executive Summary via Gemini (uses asyncio.gather for minimal endpoint latency)
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

    # 5. Record session in memory for supervisor audit and dashboard tracking
    session_id = f"batch-{uuid.uuid4().hex[:8]}"
    sessions_db[session_id] = HandoverSession(
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

    # 6. Return 200 OK wrapper response
    return CapsuleBatchSyncResponse(
        sync_status=sync_status,
        synced_count=len(req.capsules),
        has_critical_conflict=has_critical_conflict,
        conflicts=conflicts,
        summary=summary,
        processed_at=now_utc
    )


# ==========================================
# Legacy / Full Handover Endpoints
# ==========================================

@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "Baton MVP", "timestamp": datetime.now(timezone.utc).isoformat()}



@app.post("/api/handover/start", response_model=HandoverSession)
def start_handover(req: HandoverRequest):
    session_id = f"session-{uuid.uuid4().hex[:8]}"

    # 1. Gemini Agent: Fact Extraction
    facts = agent_service.extract_facts(req.log_text, req.voice_transcripts)

    # 2. Deterministic Safety Rules Engine Evaluation
    conflicts = rules_engine.evaluate(facts, req.plant_sensor_state, req.active_permits)

    # 3. Gemini Agent: Generate Gap Questions if conflicts exist
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

    sessions_db[session_id] = session
    return session


@app.get("/api/handover/{session_id}", response_model=HandoverSession)
def get_session(session_id: str):
    if session_id not in sessions_db:
        raise HTTPException(status_code=404, detail="Handover session not found")
    return sessions_db[session_id]


class AnswerPayload(BaseModel):
    answers: Dict[str, str]  # question_id -> answer text


@app.post("/api/handover/{session_id}/answer", response_model=HandoverSession)
def submit_answers(session_id: str, payload: AnswerPayload):
    if session_id not in sessions_db:
        raise HTTPException(status_code=404, detail="Handover session not found")

    session = sessions_db[session_id]

    # Process answers and convert to facts
    for q in session.questions:
        if q.id in payload.answers:
            q.answer_text = payload.answers[q.id]
            q.answered = True
            session.facts.append(
                Fact(
                    id=f"FACT-ANS-{q.id}",
                    text=f"Operator Verified: {payload.answers[q.id]}",
                    category="OPERATOR_CLARIFICATION",
                    source_type="OPERATOR_ANSWER",
                    source_id=q.id
                )
            )

    # Re-evaluate safety rules with new clarification facts
    # (If operator clarifies, some conflicts may be resolved)
    session.brief = agent_service.compose_brief(session.conflicts, session.facts, "en")
    session.status = "READY_FOR_BRIEF"
    sessions_db[session_id] = session

    return session


class AcknowledgePayload(BaseModel):
    item_id: str
    readback_text: str


@app.post("/api/handover/{session_id}/acknowledge", response_model=HandoverSession)
def acknowledge_item(session_id: str, payload: AcknowledgePayload):
    if session_id not in sessions_db:
        raise HTTPException(status_code=404, detail="Handover session not found")

    session = sessions_db[session_id]
    if not session.brief:
        raise HTTPException(status_code=400, detail="Brief not generated yet")

    found = False
    for item in session.brief.items:
        if item.id == payload.item_id:
            item.acknowledged = True
            item.readback_text = payload.readback_text
            found = True
            break

    if not found:
        raise HTTPException(status_code=404, detail="Brief item not found")

    sessions_db[session_id] = session
    return session


@app.post("/api/handover/{session_id}/complete")
def complete_handover(session_id: str):
    if session_id not in sessions_db:
        raise HTTPException(status_code=404, detail="Handover session not found")

    session = sessions_db[session_id]
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

    session.status = "COMPLETED"
    session.brief.completion_status = "COMPLETED"
    sessions_db[session_id] = session

    return {"status": "COMPLETED", "message": "Handover responsibility successfully transferred."}


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

@app.post("/api/transcribe")
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
    
    # 1. Auth check
    expected_key = os.environ.get("AEGIS_API_KEY", "dev-key")
    if not x_aegis_key or not secrets.compare_digest(x_aegis_key, expected_key):
        raise HTTPException(status_code=401, detail={"error": {"code": "UNAUTHORIZED", "message": "Invalid or missing X-Aegis-Key"}})
        
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
    engine = os.environ.get("TRANSCRIBE_ENGINE", "gemini")
    
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "test-project")
    region = "us-central1" # Regional endpoint for Vertex AI
    
    transcript_text = ""
    detected_lang = None
    no_speech = False
    english_text = None
    
    # Calculate approx audio length for logs (assume 16kHz, 16bit mono = 32kB/s)
    audio_seconds = byte_size / 32000.0 
    
    try:
        if engine == "gemini":
            client = genai.Client(vertexai=True, project=project_id, location=region)
            model_id = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            mime = audio.content_type if audio.content_type and "audio" in audio.content_type else "audio/mp4"
            response = client.models.generate_content(
                model=model_id,
                contents=[
                    genai.types.Part.from_bytes(data=audio_content, mime_type=mime),
                    "Transcribe the following audio accurately. If it is in a non-English language (such as Tamil or Malay), output the original transcription, and on a new line prefixed with 'TRANSLATION: ', output the English translation keeping asset tags (like P-201B) unchanged. If already English, just output the transcription."
                ]
            )
            raw_text = response.text.strip() if response.text else ""
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
        raise HTTPException(status_code=status_code, detail={"error": {"code": "UPSTREAM_ERROR", "message": str(e)}})
    except Exception as e:
        if "duration" in str(e).lower() or "too long" in str(e).lower():
            raise HTTPException(status_code=413, detail={"error": {"code": "PAYLOAD_TOO_LARGE", "message": "Audio duration too long"}})
        raise HTTPException(status_code=500, detail={"error": {"code": "INTERNAL_ERROR", "message": str(e)}})

    # 5. Translation step if not English (if not already populated)
    if not english_text and not no_speech and detected_lang and not detected_lang.startswith("en"):

        try:
            client = genai.Client(vertexai=True, project=project_id, location=region)
            model_id = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            
            prompt = (
                "Translate the following transcript to English. "
                "Keep asset tags (like P-201B) unchanged. Return ONLY the plain English text.\n\n"
                f"{transcript_text}"
            )
            
            if asset_hints:
                prompt += f"\n\nContext/Hints for proper nouns: {asset_hints}"
                
            res = client.models.generate_content(
                model=model_id,
                contents=prompt
            )
            english_text = res.text.strip() if res.text else None
        except Exception as e:
            logger.error(f"Translation failed: {e}")
            english_text = None

    latency_ms = int((time.time() - start_time) * 1000)
    model_used = "chirp_3" if engine == "chirp3" else os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

    print(
        f"Transcribe request_id={client_request_id} size={byte_size} "
        f"audio_s={audio_seconds:.1f} lang={detected_lang} "
        f"engine={engine} lat_ms={latency_ms} status=200"
    )

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
