"""Query mode: a fast, grounded answer for a worker with a doubt, on the spot.

Two calls make it feel instant:
  1. search_documents(): vector search only (about a second). The app shows the matching documents straight away.
  2. answer_query():   the same retrieval, plus ONE model call that writes the answer (a few seconds). No agent loop.

The model writes prose. Code decides everything else, exactly as in the Ask agent: which chunks count as citations,
which open conflicts are quoted (unchanged), that no text may say work is safe or clear while a conflict is open, and
that an expired permit is called out. When a worker is working under a permit, the permit and its type steer the search
and are part of the prompt, so "what exactly do I need to do" is answered for that job.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, ValidationError

from app.agents import guardrails
from app.agents.ask import _write_run, dedupe_conflicts, partial_answer, strip_chunk_ids
from app.agents.context import RunContext
from app.agents.tools import make_tools
from app.agents.tracing import TraceCollector
from app.config import get_settings
from app.knowledge.schema import COLLECTION, SOURCE_HANDOVER, SOURCE_OBSERVATION, SOURCE_SOP
from app.knowledge.search import search as knowledge_search
from app.knowledge.store import get_db
from app.knowledge.tags import detect_language, extract_asset_tags, normalize_unit
from app.llm import generate
from app.plant_data import MOCK_ACTIVE_PERMITS

logger = logging.getLogger("baton.agents.query")

QUERY_TIMEOUT_S = 14.0
MAX_QUESTION_CHARS = 500
LANGS = {"en", "ta", "ms", "zh"}
SNIPPET_CHARS = 220
CHUNK_CHARS = 700

# What a permit type usually involves, so the search finds the right procedures even for a vague question.
PERMIT_TOPICS = {
    "HOT_WORK": "hot work welding cutting grinding fire watch gas testing ignition sources",
    "MAINTENANCE": "maintenance isolation lock out tag out depressurise drain pump gasket seal",
    "COLD_WORK": "cold work maintenance isolation lock out tag out",
    "CONFINED_SPACE": "confined space entry gas testing ventilation standby person rescue",
    "ELECTRICAL": "electrical isolation lock out tag out proving dead",
}

SYSTEM = """You help operators and maintenance workers at a process plant who have a doubt or are about to do a job. You answer ONLY from the source records provided below.

Return ONLY a JSON object, no markdown:
{"in_scope": true|false, "answer": "...", "steps": ["..."], "cautions": ["..."], "follow_ups": ["..."], "answer_language": "en|ta|ms|zh", "citation_ids": ["..."], "confidence_note": "..."|null}

Rules:
- Use only the SOURCES. Never invent procedures, limits, values, tags, permit numbers or times. If the sources do not cover the question, say so plainly in "answer", leave steps empty and tell the worker to ask their supervisor or permit issuer. Do not guess.
- "answer": one to three short sentences that directly answer the question (under 60 words). Workers are busy and may be wearing gloves.
- "steps": when the question asks what to do, how, or what is required, give the ordered actions from the sources, each short and in plain words (at most 8). Otherwise leave empty.
- "cautions": stop-work conditions, limits and things that must NOT be done, from the sources (at most 4).
- "citation_ids": only chunk_id values of sources you actually used. Never write chunk ids inside the text; name the document instead, for example SOP-HW-01.
- Never say or imply that work is safe, clear, resolved or approved to proceed. An open or acknowledged conflict is never resolved. For "is it safe to ..." say you cannot confirm it is safe, give what the procedure requires, and name any open conflict by rule id.
- If a PERMIT is given, tailor the answer to that job. If the permit is EXPIRED, say work must not start or continue until it is re-issued, whatever else the question asks.
- If the question is not about this plant, its equipment, permits, procedures or safety, set in_scope to false, say you can only help with plant records, and cite nothing.
- Answer in the language of the question (English, Tamil, Malay, Mandarin) and set answer_language to its code. Keep equipment tags such as P-201B exactly as written.
- "follow_ups": up to 3 short questions the worker might ask next, from the same sources (under 70 characters each).
- confidence_note: one short sentence only when the sources are thin, partial or conflicting; otherwise null."""


class QueryAnswer(BaseModel):
    in_scope: bool
    answer: str = Field(max_length=1200)
    steps: list[str] = Field(default_factory=list)
    cautions: list[str] = Field(default_factory=list)
    follow_ups: list[str] = Field(default_factory=list)
    answer_language: str = "en"
    citation_ids: list[str] = Field(default_factory=list)
    confidence_note: Optional[str] = Field(default=None, max_length=300)

    def trimmed(self) -> "QueryAnswer":
        self.steps = [s.strip()[:260] for s in self.steps if str(s).strip()][:8]
        self.cautions = [s.strip()[:220] for s in self.cautions if str(s).strip()][:4]
        self.follow_ups = [s.strip()[:90] for s in self.follow_ups if str(s).strip()][:3]
        self.citation_ids = list(dict.fromkeys(self.citation_ids))[:8]
        return self


# ------------------------------------------------------------------ permits
def list_permits() -> list[dict]:
    """The active permits from the (simulated) permit register."""
    return [{"id": p["id"], "type": p.get("type", ""), "title": p.get("title", ""), "status": p.get("status", ""),
             "expired": bool(p.get("expired")) or str(p.get("status", "")).upper() == "EXPIRED"} for p in MOCK_ACTIVE_PERMITS]


def get_permit(permit_id: Optional[str]) -> Optional[dict]:
    if not permit_id:
        return None
    pid = permit_id.strip().upper()
    return next((p for p in list_permits() if p["id"].upper() == pid), None)


def _search_text(question: str, permit: Optional[dict]) -> str:
    """The text that is embedded: the question, steered by the permit's job when one is given."""
    if not permit:
        return question
    return f"{question} {permit['title']} {PERMIT_TOPICS.get(permit['type'], '')}".strip()


