import pytest
from app.config import ConfigError, get_settings, validate_startup


def test_reads_env(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIM", "1536")
    s = get_settings()
    assert s.gemini_model == "test-model" and s.embedding_dim == 1536


def test_vertex_location_is_fallback(monkeypatch):
    monkeypatch.delenv("GEMINI_LOCATION")
    monkeypatch.setenv("VERTEX_LOCATION", "us-central1")
    assert get_settings().gemini_location == "us-central1"
    monkeypatch.setenv("GEMINI_LOCATION", "global")
    assert get_settings().gemini_location == "global"


def test_fast_model_defaults_to_main(monkeypatch):
    monkeypatch.delenv("GEMINI_FAST_MODEL")
    assert get_settings().gemini_fast_model == "test-model"


def test_bad_dim(monkeypatch):
    monkeypatch.setenv("EMBEDDING_DIM", "abc")
    with pytest.raises(ConfigError):
        get_settings()


def test_validate_reports_missing(monkeypatch):
    monkeypatch.delenv("AEGIS_API_KEY")
    monkeypatch.delenv("GEMINI_MODEL")
    problems = validate_startup()
    assert any("AEGIS_API_KEY" in p for p in problems)
    assert any("GEMINI_MODEL" in p for p in problems)


def test_no_dev_key_default(monkeypatch):
    monkeypatch.delenv("AEGIS_API_KEY")
    assert get_settings().aegis_api_key == ""
