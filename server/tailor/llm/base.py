"""The LLM interface: `complete_json(prompt, schema) -> validated model`.

Backends implement only `complete_text`. Validation and the single retry live here,
so every backend (CLI, replay, a future SDK backend) behaves the same way.
"""

from __future__ import annotations

import json
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from tailor.errors import LLMError
from tailor.llm.parse import extract_json
from tailor.prompts import load_prompt

T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class Completion:
    text: str
    usage: dict[str, Any] = field(default_factory=dict)
    model: str | None = None  # model id the CLI reports
    cost_usd: float | None = None
    requested_model: str | None = None  # alias we asked for (--model)


@dataclass(frozen=True)
class CallRecord:
    """One model call, for run.json `llm_calls`."""

    stage: str
    attempt: int
    ok: bool
    duration_s: float
    prompt_chars: int
    model: str | None = None
    usage: dict[str, Any] = field(default_factory=dict)
    cost_usd: float | None = None
    error: str | None = None
    requested_model: str | None = None


def _short(err: Exception, limit: int = 800) -> str:
    if isinstance(err, ValidationError):
        msg = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in err.errors()
        )
    else:
        msg = str(err)
    return msg[:limit]


class LLM(ABC):
    def __init__(self) -> None:
        self.calls: list[CallRecord] = []

    @abstractmethod
    async def complete_text(self, prompt: str, *, stage: str) -> Completion:
        """Send `prompt`, return the model's answer text."""

    async def _attempt(self, prompt: str, stage: str, attempt: int) -> Completion:
        start = time.monotonic()
        try:
            done = await self.complete_text(prompt, stage=stage)
        except Exception as e:
            self.calls.append(
                CallRecord(
                    stage, attempt, False, time.monotonic() - start, len(prompt), error=str(e)
                )
            )
            raise
        self.calls.append(
            CallRecord(
                stage,
                attempt,
                True,
                time.monotonic() - start,
                len(prompt),
                done.model,
                done.usage,
                done.cost_usd,
                requested_model=done.requested_model,
            )
        )
        return done

    async def complete_json(self, prompt: str, schema: type[T], *, stage: str) -> T:
        """Validated output. One retry with the validation error attached, then LLMError."""
        done = await self._attempt(prompt, stage, 1)
        try:
            return schema.model_validate(extract_json(done.text))
        except (ValidationError, json.JSONDecodeError) as e:
            retry = prompt.rstrip() + "\n\n" + load_prompt("_retry").render(schema, error=_short(e))
        done = await self._attempt(retry, stage, 2)
        try:
            return schema.model_validate(extract_json(done.text))
        except (ValidationError, json.JSONDecodeError) as e:
            raise LLMError(
                stage, f"invalid output after retry: {_short(e)}", done.text[:500]
            ) from e
