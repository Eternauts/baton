"""Structured outputs. Agents return JSON that must validate against these models."""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Severity = Literal["CRITICAL", "WARNING", "INFO"]
SEVERITY_RANK = {"INFO": 0, "WARNING": 1, "CRITICAL": 2}


class Retrieval(BaseModel):
    """Output of the SOP and history retrievers."""
    summary: str = Field(max_length=400)
    relevant_chunk_ids: list[str] = Field(default_factory=list, max_length=6)


class RuleVerdict(BaseModel):
    """A deterministic verdict from rules.py. Never produced by a model."""
    verdict_id: str
    rule_id: str
    severity: Severity
    asset_tag: Optional[str] = None
    title: str
    description: str
    evidence_ids: list[str] = Field(default_factory=list)


class AssessmentItem(BaseModel):
    severity: Severity
    explanation: str = Field(max_length=700)
    source: Literal["rule", "advisory"] = "rule"
    verdict_id: Optional[str] = None      # set for source == "rule"
    rule_id: Optional[str] = None
    asset_tag: Optional[str] = None
    sop_citations: list[str] = Field(default_factory=list)
    history_citations: list[str] = Field(default_factory=list)


class SafetyAssessment(BaseModel):
    items: list[AssessmentItem] = Field(max_length=12)


class BriefLine(BaseModel):
    severity: Severity
    text: str = Field(max_length=400)
    rule_id: Optional[str] = None
    verdict_id: Optional[str] = None
    asset_tag: Optional[str] = None
    citations: list[str] = Field(default_factory=list)


class ShiftBrief(BaseModel):
    headline: str = Field(max_length=240)
    items: list[BriefLine] = Field(max_length=12)


class DeviceUpdate(BaseModel):
    update_id: str
    unit: Optional[str]
    target: str = "all"                   # a device_id, or "all" for every device in the unit
    severity: Severity
    alerts: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)
    summary: str = Field(max_length=400)
    handover_id: str
    run_id: str
