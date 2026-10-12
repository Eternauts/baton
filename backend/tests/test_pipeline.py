import base64
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.pipeline import auth, intake, publisher, runs
from app.pipeline.auth import PushAuthError

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)


# ---------- idempotent run decision ----------
@pytest.mark.parametrize("existing,expected", [
    (None, runs.CLAIMED),
    ({"status": "completed"}, runs.ALREADY_DONE),
    ({"status": "fallback"}, runs.ALREADY_DONE),
    ({"status": "running", "started_at": NOW - timedelta(seconds=30)}, runs.IN_PROGRESS),
    ({"status": "running", "started_at": NOW - timedelta(minutes=10)}, runs.CLAIMED),  # stale: take over
    ({"status": "running", "started_at": None}, runs.CLAIMED),
    ({"status": "failed"}, runs.CLAIMED),
])
def test_decide(existing, expected):
    assert runs.decide(existing, NOW) == expected


# ---------- publisher ----------
def test_message_has_ids_only():
    m = publisher.build_message("batch-1", ["c1", "c2"], "HYDROCRACKER-01", "dev-1")
    assert set(m) == {"type", "handover_id", "event_ids", "unit", "device_id", "published_at"}
    assert m["type"] == "handover.synced" and m["event_ids"] == ["c1", "c2"]


def test_publish_disabled_without_topic(monkeypatch):
    monkeypatch.delenv("PUBSUB_TOPIC", raising=False)
    assert publisher.publish_handover_synced("b1", [], None, None) is False


def test_publish_builds_topic_path_and_returns_true(monkeypatch):
    monkeypatch.setenv("PUBSUB_TOPIC", "baton-handover-events")
    client = MagicMock()
    client.publish.return_value.result.return_value = "mid-1"
    with patch.object(publisher, "_client", return_value=client):
        assert publisher.publish_handover_synced("b1", ["c"], "U", "d") is True
    assert client.publish.call_args.args[0] == "projects/test-project/topics/baton-handover-events"
    assert json.loads(client.publish.call_args.kwargs["data"])["handover_id"] == "b1"


def test_publish_failure_is_swallowed(monkeypatch):
    monkeypatch.setenv("PUBSUB_TOPIC", "t")
    client = MagicMock()
    client.publish.side_effect = RuntimeError("pubsub down")
    with patch.object(publisher, "_client", return_value=client):
        assert publisher.publish_handover_synced("b1", [], None, None) is False


def test_run_id_is_deterministic():
    assert publisher.run_id_for("batch-ab12") == "run-batch-ab12" == publisher.run_id_for("batch-ab12")


# ---------- batch_sync integration with the pipeline ----------
@pytest.fixture
def api(monkeypatch):
    import app.main as m
    monkeypatch.setattr(m, "firestore_db", None)  # never write to the real database from tests
    m.dashboard_telemetry_stream.clear()           # a previous test's sync would make this one a replay
    monkeypatch.setattr(m.agent_service, "generate_batch_summary", AsyncMock(return_value="LLM summary"))
    return TestClient(m.app), m


PAYLOAD = {"capsules": [{"uuid": "u1", "timestamp": "2026-10-11T10:00:00Z", "category": "ISOLATION",
                         "asset_tag": "P-201B", "asserted_state": "ISOLATED", "text_transcript": "isolated"}],
           "device_id": "d1", "unit_name": "HYDROCRACKER-01"}


def _payload(uuid):
    return {**PAYLOAD, "capsules": [{**PAYLOAD["capsules"][0], "uuid": uuid}]}


def test_sync_returns_run_id_when_published(api):
    client, m = api
    with patch.object(m, "publish_handover_synced", return_value=True) as pub:
        r = client.post("/api/v1/handover/batch_sync", json=PAYLOAD)
    assert r.status_code == 200
    body = r.json()
    assert body["sync_status"] == "CONFLICT_DETECTED" and body["pipeline_run_id"].startswith("run-batch-")
    assert pub.call_args.args[1] == ["u1"] and pub.call_args.args[2] == "HYDROCRACKER-01"
    assert set(body) >= {"sync_status", "synced_count", "has_critical_conflict", "conflicts", "summary", "processed_at"}


