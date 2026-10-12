"""Headless Claude Code (`claude -p`) as a pure text-in, JSON-out function.

Flag mapping, checked against `claude --help` for Claude Code 2.1.296 (2026-10-12):

  print and exit             -p
  JSON result envelope       --output-format json    answer in `result`; errors set `is_error`
  model choice               --model <alias|id>      per stage: config.model_for(stage)
  no tools at all            --tools ""              help: "" disables all tools
  replace system prompt      --system-prompt <text>
  don't save the session     --no-session-persistence    (print mode only)
  limit agent turns          (none)                  --max-turns doesn't exist in 2.1.296; with
                                                     no tools, print mode answers in one turn
  schema-constrained output  --json-schema <schema>  opt-in. Fills `structured_output` but costs
                                                     an extra turn; by default pydantic validates
  ignore user/project config --setting-sources ""
  no MCP servers             --strict-mcp-config     (no --mcp-config, so none load)
  no skills/slash commands   --disable-slash-commands
  never block on a prompt    --permission-prompts none
  NOT used                   --bare                  reads only ANTHROPIC_API_KEY, so a
                                                     subscription login would fail

Isolation: runs in config.LLM_CWD (an empty dir), prompt on stdin (never argv), minimal
environment, its own process group so a timeout kills everything it spawned.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import signal
from pathlib import Path
from typing import Any

from tailor import config
from tailor.errors import LLMError
from tailor.llm.base import LLM, Completion
from tailor.llm.parse import parse_envelope

SYSTEM_PROMPT = (
    "You are a JSON-producing function inside a resume-tailoring pipeline. "
    "Follow the user's instructions exactly and answer with JSON only."
)

# Environment passed through to the CLI. Everything else (including CLAUDECODE, which
# marks a nested session, and project variables) is dropped.
ENV_ALLOW = frozenset(
    {
        "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "LC_CTYPE", "TMPDIR",
        "TERM", "SSL_CERT_FILE", "NODE_EXTRA_CA_CERTS", "HTTP_PROXY", "HTTPS_PROXY",
        "NO_PROXY", "http_proxy", "https_proxy", "no_proxy",
        "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
        "CLAUDE_CONFIG_DIR", "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
    }
)  # fmt: skip
ENV_ALLOW_PREFIXES = ("AWS_", "CLOUD_ML_", "GOOGLE_", "VERTEX_")

# Set by the test suite: constructing a backend that would run the real `claude` fails.
FORBID_ENV = "TAILOR_FORBID_REAL_CLAUDE"


def minimal_env(source: dict[str, str] | None = None) -> dict[str, str]:
    src = os.environ if source is None else source
    return {k: v for k, v in src.items() if k in ENV_ALLOW or k.startswith(ENV_ALLOW_PREFIXES)}


class ClaudeCLI(LLM):
    def __init__(
        self,
        *,
        model: str | None = None,  # None: per-stage model from config.model_for
        timeout_s: float = config.LLM_TIMEOUT_S,
        concurrency: int = config.LLM_CONCURRENCY,
        cwd: Path = config.LLM_CWD,
        executable: Path | None = None,
        json_schema: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        if executable is None:
            if os.environ.get(FORBID_ENV):
                raise RuntimeError(
                    "tests must not call the real claude CLI; use ReplayLLM "
                    "(or pass a fake `executable`)"
                )
            found = shutil.which("claude")
            if found is None:
                raise LLMError(
                    "setup", "claude CLI not found on PATH; install Claude Code and run `claude`"
                )
            executable = Path(found)
        self.executable = executable
        self.model = model
        self.timeout_s = timeout_s
        self.cwd = cwd
        self.json_schema = json_schema
        self._sem = asyncio.Semaphore(concurrency)

    def model_for(self, stage: str) -> str:
        return self.model or config.model_for(stage)

    def argv(self, model: str) -> list[str]:
        args = [
            str(self.executable),
            "-p",
            "--output-format", "json",
            "--model", model,
            "--tools", "",
            "--system-prompt", SYSTEM_PROMPT,
            "--no-session-persistence",
            "--setting-sources", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--permission-prompts", "none",
        ]  # fmt: skip
        if self.json_schema is not None:
            args += ["--json-schema", json.dumps(self.json_schema)]
        return args

    def _prepare_cwd(self) -> None:
        self.cwd.mkdir(parents=True, exist_ok=True)
        stray = [p.name for p in self.cwd.iterdir() if p.name != ".DS_Store"]
        if stray:
            raise LLMError("setup", f"{self.cwd} must stay empty; found {', '.join(stray[:5])}")

    async def complete_text(self, prompt: str, *, stage: str) -> Completion:
        self._prepare_cwd()
        model = self.model_for(stage)
        async with self._sem:
            proc = await asyncio.create_subprocess_exec(
                *self.argv(model),
                cwd=self.cwd,
                env=minimal_env(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,  # own process group, killed as a unit on timeout
            )
            try:
                out, err = await asyncio.wait_for(
                    proc.communicate(prompt.encode("utf-8")), timeout=self.timeout_s
                )
            except TimeoutError as e:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                await proc.wait()
                raise LLMError(stage, f"timeout after {self.timeout_s:.0f}s") from e
        stdout = out.decode("utf-8", errors="replace")
        if not stdout.strip():
            detail = err.decode("utf-8", errors="replace").strip()[:500] or "no output"
            raise LLMError(stage, f"claude exited {proc.returncode}: {detail}")
        env = parse_envelope(stdout, stage)  # raises on error envelopes
        if proc.returncode != 0:
            raise LLMError(stage, f"claude exited {proc.returncode}", stdout[:500])
        return Completion(
            text=env.text,
            usage=env.usage,
            model=env.model,
            cost_usd=env.cost_usd,
            requested_model=model,
        )
