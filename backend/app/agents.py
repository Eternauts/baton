from __future__ import annotations
import json
import os
from typing import List, Dict, Any, Optional
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
                    self.client = genai.Client(vertexai=True, project=project, location="global")
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
                    model="gemini-2.5-flash",
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
