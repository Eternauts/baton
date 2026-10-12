"""HandoverPipeline: the ADK multi-agent system that runs after a handover is synced.

  Intake (custom) -> ContextGatherer [SOPRetriever || HistoryRetriever] + assembler (custom)
  -> RulesGate (custom, no model) -> SafetyCrossCheck (LLM) -> Briefing (LLM) -> Distill (custom)

Rules decide, models explain. Every model stage runs inside a GuardedStage that validates the output
in code and substitutes a deterministic fallback when it cannot be trusted.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, AsyncGenerator, Callable, Optional

from google.adk.agents import BaseAgent, LlmAgent, ParallelAgent, SequentialAgent
from google.adk.events import Event, EventActions
from google.adk.models import Gemini
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from pydantic import BaseModel, ConfigDict, ValidationError

from app.agents import fallbacks, guardrails, outputs
from app.agents.context import RunContext
from app.agents.schemas import (AssessmentItem, Retrieval, RuleVerdict, SafetyAssessment, ShiftBrief)
from app.agents.tools import compute_verdicts, load_event, make_tools
from app.agents.tracing import TraceCollector
from app.config import get_settings
from app.knowledge.handover_chunker import _names_from_operator_id, scrub_names
from app.knowledge.tags import extract_asset_tags, normalize_unit
from app.pipeline.intake import HandoverNotFound, run_intake

logger = logging.getLogger("baton.agents.pipeline")
APP_NAME = "baton"
PIPELINE_TIMEOUT_S = 100       # must stay under the worker's 120 s Cloud Run timeout and the 120 s ack deadline
RETRIEVER_TIMEOUT_S = 25      # a slow model must not hold up a safety brief: past the budget the stage falls back
MAIN_STAGE_TIMEOUT_S = 35


# ------------------------------------------------------------------ models
def make_model(name: str) -> Gemini:
    s = get_settings()
    location = s.gemini_fast_location if name == s.gemini_fast_model and name != s.gemini_model else s.gemini_location
    return Gemini(model=name, client_kwargs={"vertexai": True, "project": s.project, "location": location},
                  retry_options=types.HttpRetryOptions(attempts=3))


def _gen_cfg(max_tokens: int, thinking: str) -> types.GenerateContentConfig:
    return types.GenerateContentConfig(max_output_tokens=max_tokens, thinking_config=types.ThinkingConfig(thinking_level=thinking))


async def close_models(agents) -> None:
    """Close the model clients while their event loop is still running. Each run uses its own loop, and a client
    left for the garbage collector is closed after the loop is gone, which logs 'Event loop is closed' errors."""
    seen = set()
    for a in agents:
        client = getattr(getattr(a, "model", None), "api_client", None)
        if client is None or id(client) in seen:
            continue
        seen.add(id(client))
        try:
            await client.aio.aclose()
        except Exception as err:  # noqa: BLE001 - cleanup must never fail a run
            logger.debug("model client close failed: %s", type(err).__name__)


# ------------------------------------------------------------------ prompt inputs
def facts_text(capsules: list[dict], operator_id: Optional[str]) -> str:
    names = _names_from_operator_id(operator_id)
    lines = []
    for c in capsules:
        note = scrub_names(c.get("text_transcript") or "", names)
        lines.append(f"- {c.get('asset_tag')} ({str(c.get('category', '')).upper()}) state {c.get('asserted_state')}: {note[:300]}")
    return "\n".join(lines) or "- (no entries)"


def _ctx_lines(ctx: RunContext, ids: list[str], source_types: tuple[str, ...]) -> str:
    out = []
    for cid in ids:
        h = ctx.retrieved.get(cid)
        if h and h["source_type"] in source_types:
            sup = f" [supersedes {h['supersedes']}]" if h.get("supersedes") else ""
            out.append(f"[{cid}] {h['title']}{sup}: {h['text']}")
    return "\n".join(out) or "(none)"


# ------------------------------------------------------------------ instructions
SOP_INSTRUCTION = """You support a shift-handover safety check at a process plant.

Facts logged by the outgoing shift:
{facts_text}

