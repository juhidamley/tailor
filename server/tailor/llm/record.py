"""`make record-fixtures`: the only path that writes replay fixtures with the real CLI.

Each scenario builds its prompts from the fixture bank. Later milestones add the
pipeline stages (jobspec, rank, rewrite, ...) on the sample listings.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path

from tailor import config
from tailor.llm.base import LLM
from tailor.llm.ping import ping
from tailor.llm.replay import FixtureStatus, ReplayLLM, assert_fixture_bank


async def _ping(llm: LLM, bank_path: Path) -> None:
    await ping(llm)


SCENARIOS: dict[str, Callable[[LLM, Path], Awaitable[None]]] = {"ping": _ping}


async def record_fixtures(
    bank_path: Path,
    inner: LLM,
    stages: list[str] | None = None,
    fixtures_dir: Path = config.LLM_FIXTURES_DIR,
) -> dict[str, FixtureStatus]:
    """Run scenarios through a recording backend and return {fixture key: status}."""
    assert_fixture_bank(bank_path)  # before any model call
    unknown = sorted(set(stages or []) - set(SCENARIOS))
    if unknown:
        raise ValueError(f"unknown stage(s) {unknown}; known: {sorted(SCENARIOS)}")
    recorder = ReplayLLM("record", fixtures_dir, inner=inner, bank_path=bank_path)
    for name in stages or list(SCENARIOS):
        await SCENARIOS[name](recorder, bank_path)
    return recorder.recorded
