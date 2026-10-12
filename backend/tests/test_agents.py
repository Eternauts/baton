import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

import fake_llm
from app.agents import fallbacks, guardrails, pipeline as P, tools as T
from app.agents.context import RunContext
from app.agents.schemas import AssessmentItem, BriefLine, RuleVerdict, ShiftBrief
from app.agents.tracing import TraceCollector
from app.knowledge.search import Hit
from app.pipeline.intake import HandoverNotFound

R1 = RuleVerdict(verdict_id="CONF-R1-1", rule_id="R1", severity="CRITICAL", asset_tag="P-201B", title="Isolation Mismatch: P-201B", description="d1")
R4 = RuleVerdict(verdict_id="CONF-R4-2", rule_id="R4", severity="WARNING", asset_tag="PERMIT-M-102", title="Expired permit", description="d4")


# ===================== guardrails =====================
@pytest.mark.parametrize("text", [
    "Safety interlock clear.", "The interlock is clear and work can start.", "All clear.", "Conflict has been resolved.",
    "Risk mitigated.", "It is safe to proceed with hot work.", "No further action required.", "Everything looks normal.",
    "Situation is under control.", "The R1 and R4 conflicts are resolved.", "Work may begin because the issue is resolved.", "While the supervisor checks, the issue is resolved.", "The issue is resolved.", "The hazard has been mitigated.", "Resolved.", "Pump P-201B is now cleared for work.",
    "Supervisor acknowledged and mitigated active isolation alert. Safety interlock clear.",
])
def test_clearing_language_is_caught(text):
    assert guardrails.find_clearing_language(text), text


@pytest.mark.parametrize("text", [
    "The conflict is not yet resolved.", "Do not proceed until the interlock is verified.", "Clear the area before inspection.",
    "Unresolved conflicts: R1.", "Hot work is not safe to proceed while the bypass is active.",
    "Pump P-201B isolation mismatch needs field verification.", "Conflicts must be mitigated before work resumes.",
    "This conflict must be resolved before work resumes.", "The mismatch needs to be resolved by the incoming supervisor.",
    "It should be resolved only after physical verification.", "Work stays suspended until the issue is resolved.",
    "The R1 conflict remains unresolved.", "The permit issue was not resolved on the last shift.",
    "Open conflicts cannot be treated as resolved or mitigated.",
    "I cannot confirm it is safe to start hot work near V-102, and it must not proceed until these isolation and permit conflicts are resolved.",
    "Work must wait until the R1 and R4 conflicts have been resolved by the supervisor and re-verified.",
    "Hot work stays suspended pending confirmation that the issue is resolved.",
    "Do not resume while the alert is unresolved or only acknowledged.",
])
def test_legitimate_text_is_not_flagged(text):
    assert guardrails.find_clearing_language(text) == []


def test_no_false_all_clear_only_applies_with_open_conflicts():
    assert guardrails.check_no_false_all_clear(["All clear."], unresolved_conflicts=True)
    assert guardrails.check_no_false_all_clear(["All clear."], unresolved_conflicts=False) == []


def test_status_mapping_acknowledged_is_not_resolved():
    for raw in (None, "OPEN", "CONFIRMED", "CLARIFIED", "MITIGATED", "ACKNOWLEDGED"):
        assert guardrails.is_unresolved(raw), raw
    assert guardrails.map_status("MITIGATED") == guardrails.ACKNOWLEDGED
    assert not guardrails.is_unresolved("RESOLVED")


def _item(**kw):
    base = dict(severity="CRITICAL", explanation="x", source="rule", verdict_id="CONF-R1-1", rule_id="R1", asset_tag="P-201B")
    base.update(kw)
    return AssessmentItem(**base)


def test_verdict_lock():
    assert guardrails.check_verdict_lock([_item()], [R1]) == []
    assert "missing" in guardrails.check_verdict_lock([], [R1])[0]
    assert "downgraded" in guardrails.check_verdict_lock([_item(severity="WARNING")], [R1])[0]
    # upgrading is not hiding anything
    assert guardrails.check_verdict_lock([_item(severity="CRITICAL")], [R4.model_copy(update={"verdict_id": "CONF-R1-1", "rule_id": "R1", "asset_tag": "P-201B"})]) == []