Write at most two search queries, each a natural question such as "how to isolate a pump before seal replacement", covering the equipment, states and hazards in these facts, and call search_sops for both at the same time in one step. Do not search again afterwards. Pass asset_tag only when a single piece of equipment is clearly the subject. Then select the chunks that are genuinely relevant to these facts. Use only chunk_id values returned by the tool. If nothing is relevant, return an empty list. Give a one or two sentence summary."""

HISTORY_INSTRUCTION = """You support a shift-handover safety check at a process plant.

Unit: {unit}
Equipment tags in the current facts: {asset_tags}
Facts logged by the outgoing shift:
{facts_text}

For each distinct equipment tag (at most three), call search_history with a short query about its recent condition and pass asset_tag. Make all the calls together in one step and do not search again afterwards. Keep only events from earlier shifts that bear on the current facts, for example a worsening trend, a repair that was planned, or an isolation or bypass. Use only chunk_id values returned by the tool. If nothing is relevant, return an empty list. Give a one or two sentence summary."""

CROSSCHECK_INSTRUCTION = """You are the safety cross-checker for a shift handover at a process plant. Deterministic safety rules have already produced verdicts. They are final: you must not remove, soften, relabel or contradict any of them.

Facts logged by the outgoing shift:
{facts_text}

Simulated plant feed readings for these assets (not live telemetry):
{scada_text}

Rule verdicts (authoritative, one JSON object per line):
{verdicts_text}

Relevant SOP chunks (cite by chunk_id):
{sop_context}

Related events from earlier shifts (cite by chunk_id):
{history_context}

Produce items:
1. One item for EVERY rule verdict: source "rule", copy verdict_id, rule_id, severity and asset_tag exactly, and explain in plain language, in at most three sentences, why it matters. Cite SOP chunk_ids in sop_citations where a chunk supports the point. Never say a conflict is clear, resolved, mitigated or safe: it stays open until someone verifies it physically.
2. Extra items with source "advisory" (severity WARNING or INFO only) for anything the operator did not mention that the facts, plant feed, SOPs or history suggest, such as a worsening trend or a bypass missing from the log. Cite only chunk_ids you were given. Do not invent readings or IDs. If there is nothing to add, add none."""

BRIEF_INSTRUCTION = """Write the incoming-shift safety brief for the supervisor at a process plant.

Facts logged by the outgoing shift:
{facts_text}

Verified assessment (JSON; the rule items are final):
{assessment_text}

headline: one sentence of at most 200 characters stating how many conflicts are open and the most critical one.
items: one line per assessment item, most severe first. Keep its severity, rule_id, verdict_id, asset_tag and citations unchanged. The text is one or two plain sentences of at most 250 characters and must not repeat the severity, rule ID, verdict ID or asset tag, which are shown separately.
Say that open conflicts must be physically verified and read back by the incoming supervisor. Never say they are clear, resolved, mitigated or safe. Use plain operational language."""


# ------------------------------------------------------------------ custom agents
class _Base(BaseAgent):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    rc: Any = None


class IntakeAgent(_Base):
    """Deterministic: store capsules, chunk, embed, write knowledge chunks (idempotent)."""
    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        res = await asyncio.to_thread(run_intake, self.rc.handover_id)
        self.rc.step("tool_result", self.name, f"stored {res['capsules']} capsule(s), {res['chunks']} chunk(s)")
        yield Event(author=self.name, actions=EventActions(state_delta={"intake_chunks": res["chunks"]}))


class ContextAssembler(_Base):
    """Deterministic: turn the retrievers' selections into prompt text. Only chunks actually retrieved are used."""
    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        st = ctx.session.state

        def chosen(key: str, types_: tuple[str, ...]) -> list[str]:
            raw = st.get(key) or {}
            ids = [i for i in (raw.get("relevant_chunk_ids") or []) if i in self.rc.retrieved]
            if not ids:   # retriever failed or chose nothing: nothing is cited, but keep the closest hits as context
                ids = [i for i, h in sorted(self.rc.retrieved.items(), key=lambda kv: kv[1]["distance"])
                       if h["source_type"] in types_][:2] if not raw else []
            return ids

        sop_ids, hist_ids = chosen("sop_result", ("SOP",)), chosen("hist_result", ("HANDOVER", "OBSERVATION"))
        self.rc.step("tool_result", self.name, f"assembled {len(sop_ids)} SOP and {len(hist_ids)} history chunk(s)",
                     retrieved_ids=sop_ids + hist_ids)
        yield Event(author=self.name, actions=EventActions(state_delta={
            "sop_context": _ctx_lines(self.rc, sop_ids, ("SOP",)),
            "history_context": _ctx_lines(self.rc, hist_ids, ("HANDOVER", "OBSERVATION"))}))


