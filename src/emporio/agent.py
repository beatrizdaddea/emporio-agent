"""Command-line entry point and the LangChain/LangGraph support agent."""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import openai
from langchain.agents import create_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ToolCallLimitMiddleware
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphRecursionError
from pydantic import SecretStr

from emporio import __version__
from emporio.agent_tools import build_tools, safe_tool_errors
from emporio.config import Settings, load_settings
from emporio.history import Session
from emporio.llm import require_free_model
from emporio.prompts import SYSTEM_PROMPT
from emporio.retrieval import POLICY_FILE, PolicyExtractionError, PolicyIndex, load_policy
from emporio.tools import CatalogStore, SourceDataError, load_store

LOGGER = logging.getLogger(__name__)

MAX_INPUT_CHARS = 1000
MODEL_TIMEOUT_SECONDS = 30.0
MAX_OUTPUT_TOKENS = 700
RUN_MODEL_CALL_LIMIT = 5
THREAD_MODEL_CALL_LIMIT = 30
RUN_TOOL_CALL_LIMIT = 6
# Backstop only: measured ~4 graph steps + 5 per tool round, so 5 model calls need <= ~30.
# The model-call limit above is the primary bound and must fire first.
RECURSION_LIMIT = 40
EXIT_COMMANDS = frozenset({"exit", "quit"})

MESSAGES = {
    "rate_limited": (
        "I've hit the assistant's usage limit right now. Please try again in a few minutes."
    ),
    "unreachable": "I couldn't reach the assistant service. Please try again.",
    "provider_error": "Something went wrong on the assistant service. Please try again later.",
    "step_limit": (
        "I couldn't finish that within my step limit. Could you rephrase or split your "
        "question into smaller parts? If we've been chatting for a long time, restart the session."
    ),
    "empty_reply": "I couldn't put together an answer. Could you rephrase your question?",
    "empty_input": "Please enter a message so I can help.",
    "input_too_long": (
        f"That message is too long. Please keep it under {MAX_INPUT_CHARS} characters."
    ),
    "unexpected": "Something unexpected happened. Please try again.",
}


@dataclass(frozen=True)
class TurnResult:
    """Outcome of one customer turn."""

    reply: str
    error: str | None = None
    trace: list[str] = field(default_factory=list)
    usage: dict[str, int] | None = None


# ------------------------------------------------------------------ construction


def build_chat_model(settings: Settings) -> Any:
    """Create the single OpenRouter chat model: free ID only, no retries, no fallbacks."""
    from langchain_openai import ChatOpenAI

    require_free_model(settings.openrouter_model)
    return ChatOpenAI(
        model=settings.openrouter_model,
        api_key=SecretStr(settings.openrouter_api_key),
        base_url=settings.openrouter_base_url,
        temperature=0,
        max_retries=0,
        timeout=MODEL_TIMEOUT_SECONDS,
        max_tokens=MAX_OUTPUT_TOKENS,
        extra_body={"provider": {"allow_fallbacks": False, "require_parameters": True}},
    )


def build_agent(
    model: Any,
    store: CatalogStore,
    index: PolicyIndex,
    reference_date: date,
) -> Any:
    """Compile the bounded tool-calling agent with in-memory session checkpoints."""
    # Never ship conversations to a third-party tracing service.
    os.environ["LANGSMITH_TRACING"] = "false"
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    return create_agent(
        model=model,
        tools=build_tools(store, index, reference_date),
        system_prompt=SYSTEM_PROMPT,
        middleware=[
            safe_tool_errors,
            ModelCallLimitMiddleware(
                run_limit=RUN_MODEL_CALL_LIMIT,
                thread_limit=THREAD_MODEL_CALL_LIMIT,
                exit_behavior="error",
            ),
            ToolCallLimitMiddleware(run_limit=RUN_TOOL_CALL_LIMIT),
        ],
        checkpointer=InMemorySaver(),
    )


# ------------------------------------------------------------------ one turn


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [
            block if isinstance(block, str) else str(block.get("text", ""))
            for block in content
            if isinstance(block, (str, dict))
        ]
        return "".join(parts)
    return ""


def _sources(value: Any, found: list[str]) -> None:
    if isinstance(value, dict):
        if "file" in value and "row" in value:
            found.append(f"{value['file']}:{value['row']}")
        if "section_id" in value and "pages" in value:
            found.append(f"policy §{value['section_id']} p{value['pages']}")
        for item in value.values():
            _sources(item, found)
    elif isinstance(value, list):
        for item in value:
            _sources(item, found)


def summarize_tool_result(content: str) -> str:
    """Short, non-sensitive trace summary: outcome plus source references."""
    try:
        data = json.loads(content)
    except (TypeError, ValueError):
        return "unparseable"
    outcome = "error" if isinstance(data, dict) and "error" in data and len(data) == 1 else "ok"
    if isinstance(data, dict) and (data.get("found") is False or data.get("matched") is False):
        outcome = "no_result"
    found: list[str] = []
    _sources(data, found)
    unique = list(dict.fromkeys(found))
    shown = ", ".join(unique[:6]) + (" ..." if len(unique) > 6 else "")
    return f"{outcome}" + (f" sources=[{shown}]" if shown else "")