def test_citations_and_advisory_clamp():
    kept, removed = guardrails.strip_unretrieved(["a", "b", "c"], {"a", "c"})
    assert kept == ["a", "c"] and removed == ["b"]
    items = [_item(source="advisory", severity="CRITICAL", verdict_id=None, rule_id=None)]
    assert guardrails.clamp_advisory_severity(items) and items[0].severity == "WARNING"


# ===================== fallbacks =====================
def test_fallback_brief_and_update_from_verdicts_only():
    b = fallbacks.fallback_brief([R4, R1], 2)
    assert [i.rule_id for i in b.items] == ["R1", "R4"]       # most severe first
    assert guardrails.find_clearing_language(b.headline + " ".join(i.text for i in b.items)) == []
    assert "No rule violations" in fallbacks.fallback_brief([], 1).headline
    u = fallbacks.build_device_update("batch-1", "run-batch-1", "U", b, [R1, R4])
    assert u.severity == "CRITICAL" and u.update_id == "upd-batch-1" and len(u.summary) <= 400
    assert any("Physically verify the isolation of P-201B" in a for a in u.required_actions)


# ===================== tools =====================
def _hit(i, source_type="SOP", source_id="S", distance=0.2):
    return Hit(chunk_id=i, source_type=source_type, source_id=source_id, title=f"t-{i}", text="x" * 900, asset_tags=["P-201B"],
               created_at=datetime.now(timezone.utc), distance=distance)


def test_search_tools_record_what_they_retrieve_and_exclude_own_handover():
    rc = RunContext(run_id="r", trigger="t", handover_id="batch-1", unit="U")
    tools = T.make_tools(rc)
    with patch.object(T, "knowledge_search", return_value=[_hit("c1")]) as ks:
        out = tools["search_sops"]("how to isolate", "P-201B")
    assert out["hits"][0]["chunk_id"] == "c1" and len(out["hits"][0]["text"]) == T.MAX_TEXT      # size capped
    assert ks.call_args.kwargs["source_types"] == ["SOP"] and ks.call_args.kwargs["asset_tag"] == "P-201B"
    assert rc.retrieved_ids == {"c1"}
    with patch.object(T, "knowledge_search", return_value=[_hit("own", "HANDOVER", "batch-1"), _hit("h2", "HANDOVER", "seed-h3")]) as ks:
        out = tools["search_history"]("history", asset_tag="P-201B")
    assert [h["chunk_id"] for h in out["hits"]] == ["h2"]                                           # other shifts only
    assert ks.call_args.kwargs["unit"] == "U" and ks.call_args.kwargs["since"] is not None
    assert rc.retrieved_ids == {"c1", "h2"}


def test_get_scada_labels_simulated_feed():
    rc = RunContext(run_id="r", trigger="t", handover_id="h", unit="U")
    out = T.make_tools(rc)["get_scada"](["p-201b", "ZZ-999"])
    assert out["source"] == "simulated plant feed" and out["readings"]["P-201B"]["status"] == "OPEN" and out["unknown"] == ["ZZ-999"]


def test_evaluate_rules_tool_runs_the_real_rules():
    rc = RunContext(run_id="r", trigger="t", handover_id="h", unit="U", capsules=[
        {"uuid": "u1", "asset_tag": "P-201B", "asserted_state": "ISOLATED", "category": "ISOLATION", "text_transcript": "isolated"}])
    out = T.make_tools(rc)["evaluate_rules"]("h")
    assert {v["rule_id"] for v in out["verdicts"]} == {"R1", "R4"}
    assert next(v for v in out["verdicts"] if v["rule_id"] == "R4")["asset_tag"] == "PERMIT-M-102"


