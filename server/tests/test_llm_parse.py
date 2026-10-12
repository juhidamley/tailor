"""Envelope and JSON extraction tests (pure functions)."""

from __future__ import annotations

import json

import pytest

from tailor import config
from tailor.errors import LLMError
from tailor.llm.parse import extract_json, parse_envelope

FIXTURES = config.LLM_FIXTURES_DIR


def test_real_envelope_sample() -> None:
    env = parse_envelope((FIXTURES / "envelope_sample.json").read_text(), "ping")
    assert json.loads(env.text) == {"reply": "pong", "sum": 4}
    assert env.model and env.model.startswith("claude-")
    assert env.usage["input_tokens"] > 0
    assert env.cost_usd is not None


def test_real_error_envelope_raises_with_cli_message() -> None:
    with pytest.raises(LLMError) as exc:
        parse_envelope((FIXTURES / "envelope_error_sample.json").read_text(), "ping")
    assert "issue with the selected model" in exc.value.detail
    assert exc.value.stage == "ping"


def test_auth_error_gets_friendly_message() -> None:
    stdout = json.dumps({"type": "result", "is_error": True, "result": "Not logged in · /login"})
    with pytest.raises(LLMError) as exc:
        parse_envelope(stdout, "rank")
    assert "isn't signed in" in exc.value.detail


def test_error_subtype_raises() -> None:
    stdout = json.dumps({"type": "result", "subtype": "error_max_turns", "result": None})
    with pytest.raises(LLMError, match="error_max_turns"):
        parse_envelope(stdout, "rank")


def test_structured_output_preferred() -> None:
    stdout = json.dumps({"result": "ignored", "structured_output": {"a": 1}, "is_error": False})
    assert json.loads(parse_envelope(stdout, "s").text) == {"a": 1}


@pytest.mark.parametrize("stdout", ["", "not json", "[1, 2]", json.dumps({"is_error": False})])
def test_bad_envelopes(stdout: str) -> None:
    with pytest.raises(LLMError):
        parse_envelope(stdout, "s")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('{"a": 1}', {"a": 1}),
        ('```json\n{"a": 1}\n```', {"a": 1}),
        ("```\n[1, 2]\n```", [1, 2]),
        ('Sure! Here it is:\n{"a": {"b": [1, 2]}}\nHope that helps.', {"a": {"b": [1, 2]}}),
        ('{"text": "braces } and { inside", "n": 2}', {"text": "braces } and { inside", "n": 2}),
        ('{"q": "escaped \\" quote }"}', {"q": 'escaped " quote }'}),
        ('prefix {not json} then {"ok": true}', {"ok": True}),
        ('  [{"id": "x"}]  ', [{"id": "x"}]),
    ],
)
def test_extract_json(text: str, expected: object) -> None:
    assert extract_json(text) == expected


@pytest.mark.parametrize("text", ["", "no json here", '{"a": 1', "{'single': 'quotes'}"])
def test_extract_json_failures(text: str) -> None:
    with pytest.raises(json.JSONDecodeError):
        extract_json(text)
