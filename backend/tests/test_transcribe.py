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
@patch("app.main.genai.Client")
def test_translation_fallback(mock_genai, mock_speech_client_class):
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
    mock_genai_client = MagicMock()
    mock_genai.return_value = mock_genai_client
    mock_genai_client.models.generate_content.side_effect = Exception("Translation API down")
    
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