def test_get_open_conflicts_maps_status_and_window():
    now = datetime.now(timezone.utc)
    sessions = [
        {"id": "a", "unit_name": "HYDROCRACKER-01", "created_at": now.isoformat(), "conflicts": [
            {"rule_id": "R1", "title": "t", "status": "MITIGATED"}, {"rule_id": "R4", "title": "t4", "status": "RESOLVED"}]},
        {"id": "old", "unit_name": "HYDROCRACKER-01", "created_at": (now - timedelta(hours=40)).isoformat(), "conflicts": [{"rule_id": "R1", "title": "t", "status": "OPEN"}]},
        {"id": "other", "unit_name": "UNIT-9", "created_at": now.isoformat(), "conflicts": [{"rule_id": "R1", "title": "t", "status": "OPEN"}]},
    ]
    db = MagicMock()
    db.collection.return_value.order_by.return_value.limit.return_value.stream.return_value = [SimpleNamespace(to_dict=lambda s=s: s) for s in sessions]
    rc = RunContext(run_id="r", trigger="t", handover_id="h", unit="U")
    with patch.object(T, "get_db", return_value=db):
        out = T.make_tools(rc)["get_open_conflicts"]("Hydrocracker Unit 01")
    assert out["conflicts"] == [{"rule_id": "R1", "severity": "WARNING", "asset_tag": None, "title": "t", "status": "ACKNOWLEDGED", "handover_id": "a", "reports": 1}]


def test_get_open_conflicts_groups_repeats_and_the_newest_report_decides():
    now = datetime.now(timezone.utc)
    conflict = lambda status, title="Isolation Mismatch: P-201B": {"rule_id": "R1", "title": title, "status": status, "severity": "CRITICAL", "evidence_ids": ["DCS-P-201B"]}
    sessions = [   # newest first, as the query returns them
        {"id": "s3", "unit_name": "HYDROCRACKER-01", "created_at": now.isoformat(), "conflicts": [conflict("OPEN")]},
        {"id": "s2", "unit_name": "HYDROCRACKER-01", "created_at": (now - timedelta(minutes=5)).isoformat(), "conflicts": [conflict("OPEN"), conflict("OPEN", "Isolation Mismatch: V-104")]},
        {"id": "s1", "unit_name": "HYDROCRACKER-01", "created_at": (now - timedelta(minutes=9)).isoformat(), "conflicts": [conflict("ACKNOWLEDGED")]},
    ]
    db = MagicMock()
    db.collection.return_value.order_by.return_value.limit.return_value.stream.return_value = [SimpleNamespace(to_dict=lambda s=s: s) for s in sessions]
    rc = RunContext(run_id="r", trigger="t", handover_id="h", unit="U")
    with patch.object(T, "get_db", return_value=db):
        rows = T.make_tools(rc)["get_open_conflicts"]("Hydrocracker Unit 01")["conflicts"]
    p201 = next(r for r in rows if r["title"].endswith("P-201B"))
    assert len(rows) == 2                                        # P-201B once, V-104 once: not 4 rows
    assert p201["reports"] == 3 and p201["handover_id"] == "s3" and p201["status"] == "OPEN"   # newest report wins over an older acknowledgement


# ===================== trace collector =====================
def test_trace_write_failure_never_raises():
    rc = RunContext(run_id="r", trigger="t", handover_id="h", unit="U")
    tc = TraceCollector(rc, write=True)
    tc.add_step("agent_start", "A", "A started")
    with patch("app.agents.tracing.get_db", side_effect=RuntimeError("firestore down")):
        asyncio.run(tc.flush())          # must swallow the error
    assert tc.steps[0]["seq"] == 1


# ===================== the whole pipeline, offline =====================
EVENT = {"unit_name": "HYDROCRACKER-01", "shift_name": "NIGHT-SHIFT-A", "operator_id": "TECH-KIRAN-88", "capsules": [
    {"uuid": "u1", "timestamp": "2026-10-11T12:00:00Z", "category": "ISOLATION", "asset_tag": "P-201B", "asserted_state": "ISOLATED",
     "text_transcript": "Pump P-201B isolated and lock applied. Reported by Kiran"}]}


