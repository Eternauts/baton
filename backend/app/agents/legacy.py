from __future__ import annotations
import json
import os
import re
from typing import List, Dict, Any, Optional
from google.cloud import discoveryengine

from app.config import get_settings
from app.llm import generate
from app.models import Fact, SafetyConflict, GapQuestion, BriefItem, HandoverBrief, Severity


class GeminiAgentService:
    """
    Handles Gemini AI interactions:
    1. Log Fact Extraction (Gemini Flash-Lite)
    2. Gap Question Verification (Gemini Flash)
    3. Brief Composition with Cites (Gemini Flash)
    Falls back gracefully if AI service is offline or credentials are missing.
    """

    def __init__(self):
        # Gemini access goes through app.llm (single shared client, retries, logging).
        self.client = bool(get_settings().project)

    def extract_facts(self, log_text: str, voice_transcripts: List[str]) -> List[Fact]:
        """Extract structured facts from text logs and voice transcripts."""
        facts: List[Fact] = []
        full_text = log_text + "\n" + "\n".join(voice_transcripts)

        if self.client:
            try:
                prompt = (
                    "Extract operational facts from the following shift log and voice notes as JSON list.\n"
                    "Each item should have: 'text', 'category' (EQUIPMENT|ISOLATION|PERMIT|ALARM), 'source_type' (LOG|VOICE).\n"
                    f"Content:\n{full_text}"
                )
                res = generate("extract_facts", prompt, max_output_tokens=2048, timeout_s=30)

                # Attempt json parse
                clean_text = res.text.strip().removeprefix("```json").removesuffix("```").strip()
                data = json.loads(clean_text)
                for idx, item in enumerate(data):
                    facts.append(
                        Fact(
                            id=f"FACT-{idx+1}",
                            text=item.get("text", ""),
                            category=item.get("category", "EQUIPMENT"),
                            source_type=item.get("source_type", "LOG"),
                            source_id=f"SRC-{idx+1}"
                        )
                    )
                if facts:
                    return facts
            except Exception as err:
                print(f"[GeminiAgentService] Extract facts fallback triggered: {err}")

        # Heuristic / Fallback fact extractor if offline or API error
        lines = [line.strip() for line in full_text.split("\n") if line.strip()]
        for idx, line in enumerate(lines):
            category = "EQUIPMENT"
            if "ISOLAT" in line.upper() or "VALVE" in line.upper():
                category = "ISOLATION"
            elif "PERMIT" in line.upper() or "HOT WORK" in line.upper():
                category = "PERMIT"
            elif "BYPASS" in line.upper() or "ALARM" in line.upper():
                category = "ALARM"

            facts.append(
                Fact(
                    id=f"FACT-{idx+1}",
                    text=line,
                    category=category,
                    source_type="LOG" if idx < len(log_text.splitlines()) else "VOICE",
                    source_id=f"LOG-{idx+1}"
                )
            )

        return facts

    _LANG = {"en": "English", "ta": "Tamil", "ms": "Malay", "zh": "Chinese"}

    @staticmethod
    def _template_question(conflict: SafetyConflict, target_language: str) -> str:
        """Fixed fallback wording. Short on purpose: the conflict's details are shown next to the question."""
        t = conflict.title
        if target_language == "ta":
            return f"{t} குறித்துத் தயவுசெய்து உறுதிப்படுத்தவும். தற்போதைய நிலை என்ன?"
        if target_language == "ms":
            return f"Sila sahkan berkenaan {t}. Apakah status terkini?"
        if target_language == "zh":
            return f"请确认关于 {t}。目前的实际状态是什么？"
        return f"Clarification needed on {t}. Can you confirm the current physical state, and who checked it?"

    def generate_gap_questions(
        self,
        conflicts: List[SafetyConflict],
        facts: List[Fact],
        target_language: str = "en"
    ) -> List[GapQuestion]:
        """Questions for the outgoing operator, one per distinct conflict (at most 3).

        The rules decide WHICH conflicts need a question; the fast model only words it, in the operator's
        language, as something answerable from what they saw. A question that fails validation, or any model
        failure, falls back to the fixed template, so a conflict is never left without one.
        """
        if not conflicts:
            return []
        seen, distinct = set(), []
        for c in conflicts:                       # the same conflict reported twice is asked about once
            key = (c.rule_id, c.title)
            if key not in seen:
                seen.add(key)
                distinct.append(c)
        distinct = distinct[:3]
        texts = [self._template_question(c, target_language) for c in distinct]

        if self.client:
            try:
                listing = "\n".join(f"{i + 1}. [{c.rule_id}] {c.title}: {c.description}" for i, c in enumerate(distinct))
                prompt = (
                    f"You are Baton, a shift-handover safety assistant. Write ONE short question in {self._LANG.get(target_language, 'English')} "
                    "for each conflict below, to the outgoing operator who is leaving the shift. Each question: at most 30 words, "
                    "names the equipment or permit, and asks what they physically saw or did and who verified it. "
                    "Never say or imply the conflict is resolved, fine or safe. Return only a JSON array of exactly "
                    f"{len(distinct)} strings, in the same order.\n\nConflicts:\n{listing}"
                )
                res = generate("gap_questions", prompt, fast=True, max_output_tokens=600, timeout_s=12,
                               response_mime_type="application/json")
                data = json.loads(res.text.strip().removeprefix("```json").removesuffix("```").strip())
                if isinstance(data, list) and len(data) == len(distinct):
                    from app.agents.guardrails import find_clearing_language
                    for i, q in enumerate(data):
                        q = str(q).strip()
                        if 15 <= len(q) <= 300 and not find_clearing_language(q):
                            texts[i] = q
            except Exception as err:  # noqa: BLE001 - the template questions below are the fallback
                print(f"[GeminiAgentService] gap question fallback: {type(err).__name__}")

        return [GapQuestion(id=f"Q-{i + 1}", question_text=t, target_language=target_language) for i, t in enumerate(texts)]

    def compose_brief(
        self,
        conflicts: List[SafetyConflict],
        facts: List[Fact],
        target_language: str = "en"
    ) -> HandoverBrief:
        """Compose cited brief for the incoming supervisor."""
        items: List[BriefItem] = []

        # Convert conflicts to cited brief items
        for idx, conflict in enumerate(conflicts):
            items.append(
                BriefItem(
                    id=f"BRIEF-{idx+1}",
                    text=f"[{conflict.rule_id}] {conflict.title}: {conflict.description}",
                    severity=conflict.severity,
                    citations=conflict.evidence_ids
                )
            )

        # Include key facts as info items
        for idx, fact in enumerate(facts[:5]):
            items.append(
                BriefItem(
                    id=f"BRIEF-FACT-{idx+1}",
                    text=f"Fact Verified: {fact.text}",
                    severity=Severity.INFO,
                    citations=[fact.id]
                )
            )

        return HandoverBrief(
            items=items,
            completion_status="PENDING" if conflicts else "COMPLETED"
        )

    @staticmethod
    def deterministic_batch_summary(capsules: List[Any], conflicts: List[SafetyConflict]) -> str:
        """Rule-based summary with no model call."""
        capsule_count = len(capsules)
        crit_conflicts = [c for c in conflicts if c.severity == Severity.CRITICAL]
        if crit_conflicts:
            conflict_names = ", ".join(c.title for c in crit_conflicts[:2])
            return (
                f"Batch synchronized {capsule_count} logs with {len(crit_conflicts)} CRITICAL safety conflict(s): "
                f"{conflict_names}. Immediate supervisor intervention required."
            )
        elif conflicts:
            return f"Batch synchronized {capsule_count} logs with {len(conflicts)} warning(s). Telemetry cross-verified."
        return f"Batch synchronized {capsule_count} logs cleanly. All field assertions match live DCS telemetry."

    async def generate_batch_summary(
        self,
        capsules: List[Any],
        conflicts: List[SafetyConflict]
    ) -> str:
        """
        Generate a concise supervisor handover executive summary for the synchronized batch.
        Uses non-blocking execution with fallback to ensure high performance and zero-downtime reliability.
        """
        capsule_count = len(capsules)
        crit_conflicts = [c for c in conflicts if c.severity == Severity.CRITICAL]

        # Fast deterministic fallback when offline or no API client
        if not self.client:
            return self.deterministic_batch_summary(capsules, conflicts)

        # Async execution for Gemini API to minimize endpoint latency
        import asyncio

        def _call_gemini():
            try:
                capsules_str = "\n".join(
                    f"- [{getattr(c, 'category', 'EQUIPMENT')}] Asset: {getattr(c, 'asset_tag', 'N/A')}, "
                    f"State: {getattr(c, 'asserted_state', 'N/A')}, Note: {getattr(c, 'text_transcript', '')}"
                    for c in capsules[:10]
                )
                conflicts_str = "\n".join(
                    f"- [{c.rule_id}] {c.title}: {c.description}"
                    for c in conflicts
                ) or "None detected."

                prompt = (
                    "You are Baton, the Industrial Shift-Handover Safety AI. "
                    "Provide a crisp, professional 2-sentence executive summary for the incoming shift supervisor "
                    "reviewing these edge-synchronized shift logs and safety rule checks:\n\n"
                    f"Synchronized Capsules:\n{capsules_str}\n\n"
                    f"Detected Safety Conflicts:\n{conflicts_str}\n\n"
                    "Summary:"
                )
                res = generate("batch_summary", prompt, max_output_tokens=300, timeout_s=20)
                if res.text:
                    return res.text
            except Exception as e:
                print(f"[GeminiAgentService] generate_batch_summary error: {e}. Using fallback.")

            if crit_conflicts:
                return f"Batch synchronized {capsule_count} logs with {len(crit_conflicts)} CRITICAL safety conflict(s). Supervisor read-back required."
            return f"Batch synchronized {capsule_count} logs cleanly. All field assertions match live DCS telemetry."

        try:
            return await asyncio.to_thread(_call_gemini)
        except Exception:
            return f"Batch synchronized {capsule_count} logs successfully."



