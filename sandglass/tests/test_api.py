from __future__ import annotations

import json
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.payload import fit

from .conftest import FakeLLM
from .test_engine import Q, _draft


@pytest.fixture
def client(settings):
    s = replace(settings, api_keys=["device-key"], admin_key="admin-key")
    with TestClient(create_app(s, FakeLLM(_draft()))) as c:
        c.headers["X-API-Key"] = "device-key"
        yield c


def test_requires_api_key(client):
    assert client.post("/v1/ask", json={"q": Q}, headers={"X-API-Key": "nope"}).status_code == 401
    assert client.get("/health", headers={"X-API-Key": ""}).status_code == 200


def test_compact_answer_fits_budget_and_revalidates_with_etag(client):
    r = client.post("/v1/ask", json={"q": Q, "budget": 400})
    assert r.status_code == 200
    assert len(r.content) <= 400
    body = r.json()
    assert body["d"] == "A" and body["g"] == "g" and 0 < body["c"] <= 1
    assert body["s"][0][0].startswith("BUL-2026-07")

    again = client.post("/v1/ask", json={"q": Q, "budget": 400}, headers={"If-None-Match": r.headers["etag"]})
    assert again.status_code == 304 and again.content == b""


def test_full_view_explains_confidence(client):
    body = client.post("/v1/ask?view=full", json={"q": Q}).json()
    assert set(body["breakdown"]) == {"retrieval", "grounding", "model"}
    assert body["claims"][0]["grounding"] == "exact"


def test_search_returns_passages_without_gemini(client):
    r = client.post("/v1/search", json={"q": "relief valve removed start pump", "k": 3, "budget": 600})
    body = r.json()
    assert len(r.content) <= 600 and body["r"]
    assert all(len(hit) == 4 for hit in body["r"])


def test_rejects_unknown_fields_and_oversized_questions(client):
    assert client.post("/v1/ask", json={"q": Q, "extra": 1}).status_code == 422
    assert client.post("/v1/ask", json={"q": "x" * 1001}).status_code == 422


def test_admin_reindex(client):
    assert client.post("/v1/admin/reindex").status_code == 403
    r = client.post("/v1/admin/reindex", headers={"X-Admin-Key": "admin-key"})
    assert r.status_code == 200 and r.json()["chunks"] > 0


@pytest.mark.parametrize("budget", [200, 260, 400, 800, 3000])
def test_fit_always_respects_budget_and_keeps_core_keys(budget):
    payload = {"v": "abc1234567", "d": "A", "c": 0.87, "g": "g", "t": 1234,
               "a": "No. " + "Hot work stays suspended until the detector is restored and tested. " * 6,
               "f": [[f"fact {i} " + "x" * 60, 0.9 - i / 10, [i]] for i in range(4)],
               "s": [[f"SOP-{i}#2", "4 Fixed gas detection", 1 - i / 10] for i in range(4)],
               "x": "Keep hot work stopped and restore GD-311 before resuming any work on the platform.",
               "w": "Bulletin 2026-07 supersedes SOP-GD-03 section 2 on the stripper platform only."}
    out = fit(payload, budget)
    data = json.loads(out)
    assert len(out) <= budget
    assert {"v", "d", "c", "g", "a"} <= set(data)
    for fact in data.get("f", []):  # references stay valid after pruning
        assert all(i < len(data["s"]) for i in fact[2])