@pytest.fixture
def harness(monkeypatch):
    fake_llm.CONTROL.update(mode="good", calls={}, delay=0.0)
    saved = {"brief": None, "update": None, "tracer": None}

    def fake_search(query, k=6, source_types=None, **kw):
        if source_types == ["SOP"]:
            return [_hit("chunk-sop-1", "SOP", "SOP-PMP-05")]
        return [_hit("chunk-hist-1", "HANDOVER", "seed-h3")]

    class Spy(TraceCollector):
        def __init__(self, rc, write=True):
            super().__init__(rc, write=False)
            saved["tracer"] = self

    db = MagicMock()
    db.collection.return_value.order_by.return_value.limit.return_value.stream.return_value = []
    monkeypatch.setattr(P, "make_model", lambda name: fake_llm.FakeLlm())
    monkeypatch.setattr(P, "load_event", lambda hid: EVENT)
    monkeypatch.setattr(P, "run_intake", lambda hid: {"capsules": 1, "chunks": 1, "models_used": ["emb"], "unit": "U"})
    monkeypatch.setattr(P.outputs, "save_brief", lambda hid, doc: saved.update(brief=doc))
    monkeypatch.setattr(P.outputs, "save_device_update", lambda u: saved.update(update=u))
    monkeypatch.setattr(P, "TraceCollector", Spy)
    monkeypatch.setattr(T, "knowledge_search", fake_search)
    monkeypatch.setattr(T, "get_db", lambda: db)

    def run(mode="good"):
        fake_llm.CONTROL["mode"] = mode
        res = asyncio.run(P.run_pipeline_async("batch-x", "run-batch-x", write_trace=False))
        return res, saved
    return run


def _brief_text(doc):
    return doc["headline"] + " " + " ".join(i["text"] for i in doc["items"])


def test_pipeline_happy_path(harness):
    res, saved = harness("good")
    assert res["status"] == "completed" and res["guardrails_triggered"] == []
    brief = saved["brief"]
    assert {i["rule_id"] for i in brief["items"]} == {"R1", "R4"} and brief["guardrail_status"] == "passed"
    assert brief["items"][0]["severity"] == "CRITICAL"
    assert set(brief["citations"]) <= {"chunk-sop-1", "chunk-hist-1"} and brief["citation_details"]
    assert saved["update"]["severity"] == "CRITICAL" and saved["update"]["update_id"] == "upd-batch-x"
    assert res["tokens"] and sum(t["prompt"] for t in res["tokens"].values()) > 0


def test_trace_has_every_stage_tool_and_rule_verdicts_but_no_transcripts(harness):
    res, saved = harness("good")
    steps = saved["tracer"].steps
    started = [s["agent"] for s in steps if s["kind"] == "agent_start"]
    for name in ("Intake", "SOPRetriever", "HistoryRetriever", "RulesGate", "SafetyCrossCheck", "Briefing", "Distill"):
        assert name in started
    tool_results = {s["tool_name"]: s for s in steps if s["kind"] == "tool_result" and s["tool_name"]}
    assert tool_results["search_sops"]["retrieved_ids"] == ["chunk-sop-1"]
    assert tool_results["search_history"]["retrieved_ids"] == ["chunk-hist-1"]
    assert tool_results["evaluate_rules"]["rule_ids"] == ["R1", "R4"]
    assert not any("set_model_response" in (s["tool_name"] or "") for s in steps)       # ADK internals hidden
    assert not any("lock applied" in s["summary"] or "Kiran" in s["summary"] for s in steps)
    assert [s["seq"] for s in steps] == sorted(s["seq"] for s in steps)


@pytest.mark.parametrize("mode,guard", [("drop_verdict", "verdict_lock"), ("downgrade", "verdict_lock"), ("clear_language", "false_all_clear")])
def test_unsafe_assessment_is_discarded_for_the_deterministic_one(harness, mode, guard):
    res, saved = harness(mode)
    assert res["status"] == "fallback" and guard in {t["guardrail"] for t in res["guardrails_triggered"]}
    brief = saved["brief"]
    assert brief["guardrail_status"] == "fallback" and "SafetyCrossCheck" in brief["fallback_agents"]
    r1 = next(i for i in brief["items"] if i["rule_id"] == "R1")
    assert r1["severity"] == "CRITICAL"                                                    # the verdict survived unchanged
    assert guardrails.find_clearing_language(_brief_text(brief)) == []
    assert any(s["kind"] == "guardrail" for s in saved["tracer"].steps)


