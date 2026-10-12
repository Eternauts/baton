import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

import fake_llm
from app.agents import ask as A, guardrails, tools as T
from app.knowledge.search import Hit

NOW = datetime.now(timezone.utc)
SESSIONS = [
    {"id": "h-new", "unit_name": "HYDROCRACKER-01", "created_at": NOW.isoformat(), "conflicts": [
        {"rule_id": "R4", "severity": "WARNING", "title": "Expired Maintenance Permit Active: PERMIT-M-102", "status": "OPEN", "evidence_ids": ["PERMIT-M-102"]},
        {"rule_id": "R1", "severity": "CRITICAL", "title": "Isolation Mismatch: P-201B", "status": "OPEN", "evidence_ids": ["u1", "DCS-P-201B"]}]},
    {"id": "h-old", "unit_name": "HYDROCRACKER-01", "created_at": NOW.isoformat(), "conflicts": [
        {"rule_id": "R4", "severity": "WARNING", "title": "Expired Maintenance Permit Active: PERMIT-M-102", "status": "OPEN", "evidence_ids": ["PERMIT-M-102"]}]},
]


def _hit(i, st, sid):
    return Hit(chunk_id=i, source_type=st, source_id=sid, title=f"title-{i}", text="requirement text " * 10, asset_tags=[], created_at=NOW, distance=0.2)


@pytest.fixture
def harness(monkeypatch):
    fake_llm.CONTROL.update(mode="ask_good", calls={}, delay=0.0)
    db = MagicMock()
    db.collection.return_value.order_by.return_value.limit.return_value.stream.return_value = [SimpleNamespace(to_dict=lambda s=s: s) for s in SESSIONS]
    monkeypatch.setattr(A, "make_model", lambda name: fake_llm.FakeLlm())
    monkeypatch.setattr(T, "get_db", lambda: db)
    monkeypatch.setattr(T, "knowledge_search",
                        lambda q, k=6, source_types=None, **kw: [_hit("chunk-sop-1", "SOP", "SOP-HW-01")] if source_types == ["SOP"] else [_hit("chunk-hist-1", "HANDOVER", "seed-h3")])
    monkeypatch.setattr(A, "knowledge_search", lambda q, k=3, *a, **kw: [_hit("chunk-sop-1", "SOP", "SOP-HW-01")])

    def run(mode="ask_good", **kw):
        fake_llm.CONTROL["mode"] = mode
        args = dict(question="Is it safe to start hot work near V-102?", unit="Hydrocracker Unit 01", write_trace=False)
        args.update(kw)
        return asyncio.run(A.answer_question(**args))
    return run


def test_in_scope_answer_has_real_citations_and_unchanged_verdicts(harness):
    r = harness()
    assert {c["chunk_id"] for c in r["citations"]} == {"chunk-sop-1", "chunk-hist-1"}
    assert set(r["citations"][0]) == {"chunk_id", "source_type", "source_id", "title", "created_at"}
    assert [v["rule_id"] for v in r["rule_verdicts"]] == ["R1", "R4"]            # deduped, most severe first
    assert r["rule_verdicts"][0]["severity"] == "CRITICAL" and r["rule_verdicts"][0]["asset_tag"] == "P-201B"
    assert r["model"] and r["run_id"].startswith("ask-") and r["latency_ms"] >= 0 and r["answer_language"] == "en"
    assert guardrails.find_clearing_language(r["answer"]) == []


def test_asset_focus_puts_that_assets_conflicts_first(harness):
    r = harness(asset_tag="PERMIT-M-102")
    assert r["rule_verdicts"][0]["rule_id"] == "R4"


def test_open_conflicts_are_appended_when_the_model_omits_them(harness):
    r = harness("ask_mentions_nothing")
    assert "R1" in r["answer"] and "R4" in r["answer"] and "stay open" in r["answer"]
    r2 = harness("ask_good")                      # model already named R1 and R4: nothing appended twice
    assert r2["answer"].count("Open conflicts") == 1