# ------------------------------------------------------------------ instant document search
def _heading(title: str, source_id: str) -> str:
    return title[len(source_id):].strip(" :-") if title.startswith(source_id) else title


def search_documents(query: str, permit_id: Optional[str] = None, k: int = 6) -> dict:
    """Vector search over the documents only, grouped by document. This is what the app shows first."""
    started = time.time()
    permit = get_permit(permit_id)
    hits = knowledge_search(_search_text(query, permit), k=k, source_types=[SOURCE_SOP])
    docs: dict[str, dict] = {}
    for h in hits:                                   # best hit first: the first chunk seen per document is its best
        d = docs.setdefault(h.source_id, {"source_id": h.source_id, "doc_type": h.doc_type or "SOP", "sections": 0,
                                          "best": {"chunk_id": h.chunk_id, "heading": _heading(h.title, h.source_id),
                                                   "snippet": h.text[:SNIPPET_CHARS].strip(), "distance": round(h.distance, 3)}})
        d["sections"] += 1
    return {"documents": list(docs.values())[:5], "permit": permit, "latency_ms": int((time.time() - started) * 1000)}


_catalog_cache: dict[str, Any] = {"at": 0.0, "docs": None}


def document_catalog() -> list[dict]:
    """Every document the assistant can search (distinct SOP, bulletin and manual ids), cached for five minutes."""
    now = time.time()
    if _catalog_cache["docs"] is not None and now - _catalog_cache["at"] < 300:
        return _catalog_cache["docs"]
    docs: dict[str, dict] = {}
    q = get_db().collection(COLLECTION).where("source_type", "==", SOURCE_SOP).select(["source_id", "doc_type", "title", "asset_tags"])
    for d in q.stream():
        f = d.to_dict()
        x = docs.setdefault(f["source_id"], {"source_id": f["source_id"], "doc_type": f.get("doc_type") or "SOP", "sections": 0, "asset_tags": set()})
        x["sections"] += 1
        x["asset_tags"].update(f.get("asset_tags") or [])
    out = [{**v, "asset_tags": sorted(v["asset_tags"])} for v in sorted(docs.values(), key=lambda v: v["source_id"])]
    _catalog_cache.update(at=now, docs=out)
    return out


# ------------------------------------------------------------------ the answer
def _compact(h) -> dict:
    return {"chunk_id": h.chunk_id, "source_type": h.source_type, "source_id": h.source_id, "title": h.title, "text": h.text[:CHUNK_CHARS],
            "distance": round(h.distance, 3), "asset_tags": h.asset_tags[:6], "created_at": h.created_at.isoformat() if h.created_at else None,
            "supersedes": h.supersedes}


def _sources_text(retrieved: dict[str, dict]) -> str:
    rows = sorted(retrieved.values(), key=lambda r: r["distance"])
    if not rows:
        return "(no matching records were found)"
    out = []
    for r in rows:
        extra = f" [supersedes {r['supersedes']}]" if r.get("supersedes") else ""
        when = f" ({r['created_at'][:10]})" if r.get("created_at") else ""
        out.append(f"chunk_id={r['chunk_id']} | {r['source_type']} | {r['title']}{when}{extra}\n{r['text']}")
    return "\n---\n".join(out)


