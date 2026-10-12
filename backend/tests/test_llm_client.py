import logging
from unittest.mock import MagicMock, patch

import pytest
from google.genai import errors

from app.llm import client as llm


def _ok(text="hello"):
    r = MagicMock()
    r.text = text
    return r


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda s: None)


def _fake(side_effects):
    c = MagicMock()
    c.models.generate_content.side_effect = side_effects
    return c


def test_success_uses_configured_model_and_logs(caplog):
    c = _fake([_ok(" hi ")])
    with patch.object(llm, "get_client", return_value=c), caplog.at_level(logging.INFO, logger="baton.llm"):
        r = llm.generate("unit", "prompt text")
    assert r.text == "hi" and r.model == "test-model" and r.location == "global"
    assert c.models.generate_content.call_args.kwargs["model"] == "test-model"
    line = [m for m in caplog.messages if "gemini_call" in m][0]
    assert "purpose=unit" in line and "in=11" in line and "out=2" in line and "status=ok" in line
    assert "prompt text" not in line


def test_fast_flag_uses_fast_model():
    c = _fake([_ok()])
    with patch.object(llm, "get_client", return_value=c):
        r = llm.generate("unit", "x", fast=True)
    assert r.model == "test-fast-model"


def test_retries_429_then_succeeds():
    c = _fake([errors.ClientError(429, {"error": {"message": "slow down"}}), _ok("done")])
    with patch.object(llm, "get_client", return_value=c):
        assert llm.generate("unit", "x").text == "done"
    assert c.models.generate_content.call_count == 2


def test_gives_up_after_two_retries():
    err = errors.ServerError(503, {"error": {"message": "down"}})
    c = _fake([err, err, err, _ok()])
    with patch.object(llm, "get_client", return_value=c), pytest.raises(errors.ServerError):
        llm.generate("unit", "x")
    assert c.models.generate_content.call_count == 3  # 1 try + 2 retries


def test_400_not_retried():
    c = _fake([errors.ClientError(400, {"error": {"message": "bad"}}), _ok()])
    with patch.object(llm, "get_client", return_value=c), pytest.raises(errors.ClientError):
        llm.generate("unit", "x")
    assert c.models.generate_content.call_count == 1


def test_404_logs_env_var_name(caplog):
    c = _fake([errors.ClientError(404, {"error": {"message": "not found"}})])
    with patch.object(llm, "get_client", return_value=c), caplog.at_level(logging.ERROR, logger="baton.llm"), pytest.raises(errors.ClientError):
        llm.generate("unit", "x", fast=True)
    assert any("GEMINI_FAST_MODEL" in m for m in caplog.messages)


def test_timeout_and_token_cap_passed_to_sdk():
    c = _fake([_ok()])
    with patch.object(llm, "get_client", return_value=c):
        llm.generate("unit", "x", max_output_tokens=77, timeout_s=12)
    cfg = c.models.generate_content.call_args.kwargs["config"]
    assert cfg.max_output_tokens == 77 and cfg.http_options.timeout == 12000


def test_fast_model_uses_its_own_location(monkeypatch):
    monkeypatch.setenv("GEMINI_LOCATION", "asia-southeast1")
    monkeypatch.setenv("GEMINI_FAST_LOCATION", "global")
    c = _fake([_ok(), _ok()])
    with patch.object(llm, "get_client", return_value=c) as gc:
        main = llm.generate("unit", "x")
        fast = llm.generate("unit", "x", fast=True)
    assert (main.location, fast.location) == ("asia-southeast1", "global")
    assert [call.args[0] for call in gc.call_args_list] == ["asia-southeast1", "global"]


def test_fast_location_defaults_to_main_location(monkeypatch):
    from app.config import get_settings
    monkeypatch.setenv("GEMINI_LOCATION", "asia-southeast1")
    monkeypatch.delenv("GEMINI_FAST_LOCATION", raising=False)
    assert get_settings().gemini_fast_location == "asia-southeast1"
