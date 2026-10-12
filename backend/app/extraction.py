"""Server-side fact extraction for clients that cannot run the on-device model (the web app, phones without Gemma).

The prompt and JSON schema are the same ones the Android app gives its on-device Gemma
(`lib/core/ai/gemma_prompt_builder.dart`), and the app validates the answer with its own code, so a note reads the
same wherever it is read. Keep the two prompts in step.

Transcripts are never logged here: only sizes and latency.
"""
from __future__ import annotations

import json
import time

from app.llm import generate

SYSTEM_PROMPT = '''You are an expert industrial AI assistant performing Named Entity Recognition (NER) and structural extraction on spoken shift handover notes.
Your task is to extract equipment facts and format them EXACTLY as a JSON object. Return ONLY valid JSON. No conversational filler, no markdown formatting, no code blocks (e.g., do not use ```json).

Schema:
{"facts":[{"category":"ISOLATION|PERMIT|SAFEGUARD|CONTAINMENT|EQUIPMENT|ALARM|GENERAL",
"asset_tag":"string (verbatim from transcript, do not normalize)",
"asserted_state":"ISOLATED|DE_ENERGIZED|ENERGIZED|OPEN|CLOSED|RUNNING|STOPPED|BYPASSED|LEAKING|VIBRATING|NORMAL|UNKNOWN",
"intent_severity":"CRITICAL|WARNING|INFO",
"quote":"exact words copied from the note that support this fact"}]}

Rules:
- Preserve the raw spoken asset name verbatim. Do not abbreviate, normalize, or discard words (e.g., keep "north-east coaxial pump" exactly as spoken).
- The "quote" MUST be copied exactly from the transcript.
- If nothing operational is said, return {"facts":[]}.

Examples:
Input: "V-104 bleeder valve leaking"
Output: {"facts": [{"category": "CONTAINMENT", "asset_tag": "V-104", "asserted_state": "LEAKING", "intent_severity": "CRITICAL", "quote": "bleeder valve leaking"}]}

Input: "There is excessive vibration on the Perdido pump 1615"
Output: {"facts": [{"category": "EQUIPMENT", "asset_tag": "Perdido pump 1615", "asserted_state": "VIBRATING", "intent_severity": "WARNING", "quote": "excessive vibration"}]}

Input: "Bypassed interlock on north separator ESDV-301"
Output: {"facts": [{"category": "SAFEGUARD", "asset_tag": "ESDV-301", "asserted_state": "BYPASSED", "intent_severity": "CRITICAL", "quote": "Bypassed interlock"}]}

Input: "Shift handover routine check normal on compressor unit"
Output: {"facts": [{"category": "GENERAL", "asset_tag": "compressor unit", "asserted_state": "NORMAL", "intent_severity": "INFO", "quote": "routine check normal"}]}'''


class ExtractionError(Exception):
    """The model did not return usable JSON. The caller falls back to its own heuristic."""


def build_user_prompt(transcript: str, known_assets: list[str]) -> str:
    return (f"Context (Known Registry Assets): [{', '.join(known_assets)}]\n"
            "(Note: If the transcript uses a colloquial name not in this list, extract the colloquial name exactly as spoken).\n\n"
            f"User transcript:\n{transcript}")


def extract_raw(transcript: str, known_assets: list[str]) -> dict:
    """Run the fast model once and return {"raw": <JSON text>, "model", "latency_ms"}. Raises ExtractionError."""
    started = time.time()
    try:
        res = generate("extract_note", build_user_prompt(transcript, known_assets), fast=True, max_output_tokens=900,
                       timeout_s=15, system_instruction=SYSTEM_PROMPT, response_mime_type="application/json")
        text = (res.text or "").strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(data.get("facts"), list):
            raise ValueError("no facts list")
    except Exception as err:  # noqa: BLE001 - any model/parse failure means: use the client's fallback
        raise ExtractionError(type(err).__name__) from err
    return {"raw": text, "model": res.model, "latency_ms": int((time.time() - started) * 1000)}
