from __future__ import annotations
from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class Severity(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


class Fact(BaseModel):
    id: str
    text: str
    category: str  # e.g., "EQUIPMENT", "ISOLATION", "PERMIT", "ALARM"
    source_type: str  # "LOG", "VOICE", "PERMIT", "PLANT"
    source_id: str


class SafetyConflict(BaseModel):
    id: str
    rule_id: str  # e.g., "R1", "R2"
    title: str
    description: str
    severity: Severity
    evidence_ids: List[str] = Field(default_factory=list)
    status: str = "OPEN"  # "OPEN", "CONFIRMED", "CLARIFIED", "MITIGATED"
    mitigation_notes: Optional[str] = None


class GapQuestion(BaseModel):
    id: str
    question_text: str
    target_language: str = "en"
    answer_text: Optional[str] = None
    answered: bool = False


class BriefItem(BaseModel):
    id: str
    text: str
    severity: Severity
    citations: List[str] = Field(default_factory=list)
    acknowledged: bool = False
    readback_text: Optional[str] = None


class HandoverBrief(BaseModel):
    items: List[BriefItem] = Field(default_factory=list)
    completion_status: str = "PENDING"  # "PENDING", "COMPLETED", "ESCALATED"
    incoming_supervisor: Optional[str] = None


class HandoverRequest(BaseModel):
    unit_name: str
    shift_name: str
    outgoing_operator: str
    log_text: str
    voice_transcripts: List[str] = Field(default_factory=list)
    active_permits: List[Dict[str, Any]] = Field(default_factory=list)
    plant_sensor_state: Dict[str, Any] = Field(default_factory=dict)
    target_language: str = "en"


class HandoverSession(BaseModel):
    id: str
    unit_name: str
    shift_name: str
    outgoing_operator: str
    status: str = "PREPARING"  # "PREPARING", "NEEDS_CLARIFICATION", "READY_FOR_BRIEF", "COMPLETED"
    facts: List[Fact] = Field(default_factory=list)
    conflicts: List[SafetyConflict] = Field(default_factory=list)
    questions: List[GapQuestion] = Field(default_factory=list)
    brief: Optional[HandoverBrief] = None
    created_at: str