def _trace(messages: Sequence[BaseMessage]) -> list[str]:
    start = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
    lines: list[str] = []
    for message in messages[start + 1 :]:
        if isinstance(message, AIMessage):
            for call in message.tool_calls:
                lines.append(f"call {call['name']} {json.dumps(call['args'], ensure_ascii=False)}")
        elif isinstance(message, ToolMessage):
            lines.append(f"result {message.name} {summarize_tool_result(_text(message.content))}")
    return lines


def _usage(messages: Sequence[BaseMessage]) -> dict[str, int] | None:
    """Aggregate provider-reported token usage for only the latest user turn."""
    start = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
    totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    reported_messages = 0
    for message in messages[start + 1 :]:
        if not isinstance(message, AIMessage) or not message.usage_metadata:
            continue
        reported_messages += 1
        for key in totals:
            value = message.usage_metadata.get(key)
            if isinstance(value, int) and not isinstance(value, bool):
                totals[key] += value
    if not reported_messages:
        return None
    return {**totals, "reported_messages": reported_messages}


def run_turn(agent: Any, session: Session, user_text: str) -> TurnResult:
    """Run one bounded turn; never raises, never leaks provider or tool internals."""
    text = user_text.strip()
    if not text:
        return TurnResult(MESSAGES["empty_input"], error="empty_input")
    if len(text) > MAX_INPUT_CHARS:
        return TurnResult(MESSAGES["input_too_long"], error="input_too_long")

    config = {"configurable": {"thread_id": session.thread_id}, "recursion_limit": RECURSION_LIMIT}
    try:
        state = agent.invoke({"messages": [HumanMessage(content=text)]}, config=config)
    except (ModelCallLimitExceededError, GraphRecursionError) as exc:
        LOGGER.error("agent_turn status=error error_class=%s", type(exc).__name__)
        return TurnResult(MESSAGES["step_limit"], error="step_limit")
    except openai.RateLimitError:
        LOGGER.error("agent_turn status=error error_class=RateLimitError status_code=429")
        return TurnResult(MESSAGES["rate_limited"], error="rate_limited")
    except openai.APIConnectionError as exc:  # includes APITimeoutError
        LOGGER.error("agent_turn status=error error_class=%s", type(exc).__name__)
        return TurnResult(MESSAGES["unreachable"], error="unreachable")
    except openai.APIStatusError as exc:
        LOGGER.error(
            "agent_turn status=error error_class=%s status_code=%s",
            type(exc).__name__,
            exc.status_code,
        )
        return TurnResult(MESSAGES["provider_error"], error="provider_error")
    except Exception as exc:
        LOGGER.error("agent_turn status=error error_class=%s", type(exc).__name__)
        return TurnResult(MESSAGES["unexpected"], error="unexpected")

    messages = state["messages"]
    trace = _trace(messages)
    usage = _usage(messages)
    last = messages[-1] if messages else None
    reply = _text(last.content).strip() if isinstance(last, AIMessage) else ""
    if not reply:
        return TurnResult(MESSAGES["empty_reply"], error="empty_reply", trace=trace, usage=usage)
    return TurnResult(reply, trace=trace, usage=usage)


# ------------------------------------------------------------------ CLI


def chat(
    agent: Any,
    session: Session,
    *,
    read: Callable[[str], str] = input,
    write: Callable[[str], None] = print,
    write_trace: Callable[[str], None] | None = None,
) -> None:
    """Interactive loop. Ends on `exit`/`quit` or end of input."""
    write("Empório da Música assistant. Type 'exit' to leave.")
    while True:
        try:
            line = read("You: ")
        except (EOFError, KeyboardInterrupt):
            write("")
            return
        text = line.strip()
        if not text:
            continue
        if text.lower() in EXIT_COMMANDS:
            write("Bye!")
            return
        result = run_turn(agent, session, text)
        if write_trace is not None:
            for entry in result.trace:
                write_trace(f"  [trace] {entry}")
        session.record("user", text)
        session.record("assistant", result.reply)
        write(f"Assistant: {result.reply}")


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser."""
    parser = argparse.ArgumentParser(
        prog="emporio",
        description="Empório da Música customer-support assistant (English).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--check-config",
        action="store_true",
        help="validate environment settings without making a network request",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="print tool calls and source references to stderr",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)

    try:
        settings = load_settings()
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    if args.check_config:
        print("Configuration is valid.")
        return 0

    try:
        store = load_store(settings.data_dir)
        index = load_policy(settings.data_dir / POLICY_FILE)
        model = build_chat_model(settings)
    except (ValueError, OSError, SourceDataError, PolicyExtractionError) as exc:
        print(f"Startup error: {exc}", file=sys.stderr)
        return 2

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    agent = build_agent(model, store, index, settings.reference_date)
    chat(
        agent,
        Session(),
        write_trace=(lambda line: print(line, file=sys.stderr)) if args.trace else None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
