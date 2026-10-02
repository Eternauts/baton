from __future__ import annotations
import uuid
from datetime import datetime
from typing import Dict
from fastapi import FastAPI, HTTPException, Status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

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
