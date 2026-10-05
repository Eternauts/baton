from __future__ import annotations
import uuid
from datetime import datetime
from typing import Dict, List, Optional
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
    SafetyConflict, GapQuestion, Fact
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


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": "Baton MVP", "timestamp": datetime.utcnow().isoformat()}


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
    expected_key = os.environ.get("AEGIS_API_KEY", "")
    if not x_aegis_key or not expected_key or not secrets.compare_digest(x_aegis_key, expected_key):
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
    engine = os.environ.get("TRANSCRIBE_ENGINE", "chirp3")
    
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "test-project")
    region = "us-central1" # Chosen region as per plan
    
    transcript_text = ""
    detected_lang = None
    no_speech = False
    
    # Calculate approx audio length for logs (assume 16kHz, 16bit mono = 32kB/s)
    audio_seconds = byte_size / 32000.0 
    
    try:
        if engine == "gemini":
            client = genai.Client(vertexai=True, project=project_id, location=region)
            model_id = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
            response = client.models.generate_content(
                model=model_id,
                contents=[
                    genai.types.Part.from_bytes(data=audio_content, mime_type="audio/wav"),
                    "Transcribe the following audio accurately. Just output the transcription text, no other comments."
                ]
            )
            transcript_text = response.text.strip() if response.text else ""
            if not transcript_text:
                no_speech = True
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

    # 5. Translation step if not English
    english_text = None
    if not no_speech and detected_lang and not detected_lang.startswith("en"):
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