class RulesGate(_Base):
    """Deterministic: run rules R1 to R4. No model is involved and nothing downstream can change a verdict."""
    tools: Any = None

    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        rc = self.rc
        rc.step("tool_call", self.name, f"evaluate_rules({rc.handover_id})", tool_name="evaluate_rules")
        t = time.time()
        verdicts = await asyncio.to_thread(compute_verdicts, rc.capsules)
        rc.verdicts = verdicts
        rc.step("tool_result", self.name, "rule verdicts: " + (", ".join(f"{v.rule_id} {v.severity}" for v in verdicts) or "none"),
                tool_name="evaluate_rules", rule_ids=[v.rule_id for v in verdicts], latency_ms=int((time.time() - t) * 1000))
        tags = list(dict.fromkeys([c.get("asset_tag") for c in rc.capsules if c.get("asset_tag")]))
        scada = self.tools["get_scada"](tags)
        rc.step("tool_result", self.name, f"plant feed read for {len(scada['readings'])} asset(s)", tool_name="get_scada")
        try:
            others = await asyncio.to_thread(self.tools["get_open_conflicts"], rc.unit or "")
            rc.unresolved_elsewhere = any(c.get("handover_id") != rc.handover_id for c in others.get("conflicts", []))
            rc.step("tool_result", self.name, f"{len(others.get('conflicts', []))} unresolved conflict(s) in unit (24 h)", tool_name="get_open_conflicts")
        except Exception as err:  # noqa: BLE001 - extra context only; the rules themselves already ran
            logger.warning("get_open_conflicts failed: %s", type(err).__name__)
        yield Event(author=self.name, actions=EventActions(state_delta={
            "verdicts_text": "\n".join(json.dumps(v.model_dump()) for v in verdicts) or "(no rule verdicts)",
            "scada_text": json.dumps(scada["readings"]) or "{}"}))


class GuardedStage(_Base):
    """Run an LLM agent, then check its output in code. Malformed output is retried once; output that
    breaks a guardrail (or a failed call) is replaced by the deterministic fallback."""
    inner: Any = None
    out_key: str = ""
    final_key: str = ""
    kind: str = ""                      # retrieval | assessment | brief
    check: Callable = None
    stage_timeout: float = 40.0

    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        rc = self.rc
        parsed, used_fallback = None, False
        for attempt in range(2):
            captured = None
            try:
                async with asyncio.timeout(self.stage_timeout):
                    async for ev in self.inner.run_async(ctx):
                        yield ev
                        sd = ev.actions.state_delta if ev.actions else None
                        if sd and self.out_key in sd:
                            captured = sd[self.out_key]
            except ValidationError as err:       # ADK rejected malformed structured output itself: retry once
                rc.guard.add(self.name, "invalid_output", f"attempt {attempt + 1}: {err.error_count()} schema error(s)")
                rc.step("guardrail", self.name, f"invalid output (attempt {attempt + 1}), {'retrying' if attempt == 0 else 'falling back'}")
                continue
            except Exception as err:  # noqa: BLE001 - model, tool or timeout failure: fall back, never fail the run
                name = "stage_timeout" if isinstance(err, TimeoutError) else "stage_error"
                rc.guard.add(self.name, name, f"{type(err).__name__} after {self.stage_timeout:.0f}s budget" if name == "stage_timeout" else type(err).__name__)
                rc.step("guardrail", self.name, f"{name} ({type(err).__name__}); using deterministic fallback")
                break
            try:
                parsed = self.check(captured, rc)
                break
            except ValidationError as err:       # malformed JSON / schema: retry once
                rc.guard.add(self.name, "invalid_output", f"attempt {attempt + 1}: {err.error_count()} schema error(s)")
                rc.step("guardrail", self.name, f"invalid output (attempt {attempt + 1}), {'retrying' if attempt == 0 else 'falling back'}")
            except guardrails_violation() as err:   # unsafe content: no retry, discard
                rc.guard.add(self.name, err.name, "; ".join(err.problems))
                rc.step("guardrail", self.name, f"{err.name}: output discarded ({'; '.join(err.problems)[:120]})")
                break
        if parsed is None:
            used_fallback = True
            rc.fallback_agents.append(self.name)
            parsed = self._fallback()
        yield Event(author=self.name, actions=EventActions(state_delta={
            self.final_key: parsed.model_dump(), self.final_key + "_text": json.dumps(parsed.model_dump()),
            self.final_key + "_fallback": used_fallback}))

    def _fallback(self) -> BaseModel:
        rc = self.rc
        if self.kind == "assessment":
            return fallbacks.fallback_assessment(rc.verdicts)
        if self.kind == "brief":
            return fallbacks.fallback_brief(rc.verdicts, len(rc.capsules))
        return Retrieval(summary="No context retrieved.", relevant_chunk_ids=[])


