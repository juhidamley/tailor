"""Tests for tool checks. These use fake executables on PATH, never the real tectonic or claude."""

from __future__ import annotations

import asyncio
import stat
from pathlib import Path

import pytest

from tailor import cli
from tailor.checks import TECTONIC_SAFE_ARGS, check_tool, warm_tectonic

FAKE_TECTONIC = """#!/bin/sh
if [ "$1" = "--version" ]; then echo "Tectonic 0.17.0"; exit 0; fi
echo "$@" > "$ARGS_LOG"
outdir=""
while [ $# -gt 0 ]; do
  if [ "$1" = "--outdir" ]; then outdir="$2"; fi
  shift
done
: > "$outdir/check.pdf"
"""

FAKE_CLAUDE = """#!/bin/sh
echo "2.1.296 (Claude Code)"
"""


def _install(bindir: Path, name: str, body: str) -> None:
    exe = bindir / name
    exe.write_text(body)
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR)


@pytest.fixture
def fake_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    monkeypatch.setenv("PATH", str(bindir))
    monkeypatch.setenv("ARGS_LOG", str(tmp_path / "args.log"))
    return bindir


def test_missing_tool_reports_not_found(fake_path: Path) -> None:
    status = asyncio.run(check_tool("tectonic"))
    assert not status.ok
    assert status.error is not None and "not found" in status.error


def test_present_tool_reports_version(fake_path: Path) -> None:
    _install(fake_path, "tectonic", FAKE_TECTONIC)
    status = asyncio.run(check_tool("tectonic"))
    assert status.ok
    assert status.version == "Tectonic 0.17.0"


def test_warm_compiles_untrusted_without_shell_escape(fake_path: Path, tmp_path: Path) -> None:
    _install(fake_path, "tectonic", FAKE_TECTONIC)
    workdir = tmp_path / "work"
    status = asyncio.run(warm_tectonic(workdir))
    assert status.ok, status.error
    args = (tmp_path / "args.log").read_text().split()
    assert "--untrusted" in args
    assert "shell-escape" not in " ".join(args)
    assert "--untrusted" in TECTONIC_SAFE_ARGS


def test_warm_reports_failure_when_no_pdf(fake_path: Path, tmp_path: Path) -> None:
    _install(fake_path, "tectonic", '#!/bin/sh\necho "Tectonic 0.17.0"\nexit 0\n')
    status = asyncio.run(warm_tectonic(tmp_path / "work"))
    assert not status.ok
    assert status.error is not None and "warm-up compile failed" in status.error


def test_cli_check_exit_codes(fake_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert cli.main(["check"]) == 1
    assert "FAIL  tectonic" in capsys.readouterr().out
    _install(fake_path, "tectonic", FAKE_TECTONIC)
    _install(fake_path, "claude", FAKE_CLAUDE)
    assert cli.main(["check"]) == 0
