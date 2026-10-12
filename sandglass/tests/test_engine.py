from __future__ import annotations

import asyncio

from app.engine import grounding_score
from app.schemas import AskRequest, DraftAnswer, DraftClaim

Q = "Can hot work resume on the stripper platform while GD-311 is bypassed?"
BULLETIN_QUOTE = "hot work may not resume while GD-311 or GD-312 is bypassed"


def _draft(status="ANSWERED", quote=BULLETIN_QUOTE, source=1, confidence=0.9) -> DraftAnswer:
    return DraftAnswer(
        status=status,
        answer="No. Return GD-311 to service and test it first.",
        claims=[DraftClaim(text="Hot work stays stopped while GD-311 is bypassed.", quote=quote,
                           source=source, confidence=confidence)],
        confidence=confidence,
        action="Keep hot work stopped; restore and test GD-311.",
    )


def test_grounding_score_levels():
    passage = "Hot work must stop immediately and may only resume under the compensating measures."
    assert grounding_score("hot work must stop  immediately", passage) == 1.0
    assert grounding_score("hot work must stop now and may only resume", passage) == 0.75
    assert grounding_score("hot work is always allowed here", passage) == 0.0
    assert grounding_score("stop", passage) == 0.0  # too short to verify anything


def test_grounded_answer_is_accepted(make_engine):
    engine, llm = make_engine(_draft())
    result = asyncio.run(engine.ask(AskRequest(q=Q)))
    assert result.decision == "A"
    assert result.generator == "gemini" and result.model == "fake-gemini"
    assert result.breakdown.grounding == 1.0
    assert result.confidence >= 0.8
    assert result.sources[0].id.startswith("BUL-2026-07")
    assert "[S1] BUL-2026-07" in llm.prompts[0]


def test_wrong_source_number_is_reattributed(make_engine):
    engine, _ = make_engine(_draft(source=3))
    result = asyncio.run(engine.ask(AskRequest(q=Q)))
    assert result.sources[0].id.startswith("BUL-2026-07")
    assert result.claims[0].grounding == "exact"


def test_invented_quote_is_dropped_and_confidence_capped(make_engine):
    engine, _ = make_engine(_draft(quote="hot work is permitted with a portable monitor in all cases"))
    result = asyncio.run(engine.ask(AskRequest(q=Q)))
    assert result.decision == "N"
    assert result.claims == []
    assert result.confidence == 0.0


def test_conflict_is_reported(make_engine):
    engine, _ = make_engine(_draft(status="CONFLICT"))
    assert asyncio.run(engine.ask(AskRequest(q=Q))).decision == "C"


def test_low_confidence_becomes_partial(make_engine):
    engine, _ = make_engine(_draft(confidence=0.2))
    assert asyncio.run(engine.ask(AskRequest(q=Q))).decision == "P"


def test_off_topic_question_never_reaches_gemini(make_engine):
    engine, llm = make_engine(_draft())
    result = asyncio.run(engine.ask(AskRequest(q="What is the capital of Peru?")))
    assert result.decision == "N" and result.generator == "none"
    assert llm.prompts == []


def test_outage_falls_back_to_verbatim_excerpts(make_engine):
    engine, _ = make_engine(None)
    result = asyncio.run(engine.ask(AskRequest(q=Q)))
    assert result.decision == "P" and result.generator == "extractive"
    assert result.confidence < 0.65
    assert "GD-311" in result.answer or "bypassed" in result.answer


def test_device_context_reaches_prompt_but_not_sources(make_engine):
    engine, llm = make_engine(_draft())
    req = AskRequest(q="Can welding restart on the stripper platform?", ctx={"state": {"GD-311": "BYPASSED"}})
    asyncio.run(engine.ask(req))
    assert '"GD-311": "BYPASSED"' in llm.prompts[0]
