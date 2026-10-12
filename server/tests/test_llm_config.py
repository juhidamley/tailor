"""Per-stage model selection and prompt loading."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import pytest

from tailor import config, prompts
from tailor.llm.base import LLM, Completion


def test_stage_model_defaults() -> None:
    assert config.model_for("jobspec") == "sonnet"
    assert config.model_for("rank") == "sonnet"
    assert config.model_for("ping") == "sonnet"
    for stage in ("rewrite", "repair", "verifier", "cover_letter"):
        assert config.model_for(stage) == "opus"
    assert config.model_for("some-new-stage") == config.DEFAULT_MODEL


def test_user_config_models_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('[models]\nrank = "opus"\n')
    monkeypatch.setenv("TAILOR_CONFIG", str(cfg))
    assert config.model_for("rank") == "opus"
    assert config.model_for("jobspec") == "sonnet"  # untouched stages keep defaults


def test_env_overrides_everything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = tmp_path / "config.toml"
    cfg.write_text('[models]\nrank = "opus"\n')
    monkeypatch.setenv("TAILOR_CONFIG", str(cfg))
    monkeypatch.setenv("TAILOR_LLM_MODEL", "haiku")
    assert {config.model_for(s) for s in ("rank", "rewrite", "ping")} == {"haiku"}


class Echo(LLM):
    async def complete_text(self, prompt: str, *, stage: str) -> Completion:
        return Completion(text='{"reply": "pong", "sum": 5}', requested_model=f"m-{stage}")


def test_call_records_keep_the_model() -> None:
    from tailor.schemas import Ping

    llm = Echo()
    asyncio.run(llm.complete_json("p", Ping, stage="ping"))
    assert llm.calls[0].requested_model == "m-ping"


def test_prompts_are_txt() -> None:
    p = prompts.load_prompt("ping")
    assert p.version >= 1 and p.stage == "ping"
    assert not list(config.PROMPTS_DIR.glob("*.md")) or all(
        f.name in prompts.LOCAL_ONLY for f in config.PROMPTS_DIR.glob("*.md")
    )


def test_local_only_part_is_optional(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(config, "PROMPTS_DIR", tmp_path)
    prompts.load_prompt.cache_clear()
    (tmp_path / "t.txt").write_text(
        '---\nversion: 2\nstage: t\n---\nA {% include "_juhi_voice.md" ignore missing %}B\n'
    )
    try:
        with caplog.at_level(logging.WARNING):
            assert prompts.load_prompt("t").render() == "A B\n"
        assert "_juhi_voice.md not found" in caplog.text
        assert prompts.prompt_versions("t") == {"t": 2}

        (tmp_path / "_juhi_voice.md").write_text("---\nversion: 7\n---\nwarm")
        assert prompts.load_prompt("t").render() == "A warmB\n"
        assert prompts.prompt_versions("t") == {"t": 2, "_juhi_voice": 7}
    finally:
        prompts.load_prompt.cache_clear()


def test_includes_must_be_txt_or_local_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import jinja2

    monkeypatch.setattr(config, "PROMPTS_DIR", tmp_path)
    prompts.load_prompt.cache_clear()
    (tmp_path / "t.txt").write_text('---\nversion: 1\n---\n{% include "notes.md" %}\n')
    try:
        with pytest.raises(jinja2.TemplateNotFound):
            prompts.load_prompt("t").render()
    finally:
        prompts.load_prompt.cache_clear()