def test_sync_survives_publish_failure(api):
    client, m = api
    with patch.object(m, "publish_handover_synced", side_effect=RuntimeError("boom")):
        r = client.post("/api/v1/handover/batch_sync", json=PAYLOAD)
    assert r.status_code == 200 and r.json()["pipeline_run_id"] is None
    with patch.object(m, "publish_handover_synced", return_value=False):
        assert client.post("/api/v1/handover/batch_sync", json=_payload("u2")).json()["pipeline_run_id"] is None


def test_legacy_flag_controls_inline_summary(api, monkeypatch):
    client, m = api
    with patch.object(m, "publish_handover_synced", return_value=False):
        monkeypatch.setenv("LEGACY_BRIEF_INLINE", "true")
        assert client.post("/api/v1/handover/batch_sync", json=_payload("u3")).json()["summary"] == "LLM summary"
        monkeypatch.setenv("LEGACY_BRIEF_INLINE", "false")
        r = client.post("/api/v1/handover/batch_sync", json=_payload("u4"))
    assert "CRITICAL safety conflict" in r.json()["summary"]
    m.agent_service.generate_batch_summary.assert_awaited_once()  # not called when the flag is off


# ---------- idempotent sync: the same capsules are the same handover ----------
def test_resending_the_same_capsule_is_a_replay(api):
    client, m = api
    with patch.object(m, "publish_handover_synced", return_value=True) as pub:
        first = client.post("/api/v1/handover/batch_sync", json=_payload("same")).json()
        again = client.post("/api/v1/handover/batch_sync", json=_payload("same")).json()
    assert pub.call_count == 1                                  # one pipeline run, not two
    assert len(m.dashboard_telemetry_stream) == 1               # one event, not two
    assert again["sync_status"] == "CONFLICT_DETECTED" == first["sync_status"]
    assert [c["rule_id"] for c in again["conflicts"]] == [c["rule_id"] for c in first["conflicts"]]
    assert again["pipeline_run_id"] == first["pipeline_run_id"] and again["processed_at"] == first["processed_at"]


def test_replay_after_acknowledge_still_reports_the_conflict(api):
    client, m = api
    with patch.object(m, "publish_handover_synced", return_value=True):
        client.post("/api/v1/handover/batch_sync", json=_payload("ack"))
        for c in m.dashboard_telemetry_stream[0]["conflicts"]:
            c["status"] = "ACKNOWLEDGED"                        # what clear_alert does
        again = client.post("/api/v1/handover/batch_sync", json=_payload("ack")).json()
    assert again["sync_status"] == "CONFLICT_DETECTED"          # acknowledged is not resolved, and the app must not see an unknown status
    assert {c["status"] for c in again["conflicts"]} == {"ACKNOWLEDGED"}


def test_a_new_capsule_or_another_device_is_a_new_handover(api):
    client, m = api
    with patch.object(m, "publish_handover_synced", return_value=True) as pub:
        client.post("/api/v1/handover/batch_sync", json=_payload("n1"))
        client.post("/api/v1/handover/batch_sync", json=_payload("n2"))
        client.post("/api/v1/handover/batch_sync", json={**_payload("n1"), "device_id": "d2"})
    assert pub.call_count == 3 and len(m.dashboard_telemetry_stream) == 3



# ---------- interview handover: questions, answers, read-back, transfer ----------
KEY = {"X-Aegis-Key": "test_super_secret_key"}


def _synced(client, m, uuid="iv1"):
    with patch.object(m, "publish_handover_synced", return_value=True):
        r = client.post("/api/v1/handover/batch_sync", json=_payload(uuid)).json()
    assert r["handover_id"].startswith("batch-")
    return r["handover_id"]


def test_interview_endpoints_need_the_key(api):
    client, m = api
    hid = _synced(client, m)
    bodies = {"answer": {"answers": {}}, "acknowledge": {"item_id": "x", "readback_text": "a b c", "supervisor": "S"},
              "start": {"unit_name": "U", "shift_name": "S", "outgoing_operator": "T", "log_text": "x"}}
    for method, path, body in (("post", f"/api/handover/{hid}/interview", None), ("get", f"/api/handover/{hid}", None), ("get", f"/api/handover/{hid}/brief", None),
                               ("post", f"/api/handover/{hid}/answer", bodies["answer"]), ("post", f"/api/handover/{hid}/acknowledge", bodies["acknowledge"]),
                               ("post", f"/api/handover/{hid}/complete", None), ("post", "/api/handover/start", bodies["start"])):
        assert client.request(method.upper(), path, json=body, headers={"X-Aegis-Key": "wrong"}).status_code == 401, path
        assert client.request(method.upper(), path, json=body).status_code == 401, path          # and no key at all


