"""Environment checks for external tools (Tectonic, the claude CLI).

Checked against Tectonic 0.17.0 (`tectonic --help`). We use the V1 interface
(`tectonic [OPTIONS] <INPUT>`), which 0.17.0 still treats as the default.
Relevant flags:
  --untrusted     disable all known-insecure features. This also blocks
                  `-Z shell-escape`, so shell-escape can't be turned on by accident
                  (invariant 7).
  -o, --outdir    output directory
  --keep-logs     keep the .log file for debugging failed compiles
  -C, --only-cached  offline mode, using only the local resource cache
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path

TECTONIC_SAFE_ARGS: tuple[str, ...] = ("--untrusted",)

_WARM_DOC = r"""\documentclass[letterpaper,11pt]{article}
\begin{document}
resume-tailor tectonic check
\end{document}
"""


@dataclass(frozen=True)
class ToolStatus:
    name: str
    path: str | None
    version: str | None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.path is not None and self.error is None


async def _run(*args: str, cwd: Path | None = None, timeout: float = 30.0) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *args,
        cwd=cwd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return -1, f"timed out after {timeout:.0f}s"
    return proc.returncode or 0, out.decode(errors="replace").strip()


async def check_tool(name: str) -> ToolStatus:
    """Find `name` on PATH and read its `--version`."""
    path = shutil.which(name)
    if path is None:
        return ToolStatus(name=name, path=None, version=None, error=f"{name} not found on PATH")
    code, out = await _run(path, "--version")
    if code != 0:
        return ToolStatus(name=name, path=path, version=None, error=out or f"exit code {code}")
    return ToolStatus(name=name, path=path, version=out.splitlines()[0] if out else None)


async def warm_tectonic(workdir: Path, timeout: float = 600.0) -> ToolStatus:
    """Compile a trivial document so Tectonic downloads its resource bundle.

    The first compile fetches packages over the network and can take minutes.
    Later compiles use the cache and work offline.
    """
    status = await check_tool("tectonic")
    if not status.ok or status.path is None:
        return status
    workdir.mkdir(parents=True, exist_ok=True)
    tex = workdir / "check.tex"
    tex.write_text(_WARM_DOC, encoding="utf-8")
    code, out = await _run(
        status.path,
        *TECTONIC_SAFE_ARGS,
        "--outdir",
        str(workdir),
        "--keep-logs",
        str(tex),
        cwd=workdir,
        timeout=timeout,
    )
    if code != 0 or not (workdir / "check.pdf").exists():
        tail = "\n".join(out.splitlines()[-10:])
        error = f"warm-up compile failed:\n{tail}"
        return ToolStatus(status.name, status.path, status.version, error)
    return status