class GuardrailViolation(Exception):
    def __init__(self, name: str, problems: list[str]):
        super().__init__(name)
        self.name, self.problems = name, problems


def guardrails_violation():
    return GuardrailViolation


# ---- validators: return the cleaned model or raise ValidationError / GuardrailViolation
def _load(model_cls, captured):
    if captured is None:
        raise ValidationError.from_exception_data(model_cls.__name__, [{"type": "missing", "loc": ("output",), "input": None}])
    return model_cls.model_validate_json(captured) if isinstance(captured, str) else model_cls.model_validate(captured)


def validate_retrieval(captured, rc: RunContext) -> Retrieval:
    r = _load(Retrieval, captured)
    kept, removed = guardrails.strip_unretrieved(r.relevant_chunk_ids, rc.retrieved_ids)
    if removed:
        rc.guard.add("retrieval", "citation_stripped", f"{len(removed)} unknown chunk id(s) removed")
        rc.step("guardrail", "retrieval", f"citation_stripped: {len(removed)} id(s) were never retrieved")
    return Retrieval(summary=r.summary, relevant_chunk_ids=kept)


def _check_texts(texts: list[str], rc: RunContext) -> None:
    bad = guardrails.check_no_false_all_clear(texts, rc.has_unresolved)
    if bad:
        raise GuardrailViolation("false_all_clear", bad)


def validate_assessment(captured, rc: RunContext) -> SafetyAssessment:
    a = _load(SafetyAssessment, captured)
    changed = guardrails.clamp_advisory_severity(a.items)
    if changed:
        rc.guard.add("SafetyCrossCheck", "advisory_clamped", changed[0])
    problems = guardrails.check_verdict_lock(a.items, rc.verdicts)
    if problems:
        raise GuardrailViolation("verdict_lock", problems)
    _check_texts([i.explanation for i in a.items], rc)
    by_id = {v.verdict_id: v for v in rc.verdicts}
    for i in a.items:                       # rule items carry the rule's own severity and asset, whatever the model wrote
        v = by_id.get(i.verdict_id or "")
        if i.source == "rule" and v:
            i.severity, i.rule_id, i.asset_tag = v.severity, v.rule_id, v.asset_tag
        for field in ("sop_citations", "history_citations"):
            kept, removed = guardrails.strip_unretrieved(getattr(i, field), rc.retrieved_ids)
            if removed:
                rc.guard.add("SafetyCrossCheck", "citation_stripped", f"{len(removed)} unknown id(s) in {field}")
                rc.step("guardrail", "SafetyCrossCheck", f"citation_stripped: {len(removed)} id(s) were never retrieved")
            setattr(i, field, kept)
    return a


def validate_brief(captured, rc: RunContext) -> ShiftBrief:
    b = _load(ShiftBrief, captured)
    problems = guardrails.check_verdict_lock(b.items, rc.verdicts)
    if problems:
        raise GuardrailViolation("verdict_lock", problems)
    _check_texts([b.headline] + [i.text for i in b.items], rc)
    for i in b.items:
        kept, removed = guardrails.strip_unretrieved(i.citations, rc.retrieved_ids)
        if removed:
            rc.guard.add("Briefing", "citation_stripped", f"{len(removed)} unknown id(s)")
            rc.step("guardrail", "Briefing", f"citation_stripped: {len(removed)} id(s) were never retrieved")
        i.citations = kept
    return b