def test_false_all_clear_is_withheld_and_replaced_by_retrieval(harness):
    r = harness("ask_clear")
    assert "safe to proceed" not in r["answer"].lower() or "not" in r["answer"].lower()
    assert guardrails.find_clearing_language(r["answer"]) == []
    assert "withheld by a safety check" in r["confidence_note"] and r["citations"]
    assert [v["rule_id"] for v in r["rule_verdicts"]] == ["R1", "R4"]


def test_unretrieved_citation_is_stripped(harness):
    r = harness("ask_bad_citation")
    assert "chunk-never-retrieved" not in {c["chunk_id"] for c in r["citations"]} and len(r["citations"]) == 2


def test_out_of_scope_declines_with_no_citations_and_no_verdicts(harness):
    r = harness("ask_out_of_scope", question="What is the weather?")
    assert r["citations"] == [] and r["rule_verdicts"] == [] and "plant records" in r["answer"]


def test_model_crash_still_returns_retrieved_records_and_conflicts(harness):
    r = harness("ask_crash")
    assert "problem" in r["confidence_note"] and r["citations"][0]["chunk_id"] == "chunk-sop-1"      # direct search filled in
    assert [v["rule_id"] for v in r["rule_verdicts"]] == ["R1", "R4"] and "Open conflicts" in r["answer"]


def test_timeout_returns_partial_answer_quickly(harness, monkeypatch):
    monkeypatch.setattr(A, "ASK_TIMEOUT_S", 1.0)
    fake_llm.CONTROL["delay"] = 3.0
    t = datetime.now().timestamp()
    r = harness("ask_good")
    assert datetime.now().timestamp() - t < 4 and "timed out" in r["confidence_note"] and r["citations"]


def test_malformed_output_is_retried_once(harness):
    r = harness("ask_bad_json_once")
    assert fake_llm.CONTROL["calls"]["ask"] == 2 and r["citations"] and r["confidence_note"] is None


def test_conflict_helpers():
    rows = [{"rule_id": "R4", "title": "t4", "severity": "WARNING", "status": "OPEN"}, {"rule_id": "R4", "title": "t4", "severity": "WARNING", "status": "OPEN"},
            {"rule_id": "R1", "title": "t1", "severity": "CRITICAL", "status": "ACKNOWLEDGED"}]
    out = A.dedupe_conflicts(rows)
    assert [c["rule_id"] for c in out] == ["R1", "R4"]
    assert "ACKNOWLEDGED" in A.conflicts_line(out) and "stay open" in A.conflicts_line(out)


# ===================== endpoints =====================
@pytest.fixture
def api(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "firestore_db", None)
    m.rate_limit_db.clear()
    return TestClient(m.app), m


KEY = {"X-Aegis-Key": "test_super_secret_key"}
BODY = {"question": "What happened with P-201B?", "unit": "HYDROCRACKER-01"}


def test_ask_requires_key_and_validates(api):
    client, m = api
    assert client.post("/api/v1/ask", json=BODY).status_code == 401
    assert client.post("/api/v1/ask", json=BODY, headers={"X-Aegis-Key": "wrong"}).status_code == 401
    assert client.post("/api/v1/ask", json={"unit": "U"}, headers=KEY).status_code == 422
    assert client.post("/api/v1/ask", json={**BODY, "question": "x" * 501}, headers=KEY).status_code == 422
    assert client.post("/api/v1/ask", json={**BODY, "question": ""}, headers=KEY).status_code == 422


def test_ask_success_passes_fields_through(api):
    client, m = api
    result = {"answer": "a", "answer_language": "en", "citations": [], "rule_verdicts": [], "confidence_note": None,
              "run_id": "ask-1", "model": "m", "latency_ms": 5}
    with patch("app.agents.ask.answer_question", return_value=result) as aq:
        r = client.post("/api/v1/ask", json={**BODY, "asset_tag": "P-201B", "language": "ta", "device_id": "d1"}, headers=KEY)
    assert r.status_code == 200 and r.json() == result
    assert aq.call_args.args == ("What happened with P-201B?", "HYDROCRACKER-01", "P-201B", "ta", "d1")


def test_ask_is_rate_limited(api):
    client, m = api
    for _ in range(30):
        m.check_rate_limit("testclient")
    assert client.post("/api/v1/ask", json=BODY, headers=KEY).status_code == 429


