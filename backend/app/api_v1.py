"""New v1 endpoints: Ask the logs, and device updates. Auth and rate limiting are injected by main.py."""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Callable, Optional

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.knowledge.tags import normalize_unit

logger = logging.getLogger("baton.api_v1")
MAX_UPDATES = 20


class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    unit: str = Field(..., min_length=1, max_length=80)
    asset_tag: Optional[str] = Field(default=None, max_length=40)
    language: Optional[str] = Field(default=None, max_length=20)
    device_id: Optional[str] = Field(default=None, max_length=80)


class QueryRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    unit: str = Field(default="HYDROCRACKER-01", min_length=1, max_length=80)
    asset_tag: Optional[str] = Field(default=None, max_length=40)
    permit_id: Optional[str] = Field(default=None, max_length=40)
    language: Optional[str] = Field(default=None, max_length=20)
    device_id: Optional[str] = Field(default=None, max_length=80)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=500)
    permit_id: Optional[str] = Field(default=None, max_length=40)


class ExtractRequest(BaseModel):
    transcript: str = Field(..., min_length=1, max_length=1000)
    known_assets: list[str] = Field(default_factory=list, max_length=50)


def _iso(v) -> Optional[str]:
    return v.isoformat() if hasattr(v, "isoformat") else (str(v) if v is not None else None)


def read_device_updates(device_id: str, since: Optional[datetime], unit_hint: Optional[str]) -> dict:
    """Blocking Firestore work, run in a thread."""
    from app.knowledge.store import get_db
    from google.cloud.firestore_v1.base_query import FieldFilter
    db = get_db()
    unit = None
    snap = db.collection("devices").document(device_id).get()
    if snap.exists:
        unit = (snap.to_dict() or {}).get("unit")
    unit = unit or normalize_unit(unit_hint)
    if not unit:
        return {"device_id": device_id, "unit": None, "updates": [],
                "note": "unknown device: it has not synced since updates were enabled; pass ?unit=<unit> to look up by unit"}
    q = db.collection("device_updates").where(filter=FieldFilter("unit", "==", unit))
    if since is not None:
        q = q.where(filter=FieldFilter("created_at", ">", since))
    docs = q.order_by("created_at", direction="DESCENDING").limit(MAX_UPDATES * 2).stream()
    updates = []
    for d in docs:
        u = d.to_dict()
        if u.get("target", "all") not in ("all", device_id):
            continue
        updates.append({"update_id": u.get("update_id", d.id), "severity": u.get("severity"), "alerts": u.get("alerts", []),
                        "required_actions": u.get("required_actions", []), "summary": u.get("summary", ""),
                        "handover_id": u.get("handover_id"), "run_id": u.get("run_id"), "created_at": _iso(u.get("created_at"))})
        if len(updates) >= MAX_UPDATES:
            break
    return {"device_id": device_id, "unit": unit, "updates": updates}


_RUN_ID = re.compile(r"^(run|ask)-[A-Za-z0-9_-]{1,80}$")
_CHUNK_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
MAX_STEPS = 400
RUN_FIELDS = ("run_id", "trigger", "status", "handover_id", "question_id", "unit", "started_at", "finished_at", "total_ms",
              "models_used", "guardrails_triggered", "tokens", "attempts", "question_preview", "device_id")


def _clean(d: dict, fields) -> dict:
    return {k: (_iso(d[k]) if hasattr(d.get(k), "isoformat") else d[k]) for k in fields if k in d}


def read_runs(limit: int) -> list[dict]:
    from app.knowledge.store import get_db
    q = get_db().collection("agent_runs").order_by("started_at", direction="DESCENDING").limit(limit)
    return [_clean(d.to_dict(), RUN_FIELDS) for d in q.stream()]


