"""Minimal OpenRouter client and controlled live smoke checks."""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Callable, Sequence
from typing import Any

from openai import OpenAI

from emporio.config import Settings, load_settings

LOGGER = logging.getLogger(__name__)
DEFAULT_TIMEOUT_SECONDS = 30.0
EXPECTED_ENGLISH_RESPONSE = "English smoke check passed."
TOY_ITEM = "alpha"
TOY_CODE = "A-17"
TOY_TOOL_NAME = "lookup_test_code"

TOY_TOOL = {
    "type": "function",
    "function": {
        "name": TOY_TOOL_NAME,
        "description": "Look up a fixed test code from a read-only toy mapping.",
        "parameters": {
            "type": "object",
            "properties": {
                "item": {
                    "type": "string",
                    "enum": [TOY_ITEM],
                    "description": "The toy item to look up.",
                }
            },
            "required": ["item"],
            "additionalProperties": False,
        },
    },
}


class SmokeCheckError(RuntimeError):
    """Raised when a live response does not satisfy the smoke contract."""


def require_free_model(model_id: str) -> None:
    """Reject model identifiers that are not explicitly free."""
    if not model_id.endswith(":free"):
        raise ValueError("Smoke checks require an explicit OpenRouter model ending in ':free'.")


def create_client(settings: Settings) -> OpenAI:
    """Create the single OpenRouter client used by the smoke runner."""
    require_free_model(settings.openrouter_model)
    return OpenAI(
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        max_retries=0,
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )


def lookup_test_code(item: str) -> dict[str, str]:
    """Return a deterministic value from a read-only toy mapping."""
    if item != TOY_ITEM:
        raise ValueError(f"Unknown toy item: {item!r}")
    return {"item": item, "code": TOY_CODE}


def _invoke(
    *,
    model_id: str,
    phase: str,
    request: Callable[[], Any],
) -> Any:
    started = time.perf_counter()
    try:
        response = request()
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        LOGGER.error(
            "llm_request model=%s phase=%s status=error latency_ms=%.1f "
            "finish_reason=none error_class=%s",
            model_id,
            phase,
            latency_ms,
            type(exc).__name__,
        )
        raise

    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    finish_reason = response.choices[0].finish_reason
    LOGGER.info(
        "llm_request model=%s phase=%s status=success latency_ms=%.1f "
        "finish_reason=%s error_class=none",
        model_id,
        phase,
        latency_ms,
        finish_reason,
    )
    return response


def _request_options(model_id: str) -> dict[str, Any]:
    require_free_model(model_id)
    return {
        "model": model_id,
        "temperature": 0,
        "extra_body": {
            "provider": {
                "allow_fallbacks": False,
                "require_parameters": True,
            }
        },
    }


def run_english_smoke(client: Any, model_id: str) -> dict[str, Any]:
    """Make one request and require one exact English sentence."""
    options = _request_options(model_id)
    response = _invoke(
        model_id=model_id,
        phase="english",
        request=lambda: client.chat.completions.create(
            **options,
            max_tokens=16,
            messages=[
                {
                    "role": "user",
                    "content": f"Reply with exactly: {EXPECTED_ENGLISH_RESPONSE}",
                }
            ],
        ),
    )
    content = response.choices[0].message.content or ""
    if content.strip() != EXPECTED_ENGLISH_RESPONSE:
        raise SmokeCheckError("The English smoke response did not match the expected sentence.")
    return {
        "status": "passed",
        "finish_reason": response.choices[0].finish_reason,
    }


def run_tool_smoke(client: Any, model_id: str) -> dict[str, Any]:
    """Run one controlled tool request, local execution, and model follow-up."""
    options = _request_options(model_id)
    messages: list[Any] = [
        {
            "role": "user",
            "content": (
                f"Call {TOY_TOOL_NAME} with item={TOY_ITEM!r}. "
                "After receiving its result, state the returned code."
            ),
        }
    ]
    first = _invoke(
        model_id=model_id,
        phase="tool_request",
        request=lambda: client.chat.completions.create(
            **options,
            max_tokens=64,
            messages=messages,
            tools=[TOY_TOOL],
            tool_choice={"type": "function", "function": {"name": TOY_TOOL_NAME}},
        ),
    )

    assistant_message = first.choices[0].message
    tool_calls = assistant_message.tool_calls or []
    if len(tool_calls) != 1:
        raise SmokeCheckError("Expected exactly one tool call.")

    call = tool_calls[0]
    if call.type != "function" or call.function.name != TOY_TOOL_NAME or not call.id:
        raise SmokeCheckError("The returned tool-call structure is invalid.")
    try:
        arguments = json.loads(call.function.arguments)
    except (TypeError, json.JSONDecodeError) as exc:
        raise SmokeCheckError("The tool-call arguments are not valid JSON.") from exc
    if arguments != {"item": TOY_ITEM}:
        raise SmokeCheckError("The tool-call arguments do not match the controlled request.")

    tool_result = lookup_test_code(**arguments)
    messages.extend(
        [
            assistant_message,
            {
                "role": "tool",
                "tool_call_id": call.id,
                "content": json.dumps(tool_result, sort_keys=True),
            },
        ]
    )
    final = _invoke(
        model_id=model_id,
        phase="tool_follow_up",
        request=lambda: client.chat.completions.create(
            **options,
            max_tokens=64,
            messages=messages,
            tools=[TOY_TOOL],
        ),
    )
    final_message = final.choices[0].message
    if final_message.tool_calls:
        raise SmokeCheckError("The follow-up unexpectedly requested another tool call.")
    if TOY_CODE not in (final_message.content or ""):
        raise SmokeCheckError("The follow-up response did not use the toy tool result.")

    return {
        "status": "passed",
        "tool_call": {
            "type": call.type,
            "name": call.function.name,
            "arguments": arguments,
            "id_present": bool(call.id),
        },
        "tool_executed": True,
        "follow_up_used_result": True,
        "finish_reason": final.choices[0].finish_reason,
    }


def run_smoke_checks(client: Any, model_id: str) -> dict[str, Any]:
    """Run the three-request live smoke budget for one explicit free model."""
    require_free_model(model_id)
    return {
        "model": model_id,
        "english": run_english_smoke(client, model_id),
        "tool_cycle": run_tool_smoke(client, model_id),
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run live checks without printing credentials, prompts, or response bodies."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="explicit OpenRouter :free model ID")
    args = parser.parse_args(argv)
    settings = load_settings()
    model_id = args.model or settings.openrouter_model
    require_free_model(model_id)
    client = create_client(
        Settings(
            openrouter_api_key=settings.openrouter_api_key,
            openrouter_model=model_id,
            openrouter_base_url=settings.openrouter_base_url,
            reference_date=settings.reference_date,
            data_dir=settings.data_dir,
        )
    )

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        summary = run_smoke_checks(client, model_id)
    except Exception as exc:
        print(f"Smoke checks failed: {type(exc).__name__}")
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