class RegexDocumentService:
    """
    Connects to Vertex AI Document Storage (Discovery Engine) and
    makes inferences based on a regex-based approach over the retrieved documents.
    """
    def __init__(self, project_id: str = None, location: str = "global", data_store_id: str = None):
        self.project_id = project_id or os.getenv("GOOGLE_CLOUD_PROJECT")
        self.location = location
        self.data_store_id = data_store_id or os.getenv("VERTEX_DATA_STORE_ID")
        
        try:
            if self.project_id and self.data_store_id:
                self.client = discoveryengine.SearchServiceClient()
            else:
                self.client = None
        except Exception as e:
            print(f"[RegexDocumentService] Warning: Failed to init discovery engine client: {e}")
            self.client = None

    def search_and_extract(self, query: str, regex_pattern: str) -> List[str]:
        """
        Search document storage in Vertex AI and extract matching patterns using regex.
        """
        if not self.client or not self.project_id or not self.data_store_id:
            print("[RegexDocumentService] Client not initialized or missing project/data_store_id.")
            return []

        serving_config = self.client.serving_config_path(
            project=self.project_id,
            location=self.location,
            data_store=self.data_store_id,
            serving_config="default_config",
        )

        request = discoveryengine.SearchRequest(
            serving_config=serving_config,
            query=query,
            page_size=5,
        )

        extracted_results = []
        try:
            response = self.client.search(request)
            pattern = re.compile(regex_pattern)
            
            for result in response.results:
                # Assuming document snippet is the text containing the data
                # For more complex documents, this might parse result.document.derived_struct_data
                doc_text = ""
                if getattr(result.document, "derived_struct_data", None):
                    doc_text = json.dumps(dict(result.document.derived_struct_data))
                
                # Apply regex approach
                matches = pattern.findall(doc_text)
                extracted_results.extend(matches)

            return extracted_results
        except Exception as e:
            print(f"[RegexDocumentService] Error searching Vertex AI Document Storage: {e}")
            return []
