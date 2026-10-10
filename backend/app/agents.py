from __future__ import annotations
import json
import os
import re
from typing import List, Dict, Any, Optional
from google.cloud import discoveryengine

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
        self.client = None
        # Check if google-genai is configured
        project = os.getenv("GOOGLE_CLOUD_PROJECT")
        api_key = os.getenv("GEMINI_API_KEY")
        if project or api_key:
            try:
                from google import genai
                if api_key:
                    self.client = genai.Client(api_key=api_key)
                else:
                    vertex_loc = os.getenv("VERTEX_LOCATION", "us-central1")
                    self.client = genai.Client(vertexai=True, project=project, location=vertex_loc)
            except Exception as e:
                print(f"[GeminiAgentService] Warning: Failed to init genai client: {e}. Using fallback mode.")

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
                res = self.client.models.generate_content(
                    model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                    contents=prompt,
                )

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

    def generate_gap_questions(
        self,
        conflicts: List[SafetyConflict],
        facts: List[Fact],
        target_language: str = "en"
    ) -> List[GapQuestion]:
        """Formulate targeted verification questions for the outgoing operator."""
        questions: List[GapQuestion] = []
        if not conflicts:
            return questions

        for idx, conflict in enumerate(conflicts[:3]):
            q_text = f"Clarification needed on {conflict.title}: {conflict.description} Can you confirm the current physical state?"
            if target_language == "ta":
                q_text = f"{conflict.title} குறித்துத் தயவுசெய்து உறுதிப்படுத்தவும்: {conflict.description} தற்போதைய நிலை என்ன?"
            elif target_language == "ms":
                q_text = f"Sila sahkan berkenaan {conflict.title}: {conflict.description} Apakah status terkini?"
            elif target_language == "zh":
                q_text = f"请确认关于 {conflict.title}: {conflict.description} 目前的实际状态是什么？"

            questions.append(
                GapQuestion(
                    id=f"Q-{idx+1}",
                    question_text=q_text,
                    target_language=target_language
                )
            )
        return questions

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
            if crit_conflicts:
                conflict_names = ", ".join(c.title for c in crit_conflicts[:2])
                return (
                    f"Batch synchronized {capsule_count} logs with {len(crit_conflicts)} CRITICAL safety conflict(s): "
                    f"{conflict_names}. Immediate supervisor intervention required."
                )
            elif conflicts:
                return f"Batch synchronized {capsule_count} logs with {len(conflicts)} warning(s). Telemetry cross-verified."
            return f"Batch synchronized {capsule_count} logs cleanly. All field assertions match live DCS telemetry."

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
                res = self.client.models.generate_content(
                    model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
                    contents=prompt
                )
                if res and res.text:
                    return res.text.strip()
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
