import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock
from app.main import app
import os

client = TestClient(app)

# Test data
VALID_KEY = "test_super_secret_key"
os.environ["AEGIS_API_KEY"] = VALID_KEY
os.environ["GOOGLE_CLOUD_PROJECT"] = "test-project"

def get_headers():
    return {"X-Aegis-Key": VALID_KEY}

def test_health_check():
    response = client.get("/api/health")
    assert response.status_code == 200

def test_missing_auth():
    response = client.post("/api/transcribe", files={"audio": ("test.wav", b"dummy")})
    assert response.status_code == 401

def test_invalid_auth():
    response = client.post("/api/transcribe", headers={"X-Aegis-Key": "wrong"}, files={"audio": ("test.wav", b"dummy")})
    assert response.status_code == 401

def test_oversize_payload():
    large_audio = b"0" * (10 * 1024 * 1024 + 1)
    response = client.post("/api/transcribe", headers=get_headers(), files={"audio": ("large.wav", large_audio)})
    assert response.status_code == 413

@patch("app.main.SpeechClient")
def test_successful_transcribe(mock_speech_client_class):
    # Mock Speech Client
    mock_client = MagicMock()
    mock_speech_client_class.return_value = mock_client
    
    mock_response = MagicMock()
    mock_result = MagicMock()
    mock_alt = MagicMock()
    mock_alt.transcript = "hello world"
    mock_result.alternatives = [mock_alt]
    mock_result.language_code = "en-US"
    mock_response.results = [mock_result]
    mock_client.recognize.return_value = mock_response
    
    response = client.post("/api/transcribe", headers=get_headers(), files={"audio": ("test.wav", b"dummy")})
    
    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "hello world"
    assert data["language"] == "en-US"
    assert data["no_speech"] == False
    assert data["engine"] == "chirp3"

@patch("app.main.SpeechClient")
def test_no_speech(mock_speech_client_class):
    mock_client = MagicMock()
    mock_speech_client_class.return_value = mock_client
    
    mock_response = MagicMock()
    mock_response.results = []
    mock_client.recognize.return_value = mock_response
    
    response = client.post("/api/transcribe", headers=get_headers(), files={"audio": ("test.wav", b"dummy")})
    
    assert response.status_code == 200
    data = response.json()
    assert data["no_speech"] == True
    assert data["text"] == ""

@patch("app.main.SpeechClient")
@patch("app.main.llm_generate")
def test_translation_fallback(mock_generate, mock_speech_client_class):
    # Mock Speech Client returning French
    mock_client = MagicMock()
    mock_speech_client_class.return_value = mock_client
    mock_response = MagicMock()
    mock_result = MagicMock()
    mock_alt = MagicMock()
    mock_alt.transcript = "bonjour"
    mock_result.alternatives = [mock_alt]
    mock_result.language_code = "fr-FR"
    mock_response.results = [mock_result]
    mock_client.recognize.return_value = mock_response

    # Mock Translation failure
    mock_generate.side_effect = Exception("Translation API down")
    
    response = client.post("/api/transcribe", headers=get_headers(), files={"audio": ("test.wav", b"dummy")})
    
    assert response.status_code == 200
    data = response.json()
    assert data["text"] == "bonjour"
    assert data["language"] == "fr-FR"
    assert data["english_text"] is None

from google.api_core.exceptions import DeadlineExceeded

@patch("app.main.SpeechClient")
def test_upstream_timeout(mock_speech_client_class):
    mock_client = MagicMock()
    mock_speech_client_class.return_value = mock_client
    mock_client.recognize.side_effect = DeadlineExceeded("Timeout")
    
    response = client.post("/api/transcribe", headers=get_headers(), files={"audio": ("test.wav", b"dummy")})
    assert response.status_code == 504

def test_rate_limit():
    import app.main
    app.main.rate_limit_db.clear()
    
    headers = get_headers()
    # Hit the limit (30 requests)
    for _ in range(30):
        # We can mock the IP or just use the test client which provides testclient IP
        app.main.check_rate_limit("testclient")
    
    # 31st request should fail
    response = client.post("/api/transcribe", headers=headers, files={"audio": ("test.wav", b"dummy")})
    assert response.status_code == 429


@patch("app.main.llm_generate")
def test_gemini_engine_reports_model_actually_used(mock_generate, monkeypatch):
    from app.llm import GenerateResult
    import app.main
    app.main.rate_limit_db.clear()
    monkeypatch.setenv("TRANSCRIBE_ENGINE", "gemini")
    mock_generate.return_value = GenerateResult(
        text="பம்ப் P-201B\nTRANSLATION: Pump P-201B", model="served-model-x", location="global", latency_ms=5)
    response = client.post("/api/transcribe", headers=get_headers(), files={"audio": ("a.m4a", b"\x00\x00\x00\x18ftypM4A dummy")})
    assert response.status_code == 200
    data = response.json()
    assert data["model"] == "served-model-x"
    assert data["engine"] == "gemini"
    assert data["english_text"] == "Pump P-201B"
    assert "P-201B" in data["text"]


def test_clear_alert_requires_key():
    assert client.post("/api/v1/dashboard/clear_alert").status_code == 401
    assert client.post("/api/v1/dashboard/clear_alert", headers={"X-Aegis-Key": "wrong"}).status_code == 401
    ok = client.post("/api/v1/dashboard/clear_alert", headers=get_headers())
    assert ok.status_code == 200 and ok.json()["status"] == "ACKNOWLEDGED"


def test_no_key_configured_fails_closed(monkeypatch):
    monkeypatch.delenv("AEGIS_API_KEY")
    assert client.post("/api/v1/dashboard/clear_alert", headers={"X-Aegis-Key": "dev-key"}).status_code == 401
    assert client.post("/api/v1/dashboard/clear_alert", headers={"X-Aegis-Key": ""}).status_code == 401


def test_stream_still_open_and_reports_configured_model():
    r = client.get("/api/v1/dashboard/stream")
    assert r.status_code == 200
    assert r.json()["model"] == "test-model"


def test_clear_alert_never_claims_the_conflict_is_clear():
    import app.main as m
    from app.agents.guardrails import find_clearing_language
    m.dashboard_telemetry_stream.appendleft({"id": "t", "has_critical_conflict": True, "sync_status": "CONFLICT_DETECTED", "summary": "x",
                                             "conflicts": [{"rule_id": "R1", "status": "OPEN"}]})
    with patch.object(m, "save_batch_sync_event"):
        r = client.post("/api/v1/dashboard/clear_alert", headers=get_headers())
    ev = m.dashboard_telemetry_stream[0]
    assert r.json()["status"] == "ACKNOWLEDGED"
    assert ev["conflicts"][0]["status"] == "ACKNOWLEDGED"               # acknowledged, not mitigated or resolved
    assert find_clearing_language(ev["summary"]) == [] and find_clearing_language(r.json()["message"]) == []
    m.dashboard_telemetry_stream.popleft()


def test_asset_hints_are_passed_to_the_transcription_prompt():
    import app.main as m
    assert m._asset_hint_sentence(None) == "" and m._asset_hint_sentence(" , ") == ""
    sentence = m._asset_hint_sentence("P-201B, V-102")
    assert "P-201B, V-102" in sentence and "hyphen" in sentence
    assert m._asset_hint_sentence(",".join(f"T-{i}00" for i in range(80))).count("T-") == 50   # capped