def read_run(run_id: str) -> Optional[dict]:
    """The run, its ordered steps with retrieved chunk ids resolved to titles, and its brief if it has one."""
    from app.knowledge.store import get_db
    db = get_db()
    snap = db.collection("agent_runs").document(run_id).get()
    if not snap.exists:
        return None
    run = _clean(snap.to_dict(), RUN_FIELDS)
    steps = []
    for d in db.collection("agent_runs").document(run_id).collection("steps").order_by("seq").limit(MAX_STEPS).stream():
        steps.append(_clean(d.to_dict(), ("seq", "agent", "kind", "tool_name", "summary", "retrieved_ids", "rule_ids", "latency_ms", "timestamp")))
    ids = list(dict.fromkeys(i for s in steps for i in s.get("retrieved_ids", [])))[:40]
    chunks = {}
    if ids:
        for c in db.get_all([db.collection("knowledge_chunks").document(i) for i in ids]):
            if c.exists:
                x = c.to_dict()
                chunks[c.id] = {"title": x.get("title"), "source_type": x.get("source_type"), "source_id": x.get("source_id"), "created_at": _iso(x.get("created_at"))}
    brief = None
    if run.get("handover_id"):
        b = db.collection("handover_briefs").document(run["handover_id"]).get()
        if b.exists:
            brief = _clean(b.to_dict(), ("headline", "items", "citation_details", "guardrail_status", "guardrails", "model", "created_at"))
    return {"run": run, "steps": steps, "chunks": chunks, "brief": brief}


def read_chunk(chunk_id: str) -> Optional[dict]:
    from app.knowledge.store import get_db
    snap = get_db().collection("knowledge_chunks").document(chunk_id).get()
    if not snap.exists:
        return None
    return _clean(snap.to_dict(), ("title", "source_type", "source_id", "text", "created_at", "doc_type", "revision", "asset_tags", "seeded"))


