"""Offline tests for the isolated OpenRouter smoke client."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from emporio.llm import (
    EXPECTED_ENGLISH_RESPONSE,
    TOY_CODE,
    TOY_TOOL_NAME,
    SmokeCheckError,
    require_free_model,
    run_english_smoke,
    run_tool_smoke,
)

FREE_MODEL = "google/gemma-4-31b-it:free"


def _response(*, content: str | None, tool_calls: list[object] | None = None) -> object:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls" if tool_calls else "stop",
                message=SimpleNamespace(content=content, tool_calls=tool_calls),
            )
        ]
    )


def _client_with(*responses: object) -> tuple[object, Mock]:
    create = Mock(side_effect=responses)
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    return client, create


def test_paid_model_is_rejected_before_a_request() -> None:
    with pytest.raises(ValueError, match=":free"):
        require_free_model("google/gemma-4-31b-it")


def test_english_smoke_uses_one_free_request() -> None:
    client, create = _client_with(_response(content=EXPECTED_ENGLISH_RESPONSE))

    result = run_english_smoke(client, FREE_MODEL)

    assert result == {"status": "passed", "finish_reason": "stop"}
    assert create.call_count == 1
    request = create.call_args.kwargs
    assert request["model"] == FREE_MODEL
    assert request["extra_body"]["provider"] == {
        "allow_fallbacks": False,
        "require_parameters": True,
    }


def test_english_smoke_rejects_unexpected_text() -> None:
    client, _ = _client_with(_response(content="Olá"))

    with pytest.raises(SmokeCheckError, match="English"):
        run_english_smoke(client, FREE_MODEL)


def test_tool_smoke_validates_executes_and_follows_up() -> None:
    tool_call = SimpleNamespace(
        id="call-safe-test-id",
        type="function",
        function=SimpleNamespace(name=TOY_TOOL_NAME, arguments='{"item":"alpha"}'),
    )
    client, create = _client_with(
        _response(content=None, tool_calls=[tool_call]),
        _response(content=f"The returned code is {TOY_CODE}."),
    )

    result = run_tool_smoke(client, FREE_MODEL)

    assert create.call_count == 2
    assert result["tool_call"] == {
        "type": "function",
        "name": TOY_TOOL_NAME,
        "arguments": {"item": "alpha"},
        "id_present": True,
    }
    assert result["tool_executed"] is True
    assert result["follow_up_used_result"] is True
    follow_up_messages = create.call_args_list[1].kwargs["messages"]
    assert follow_up_messages[-1]["role"] == "tool"
    assert follow_up_messages[-1]["tool_call_id"] == tool_call.id
    assert TOY_CODE in follow_up_messages[-1]["content"]


def test_provider_error_logs_class_without_message(caplog: pytest.LogCaptureFixture) -> None:
    class FakeProviderError(RuntimeError):
        pass

    client, _ = _client_with(FakeProviderError("sensitive-provider-detail"))

    with caplog.at_level(logging.ERROR), pytest.raises(FakeProviderError):
        run_english_smoke(client, FREE_MODEL)

    assert "error_class=FakeProviderError" in caplog.text
    assert "sensitive-provider-detail" not in caplog.text
