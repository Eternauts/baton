"""Ask the logs: one ADK agent that answers from retrieved evidence, plus the code that makes the answer trustworthy.

The model writes prose. Code decides everything else: which chunks count as citations, which rule verdicts
are shown (open conflicts, quoted unchanged), and whether the text may be returned at all.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from google.adk.agents import LlmAgent
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, Field, ValidationError

from app.agents import guardrails
from app.agents.context import RunContext
from app.agents.pipeline import APP_NAME, _gen_cfg, close_models, make_model
from app.agents.tools import make_tools
from app.agents.tracing import TraceCollector
from app.config import get_settings
from app.knowledge.search import search as knowledge_search
from app.knowledge.store import get_db
from app.knowledge.tags import detect_language, extract_asset_tags, normalize_unit

logger = logging.getLogger("baton.agents.ask")

ASK_TIMEOUT_S = 20.0
FALLBACK_SEARCH_S = 5.0
MAX_QUESTION_CHARS = 500
LANGS = {"en", "ta", "ms", "zh"}

INSTRUCTION = """You answer questions from shift supervisors and operators at a process plant, using only evidence you retrieve with your tools.

Unit: {unit}
Equipment tag the user is focused on: {asset_tag}
Preferred answer language: {language_hint}
Conflicts that are open in this unit right now (authoritative, one JSON object per line):
{open_conflicts_text}
Current readings from the simulated plant feed (not live telemetry) for equipment named in the question:
{scada_text}