def test_false_all_clear_in_the_brief_is_replaced(harness):
    res, saved = harness("brief_clear")
    assert res["status"] == "fallback" and "Briefing" in saved["brief"]["fallback_agents"]
    assert "all clear" not in _brief_text(saved["brief"]).lower() and "safe to proceed" not in _brief_text(saved["brief"]).lower()
    assert {i["rule_id"] for i in saved["brief"]["items"]} == {"R1", "R4"}


def test_unretrieved_citations_are_stripped(harness):
    res, saved = harness("bad_citation")
    assert "chunk-never-retrieved" not in saved["brief"]["citations"]
    assert res["status"] == "completed" and saved["brief"]["guardrail_status"] == "modified"
    assert "citation_stripped" in {t["guardrail"] for t in res["guardrails_triggered"]}


def test_advisory_cannot_be_critical(harness):
    res, saved = harness("advisory_critical")
    assert "advisory_clamped" in {t["guardrail"] for t in res["guardrails_triggered"]}


def test_malformed_json_is_retried_once(harness):
    res, saved = harness("bad_json_once")
    assert fake_llm.CONTROL["calls"]["cross"] == 2 and res["status"] == "completed"
    assert "invalid_output" in {t["guardrail"] for t in res["guardrails_triggered"]}


def test_model_crash_still_delivers_the_rule_verdicts(harness):
    res, saved = harness("crash")
    assert res["status"] == "fallback" and "stage_error" in {t["guardrail"] for t in res["guardrails_triggered"]}
    assert {i["rule_id"] for i in saved["brief"]["items"]} == {"R1", "R4"} and saved["update"]["severity"] == "CRITICAL"


def test_slow_model_hits_the_stage_budget(harness, monkeypatch):
    monkeypatch.setattr(P, "MAIN_STAGE_TIMEOUT_S", 0.3)
    fake_llm.CONTROL["delay"] = 1.0
    res, saved = harness("good")
    assert "stage_timeout" in {t["guardrail"] for t in res["guardrails_triggered"]}
    assert {i["rule_id"] for i in saved["brief"]["items"]} == {"R1", "R4"}


def test_missing_handover_raises_for_retry(monkeypatch):
    monkeypatch.setattr(P, "load_event", lambda hid: None)
    with pytest.raises(HandoverNotFound):
        asyncio.run(P.run_pipeline_async("nope", "run-nope", write_trace=False))


def test_violation_detail_keeps_the_surrounding_sentence_for_review():
    bad = guardrails.check_no_false_all_clear(["Pump P-201B was checked and the issue is resolved by the field team."], True)
    assert bad and "issue is resolved" in bad[0] and "field team" in bad[0]


def test_model_clients_are_closed_inside_the_running_loop():
    closed = []

    class FakeAio:
        async def aclose(self):
            closed.append(asyncio.get_running_loop())

    client = SimpleNamespace(aio=FakeAio())
    agents = [SimpleNamespace(model=SimpleNamespace(api_client=client)), SimpleNamespace(model=SimpleNamespace(api_client=client)),
              SimpleNamespace(model=SimpleNamespace())]          # a model without a client (the test fake) is skipped
    loop = asyncio.new_event_loop()
    loop.run_until_complete(P.close_models(agents))
    assert len(closed) == 1 and closed[0] is loop              # closed once, while its own loop was running
    loop.close()


def test_a_failing_close_never_breaks_a_run():
    class Boom:
        async def aclose(self):
            raise RuntimeError("already closed")
    asyncio.run(P.close_models([SimpleNamespace(model=SimpleNamespace(api_client=SimpleNamespace(aio=Boom())))]))
