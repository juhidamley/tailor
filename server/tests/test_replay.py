"""Record/replay tests, including the public-repo recording guard."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from conftest import FIXTURE

from tailor import cli, config
from tailor.errors import MissingFixture, RecordGuardError
from tailor.llm.base import LLM, Completion
from tailor.llm.ping import ping
from tailor.llm.record import record_fixtures
from tailor.llm.replay import ReplayLLM, assert_fixture_bank, fixture_key, normalize_prompt
from tailor.schemas import Ping


class Scripted(LLM):
    """Stands in for the real backend when testing record mode."""

    def __init__(self, *answers: str) -> None:
        super().__init__()
        self.answers = list(answers)
        self.prompts: list[str] = []

    async def complete_text(self, prompt: str, *, stage: str) -> Completion:
        self.prompts.append(prompt)
        return Completion(text=self.answers.pop(0), model="claude-scripted")


def test_key_ignores_whitespace_and_version_lines() -> None:
    a = "version: 3\nRewrite   these\n\nbullets"
    b = "version: 4\nRewrite these bullets\n"
    assert normalize_prompt(a) == normalize_prompt(b) == "Rewrite these bullets"
    assert fixture_key("rewrite", a) == fixture_key("rewrite", b)
    assert fixture_key("rewrite", a) != fixture_key("verifier", a)
    assert fixture_key("rewrite", a) != fixture_key("rewrite", a + " changed")


def test_replay_miss_raises_and_never_falls_back(tmp_path: Path) -> None:
    llm = ReplayLLM("replay", tmp_path, inner=Scripted("should not be used"))
    with pytest.raises(MissingFixture) as exc:
        asyncio.run(llm.complete_text("unknown prompt", stage="rank"))
    assert exc.value.stage == "rank"
    assert isinstance(llm.inner, Scripted) and llm.inner.prompts == []


def test_record_then_replay(tmp_path: Path) -> None:
    inner = Scripted('{"reply": "pong", "sum": 5}')
    recorder = ReplayLLM("record", tmp_path, inner=inner, bank_path=FIXTURE)
    asyncio.run(recorder.complete_json("PROMPT", Ping, stage="ping"))
    key = fixture_key("ping", "PROMPT")
    assert recorder.recorded == {key: "new"}
    saved = json.loads((tmp_path / f"{key}.json").read_text())
    assert saved["stage"] == "ping" and saved["prompt_head"] == "PROMPT"

    replay = ReplayLLM("replay", tmp_path)
    assert asyncio.run(replay.complete_json("PROMPT", Ping, stage="ping")).sum == 5


def test_record_reports_changed_and_unchanged(tmp_path: Path) -> None:
    for answer, status in [("A", "new"), ("A", "unchanged"), ("B", "changed")]:
        rec = ReplayLLM("record", tmp_path, inner=Scripted(answer), bank_path=FIXTURE)
        asyncio.run(rec.complete_text("P", stage="s"))
        assert rec.recorded == {fixture_key("s", "P"): status}


def test_record_refuses_master_bank(tmp_path: Path) -> None:
    with pytest.raises(RecordGuardError, match="repo is public"):
        ReplayLLM("record", tmp_path, inner=Scripted(), bank_path=config.MASTER_BANK)
    with pytest.raises(RecordGuardError):
        ReplayLLM("record", tmp_path, inner=Scripted(), bank_path=None)


def test_record_refuses_a_copy_of_the_fixture_elsewhere(tmp_path: Path) -> None:
    copy = tmp_path / "fixture.yaml"
    shutil.copy(FIXTURE, copy)
    with pytest.raises(RecordGuardError):
        assert_fixture_bank(copy)


def test_record_refuses_fixture_without_header(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_fixture = tmp_path / "fixture.yaml"
    fake_fixture.write_text("contact:\n  name: Real Person\n")
    monkeypatch.setattr(config, "FIXTURE_BANK", fake_fixture)
    with pytest.raises(RecordGuardError, match="FIXTURE BANK"):
        assert_fixture_bank(fake_fixture)


def test_record_fixtures_guard_runs_before_any_call(tmp_path: Path) -> None:
    inner = Scripted()
    with pytest.raises(RecordGuardError):
        asyncio.run(record_fixtures(config.MASTER_BANK, inner, fixtures_dir=tmp_path))
    assert inner.prompts == []


def test_record_fixtures_ping_scenario(tmp_path: Path) -> None:
    inner = Scripted('{"reply": "pong", "sum": 5}')
    recorded = asyncio.run(record_fixtures(FIXTURE, inner, ["ping"], fixtures_dir=tmp_path))
    assert list(recorded.values()) == ["new"]


def test_cli_record_fixtures_refuses_master(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli.main(["llm", "record-fixtures", "--bank", str(config.MASTER_BANK)])
    assert rc == 1
    assert "repo is public" in capsys.readouterr().out
    assert cli.main(["llm", "record-fixtures"]) == 1  # no --bank: refused too


def test_ping_replays_from_committed_fixture() -> None:
    result = asyncio.run(ping(ReplayLLM("replay")))
    assert result.ok and result.answer.reply == "pong"


def test_cli_llm_ping_replay(capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["llm-ping", "--replay"]) == 0
    assert "llm-ping OK" in capsys.readouterr().out