def test_interview_asks_once_per_distinct_conflict_and_is_idempotent(api):
    client, m = api
    hid = _synced(client, m)
    with patch.object(m.agent_service, "client", False):         # no model: the template questions
        a = client.post(f"/api/handover/{hid}/interview", headers=KEY).json()
        b = client.post(f"/api/handover/{hid}/interview", headers=KEY).json()
    assert a["status"] == "NEEDS_CLARIFICATION" and len(a["questions"]) == 2          # R1 and R4, each once
    assert [q["id"] for q in a["questions"]] == [q["id"] for q in b["questions"]]


def test_interview_full_flow_gates_the_transfer_on_a_real_readback(api):
    client, m = api
    hid = _synced(client, m)
    with patch.object(m.agent_service, "client", False):
        qs = client.post(f"/api/handover/{hid}/interview", headers=KEY).json()["questions"]
    # one answer is not enough: the brief is released only when every question has one
    part = client.post(f"/api/handover/{hid}/answer", json={"answers": {qs[0]["id"]: "Locked out at the MCC, tag 4471."}}, headers=KEY).json()
    assert part["status"] == "NEEDS_CLARIFICATION" and part["brief"] is None
    done = client.post(f"/api/handover/{hid}/answer", json={"answers": {q["id"]: "Checked in the field, see tag 4471." for q in qs}}, headers=KEY).json()
    assert done["status"] == "READY_FOR_BRIEF"
    crit = [i for i in done["brief"]["items"] if i["severity"] == "CRITICAL"]
    assert crit and all(c["status"] in ("OPEN", "CONFIRMED") for c in done["conflicts"])         # answers never change a verdict
    gated = client.post(f"/api/handover/{hid}/complete", headers=KEY)
    assert gated.status_code == 409
    ack = lambda text, who="A. Rahman": client.post(f"/api/handover/{hid}/acknowledge", json={"item_id": crit[0]["id"], "readback_text": text, "supervisor": who}, headers=KEY)
    assert ack("ok").status_code == 422                            # one word is not a read-back
    assert ack("Read back the isolation mismatch on P-201B", "  ").status_code == 422   # a name is required
    first = ack("Read back: P-201B shows OPEN, will verify before restart.")
    assert first.status_code == 200
    again = ack("Something else entirely said later on", "Someone Else").json()            # a repeat does not rewrite who read it back
    item = next(i for i in again["brief"]["items"] if i["id"] == crit[0]["id"])
    assert item["acknowledged_by"] == "A. Rahman" and "P-201B" in item["readback_text"]
    for c in crit[1:]:
        client.post(f"/api/handover/{hid}/acknowledge", json={"item_id": c["id"], "readback_text": "Read back the open conflict item", "supervisor": "A. Rahman"}, headers=KEY)
    out = client.post(f"/api/handover/{hid}/complete", headers=KEY)
    assert out.status_code == 200 and out.json()["incoming_supervisor"] == "A. Rahman"
    assert out.json()["open_conflicts"] >= 1                       # transferred, not resolved


def test_start_uses_the_servers_plant_feed_not_the_callers(api):
    client, m = api
    lie = {"unit_name": "HYDROCRACKER-01", "shift_name": "S", "outgoing_operator": "T", "log_text": "Pump P-201B isolated and lock applied.",
           "plant_sensor_state": {"P-201B": {"status": "CLOSED"}}, "active_permits": []}
    with patch.object(m.agent_service, "client", False):
        s = client.post("/api/handover/start", json=lie, headers=KEY).json()
    assert "R1" in {c["rule_id"] for c in s["conflicts"]}          # the feed says OPEN, whatever the caller claimed
    keys = [(c["rule_id"], c["title"]) for c in s["conflicts"]]
    assert len(keys) == len(set(keys))                             # no repeated conflict