Rules:
- Search first. Use search_sops for procedures, bulletins and manuals, and search_history for what happened on earlier shifts (pass asset_tag when one piece of equipment is the subject). Make ALL the searches you need together in a single step, then answer; do not search again afterwards. The plant feed readings above are already loaded; call get_scada only for other equipment.
- Answer only from what the tools returned. Never invent readings, times, events, procedures or IDs. If nothing relevant came back, say plainly that no records were found and cite nothing.
- Put in citation_ids only chunk_id values you actually used. Never write chunk ids (long hex strings) inside the answer text; name the source by its title instead, for example SOP-HW-01.
- If the question is not about this plant, its equipment, procedures, shifts or safety (for example weather, general knowledge or small talk), set in_scope to false, politely say you can only help with plant records and procedures, and cite nothing.
- An open or acknowledged conflict is never resolved. Never say or imply that work is safe, clear, resolved or mitigated while a conflict is open. For questions like "is it safe to ...", say you cannot confirm it is safe, give the relevant SOP requirements, and name the open conflicts by rule id.
- Answer in the language of the question (English, Tamil, Malay, Mandarin) and set answer_language to its code (en, ta, ms, zh). Keep equipment tags such as P-201B exactly as written. Be brief: at most five sentences or a short list, under 120 words.
- confidence_note: one short sentence only when evidence is thin, partial or conflicting; otherwise null."""


class AskAnswer(BaseModel):
    in_scope: bool
    answer: str = Field(max_length=1800)
    answer_language: str = "en"
    citation_ids: list[str] = Field(default_factory=list, max_length=8)
    confidence_note: Optional[str] = Field(default=None, max_length=300)


# ------------------------------------------------------------------ deterministic pieces
def dedupe_conflicts(rows: list[dict]) -> list[dict]:
    """One entry per (rule, title); the tool returns newest first, so the newest handover wins."""
    seen, out = set(), []
    for r in rows:
        key = (r.get("rule_id"), r.get("title"))
        if key not in seen:
            seen.add(key)
            out.append(r)
    sev = {"CRITICAL": 0, "WARNING": 1, "INFO": 2}
    return sorted(out, key=lambda r: sev.get(r.get("severity", "WARNING"), 1))


def conflicts_line(conflicts: list[dict]) -> str:
    parts = [f"[{c['rule_id']} {c.get('severity', '')}] {c['title']} ({c['status']})" for c in conflicts[:4]]
    return "Open conflicts in this unit: " + "; ".join(parts) + ". They stay open until verified in the field."


def ensure_conflicts_mentioned(answer: str, conflicts: list[dict]) -> str:
    """If the model left an open conflict out, append it. Code, not the model, guarantees it is not hidden."""
    missing = [c for c in conflicts[:4] if c["rule_id"] not in answer]
    return answer if not missing else f"{answer.rstrip()}\n\n{conflicts_line(conflicts)}"


_HEX_ID = re.compile(r"\s*[\[(]?\b[0-9a-f]{40,64}\b[\])]?")


def strip_chunk_ids(text: str) -> str:
    """Raw chunk ids mean nothing to a reader; citations carry them."""
    return re.sub(r"[ \t]+([.,;:])", r"\1", _HEX_ID.sub("", text))


def citation_objects(ids: list[str], retrieved: dict[str, dict]) -> list[dict]:
    return [{"chunk_id": i, "source_type": retrieved[i]["source_type"], "source_id": retrieved[i]["source_id"],
             "title": retrieved[i]["title"], "created_at": retrieved[i].get("created_at")} for i in ids if i in retrieved]


def partial_answer(retrieved: dict[str, dict], conflicts: list[dict], reason: str) -> tuple[str, list[str], str]:
    """Answer built from retrieval alone: no model prose, so nothing can be invented."""
    top = sorted(retrieved.items(), key=lambda kv: kv[1]["distance"])[:3]
    if top:
        lines = [f"- [{h['source_type']}] {h['title']}: {h['text'][:140].strip()}…" for _, h in top]
        text = "I could not compose a full answer, so here are the most relevant records I found:\n" + "\n".join(lines)
    else:
        text = "I could not compose an answer and found no matching records."
    if conflicts:
        text += "\n\n" + conflicts_line(conflicts)
    return text, [cid for cid, _ in top], reason


# ------------------------------------------------------------------ validation
def validate_answer(raw: Any, rc: RunContext, conflicts: list[dict]) -> AskAnswer:
    a = raw if isinstance(raw, AskAnswer) else (AskAnswer.model_validate_json(raw) if isinstance(raw, str) else AskAnswer.model_validate(raw))
    if not a.in_scope:
        a.citation_ids, a.confidence_note = [], None
        return a
    bad = guardrails.check_no_false_all_clear([a.answer], rc.has_unresolved)
    if bad:
        raise guardrails_violation(bad)
    kept, removed = guardrails.strip_unretrieved(a.citation_ids, rc.retrieved_ids)
    if removed:
        rc.guard.add("Ask", "citation_stripped", f"{len(removed)} unknown id(s)")
        rc.step("guardrail", "Ask", f"citation_stripped: {len(removed)} id(s) were never retrieved")
    a.citation_ids = kept
    a.answer = ensure_conflicts_mentioned(strip_chunk_ids(a.answer), conflicts)
    if a.answer_language not in LANGS:
        a.answer_language = detect_language(a.answer)
    return a


class AskViolation(Exception):
    def __init__(self, problems: list[str]):
        super().__init__("false_all_clear")
        self.problems = problems


def guardrails_violation(problems: list[str]) -> AskViolation:
    return AskViolation(problems)


# ------------------------------------------------------------------ run
def _build_agent(rc: RunContext) -> LlmAgent:
    s = get_settings()
    t = make_tools(rc)
    agent = LlmAgent(name="AskAgent", model=make_model(s.gemini_model), instruction=INSTRUCTION,
                    tools=[t["search_sops"], t["search_history"], t["get_scada"], t["get_open_conflicts"]],
                    output_schema=AskAnswer, output_key="ask_raw", generate_content_config=_gen_cfg(1600, "LOW"))   # the cap includes reasoning tokens; 800 truncated some answers mid-JSON
    rc.llm_agents = [agent]
    return agent


def _write_run(run_id: str, doc: dict) -> None:
    try:
        get_db().collection("agent_runs").document(run_id).set(doc, merge=True)
    except Exception as err:  # noqa: BLE001 - a trace write must never fail the answer
        logger.warning("ask run write failed: %s", type(err).__name__)


async def answer_question(question: str, unit: str, asset_tag: Optional[str] = None, language: Optional[str] = None,
                          device_id: Optional[str] = None, write_trace: bool = True) -> dict:
    started = time.time()
    s = get_settings()
    run_id = f"ask-{uuid.uuid4().hex[:12]}"
    unit_key = normalize_unit(unit) or unit
    rc = RunContext(run_id=run_id, trigger="ask", handover_id=None, unit=unit_key)
    trace = TraceCollector(rc, write=write_trace)
    rc.step("agent_start", "Ask", "question received")
    if write_trace:
        await asyncio.to_thread(_write_run, run_id, {
            "run_id": run_id, "trigger": "ask", "question_id": run_id, "unit": unit_key, "status": "running",
            "started_at": datetime.fromtimestamp(started, timezone.utc), "finished_at": None, "total_ms": None,
            "models_used": [], "guardrails_triggered": [], "question_preview": question[:200], "question_chars": len(question),
            "device_id": device_id})

    # Open conflicts come from code, not from the model: they are the verdicts we quote.
    tools = make_tools(rc)
    conflicts: list[dict] = []
    try:
        rows = await asyncio.to_thread(tools["get_open_conflicts"], unit_key)
        conflicts = dedupe_conflicts(rows.get("conflicts", []))
        rc.unresolved_elsewhere = bool(conflicts)
        rc.step("tool_result", "Ask", f"{len(conflicts)} open conflict(s) in unit", tool_name="get_open_conflicts",
                rule_ids=[c["rule_id"] for c in conflicts])
        if asset_tag:
            tag = asset_tag.strip().upper()
            conflicts.sort(key=lambda c: c.get("asset_tag") != tag)    # conflicts about the focus asset first (stable)
    except Exception as err:  # noqa: BLE001
        logger.warning("open conflicts lookup failed: %s", type(err).__name__)

    # Readings for any equipment named in the question are loaded by code, saving the model a whole round trip.
    tags = list(dict.fromkeys(([asset_tag.strip().upper()] if asset_tag else []) + extract_asset_tags(question)))[:6]
    scada = tools["get_scada"](tags) if tags else {"readings": {}}
    if tags:
        rc.step("tool_result", "Ask", f"plant feed read for {len(scada['readings'])} of {len(tags)} tag(s)", tool_name="get_scada")

    state = {"unit": unit_key, "scada_text": json.dumps(scada["readings"]) if scada["readings"] else "(no readings for equipment named in the question)", "asset_tag": (asset_tag or "none").upper(), "language_hint": language or "same as the question",
             "open_conflicts_text": "\n".join(json.dumps(c) for c in conflicts) or "(none)"}
    ss = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=_build_agent(rc), session_service=ss, plugins=[trace])
    await ss.create_session(app_name=APP_NAME, user_id="ask", session_id=run_id, state=state)

    parsed: Optional[AskAnswer] = None
    note: Optional[str] = None
    captured = None
    try:
        for attempt in range(2):
            try:
                async with asyncio.timeout(max(1.0, ASK_TIMEOUT_S - (time.time() - started))):
                    async for ev in runner.run_async(user_id="ask", session_id=run_id,
                                                     new_message=types.Content(role="user", parts=[types.Part(text=question)])):
                        sd = ev.actions.state_delta if ev.actions else None
                        if sd and "ask_raw" in sd:
                            captured = sd["ask_raw"]
                parsed = validate_answer(captured, rc, conflicts)
                break
            except (ValidationError, ValueError) as err:       # malformed structured output: retry once if time allows
                rc.guard.add("Ask", "invalid_output", f"attempt {attempt + 1}")
                rc.step("guardrail", "Ask", f"invalid output (attempt {attempt + 1})")
                if ASK_TIMEOUT_S - (time.time() - started) < 7:          # not enough time left for another attempt
                    break
            except AskViolation as v:
                rc.guard.add("Ask", "false_all_clear", "; ".join(v.problems))
                rc.step("guardrail", "Ask", f"false_all_clear: answer discarded ({'; '.join(v.problems)[:120]})")
                note = "The generated answer was withheld by a safety check, so only retrieved records are shown."
                break
    except TimeoutError:
        rc.guard.add("Ask", "timeout", f"no answer within {ASK_TIMEOUT_S:.0f}s")
        rc.step("guardrail", "Ask", "timeout: returning retrieval only")
        note = "The full answer timed out, so only retrieved records are shown."
    except Exception as err:  # noqa: BLE001 - model or tool failure
        rc.guard.add("Ask", "stage_error", type(err).__name__)
        rc.step("guardrail", "Ask", f"stage_error ({type(err).__name__}): returning retrieval only")
        note = "The answer service had a problem, so only retrieved records are shown."

    await close_models(rc.llm_agents)
    fallback = parsed is None
    if fallback:
        if not rc.retrieved:    # the model never got to search: do one direct search so there is something to show
            try:
                hits = await asyncio.wait_for(asyncio.to_thread(knowledge_search, question, 3), FALLBACK_SEARCH_S)
                for h in hits:
                    rc.retrieved[h.chunk_id] = {"chunk_id": h.chunk_id, "source_type": h.source_type, "source_id": h.source_id, "title": h.title,
                                                "text": h.text, "distance": h.distance, "created_at": h.created_at.isoformat() if h.created_at else None}
            except Exception as err:  # noqa: BLE001
                logger.warning("fallback search failed: %s", type(err).__name__)
        text, cite_ids, note = partial_answer(rc.retrieved, conflicts, note or "No full answer was produced, so only retrieved records are shown.")
        parsed = AskAnswer(in_scope=True, answer=text, answer_language="en", citation_ids=cite_ids, confidence_note=note)
        rc.fallback_agents.append("Ask")

    verdicts = conflicts if parsed.in_scope else []
    total_ms = int((time.time() - started) * 1000)
    rc.step("agent_end", "Ask", f"answered ({'fallback' if fallback else 'ok'})", latency_ms=total_ms)
    await trace.flush()
    if write_trace:
        await asyncio.to_thread(_write_run, run_id, {
            "status": "fallback" if fallback else "completed", "finished_at": datetime.now(timezone.utc), "total_ms": total_ms,
            "models_used": [s.gemini_model], "tokens": {k: {"prompt": v[0], "output": v[1]} for k, v in rc.tokens.items()},
            "guardrails_triggered": [f"{t['agent']}:{t['guardrail']}" for t in rc.guard.triggers]})
    return {"answer": parsed.answer, "answer_language": parsed.answer_language,
            "citations": citation_objects(parsed.citation_ids, rc.retrieved) if parsed.in_scope else [],
            "rule_verdicts": verdicts, "confidence_note": parsed.confidence_note, "run_id": run_id,
            "model": s.gemini_model, "latency_ms": total_ms}
