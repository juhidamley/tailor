"""Pure parsing: the `claude --output-format json` envelope, and JSON inside model text."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from tailor.errors import LLMError

_AUTH_HINTS = re.compile(
    r"not logged in|log ?in|/login|invalid api key|authenticat|oauth token|expired", re.I
)
_FENCE = re.compile(r"```(?:json|JSON)?\s*\n(.*?)\n?```", re.S)


@dataclass(frozen=True)
class Envelope:
    text: str  # the model's answer (structured_output re-serialized when present)
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None
    cost_usd: float | None = None
    num_turns: int | None = None


def parse_envelope(stdout: str, stage: str) -> Envelope:
    """Parse the CLI's JSON envelope. Error envelopes raise LLMError with the CLI's message.

    Checked against claude 2.1.296: errors set `is_error: true` even when
    `subtype` is "success", and put the message in `result`.
    """
    try:
        env = json.loads(stdout)
    except json.JSONDecodeError as e:
        raise LLMError(stage, "claude printed no JSON envelope", stdout[:500]) from e
    if not isinstance(env, dict):
        raise LLMError(stage, "claude envelope is not an object", stdout[:500])
    result = env.get("result")
    if env.get("is_error") or env.get("subtype") not in (None, "success"):
        message = str(result or env.get("subtype") or "unknown error")
        if _AUTH_HINTS.search(message):
            message = (
                "Claude Code isn't signed in (or the login expired); "
                f"run `claude` once in a terminal. CLI said: {message}"
            )
        raise LLMError(stage, message, stdout[:500])
    structured = env.get("structured_output")
    if structured is not None:
        text = json.dumps(structured)
    elif isinstance(result, str):
        text = result
    else:
        raise LLMError(stage, "claude envelope has no `result` text", stdout[:500])
    model_usage = env.get("modelUsage")
    model = next(iter(model_usage), None) if isinstance(model_usage, dict) else None
    usage = env.get("usage")
    cost = env.get("total_cost_usd")
    turns = env.get("num_turns")
    return Envelope(
        text=text,
        usage=usage if isinstance(usage, dict) else {},
        model=model,
        cost_usd=float(cost) if isinstance(cost, int | float) else None,
        num_turns=turns if isinstance(turns, int) else None,
    )


def _balanced_span(text: str, start: int) -> str | None:
    """The bracketed value starting at `start`, honoring JSON strings and escapes."""
    stack: list[str] = []
    in_string = escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
        elif ch == '"':
            in_string = True
        elif ch in "{[":
            stack.append("}" if ch == "{" else "]")
        elif ch in "}]":
            if not stack or ch != stack.pop():
                return None
            if not stack:
                return text[start : i + 1]
    return None


def extract_json(text: str) -> Any:
    """JSON from model text: a fenced block, else the first balanced object or array.

    Raises json.JSONDecodeError when nothing parses.
    """
    stripped = text.strip()
    fence = _FENCE.search(stripped)
    if fence:
        return json.loads(fence.group(1))
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    for m in re.finditer(r"[{\[]", stripped):
        span = _balanced_span(stripped, m.start())
        if span is None:
            continue
        try:
            return json.loads(span)
        except json.JSONDecodeError:
            continue
    raise json.JSONDecodeError("no JSON object or array found", stripped, 0)