def test_gap_questions_use_the_model_but_fall_back_and_never_claim_clear(api):
    import json as _json
    from app.agents.legacy import GeminiAgentService
    from app.models import SafetyConflict, Severity
    cs = [SafetyConflict(id="1", rule_id="R1", title="Isolation Mismatch: P-201B", description="d", severity=Severity.CRITICAL),
          SafetyConflict(id="2", rule_id="R4", title="Expired Permit", description="d4", severity=Severity.WARNING)]
    svc = GeminiAgentService()
    svc.client = True
    good = _json.dumps(["Did you physically lock out P-201B and who checked the breaker?", "Is PERMIT-M-102 still being worked under?"])
    with patch("app.agents.legacy.generate", return_value=type("R", (), {"text": good})()):
        qs = svc.generate_gap_questions(cs, [], "en")
    assert qs[0].question_text.startswith("Did you physically lock out") and len(qs) == 2
    bad = _json.dumps(["The isolation on P-201B is resolved and safe to proceed, thanks.", "Is PERMIT-M-102 still being worked under?"])
    with patch("app.agents.legacy.generate", return_value=type("R", (), {"text": bad})()):
        qs = svc.generate_gap_questions(cs, [], "en")
    assert qs[0].question_text.startswith("Clarification needed")        # a question that claims 'resolved' is replaced by the template
    assert qs[1].question_text.startswith("Is PERMIT")
    with patch("app.agents.legacy.generate", side_effect=RuntimeError("model down")):
        assert all(q.question_text.startswith("Clarification needed") for q in svc.generate_gap_questions(cs, [], "en"))



# ---------- public web app: a key that can ship in a web page, and server-side extraction ----------
DEMO = {"X-Aegis-Key": "demo_key_for_the_web_app"}


def test_demo_key_opens_app_endpoints_but_never_supervisor_ones(api, monkeypatch):
    client, m = api
    monkeypatch.setenv("AEGIS_DEMO_KEY", "demo_key_for_the_web_app")
    hid = _synced(client, m, "web1")
    assert client.get(f"/api/handover/{hid}", headers=DEMO).status_code == 200            # app scope
    assert client.get(f"/api/handover/{hid}", headers=KEY).status_code == 200             # the supervisor key still works everywhere
    assert client.post("/api/v1/dashboard/clear_alert", headers=DEMO).status_code == 401  # acknowledging an alert is supervisor-only
    assert client.post("/api/v1/dashboard/clear_alert", headers=KEY).status_code == 200
    for path in ("/api/v1/agents/runs", f"/api/v1/agents/runs/run-{hid}", "/api/v1/agents/chunks/abc"):
        assert client.get(path, headers=DEMO).status_code == 401, path                    # agent traces too
    assert client.get(f"/api/handover/{hid}", headers={"X-Aegis-Key": "something-else"}).status_code == 401


def test_demo_key_is_off_unless_configured(api, monkeypatch):
    client, m = api
    monkeypatch.delenv("AEGIS_DEMO_KEY", raising=False)
    hid = _synced(client, m, "web2")
    assert client.get(f"/api/handover/{hid}", headers={"X-Aegis-Key": ""}).status_code == 401   # an empty key never matches an unset one
    assert client.get(f"/api/handover/{hid}", headers=DEMO).status_code == 401


def test_extract_endpoint(api, monkeypatch):
    client, m = api
    monkeypatch.setenv("AEGIS_DEMO_KEY", "demo_key_for_the_web_app")
    from app import extraction
    good = {"raw": '{"facts":[{"category":"ISOLATION","asset_tag":"P-201B","asserted_state":"ISOLATED","intent_severity":"CRITICAL","quote":"isolated"}]}', "model": "m", "latency_ms": 5}
    body = {"transcript": "Pump P-201B is isolated", "known_assets": ["P-201B", "V-104"]}
    with patch.object(extraction, "extract_raw", return_value=good) as ex:
        r = client.post("/api/v1/extract", json=body, headers=DEMO)
    assert r.status_code == 200 and r.json()["raw"] == good["raw"]
    assert ex.call_args.args == ("Pump P-201B is isolated", ["P-201B", "V-104"])
    assert client.post("/api/v1/extract", json=body).status_code == 401                    # needs a key
    assert client.post("/api/v1/extract", json={"transcript": "", "known_assets": []}, headers=DEMO).status_code == 422
    assert client.post("/api/v1/extract", json={"transcript": "x" * 1001}, headers=DEMO).status_code == 422
    assert client.post("/api/v1/extract", json={"transcript": "x", "known_assets": ["a"] * 51}, headers=DEMO).status_code == 422
    with patch.object(extraction, "extract_raw", side_effect=extraction.ExtractionError("JSONDecodeError")):
        r = client.post("/api/v1/extract", json=body, headers=DEMO)
    assert r.status_code == 502 and r.json()["detail"]["error"]["code"] == "EXTRACTION_FAILED"      # the app then uses its own fallback