class Distill(_Base):
    """Deterministic: save the brief for the dashboard and build the small device update."""
    async def _run_async_impl(self, ctx) -> AsyncGenerator[Event, None]:
        rc, st = self.rc, ctx.session.state
        brief = ShiftBrief.model_validate(st.get("brief")) if st.get("brief") else fallbacks.fallback_brief(rc.verdicts, len(rc.capsules))
        cited = sorted({c for i in brief.items for c in i.citations})
        status = "fallback" if rc.fallback_agents else ("modified" if rc.guard.triggers else "passed")
        doc = {"handover_id": rc.handover_id, "run_id": rc.run_id, "unit": rc.unit, "headline": brief.headline,
               "items": [i.model_dump() for i in brief.items], "citations": cited,
               "citation_details": [{k: rc.retrieved[c][k] for k in ("chunk_id", "source_type", "source_id", "title")}
                                    for c in cited if c in rc.retrieved],
               "model": get_settings().gemini_model, "models": sorted(rc.models_used),
               "guardrail_status": status, "guardrails": rc.guard.names, "fallback_agents": rc.fallback_agents}
        update = fallbacks.build_device_update(rc.handover_id, rc.run_id, rc.unit, brief, rc.verdicts)
        try:
            await asyncio.to_thread(outputs.save_brief, rc.handover_id, doc)
            await asyncio.to_thread(outputs.save_device_update, update.model_dump())
            rc.step("tool_result", self.name, f"saved brief and device update ({status})")
        except Exception as err:  # noqa: BLE001
            logger.error("saving outputs failed: %s", type(err).__name__)
            raise
        yield Event(author=self.name, actions=EventActions(state_delta={"guardrail_status": status}))


# ------------------------------------------------------------------ assembly
def build_pipeline(rc: RunContext) -> SequentialAgent:
    s = get_settings()
    tools = make_tools(rc)
    rc.models_used.update({s.gemini_model, s.gemini_fast_model})

    sop = LlmAgent(name="SOPRetrieverLlm", model=make_model(s.gemini_fast_model), instruction=SOP_INSTRUCTION,
                   tools=[tools["search_sops"]], output_schema=Retrieval, output_key="sop_raw",
                   generate_content_config=_gen_cfg(512, "MINIMAL"))
    hist = LlmAgent(name="HistoryRetrieverLlm", model=make_model(s.gemini_fast_model), instruction=HISTORY_INSTRUCTION,
                    tools=[tools["search_history"]], output_schema=Retrieval, output_key="hist_raw",
                    generate_content_config=_gen_cfg(512, "MINIMAL"))
    cross = LlmAgent(name="SafetyCrossCheckLlm", model=make_model(s.gemini_model), instruction=CROSSCHECK_INSTRUCTION,
                     output_schema=SafetyAssessment, output_key="assessment_raw",
                     generate_content_config=_gen_cfg(1500, "LOW"))
    brief = LlmAgent(name="BriefingLlm", model=make_model(s.gemini_model), instruction=BRIEF_INSTRUCTION,
                     output_schema=ShiftBrief, output_key="brief_raw",
                     generate_content_config=_gen_cfg(1000, "MINIMAL"))

    rc.llm_agents = [sop, hist, cross, brief]
    return SequentialAgent(name="HandoverPipeline", sub_agents=[
        IntakeAgent(name="Intake", rc=rc),
        SequentialAgent(name="ContextGathering", sub_agents=[
            ParallelAgent(name="ContextGatherer", sub_agents=[
                GuardedStage(name="SOPRetriever", rc=rc, inner=sop, out_key="sop_raw", final_key="sop_result", kind="retrieval", check=validate_retrieval, stage_timeout=RETRIEVER_TIMEOUT_S),
                GuardedStage(name="HistoryRetriever", rc=rc, inner=hist, out_key="hist_raw", final_key="hist_result", kind="retrieval", check=validate_retrieval, stage_timeout=RETRIEVER_TIMEOUT_S),
            ]),
            ContextAssembler(name="ContextAssembler", rc=rc)]),
        RulesGate(name="RulesGate", rc=rc, tools=tools),
        GuardedStage(name="SafetyCrossCheck", rc=rc, inner=cross, out_key="assessment_raw", final_key="assessment", kind="assessment", check=validate_assessment, stage_timeout=MAIN_STAGE_TIMEOUT_S),
        GuardedStage(name="Briefing", rc=rc, inner=brief, out_key="brief_raw", final_key="brief", kind="brief", check=validate_brief, stage_timeout=MAIN_STAGE_TIMEOUT_S),
        Distill(name="Distill", rc=rc),
    ])


