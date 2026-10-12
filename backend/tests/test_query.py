"""Query mode: instant document search and a one-call grounded answer, with the same guardrails as Ask."""
import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.agents import query as Q
from app.knowledge.search import Hit

KEY = {"X-Aegis-Key": "test_super_secret_key"}


def hit(cid, source_id="SOP-HW-01", heading="3 Gas testing", text="Gas test with a calibrated four-gas monitor before work.", d=0.2, source_type="SOP"):
    return Hit(chunk_id=cid, source_type=source_type, source_id=source_id, title=f"{source_id} {heading}", text=text, asset_tags=[],
               created_at=datetime(2026, 10, 1, tzinfo=timezone.utc), distance=d, doc_type="SOP")


CONFLICT = {"rule_id": "R1", "severity": "CRITICAL", "asset_tag": "P-201B", "title": "Isolation Mismatch: P-201B", "status": "OPEN", "handover_id": "h", "reports": 3}


def model(**over):
    base = {"in_scope": True, "answer": "Gas test first, per SOP-HW-01.", "steps": ["Isolate within 15 m", "Gas test"], "cautions": ["Stop above 10% LEL"],
            "follow_ups": ["How often is the test repeated?"], "answer_language": "en", "citation_ids": ["c1"], "confidence_note": None}
    base.update(over)
    return SimpleNamespace(text=json.dumps(base), model="gemini-test")


@pytest.fixture
def run(monkeypatch):
    """answer_query with retrieval, conflicts and the model scripted."""
    def go(question="What PPE and checks before I start?", *, sop=None, hist=None, conflicts=None, gen=None, permit=None, asset=None):
        tools = {"get_open_conflicts": lambda unit: {"conflicts": list(conflicts if conflicts is not None else [CONFLICT])},
                 "get_scada": lambda tags: {"readings": {t: {"status": "OPEN"} for t in tags}}}
        calls = {"search": []}

        def fake_search(text, k=6, source_types=None, *a, **kw):
            calls["search"].append(text)
            return list(sop if sop is not None else [hit("c1"), hit("c2", heading="2 Pre-start", d=0.3)]) if source_types == ["SOP"] else list(hist or [])
        with patch.object(Q, "knowledge_search", side_effect=fake_search), patch.object(Q, "make_tools", return_value=tools), \
             patch.object(Q, "generate", side_effect=gen if isinstance(gen, Exception) else (gen or (lambda *a, **k: model()))) as g:
            out = asyncio.run(Q.answer_query(question, "HYDROCRACKER-01", asset, permit, None, None, write_trace=False))
        out["_gen"], out["_search"] = g, calls["search"]
        return out
    return go


def test_a_grounded_answer_with_steps_cautions_citations_and_the_open_conflicts(run):
    r = run()
    assert r["fallback"] is False and r["steps"] == ["Isolate within 15 m", "Gas test"] and r["cautions"] == ["Stop above 10% LEL"]
    assert [c["chunk_id"] for c in r["citations"]] == ["c1"] and r["citations"][0]["title"] == "SOP-HW-01 3 Gas testing"
    assert [v["rule_id"] for v in r["rule_verdicts"]] == ["R1"]                 # quoted from the rules, not written by the model
    assert r["run_id"].startswith("ask-") and r["follow_ups"] == ["How often is the test repeated?"]


def test_unknown_citations_and_raw_chunk_ids_never_reach_the_worker(run):
    ghost = "f" * 64
    r = run(gen=lambda *a, **k: model(citation_ids=["c1", "made-up"], answer=f"See the gas test section {ghost}.", steps=[f"Step {ghost}"]))
    assert [c["chunk_id"] for c in r["citations"]] == ["c1"]
    assert ghost not in r["answer"] and ghost not in r["steps"][0]


@pytest.mark.parametrize("field,value", [("answer", "The isolation is resolved, so it is safe to proceed."), ("steps", ["All clear, no further action required"]),
                                         ("cautions", ["The interlock is clear."])])
def test_a_false_all_clear_anywhere_withholds_the_answer(run, field, value):
    r = run(gen=lambda *a, **k: model(**{field: value}))
    assert r["fallback"] is True and "withheld by a safety check" in r["confidence_note"]
    assert r["steps"] == [] and [c["chunk_id"] for c in r["citations"]]         # only the retrieved records are shown
    assert [v["rule_id"] for v in r["rule_verdicts"]] == ["R1"]


def test_conditionals_and_negations_are_allowed(run):
    r = run(gen=lambda *a, **k: model(answer="I cannot confirm it is safe. The conflict must be resolved before work resumes."))
    assert r["fallback"] is False


def test_an_expired_permit_is_called_out_by_code_and_steers_the_search(run):
    r = run("What exactly do I need to do?", permit="PERMIT-M-102")
    assert r["permit"]["id"] == "PERMIT-M-102" and r["permit"]["expired"] is True
    assert "EXPIRED" in r["permit_alert"] and "re-issued" in r["permit_alert"]
    assert any("Pump Gasket Replacement" in t and "isolation" in t for t in r["_search"])      # the job, not just the question, is searched
    assert "EXPIRED" in r["_gen"].call_args.args[1]                                          # and the model is told