def test_extract_raw_validates_the_models_json():
    from unittest.mock import MagicMock
    from app import extraction
    ok = MagicMock(text='```json\n{"facts": []}\n```', model="fast")
    with patch.object(extraction, "generate", return_value=ok):
        assert extraction.extract_raw("nothing to report", [])["raw"] == '{"facts": []}'
    for bad in ("not json at all", '{"facts": "nope"}', "[]"):
        with patch.object(extraction, "generate", return_value=MagicMock(text=bad, model="fast")):
            with pytest.raises(extraction.ExtractionError):
                extraction.extract_raw("x", [])
    with patch.object(extraction, "generate", side_effect=RuntimeError("down")):
        with pytest.raises(extraction.ExtractionError):
            extraction.extract_raw("x", [])


# ---------- auth ----------
def test_auth_fails_closed_when_unconfigured(monkeypatch):
    monkeypatch.delenv("WORKER_AUDIENCE", raising=False)
    with pytest.raises(PushAuthError):
        auth.verify_push_request("Bearer x")


def test_auth_checks_identity(monkeypatch):
    monkeypatch.setenv("WORKER_AUDIENCE", "https://worker")
    monkeypatch.setenv("PUSH_INVOKER_EMAIL", "inv@p.iam.gserviceaccount.com")
    with pytest.raises(PushAuthError):
        auth.verify_push_request(None)
    with pytest.raises(PushAuthError):
        auth.verify_push_request("Basic abc")
    good = {"email": "inv@p.iam.gserviceaccount.com", "email_verified": True}
    with patch.object(auth.id_token, "verify_oauth2_token", return_value=good) as v:
        assert auth.verify_push_request("Bearer tok") == good
    assert v.call_args.kwargs["audience"] == "https://worker"
    for bad in ({"email": "other@x.com", "email_verified": True}, {"email": good["email"], "email_verified": False}):
        with patch.object(auth.id_token, "verify_oauth2_token", return_value=bad), pytest.raises(PushAuthError):
            auth.verify_push_request("Bearer tok")
    with patch.object(auth.id_token, "verify_oauth2_token", side_effect=ValueError("bad sig")), pytest.raises(PushAuthError):
        auth.verify_push_request("Bearer tok")


# ---------- intake ----------
def _event(caps):
    snap = MagicMock(exists=True)
    snap.to_dict.return_value = {"capsules": caps, "unit_name": "HYDROCRACKER-01", "shift_name": "NIGHT-SHIFT-A",
                                 "operator_id": "TECH-ARUN-42", "device_id": "d1"}
    return snap


def test_intake_missing_handover_raises():
    db = MagicMock()
    db.collection.return_value.document.return_value.get.return_value = MagicMock(exists=False)
    with patch.object(intake, "get_db", return_value=db), pytest.raises(intake.HandoverNotFound):
        intake.run_intake("batch-missing")


def test_intake_stores_capsules_and_chunks(monkeypatch):
    monkeypatch.setenv("EMBEDDING_MODEL", "emb")
    caps = [{"uuid": "u1", "asset_tag": "P-201B", "asserted_state": "ISOLATED", "category": "ISOLATION",
             "text_transcript": "isolated by Arun", "timestamp": "2026-10-11T10:00:00Z"}]
    db = MagicMock()
    db.collection.return_value.document.return_value.get.return_value = _event(caps)
    with patch.object(intake, "get_db", return_value=db), patch.object(intake, "upsert_chunks", return_value=1) as up:
        out = intake.run_intake("batch-1")
    assert out["capsules"] == 1 and out["chunks"] == 1 and out["models_used"] == ["emb"]
    chunk = up.call_args.args[0][0]
    assert chunk.source_id == "batch-1" and chunk.unit == "HYDROCRACKER-01" and "arun" not in chunk.text.lower()
    stored = db.batch.return_value.set.call_args.args[1]
    assert stored["handover_id"] == "batch-1" and stored["seeded"] is False
    db.batch.return_value.commit.assert_called_once()
    # remembers which unit the device reports for, so device updates can be looked up later
    devices_set = [c for c in db.collection.return_value.document.return_value.set.call_args_list if c.args and c.args[0].get("device_id") == "d1"]
    assert devices_set and devices_set[0].args[0]["unit"] == "HYDROCRACKER-01" and devices_set[0].kwargs == {"merge": True}


