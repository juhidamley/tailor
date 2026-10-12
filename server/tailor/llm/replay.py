"""Record/replay backend for tests. Replay never falls back to the real CLI.

The repo is public, so fixtures may only hold prompts built from bank/fixture.yaml.
Record mode refuses to start unless it's handed the fixture bank's path, and the file
there must still carry the fixture header.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from tailor import config
from tailor.errors import MissingFixture, RecordGuardError
from tailor.llm.base import LLM, Completion

FIXTURE_HEADER = "# FIXTURE BANK"
FixtureStatus = Literal["new", "changed", "unchanged"]


def normalize_prompt(prompt: str) -> str:
    """Strip `version:` lines and collapse whitespace, so a version bump alone keeps keys."""
    without_version = re.sub(r"(?m)^\s*version:\s*\S+\s*$", "", prompt)
    return re.sub(r"\s+", " ", without_version).strip()


def fixture_key(stage: str, prompt: str) -> str:
    digest = hashlib.sha256(f"{stage}\n{normalize_prompt(prompt)}".encode())
    return digest.hexdigest()[:16]


def assert_fixture_bank(bank_path: Path | None) -> None:
    """Refuse unless `bank_path` is bank/fixture.yaml with its fictional-data header."""
    if bank_path is None:
        raise RecordGuardError("recording needs an explicit --bank (only the fixture is allowed)")
    if bank_path.resolve() != config.FIXTURE_BANK.resolve():
        raise RecordGuardError(
            f"refusing to record fixtures from {bank_path}: the repo is public, so fixtures "
            f"may only come from {config.FIXTURE_BANK.relative_to(config.REPO_ROOT)}"
        )
    first = bank_path.read_text(encoding="utf-8").lstrip().splitlines()[:1]
    if not first or not first[0].startswith(FIXTURE_HEADER):
        raise RecordGuardError(
            f"{bank_path} doesn't start with {FIXTURE_HEADER!r}; refusing to record"
        )


class ReplayLLM(LLM):
    def __init__(
        self,
        mode: Literal["replay", "record"] = "replay",
        fixtures_dir: Path = config.LLM_FIXTURES_DIR,
        *,
        inner: LLM | None = None,
        bank_path: Path | None = None,
    ) -> None:
        super().__init__()
        if mode == "record":
            assert_fixture_bank(bank_path)
            if inner is None:
                raise ValueError("record mode needs the real backend as `inner`")
        self.mode = mode
        self.dir = fixtures_dir
        self.inner = inner
        self.recorded: dict[str, FixtureStatus] = {}

    def path_for(self, key: str) -> Path:
        return self.dir / f"{key}.json"

    async def complete_text(self, prompt: str, *, stage: str) -> Completion:
        key = fixture_key(stage, prompt)
        path = self.path_for(key)
        if self.mode == "replay":
            if not path.exists():
                raise MissingFixture(key, stage, prompt[:200])
            data = json.loads(path.read_text(encoding="utf-8"))
            return Completion(
                text=data["response"],
                model=data.get("model"),
                requested_model=data.get("requested_model"),
            )

        assert self.inner is not None
        done = await self.inner.complete_text(prompt, stage=stage)
        record = {
            "key": key,
            "stage": stage,
            "prompt_head": prompt[:300],
            "prompt_chars": len(prompt),
            "model": done.model,
            "requested_model": done.requested_model,
            "response": done.text,
        }
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
        if old is None:
            self.recorded[key] = "new"
        elif old.get("response") != done.text:
            self.recorded[key] = "changed"
        else:
            self.recorded[key] = "unchanged"
        self.dir.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        return done
