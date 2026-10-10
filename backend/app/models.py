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


class Capsule(BaseModel):
    """Offline shift capsule extracted on-device via Gemma E4B."""
    uuid: str = Field(..., description="Unique client-generated UUID for the offline capsule")
    timestamp: str = Field(..., description="ISO8601 timestamp of log creation on mobile")
    category: str = Field(..., description="Operational category e.g. EQUIPMENT, ISOLATION, PERMIT, ALARM")
    asset_tag: str = Field(..., description="Industrial asset identifier e.g. P-201B, V-102")
    asserted_state: str = Field(..., description="Physical state asserted by technician e.g. ISOLATED, OPEN, RUNNING")
    text_transcript: str = Field(..., description="On-device Gemma E4B transcript or manual technician note")
    intent_severity: Severity = Field(default=Severity.INFO, description="Intent severity classified by on-device model")


class CapsuleBatchSyncRequest(BaseModel):
    """Batch payload sent by Flutter app upon reconnecting from airplane mode."""
    capsules: List[Capsule] = Field(..., max_length=50, description="List of offline captured capsules (up to 50)")
    device_id: Optional[str] = Field(default="edge-flutter-01", description="Mobile device identifier")
    operator_id: Optional[str] = Field(default="TECH-OFFLINE", description="Outgoing technician identifier")
    shift_name: Optional[str] = Field(default="SHIFT-A", description="Shift identifier")
    unit_name: Optional[str] = Field(default="UNIT-01", description="Unit or plant module")


class CapsuleBatchSyncResponse(BaseModel):
    """Wrapper response for batch sync (returns 200 OK with conflict details to prevent client crash)."""
    sync_status: str = Field(..., description="'SUCCESS' or 'CONFLICT_DETECTED'")
    synced_count: int = Field(..., description="Total number of processed capsules")
    has_critical_conflict: bool = Field(..., description="True if any critical rule (R1/R2) was violated")
    conflicts: List[SafetyConflict] = Field(default_factory=list, description="List of detected safety conflicts")
    summary: str = Field(..., description="AI or deterministic safety brief summary")
    processed_at: str = Field(..., description="UTC timestamp of synchronization")