# ---------- worker ----------
def _push(handover_id="batch-1", **over):
    msg = {"type": "handover.synced", "handover_id": handover_id, "event_ids": ["u1"], "unit": "U", "device_id": "d"}
    msg.update(over)
    return {"message": {"data": base64.b64encode(json.dumps(msg).encode()).decode(), "messageId": "1"},
            "subscription": "projects/p/subscriptions/s", "deliveryAttempt": 1}


@pytest.fixture
def worker(monkeypatch):
    monkeypatch.setenv("PIPELINE_AGENTS_ENABLED", "false")      # these tests cover the intake-only mode
    import app.worker_main as w
    return TestClient(w.app), w


@pytest.fixture
def worker_agents(monkeypatch):
    monkeypatch.setenv("PIPELINE_AGENTS_ENABLED", "true")
    import app.worker_main as w
    return TestClient(w.app), w


def test_worker_rejects_unauthenticated(worker):
    client, w = worker
    assert client.post("/pubsub/handover", json=_push()).status_code == 401


def test_worker_success_marks_completed(worker):
    client, w = worker
    with patch.object(w, "verify_push_request"), patch.object(w.runs, "claim_run", return_value=runs.CLAIMED), \
            patch.object(w.runs, "finish_run") as fin, \
            patch.object(w.intake, "run_intake", return_value={"capsules": 1, "chunks": 2, "models_used": ["emb"]}):
        r = client.post("/pubsub/handover", json=_push())
    assert r.status_code == 200 and r.json()["status"] == "completed" and r.json()["run_id"] == "run-batch-1"
    assert fin.call_args.args[1] == "completed"


@pytest.mark.parametrize("outcome", [runs.ALREADY_DONE, runs.IN_PROGRESS])
def test_worker_skips_duplicates_with_2xx(worker, outcome):
    client, w = worker
    with patch.object(w, "verify_push_request"), patch.object(w.runs, "claim_run", return_value=outcome), \
            patch.object(w.intake, "run_intake") as work:
        r = client.post("/pubsub/handover", json=_push())
    assert r.status_code == 200 and r.json()["status"] == "skipped"
    work.assert_not_called()


def test_worker_missing_handover_is_retryable(worker):
    client, w = worker
    with patch.object(w, "verify_push_request"), patch.object(w.runs, "claim_run", return_value=runs.CLAIMED), \
            patch.object(w.runs, "finish_run") as fin, \
            patch.object(w.intake, "run_intake", side_effect=intake.HandoverNotFound("x")):
        r = client.post("/pubsub/handover", json=_push())
    assert r.status_code == 503 and fin.call_args.args[1] == "failed"


def test_worker_unexpected_error_is_5xx(worker):
    client, w = worker
    with patch.object(w, "verify_push_request"), patch.object(w.runs, "claim_run", return_value=runs.CLAIMED), \
            patch.object(w.runs, "finish_run"), patch.object(w.intake, "run_intake", side_effect=RuntimeError("embed down")):
        assert client.post("/pubsub/handover", json=_push()).status_code == 500


def test_worker_malformed_messages_are_400(worker):
    client, w = worker
    with patch.object(w, "verify_push_request"):
        assert client.post("/pubsub/handover", json={"message": {"data": "!!notbase64"}}).status_code == 400
        assert client.post("/pubsub/handover", json={}).status_code == 400
        assert client.post("/pubsub/handover", json=_push(type="other.event")).status_code == 400
        assert client.post("/pubsub/handover", json=_push(handover_id="")).status_code == 400


