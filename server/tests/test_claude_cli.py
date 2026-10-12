"""ClaudeCLI tests against a fake `claude` executable. The real CLI is never run."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import pytest

from tailor.errors import LLMError
from tailor.llm.claude_cli import FORBID_ENV, ClaudeCLI, minimal_env
from tailor.schemas import Ping

# A fake CLI: logs each call (argv, stdin, cwd, env, timing) and replays scripted
# responses from responses.json, one per call.
FAKE = """#!{python}
import json, os, sys, time
here = os.path.dirname(os.path.abspath(__file__))
start = time.time()
prompt = sys.stdin.read()
with open(os.path.join(here, "counter"), "a+") as f:
    f.seek(0); n = len(f.read()); f.write("x")
responses = json.load(open(os.path.join(here, "responses.json")))
spec = responses[min(n, len(responses) - 1)]
with open(os.path.join(here, "pid-%d" % n), "w") as f:
    f.write(str(os.getpid()))
time.sleep(spec.get("sleep", 0))
with open(os.path.join(here, "calls.jsonl"), "a") as f:
    f.write(json.dumps({{"argv": sys.argv[1:], "stdin": prompt, "cwd": os.getcwd(),
        "env": dict(os.environ), "start": start, "end": time.time()}}) + "\\n")
sys.stdout.write(spec.get("stdout", ""))
sys.stderr.write(spec.get("stderr", ""))
sys.exit(spec.get("exit", 0))
"""


def envelope(result: str, **extra: Any) -> str:
    env = {"type": "result", "subtype": "success", "is_error": False, "result": result}
    env.update(
        usage={"input_tokens": 10, "output_tokens": 5},
        modelUsage={"claude-fake": {}},
        total_cost_usd=0.0,
    )
    env.update(extra)
    return json.dumps(env)


class Fake:
    def __init__(self, root: Path) -> None:
        self.dir = root / "fakebin"
        self.dir.mkdir()
        self.exe = self.dir / "claude"
        self.exe.write_text(FAKE.format(python=sys.executable))
        self.exe.chmod(0o755)
        self.cwd = root / "llm-cwd"

    def respond(self, *specs: dict[str, Any]) -> None:
        (self.dir / "responses.json").write_text(json.dumps(list(specs)))

    def calls(self) -> list[dict[str, Any]]:
        path = self.dir / "calls.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]

    def cli(self, **kw: Any) -> ClaudeCLI:
        return ClaudeCLI(executable=self.exe, cwd=self.cwd, model="fake-model", **kw)


@pytest.fixture
def fake(tmp_path: Path) -> Fake:
    return Fake(tmp_path)


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_session_guard_blocks_real_cli() -> None:
    assert os.environ.get(FORBID_ENV) == "1"
    with pytest.raises(RuntimeError, match="must not call the real claude CLI"):
        ClaudeCLI()


def test_flags_stdin_cwd(fake: Fake) -> None:
    fake.respond({"stdout": envelope('{"reply": "pong", "sum": 5}')})
    out = run(fake.cli().complete_json("PROMPT BODY", Ping, stage="ping"))
    assert out == Ping(reply="pong", sum=5)
    (call,) = fake.calls()
    argv = call["argv"]
    assert argv[0] == "-p"
    for flag, value in [
        ("--output-format", "json"),
        ("--model", "fake-model"),
        ("--tools", ""),
        ("--setting-sources", ""),
        ("--permission-prompts", "none"),
    ]:
        assert argv[argv.index(flag) + 1] == value
    for flag in ("--no-session-persistence", "--strict-mcp-config", "--disable-slash-commands"):
        assert flag in argv
    assert "--system-prompt" in argv
    assert "--bare" not in argv and "--json-schema" not in argv
    assert call["stdin"] == "PROMPT BODY"  # prompt via stdin...
    assert "PROMPT BODY" not in " ".join(argv)  # ...never argv
    assert Path(call["cwd"]).resolve() == fake.cwd.resolve()


def test_minimal_env(fake: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("TAILOR_SECRET_PROJECT_VAR", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    fake.respond({"stdout": envelope('{"reply": "pong", "sum": 5}')})
    run(fake.cli().complete_text("p", stage="ping"))
    env = fake.calls()[0]["env"]
    assert "CLAUDECODE" not in env
    assert "TAILOR_SECRET_PROJECT_VAR" not in env
    assert FORBID_ENV not in env
    assert env["ANTHROPIC_API_KEY"] == "sk-test"
    assert "PATH" in env


def test_minimal_env_allowlist() -> None:
    src = {"PATH": "/bin", "AWS_REGION": "x", "CLAUDE_CODE_ENTRYPOINT": "cli", "VIRTUAL_ENV": "v"}
    assert minimal_env(src) == {"PATH": "/bin", "AWS_REGION": "x"}


def test_retry_once_with_validation_error(fake: Fake) -> None:
    fake.respond(
        {"stdout": envelope('{"reply": "nope", "sum": 5}')},
        {"stdout": envelope('```json\n{"reply": "pong", "sum": 5}\n```')},
    )
    cli = fake.cli()
    assert run(cli.complete_json("ORIGINAL", Ping, stage="ping")).sum == 5
    _, second = fake.calls()
    assert second["stdin"].startswith("ORIGINAL")
    assert "previous answer was rejected" in second["stdin"]
    assert "reply" in second["stdin"]  # the validation error names the field
    assert [(c.attempt, c.ok) for c in cli.calls] == [(1, True), (2, True)]


def test_second_failure_raises_typed_error(fake: Fake) -> None:
    fake.respond({"stdout": envelope("no json at all")})
    with pytest.raises(LLMError) as exc:
        run(fake.cli().complete_json("p", Ping, stage="ping"))
    assert exc.value.stage == "ping"
    assert "invalid output after retry" in exc.value.detail
    assert len(fake.calls()) == 2


def test_error_envelope_is_not_retried(fake: Fake) -> None:
    fake.respond({"stdout": envelope("Usage limit reached", is_error=True), "exit": 1})
    with pytest.raises(LLMError, match="Usage limit reached"):
        run(fake.cli().complete_json("p", Ping, stage="rank"))
    assert len(fake.calls()) == 1


def test_crash_without_output(fake: Fake) -> None:
    fake.respond({"stderr": "segfault-ish", "exit": 3})
    with pytest.raises(LLMError, match="exited 3: segfault-ish"):
        run(fake.cli().complete_text("p", stage="rank"))


def test_timeout_kills_process(fake: Fake) -> None:
    fake.respond({"sleep": 30, "stdout": envelope("{}")})
    t0 = time.monotonic()
    with pytest.raises(LLMError, match="timeout"):
        run(fake.cli(timeout_s=0.5).complete_text("p", stage="rank"))
    assert time.monotonic() - t0 < 5
    pid = int((fake.dir / "pid-0").read_text())
    with pytest.raises(ProcessLookupError):
        os.kill(pid, 0)


def test_concurrency_limit(fake: Fake) -> None:
    fake.respond({"sleep": 0.4, "stdout": envelope('{"reply": "pong", "sum": 5}')})
    cli = fake.cli(concurrency=2)

    async def many() -> None:
        await asyncio.gather(*(cli.complete_text(f"p{i}", stage="s") for i in range(5)))

    run(many())
    spans = [(c["start"], c["end"]) for c in fake.calls()]
    assert len(spans) == 5
    peak = max(sum(1 for s, e in spans if s <= t < e) for t, _ in spans)
    assert peak <= 2


def test_cwd_must_stay_empty(fake: Fake) -> None:
    fake.cwd.mkdir()
    (fake.cwd / "CLAUDE.md").write_text("leak")
    fake.respond({"stdout": envelope("{}")})
    with pytest.raises(LLMError, match="must stay empty"):
        run(fake.cli().complete_text("p", stage="s"))
    assert fake.calls() == []


def test_json_schema_opt_in(fake: Fake) -> None:
    fake.respond({"stdout": envelope("", structured_output={"reply": "pong", "sum": 5})})
    cli = fake.cli(json_schema=Ping.model_json_schema())
    assert run(cli.complete_json("p", Ping, stage="ping")).sum == 5
    argv = fake.calls()[0]["argv"]
    assert json.loads(argv[argv.index("--json-schema") + 1])["title"] == "Ping"