def test_a_live_permit_has_no_alert_and_an_unknown_permit_is_ignored(run):
    assert run(permit="PERMIT-HW-409")["permit_alert"] is None
    assert run(permit="NOPE-1")["permit"] is None


def test_out_of_scope_questions_get_no_citations_steps_or_verdicts(run):
    r = run("what is the weather", gen=lambda *a, **k: model(in_scope=False, answer="I can only help with plant records.", citation_ids=["c1"]))
    assert r["citations"] == [] and r["steps"] == [] and r["rule_verdicts"] == []


def test_model_failure_and_bad_json_fall_back_to_the_records(run):
    r = run(gen=RuntimeError("model down"))
    assert r["fallback"] is True and r["citations"] and "problem" in r["confidence_note"]
    r = run(gen=lambda *a, **k: SimpleNamespace(text="not json", model="m"))
    assert r["fallback"] is True


def test_bad_json_is_retried_once(run):
    answers = iter([SimpleNamespace(text="oops", model="m"), model()])
    r = run(gen=lambda *a, **k: next(answers))
    assert r["fallback"] is False and r["steps"]


def test_search_documents_groups_chunks_by_document():
    hits = [hit("a", "SOP-HW-01", "3 Gas testing", d=0.1), hit("b", "SOP-HW-01", "5 Fire watch", d=0.2), hit("c", "BUL-2026-07", "Requirement", d=0.3)]
    with patch.object(Q, "knowledge_search", return_value=hits):
        out = Q.search_documents("gas test", None)
    docs = {d["source_id"]: d for d in out["documents"]}
    assert list(docs) == ["SOP-HW-01", "BUL-2026-07"] and docs["SOP-HW-01"]["sections"] == 2
    assert docs["SOP-HW-01"]["best"]["chunk_id"] == "a" and docs["SOP-HW-01"]["best"]["heading"] == "3 Gas testing"


# ---------------------------------------------------------------- endpoints
@pytest.fixture
def client(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "firestore_db", None)
    monkeypatch.setenv("AEGIS_DEMO_KEY", "demo_key_for_the_web_app")
    return TestClient(m.app)


DEMO = {"X-Aegis-Key": "demo_key_for_the_web_app"}


def test_query_endpoints_use_the_app_scope(client):
    fake = {"answer": "a", "steps": [], "cautions": [], "follow_ups": [], "answer_language": "en", "citations": [], "rule_verdicts": [],
            "permit": None, "permit_alert": None, "confidence_note": None, "fallback": False, "run_id": "ask-1", "model": "m", "latency_ms": 5}

    async def fake_answer(*a, **k):
        return fake
    with patch.object(Q, "answer_query", fake_answer), patch.object(Q, "knowledge_search", return_value=[hit("a")]):
        assert client.get("/api/v1/permits", headers=DEMO).json()["permits"][0]["id"] == "PERMIT-HW-409"
        assert client.post("/api/v1/search", json={"query": "gas test"}, headers=DEMO).json()["documents"][0]["source_id"] == "SOP-HW-01"
        assert client.post("/api/v1/query", json={"question": "hot work?"}, headers=DEMO).json()["run_id"] == "ask-1"
        for method, path, body in (("get", "/api/v1/permits", None), ("post", "/api/v1/search", {"query": "x"}), ("post", "/api/v1/query", {"question": "x"}),
                                   ("get", "/api/v1/docs", None), ("get", "/api/v1/docs/abc", None)):
            assert client.request(method.upper(), path, json=body).status_code == 401, path          # a key is required


def test_query_input_is_validated(client):
    assert client.post("/api/v1/query", json={"question": ""}, headers=DEMO).status_code == 422
    assert client.post("/api/v1/query", json={"question": "x" * 501}, headers=DEMO).status_code == 422
    assert client.post("/api/v1/search", json={"query": ""}, headers=DEMO).status_code == 422


def test_a_document_section_can_be_read_with_the_app_key(client):
    section = {"title": "SOP-HW-01 3 Gas testing", "source_type": "SOP", "source_id": "SOP-HW-01", "text": "Gas test first.", "seeded": True}
    from app import api_v1
    with patch.object(api_v1, "read_chunk", return_value=dict(section)):
        r = client.get("/api/v1/docs/" + "a" * 64, headers=DEMO)
    assert r.status_code == 200 and r.json()["text"] == "Gas test first." and "seeded" not in r.json()
    with patch.object(api_v1, "read_chunk", return_value=None):
        assert client.get("/api/v1/docs/" + "b" * 64, headers=DEMO).status_code == 404
    assert client.get("/api/v1/docs/bad id!", headers=DEMO).status_code in (400, 404)