def test_worker_runs_the_agent_pipeline_and_records_tokens_and_guardrails(worker_agents):
    client, w = worker_agents
    result = {"status": "fallback", "models_used": ["m1"], "tokens": {"SafetyCrossCheckLlm": {"prompt": 10, "output": 5}},
              "guardrails_triggered": [{"agent": "SafetyCrossCheck", "guardrail": "verdict_lock", "detail": "x"}], "total_ms": 1234}
    with patch.object(w, "verify_push_request"), patch.object(w.runs, "claim_run", return_value=runs.CLAIMED), \
            patch.object(w.runs, "finish_run") as fin, patch("app.agents.pipeline.run_handover_pipeline", return_value=result) as pipe:
        r = client.post("/pubsub/handover", json=_push())
    assert r.status_code == 200 and r.json()["status"] == "fallback"           # a fallback brief is still a successful run
    pipe.assert_called_once_with("batch-1", "run-batch-1")
    assert fin.call_args.args[1] == "fallback"
    assert fin.call_args.kwargs["extra"]["guardrails_triggered"] == ["SafetyCrossCheck:verdict_lock"]
    assert fin.call_args.kwargs["extra"]["tokens"]["SafetyCrossCheckLlm"]["prompt"] == 10


def test_worker_agent_pipeline_missing_handover_is_retryable(worker_agents):
    client, w = worker_agents
    with patch.object(w, "verify_push_request"), patch.object(w.runs, "claim_run", return_value=runs.CLAIMED), \
            patch.object(w.runs, "finish_run") as fin, \
            patch("app.agents.pipeline.run_handover_pipeline", side_effect=intake.HandoverNotFound("x")):
        assert client.post("/pubsub/handover", json=_push()).status_code == 503
    assert fin.call_args.args[1] == "failed"


def test_stream_attaches_pipeline_brief_and_keeps_acknowledged_text(api):
    client, m = api
    m.dashboard_telemetry_stream.clear()
    m.dashboard_telemetry_stream.extend([
        {"id": "b1", "summary": "legacy", "sync_status": "CONFLICT_DETECTED"},
        {"id": "b2", "summary": "ack text", "sync_status": "ACKNOWLEDGED"},
        {"id": "b3", "summary": "no brief yet", "sync_status": "SUCCESS"}])
    brief = {"headline": "2 conflicts are open", "items": [], "citation_details": [], "model": "m", "guardrail_status": "passed", "guardrails": [], "run_id": "run-b1"}
    with patch.object(m, "_fetch_briefs", return_value={"b1": brief, "b2": brief, "b3": None}):
        data = client.get("/api/v1/dashboard/stream").json()
    by_id = {e["id"]: e for e in data["events"]}
    assert by_id["b1"]["summary"] == "2 conflicts are open" and by_id["b1"]["brief"]["run_id"] == "run-b1"
    assert by_id["b2"]["summary"] == "ack text"                 # not overwritten after acknowledgement
    assert by_id["b3"]["summary"] == "no brief yet" and "brief" not in by_id["b3"]
    assert m.dashboard_telemetry_stream[0]["summary"] == "legacy"   # stored events are not mutated


def test_ledger_count_uses_one_cached_aggregation_not_a_document_scan(api):
    client, m = api
    from types import SimpleNamespace as NS
    db = MagicMock()
    db.collection.return_value.count.return_value.get.return_value = [[NS(value=7)]]
    m._ledger_cache.update(at=0.0, n=None)
    with patch.object(m, "firestore_db", db):
        assert m.get_firestore_ledger_count() == 7
        assert m.get_firestore_ledger_count() == 7            # second call within 15 s is served from the cache
    assert db.collection.return_value.count.return_value.get.call_count == 1
    db.collection.return_value.limit.assert_not_called()      # the old implementation listed up to 100 documents per call
    m._ledger_cache.update(at=0.0, n=None)


def test_request_log_query_excludes_dashboard_polling():
    import app.main as m
    captured = {}
    client = MagicMock()
    client.list_entries.side_effect = lambda **kw: captured.update(kw) or []
    with patch.object(m, "cloud_log_client", client):
        m._last_cloud_log_fetch = 0.0
        m._cached_cloud_logs = []
        m.fetch_and_parse_cloud_logs(5)
    f = captured["filter_"]
    assert 'NOT httpRequest.requestUrl:"/agents/"' in f and 'NOT httpRequest.requestUrl:"dashboard"' in f and 'NOT httpRequest.requestUrl:"health"' in f


def test_responses_are_gzip_compressed_when_large(api):
    client, m = api
    big = client.get("/dashboard", headers={"Accept-Encoding": "gzip"})        # a large static page
    assert big.status_code == 200 and big.headers.get("content-encoding") == "gzip"