def _update(i, target="all", sev="CRITICAL"):
    return {"update_id": f"upd-{i}", "unit": "HYDROCRACKER-01", "target": target, "severity": sev, "alerts": ["a"], "required_actions": ["r"],
            "summary": "s", "handover_id": f"h{i}", "run_id": f"run-h{i}", "created_at": NOW}


def _fake_db(device_unit, updates):
    chain = MagicMock()
    chain.where.return_value = chain
    chain.order_by.return_value = chain
    chain.limit.return_value = chain
    chain.stream.return_value = [SimpleNamespace(id=u["update_id"], to_dict=lambda u=u: u) for u in updates]
    db = MagicMock()
    dev = MagicMock(exists=device_unit is not None)
    dev.to_dict.return_value = {"unit": device_unit}
    db.collection.side_effect = lambda name: MagicMock(document=lambda i: MagicMock(get=lambda: dev)) if name == "devices" else chain
    return db, chain


def test_device_updates_auth_and_validation(api):
    client, m = api
    assert client.get("/api/v1/devices/d1/updates").status_code == 401
    assert client.get("/api/v1/devices/d1/updates?since=not-a-date", headers=KEY).status_code == 400
    assert client.get("/api/v1/devices/" + "x" * 81 + "/updates", headers=KEY).status_code == 400


def test_device_updates_for_the_devices_unit_only_targeted_and_capped(api):
    client, m = api
    ups = [_update(i) for i in range(30)] + [_update(99, target="other-device")]
    ups.insert(3, _update(50, target="d1"))
    db, chain = _fake_db("HYDROCRACKER-01", ups)
    with patch("app.knowledge.store.get_db", return_value=db):
        r = client.get("/api/v1/devices/d1/updates?since=2026-10-11T00:00:00Z", headers=KEY)
    body = r.json()
    assert r.status_code == 200 and body["unit"] == "HYDROCRACKER-01" and len(body["updates"]) == 20
    ids = [u["update_id"] for u in body["updates"]]
    assert "upd-99" not in ids and "upd-50" in ids                       # others' targeted updates excluded, own included
    assert set(body["updates"][0]) == {"update_id", "severity", "alerts", "required_actions", "summary", "handover_id", "run_id", "created_at"}
    filters = [c.kwargs["filter"] for c in chain.where.call_args_list]
    assert [(f.field_path, f.op_string) for f in filters] == [("unit", "=="), ("created_at", ">")]
    assert body["server_time"]


def test_device_updates_unknown_device_uses_unit_param_or_explains(api):
    client, m = api
    db, chain = _fake_db(None, [_update(1)])
    with patch("app.knowledge.store.get_db", return_value=db):
        r = client.get("/api/v1/devices/new-device/updates", headers=KEY)
        assert r.json()["updates"] == [] and "unknown device" in r.json()["note"]
        r2 = client.get("/api/v1/devices/new-device/updates?unit=Hydrocracker%20Unit%2001", headers=KEY)
    assert r2.json()["unit"] == "HYDROCRACKER-01" and len(r2.json()["updates"]) == 1


def test_chunk_ids_are_removed_from_prose():
    cid = "f0113965d9de8d720b321d50f6ec22b767b15c514cd21e66234d5a6c1431d5d1"
    assert A.strip_chunk_ids(f"Duty was moved to P-201A [{cid}]. Then isolation ({cid}) followed.") == "Duty was moved to P-201A. Then isolation followed."
    assert A.strip_chunk_ids("See SOP-HW-01 section 2 and P-201B.") == "See SOP-HW-01 section 2 and P-201B."


# ===================== Phase 7: trace read endpoints =====================
def _doc(id_, data, exists=True):
    return SimpleNamespace(id=id_, exists=exists, to_dict=lambda d=data: d)