def create_router(require_key: Callable[[Optional[str]], None], rate_ok: Callable[[str], bool],
                  require_app_key: Optional[Callable[[Optional[str]], None]] = None) -> APIRouter:
    """require_key: supervisor scope (agent traces). require_app_key: what a shipped app may call (ask, device updates, extract)."""
    app_key = require_app_key or require_key
    router = APIRouter(prefix="/api/v1")

    # ---- Query mode: answers from the documents, on the spot (app scope)
    def _limited(request: Request) -> None:
        if not rate_ok(request.client.host if request.client else "unknown"):
            raise HTTPException(status_code=429, detail={"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "Too many requests"}})

    @router.get("/permits")
    async def permits(x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
        app_key(x_aegis_key)
        from app.agents.query import list_permits
        return {"permits": list_permits(), "source": "simulated permit register"}

    @router.post("/search")
    async def search_docs(req: SearchRequest, request: Request, x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
        app_key(x_aegis_key)
        _limited(request)
        from app.agents.query import search_documents
        try:
            return await asyncio.to_thread(search_documents, req.query.strip(), req.permit_id)
        except Exception as err:  # noqa: BLE001 - the answer call can still work; the app shows what it has
            logger.warning("search failed: %s", type(err).__name__)
            raise HTTPException(status_code=502, detail={"error": {"code": "SEARCH_FAILED", "message": "The document search had a problem"}})

    @router.get("/docs")
    async def docs_catalog(x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
        app_key(x_aegis_key)
        from app.agents.query import document_catalog
        return {"documents": await asyncio.to_thread(document_catalog)}

    @router.get("/docs/{chunk_id}")
    async def doc_section(chunk_id: str, x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
        app_key(x_aegis_key)
        if not _CHUNK_ID.match(chunk_id):
            raise HTTPException(status_code=400, detail="invalid chunk id")
        out = await asyncio.to_thread(read_chunk, chunk_id)
        if out is None:
            raise HTTPException(status_code=404, detail="document section not found")
        out.pop("seeded", None)
        return out

    @router.post("/query")
    async def query(req: QueryRequest, request: Request, x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
        app_key(x_aegis_key)
        _limited(request)
        from app.agents.query import answer_query
        result = await answer_query(req.question.strip(), req.unit.strip(), req.asset_tag, req.permit_id, req.language, req.device_id)
        logger.info("query run=%s latency_ms=%s citations=%d verdicts=%d fallback=%s qchars=%d permit=%s", result["run_id"], result["latency_ms"],
                    len(result["citations"]), len(result["rule_verdicts"]), result["fallback"], len(req.question), bool(result["permit"]))
        return result

    @router.post("/extract")
    async def extract(req: ExtractRequest, request: Request, x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
        app_key(x_aegis_key)
        if not rate_ok(request.client.host if request.client else "unknown"):
            raise HTTPException(status_code=429, detail={"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "Too many requests"}})
        from app.extraction import ExtractionError, extract_raw
        assets = [a.strip()[:40] for a in req.known_assets if a and a.strip()]
        try:
            out = await asyncio.to_thread(extract_raw, req.transcript.strip(), assets)
        except ExtractionError as err:
            logger.warning("extract failed: %s", err)
            raise HTTPException(status_code=502, detail={"error": {"code": "EXTRACTION_FAILED", "message": "The model could not read that note"}})
        logger.info("extract latency_ms=%s chars=%d assets=%d", out["latency_ms"], len(req.transcript), len(assets))
        return out

    @router.post("/ask")
    async def ask(req: AskRequest, request: Request, x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
        app_key(x_aegis_key)
        if not rate_ok(request.client.host if request.client else "unknown"):
            raise HTTPException(status_code=429, detail={"error": {"code": "RATE_LIMIT_EXCEEDED", "message": "Too many requests"}})
        from app.agents.ask import answer_question      # imported lazily: the ADK stack is heavy
        result = await answer_question(req.question.strip(), req.unit.strip(), req.asset_tag, req.language, req.device_id)
        logger.info("ask run=%s latency_ms=%s citations=%d verdicts=%d qchars=%d", result["run_id"], result["latency_ms"],
                    len(result["citations"]), len(result["rule_verdicts"]), len(req.question))
        return result

    @router.get("/devices/{device_id}/updates")
    async def device_updates(device_id: str, since: Optional[str] = Query(None), unit: Optional[str] = Query(None),
                             x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
        app_key(x_aegis_key)
        if len(device_id) > 80:
            raise HTTPException(status_code=400, detail="device_id too long")
        since_dt = None
        if since:
            try:
                since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))
                if since_dt.tzinfo is None:
                    since_dt = since_dt.replace(tzinfo=timezone.utc)
            except ValueError:
                raise HTTPException(status_code=400, detail="since must be an ISO 8601 timestamp")
        out = await asyncio.to_thread(read_device_updates, device_id, since_dt, unit)
        out["server_time"] = datetime.now(timezone.utc).isoformat()
        return out

    @router.get("/agents/runs")
    async def agent_runs(limit: int = Query(20, ge=1, le=50), x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
        require_key(x_aegis_key)
        return {"runs": await asyncio.to_thread(read_runs, limit)}

    @router.get("/agents/runs/{run_id}")
    async def agent_run(run_id: str, x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
        require_key(x_aegis_key)
        if not _RUN_ID.match(run_id):
            raise HTTPException(status_code=400, detail="invalid run id")
        out = await asyncio.to_thread(read_run, run_id)
        if out is None:
            raise HTTPException(status_code=404, detail="run not found")
        return out

    @router.get("/agents/chunks/{chunk_id}")
    async def agent_chunk(chunk_id: str, x_aegis_key: Optional[str] = Header(None, alias="X-Aegis-Key")):
        require_key(x_aegis_key)
        if not _CHUNK_ID.match(chunk_id):
            raise HTTPException(status_code=400, detail="invalid chunk id")
        out = await asyncio.to_thread(read_chunk, chunk_id)
        if out is None:
            raise HTTPException(status_code=404, detail="chunk not found")
        return out

    return router
