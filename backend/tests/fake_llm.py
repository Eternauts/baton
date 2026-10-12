"""A scripted stand-in for Gemini that plugs into ADK, so the whole pipeline can run offline."""
from __future__ import annotations

import json
from typing import AsyncGenerator

from google.adk.models import BaseLlm
from google.adk.models.llm_request import LlmRequest
from google.adk.models.llm_response import LlmResponse
from google.genai import types

CONTROL = {"mode": "good", "calls": {}, "chunk_sop": "chunk-sop-1", "chunk_hist": "chunk-hist-1", "delay": 0.0}


def _system_text(req: LlmRequest) -> str:
    si = req.config.system_instruction if req.config else None
    if si is None:
        return ""
    if isinstance(si, str):
        return si
    parts = getattr(si, "parts", None) or []
    return "\n".join(getattr(p, "text", "") or "" for p in parts)


def _json_lines(text: str) -> list[dict]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    return out


def _has_function_response(req: LlmRequest) -> bool:
    return any(getattr(p, "function_response", None) for c in (req.contents or []) for p in (c.parts or []))


def _reply(payload: dict, req: LlmRequest) -> types.Content:
    """Structured output goes through set_model_response when ADK exposes it next to other tools."""
    if "set_model_response" in (req.tools_dict or {}):
        return types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="set_model_response", args=payload))])
    return types.Content(role="model", parts=[types.Part(text=json.dumps(payload))])


class FakeLlm(BaseLlm):
    model: str = "fake-model"

    @classmethod
    def supported_models(cls) -> list[str]:
        return ["fake-model"]

    async def generate_content_async(self, llm_request: LlmRequest, stream: bool = False) -> AsyncGenerator[LlmResponse, None]:
        import asyncio
        if CONTROL["delay"]:
            await asyncio.sleep(CONTROL["delay"])
        sys_text, mode = _system_text(llm_request), CONTROL["mode"]
        usage = types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=20)

        def done(content):
            return LlmResponse(content=content, usage_metadata=usage)

        if "You answer questions from shift supervisors" in sys_text:             # Ask agent
            if mode == "ask_crash":
                raise RuntimeError("model unavailable")
            if mode == "ask_out_of_scope":
                yield done(_reply({"in_scope": False, "answer": "I can only help with plant records and procedures.", "answer_language": "en",
                                   "citation_ids": [CONTROL["chunk_sop"]]}, llm_request))     # even a bogus citation must be dropped
                return
            if not _has_function_response(llm_request) and mode != "ask_nothing_found_skip_tools":
                yield done(types.Content(role="model", parts=[
                    types.Part(function_call=types.FunctionCall(name="search_sops", args={"query": "hot work near open line"})),
                    types.Part(function_call=types.FunctionCall(name="search_history", args={"query": "V-102 history"}))]))
                return
            CONTROL["calls"]["ask"] = CONTROL["calls"].get("ask", 0) + 1
            if mode == "ask_bad_json_once" and CONTROL["calls"]["ask"] == 1:
                yield done(types.Content(role="model", parts=[types.Part(text='{"in_scope": "maybe"}')]))
                return
            cites = [CONTROL["chunk_sop"], CONTROL["chunk_hist"]]
            text = "Per the hot work SOP, no open flange within 15 m. Open conflicts: R1 and R4 apply."
            if mode == "ask_clear":
                text = "Yes, it is safe to proceed with hot work near V-102."
            if mode == "ask_bad_citation":
                cites.append("chunk-never-retrieved")
            if mode == "ask_mentions_nothing":
                text = "Hot work needs a permit and a gas test."
            yield done(_reply({"in_scope": True, "answer": text, "answer_language": "en", "citation_ids": cites,
                               "confidence_note": None}, llm_request))
        elif "Write at most two search queries" in sys_text:                       # SOP retriever
            if not _has_function_response(llm_request):
                yield done(types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="search_sops", args={"query": "how to isolate a pump"}))]))
            else:
                ids = [CONTROL["chunk_sop"], "chunk-never-retrieved"] if mode == "bad_citation" else [CONTROL["chunk_sop"]]
                yield done(_reply({"summary": "Isolation SOP is relevant.", "relevant_chunk_ids": ids}, llm_request))
        elif "call search_history" in sys_text:                                   # history retriever
            if not _has_function_response(llm_request):
                yield done(types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name="search_history", args={"query": "pump history", "asset_tag": "P-201B"}))]))
            else:
                yield done(_reply({"summary": "Earlier shift saw a wet seal.", "relevant_chunk_ids": [CONTROL["chunk_hist"]]}, llm_request))
        elif "safety cross-checker" in sys_text:                                  # cross-check
            CONTROL["calls"]["cross"] = CONTROL["calls"].get("cross", 0) + 1
            if mode == "crash":
                raise RuntimeError("model unavailable")
            if mode == "bad_json_once" and CONTROL["calls"]["cross"] == 1:
                yield done(types.Content(role="model", parts=[types.Part(text='{"items": "not a list"}')]))
                return
            verdicts = _json_lines(sys_text.split("Rule verdicts", 1)[1])
            items = []
            for v in verdicts:
                if mode == "drop_verdict" and v["rule_id"] == "R1":
                    continue
                sev = "INFO" if (mode == "downgrade" and v["rule_id"] == "R1") else v["severity"]
                text = "The interlock is clear and it is safe to proceed." if (mode == "clear_language" and v["rule_id"] == "R1") else f"{v['title']} needs field verification."
                items.append({"severity": sev, "explanation": text, "source": "rule", "verdict_id": v["verdict_id"], "rule_id": v["rule_id"],
                              "asset_tag": v.get("asset_tag"), "sop_citations": [CONTROL["chunk_sop"], "chunk-never-retrieved"] if mode == "bad_citation" else [CONTROL["chunk_sop"]]})
            if mode == "advisory_critical":
                items.append({"severity": "CRITICAL", "explanation": "Seal history suggests imminent failure.", "source": "advisory", "history_citations": [CONTROL["chunk_hist"]]})
            yield done(_reply({"items": items}, llm_request))
        elif "incoming-shift safety brief" in sys_text:                          # briefing
            assessment = json.loads(sys_text.split("Verified assessment (JSON; the rule items are final):", 1)[1].split("\n\nheadline", 1)[0].strip())
            lines = [{"severity": i["severity"], "text": i["explanation"], "rule_id": i.get("rule_id"), "verdict_id": i.get("verdict_id"),
                      "asset_tag": i.get("asset_tag"), "citations": i.get("sop_citations", []) + i.get("history_citations", [])} for i in assessment["items"]]
            text = "All clear, safe to proceed." if mode == "brief_clear" else f"{len(lines)} conflict(s) are open and must be verified and read back."
            yield done(_reply({"headline": text, "items": lines}, llm_request))
        else:
            yield done(types.Content(role="model", parts=[types.Part(text="{}")]))