def _initial_state(rc: RunContext, event: dict) -> dict:
    tags = list(dict.fromkeys(c["asset_tag"].upper() for c in rc.capsules if c.get("asset_tag")))
    return {"facts_text": facts_text(rc.capsules, event.get("operator_id")), "asset_tags": ", ".join(tags) or "(none)",
            "unit": rc.unit or "unknown", "handover_id": rc.handover_id, "assessment_text": "", "sop_context": "(none)",
            "history_context": "(none)", "scada_text": "{}", "verdicts_text": "(none)"}


async def run_pipeline_async(handover_id: str, run_id: str, write_trace: bool = True) -> dict:
    event = await asyncio.to_thread(load_event, handover_id)
    if not event:
        raise HandoverNotFound(handover_id)
    rc = RunContext(run_id=run_id, trigger="handover.synced", handover_id=handover_id,
                    unit=normalize_unit(event.get("unit_name")), capsules=event.get("capsules") or [])
    trace = TraceCollector(rc, write=write_trace)
    ss = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=build_pipeline(rc), session_service=ss, plugins=[trace])
    await ss.create_session(app_name=APP_NAME, user_id="worker", session_id=run_id, state=_initial_state(rc, event))
    started = time.time()
    error: Optional[str] = None
    try:
        async with asyncio.timeout(PIPELINE_TIMEOUT_S):
            async for _ in runner.run_async(user_id="worker", session_id=run_id,
                                            new_message=types.Content(role="user", parts=[types.Part(text="check handover")])):
                pass
    except Exception as err:  # noqa: BLE001 - infrastructure errors are re-raised below; the rest degrade to fallback
        error = type(err).__name__
        logger.error("pipeline run=%s error=%s", run_id, error)
    finally:
        await close_models(rc.llm_agents)
    await trace.flush()
    if error and not rc.verdicts:
        rc.verdicts = await asyncio.to_thread(compute_verdicts, rc.capsules)
    if error:   # the pipeline died mid-way: still deliver the rule verdicts as a fallback brief
        rc.fallback_agents.append("pipeline")
        rc.guard.add("pipeline", "pipeline_error", error)
        brief = fallbacks.fallback_brief(rc.verdicts, len(rc.capsules))
        await asyncio.to_thread(outputs.save_brief, handover_id, {
            "handover_id": handover_id, "run_id": run_id, "unit": rc.unit, "headline": brief.headline,
            "items": [i.model_dump() for i in brief.items], "citations": [], "citation_details": [],
            "model": get_settings().gemini_model, "models": [], "guardrail_status": "fallback",
            "guardrails": rc.guard.names, "fallback_agents": rc.fallback_agents})
        await asyncio.to_thread(outputs.save_device_update,
                                fallbacks.build_device_update(handover_id, run_id, rc.unit, brief, rc.verdicts).model_dump())
    return {"status": "fallback" if rc.fallback_agents else "completed", "models_used": sorted(rc.models_used),
            "tokens": {k: {"prompt": v[0], "output": v[1]} for k, v in rc.tokens.items()},
            "guardrails_triggered": rc.guard.triggers, "capsules": len(rc.capsules),
            "chunks": None, "total_ms": int((time.time() - started) * 1000), "steps": len(trace.steps)}


def run_handover_pipeline(handover_id: str, run_id: str) -> dict:
    """Blocking entry point for the worker."""
    return asyncio.run(run_pipeline_async(handover_id, run_id))