def _trace_db():
    ts = NOW
    run = {"run_id": "run-h1", "trigger": "handover.synced", "status": "completed", "handover_id": "h1", "unit": "U", "started_at": ts, "finished_at": ts,
           "total_ms": 8000, "models_used": ["m"], "guardrails_triggered": [], "secret_internal": "must not leak"}
    steps = [{"seq": 2, "agent": "B", "kind": "tool_result", "tool_name": "search_sops", "summary": "s", "retrieved_ids": ["c1", "c2"], "rule_ids": [], "latency_ms": 5, "timestamp": ts},
             {"seq": 1, "agent": "A", "kind": "agent_start", "tool_name": None, "summary": "a", "retrieved_ids": [], "rule_ids": [], "latency_ms": None, "timestamp": ts}]
    db = MagicMock()
    runs_col = MagicMock()
    runs_col.document.return_value.get.return_value = _doc("run-h1", run)
    runs_col.document.return_value.collection.return_value.order_by.return_value.limit.return_value.stream.return_value = [_doc("0001", steps[1]), _doc("0002", steps[0])]
    runs_col.order_by.return_value.limit.return_value.stream.return_value = [_doc("run-h1", run)]
    chunks_col = MagicMock()
    chunks_col.document.side_effect = lambda i: i
    briefs_col = MagicMock()
    briefs_col.document.return_value.get.return_value = _doc("h1", {"headline": "H", "items": [], "guardrail_status": "passed", "embedding_secret": 1})
    db.collection.side_effect = lambda n: {"agent_runs": runs_col, "knowledge_chunks": chunks_col, "handover_briefs": briefs_col}[n]
    db.get_all.return_value = [_doc("c1", {"title": "SOP-HW-01 2", "source_type": "SOP", "source_id": "SOP-HW-01", "text": "x"}), _doc("c2", {}, exists=False)]
    return db


def test_trace_endpoints_require_the_key(api):
    client, m = api
    for path in ("/api/v1/agents/runs", "/api/v1/agents/runs/run-h1", "/api/v1/agents/chunks/abc"):
        assert client.get(path).status_code == 401
        assert client.get(path, headers={"X-Aegis-Key": "wrong"}).status_code == 401


def test_runs_list_and_detail(api):
    client, m = api
    with patch("app.knowledge.store.get_db", return_value=_trace_db()):
        lst = client.get("/api/v1/agents/runs?limit=5", headers=KEY).json()["runs"]
        assert lst[0]["run_id"] == "run-h1" and lst[0]["total_ms"] == 8000 and "secret_internal" not in lst[0]
        assert isinstance(lst[0]["started_at"], str)                                   # datetimes are serialised
        d = client.get("/api/v1/agents/runs/run-h1", headers=KEY).json()
    assert [s["seq"] for s in d["steps"]] == [1, 2]                                  # kept in the order Firestore returns (ordered by seq)
    assert d["steps"][1]["retrieved_ids"] == ["c1", "c2"] and isinstance(d["steps"][0]["timestamp"], str)
    assert d["chunks"] == {"c1": {"title": "SOP-HW-01 2", "source_type": "SOP", "source_id": "SOP-HW-01", "created_at": None}}   # unknown chunk ids are simply absent
    assert d["brief"]["headline"] == "H" and "embedding_secret" not in d["brief"] and "secret_internal" not in d["run"]


def test_run_and_chunk_ids_are_validated_and_missing_is_404(api):
    client, m = api
    assert client.get("/api/v1/agents/runs/not-a-run", headers=KEY).status_code == 400
    assert client.get("/api/v1/agents/runs/run-..%2Fx", headers=KEY).status_code in (400, 404)
    assert client.get("/api/v1/agents/chunks/bad%20id", headers=KEY).status_code == 400
    db = MagicMock()
    db.collection.return_value.document.return_value.get.return_value = _doc("x", {}, exists=False)
    with patch("app.knowledge.store.get_db", return_value=db):
        assert client.get("/api/v1/agents/runs/run-nothing", headers=KEY).status_code == 404
        assert client.get("/api/v1/agents/chunks/nothing", headers=KEY).status_code == 404


def test_chunk_endpoint_never_returns_the_embedding(api):
    client, m = api
    db = MagicMock()
    db.collection.return_value.document.return_value.get.return_value = _doc("c1", {"title": "t", "text": "body", "source_type": "SOP", "source_id": "S", "embedding": [0.1] * 3, "created_at": NOW})
    with patch("app.knowledge.store.get_db", return_value=db):
        out = client.get("/api/v1/agents/chunks/c1", headers=KEY).json()
    assert out["text"] == "body" and "embedding" not in out
