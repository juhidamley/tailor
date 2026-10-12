"""`tailor llm-ping`: one tiny round trip through the full complete_json path."""

from __future__ import annotations

from dataclasses import dataclass

from tailor.llm.base import LLM, CallRecord
from tailor.prompts import load_prompt
from tailor.schemas import Ping

PING_A, PING_B = 2, 3


@dataclass(frozen=True)
class PingResult:
    ok: bool
    answer: Ping
    calls: list[CallRecord]
    prompt_version: int


async def ping(llm: LLM) -> PingResult:
    prompt = load_prompt("ping")
    answer = await llm.complete_json(prompt.render(Ping, a=PING_A, b=PING_B), Ping, stage="ping")
    return PingResult(
        ok=answer.sum == PING_A + PING_B,
        answer=answer,
        calls=list(llm.calls),
        prompt_version=prompt.version,
    )
