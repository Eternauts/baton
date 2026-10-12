"""Request, model-output and response shapes."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Scalar = str | int | float | bool


class DeviceContext(BaseModel):
    """What the device already knows. Kept small: it travels over the constrained link."""

    model_config = ConfigDict(extra="forbid")
    unit: str | None = Field(None, max_length=80)
    tags: list[str] = Field(default_factory=list, max_length=20)
    # Live readings or states the operator or device reports, e.g. {"GD-311": "BYPASSED"}.
    state: dict[str, Scalar] = Field(default_factory=dict, max_length=40)
    note: str | None = Field(None, max_length=300)


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(min_length=2, max_length=1000, description="The question")
    ctx: DeviceContext | None = None
    k: int = Field(6, ge=1, le=12, description="Passages to retrieve")
    lang: str = Field("en", pattern=r"^[a-z]{2,3}(-[A-Za-z]{2,4})?$", description="Answer language")
    budget: int = Field(1200, ge=200, le=16000, description="Max response size in bytes (before gzip)")


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(min_length=2, max_length=1000)
    ctx: DeviceContext | None = None
    k: int = Field(4, ge=1, le=12)
    budget: int = Field(1500, ge=200, le=16000)


# ---- Gemini structured output (no numeric bounds: clamped in code, not trusted to the model) ----

class DraftClaim(BaseModel):
    text: str
    quote: str
    source: int
    confidence: float


class DraftAnswer(BaseModel):
    status: Literal["ANSWERED", "PARTIAL", "INSUFFICIENT", "CONFLICT"]
    answer: str
    claims: list[DraftClaim]
    confidence: float
    note: str = ""
    action: str = ""


# ---- Full (debug) response ----

Decision = Literal["A", "P", "N", "C"]  # Answer, Partial, No answer, Conflict


class Claim(BaseModel):
    text: str
    confidence: float
    sources: list[int]  # indexes into AskResult.sources
    grounding: Literal["exact", "near"]


class SourceRef(BaseModel):
    id: str
    title: str
    section: str
    relevance: float  # relative to the best hit, 0-1
    snippet: str = ""


class Breakdown(BaseModel):
    retrieval: float
    grounding: float
    model: float


class AskResult(BaseModel):
    decision: Decision
    answer: str
    confidence: float
    claims: list[Claim] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    action: str = ""
    note: str = ""
    generator: Literal["gemini", "extractive", "none"]
    model: str = ""
    breakdown: Breakdown
    corpus_version: str
    latency_ms: int = 0