def _prompt(question: str, unit: str, asset_tag: Optional[str], permit: Optional[dict], conflicts: list[dict], scada: dict,
            retrieved: dict[str, dict], language: Optional[str]) -> str:
    permit_line = (f"PERMIT the worker is working under: {permit['id']} ({permit['type']}): {permit['title']}. Status: {permit['status']}"
                   f"{' (EXPIRED: work must not start or continue)' if permit['expired'] else ''}") if permit else "PERMIT: none selected"
    return (f"Unit: {unit}\nEquipment the worker is focused on: {(asset_tag or 'none').upper()}\n{permit_line}\n"
            f"Preferred answer language: {language or 'same as the question'}\n"
            f"Conflicts open in this unit right now (authoritative):\n{chr(10).join(json.dumps(c) for c in conflicts[:6]) or '(none)'}\n"
            f"Readings from the simulated plant feed (not live telemetry):\n{json.dumps(scada['readings']) if scada['readings'] else '(none for the equipment named)'}\n\n"
            f"SOURCES:\n{_sources_text(retrieved)}\n\nQUESTION: {question}")


def _all_text(a: QueryAnswer) -> list[str]:
    return [a.answer, *a.steps, *a.cautions, *a.follow_ups]


def _validate(raw: str, rc: RunContext, conflicts: list[dict]) -> QueryAnswer:
    text = (raw or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    a = QueryAnswer.model_validate(json.loads(text)).trimmed()
    if not a.in_scope:
        a.citation_ids, a.steps, a.cautions, a.follow_ups, a.confidence_note = [], [], [], [], None
        return a
    bad = guardrails.check_no_false_all_clear(_all_text(a), rc.has_unresolved)
    if bad:
        raise _Violation(bad)
    kept, removed = guardrails.strip_unretrieved(a.citation_ids, rc.retrieved_ids)
    if removed:
        rc.guard.add("Query", "citation_stripped", f"{len(removed)} unknown id(s)")
        rc.step("guardrail", "Query", f"citation_stripped: {len(removed)} id(s) were never retrieved")
    a.citation_ids = kept
    # Open conflicts are returned as `rule_verdicts`, quoted unchanged, for the app to show in their own strip: code, not the model, supplies them.
    a.answer = strip_chunk_ids(a.answer)
    a.steps = [strip_chunk_ids(s) for s in a.steps]
    a.cautions = [strip_chunk_ids(s) for s in a.cautions]
    if a.answer_language not in LANGS:
        a.answer_language = detect_language(a.answer)
    return a


class _Violation(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("false_all_clear")
        self.problems = problems


def _citations(ids: list[str], retrieved: dict[str, dict]) -> list[dict]:
    return [{"chunk_id": i, "source_type": retrieved[i]["source_type"], "source_id": retrieved[i]["source_id"], "title": retrieved[i]["title"],
             "snippet": retrieved[i]["text"][:SNIPPET_CHARS].strip(), "created_at": retrieved[i].get("created_at")} for i in ids if i in retrieved]


async def answer_query(question: str, unit: str, asset_tag: Optional[str] = None, permit_id: Optional[str] = None,
                       language: Optional[str] = None, device_id: Optional[str] = None, write_trace: bool = True) -> dict:
    started = time.time()
    s = get_settings()
    run_id = f"ask-{uuid.uuid4().hex[:12]}"          # shares the Ask run id format so the dashboard trace screens show it too
    unit_key = normalize_unit(unit) or unit
    permit = get_permit(permit_id)
    rc = RunContext(run_id=run_id, trigger="ask", handover_id=None, unit=unit_key)
    trace = TraceCollector(rc, write=write_trace)
    rc.step("agent_start", "Query", "question received" + (f" (permit {permit['id']})" if permit else ""))
    if write_trace:
        await asyncio.to_thread(_write_run, run_id, {
            "run_id": run_id, "trigger": "ask", "question_id": run_id, "unit": unit_key, "status": "running",
            "started_at": datetime.fromtimestamp(started, timezone.utc), "finished_at": None, "total_ms": None,
            "models_used": [], "guardrails_triggered": [], "question_preview": ("[query] " + question)[:200], "question_chars": len(question),
            "device_id": device_id})

    tools = make_tools(rc)
    text = _search_text(question, permit)
    since = datetime.now(timezone.utc) - timedelta(hours=72)

    async def sops():
        return await asyncio.to_thread(knowledge_search, text, 5, [SOURCE_SOP])

    async def history():
        return await asyncio.to_thread(knowledge_search, text, 3, [SOURCE_HANDOVER, SOURCE_OBSERVATION], unit_key, None, since)

    async def open_conflicts():
        return await asyncio.to_thread(tools["get_open_conflicts"], unit_key)

    t0 = time.time()
    sop_hits, hist_hits, conf_rows = await asyncio.gather(sops(), history(), open_conflicts(), return_exceptions=True)
    for name, res in (("search_sops", sop_hits), ("search_history", hist_hits)):
        if isinstance(res, Exception):
            logger.warning("%s failed: %s", name, type(res).__name__)
            rc.step("guardrail", "Query", f"{name} failed ({type(res).__name__})")
            continue
        for h in res:
            c = _compact(h)
            rc.retrieved[c["chunk_id"]] = c
        rc.step("tool_result", "Query", f"{len(res)} record(s) from {name}", tool_name=name,
                retrieved_ids=[h.chunk_id for h in res], latency_ms=int((time.time() - t0) * 1000))
    conflicts: list[dict] = []
    if not isinstance(conf_rows, Exception):
        conflicts = dedupe_conflicts(conf_rows.get("conflicts", []))
        rc.unresolved_elsewhere = bool(conflicts)
        if asset_tag:
            tag = asset_tag.strip().upper()
            conflicts.sort(key=lambda c: c.get("asset_tag") != tag)
        rc.step("tool_result", "Query", f"{len(conflicts)} open conflict(s) in unit", tool_name="get_open_conflicts",
                rule_ids=[c["rule_id"] for c in conflicts])
    tags = list(dict.fromkeys(([asset_tag.strip().upper()] if asset_tag else []) + extract_asset_tags(question)))[:6]
    scada = tools["get_scada"](tags) if tags else {"readings": {}}

    parsed: Optional[QueryAnswer] = None
    note: Optional[str] = None
    prompt = _prompt(question, unit_key, asset_tag, permit, conflicts, scada, rc.retrieved, language)
    try:
        for attempt in range(2):
            left = QUERY_TIMEOUT_S - (time.time() - started)
            if left < 2:
                raise TimeoutError
            t1 = time.time()
            try:
                res = await asyncio.wait_for(asyncio.to_thread(
                    generate, "query", prompt, system_instruction=SYSTEM, max_output_tokens=1100, timeout_s=min(left, 12),
                    response_mime_type="application/json"), left)
                rc.models_used.add(res.model)
                rc.step("model_call", "Query", f"answer written by {res.model}", latency_ms=int((time.time() - t1) * 1000))
                parsed = _validate(res.text, rc, conflicts)
                break
            except (ValidationError, ValueError) as err:          # malformed JSON: one more try if there is time
                rc.guard.add("Query", "invalid_output", f"attempt {attempt + 1}: {type(err).__name__}")
                rc.step("guardrail", "Query", f"invalid output (attempt {attempt + 1})")
            except _Violation as v:
                rc.guard.add("Query", "false_all_clear", "; ".join(v.problems))
                rc.step("guardrail", "Query", f"false_all_clear: answer discarded ({'; '.join(v.problems)[:120]})")
                note = "The generated answer was withheld by a safety check, so only the matching records are shown."
                break
    except (TimeoutError, asyncio.TimeoutError):
        rc.guard.add("Query", "timeout", f"no answer within {QUERY_TIMEOUT_S:.0f}s")
        note = "The answer took too long, so only the matching records are shown."
    except Exception as err:  # noqa: BLE001 - model failure: show the records instead
        rc.guard.add("Query", "stage_error", type(err).__name__)
        rc.step("guardrail", "Query", f"stage_error ({type(err).__name__}): returning retrieval only")
        note = "The answer service had a problem, so only the matching records are shown."

    fallback = parsed is None
    if fallback:
        text_, cite_ids, note = partial_answer(rc.retrieved, conflicts, note or "No full answer was produced, so only the matching records are shown.")
        parsed = QueryAnswer(in_scope=True, answer=text_[:1200], answer_language="en", citation_ids=cite_ids, confidence_note=note)
        rc.fallback_agents.append("Query")

    permit_alert = None
    if permit and permit["expired"]:
        permit_alert = f"{permit['id']} has EXPIRED. Do not start or continue this work until the permit is re-issued."

    total_ms = int((time.time() - started) * 1000)
    rc.step("agent_end", "Query", f"answered ({'fallback' if fallback else 'ok'})", latency_ms=total_ms)
    await trace.flush()
    if write_trace:
        await asyncio.to_thread(_write_run, run_id, {
            "status": "fallback" if fallback else "completed", "finished_at": datetime.now(timezone.utc), "total_ms": total_ms,
            "models_used": sorted(rc.models_used), "guardrails_triggered": [f"{t['agent']}:{t['guardrail']}" for t in rc.guard.triggers]})
    return {"answer": parsed.answer, "steps": parsed.steps, "cautions": parsed.cautions, "follow_ups": parsed.follow_ups,
            "answer_language": parsed.answer_language, "citations": _citations(parsed.citation_ids, rc.retrieved) if parsed.in_scope else [],
            "rule_verdicts": conflicts if parsed.in_scope else [], "permit": permit, "permit_alert": permit_alert,
            "confidence_note": parsed.confidence_note, "fallback": fallback, "run_id": run_id, "model": s.gemini_model, "latency_ms": total_ms}
