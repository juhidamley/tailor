"""Tectonic wrapper (always --untrusted, never shell-escape), page count, and text checks."""

from __future__ import annotations

import asyncio
import re
import shutil
import unicodedata
from pathlib import Path

import pdfplumber
from pypdf import PdfReader

from tailor.checks import TECTONIC_SAFE_ARGS
from tailor.errors import CompileError

COMPILE_TIMEOUT_S = 300.0


def _first_error(output: str, log: Path) -> CompileError:
    """Find the first `!` line in the log (later ones are usually a cascade)."""
    lines = log.read_text(errors="replace").splitlines() if log.exists() else []
    for i, line in enumerate(lines):
        if line.startswith("!"):
            return CompileError(line, lines[i : i + 6])
    out_lines = output.splitlines()
    for i, line in enumerate(out_lines):
        if line.startswith("error:"):
            return CompileError(line, out_lines[i : i + 6])
    return CompileError("tectonic failed without an error line", out_lines[-10:])


async def compile_tex(tex: Path, outdir: Path | None = None) -> Path:
    """Compile `tex` to a PDF next to it (or in `outdir`) and return the PDF path."""
    exe = shutil.which("tectonic")
    if exe is None:
        raise CompileError("tectonic not found on PATH (brew install tectonic)", [])
    outdir = outdir or tex.parent
    outdir.mkdir(parents=True, exist_ok=True)
    proc = await asyncio.create_subprocess_exec(
        exe,
        *TECTONIC_SAFE_ARGS,
        "--keep-logs",
        "--outdir",
        str(outdir),
        str(tex),
        cwd=outdir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        raw, _ = await asyncio.wait_for(proc.communicate(), timeout=COMPILE_TIMEOUT_S)
    except TimeoutError as e:
        proc.kill()
        await proc.wait()
        raise CompileError(f"tectonic timed out after {COMPILE_TIMEOUT_S:.0f}s", []) from e
    pdf = outdir / tex.with_suffix(".pdf").name
    if proc.returncode != 0 or not pdf.exists():
        raise _first_error(raw.decode(errors="replace"), outdir / tex.with_suffix(".log").name)
    return pdf


def overfull_lines(log: Path, min_pt: float = 1.0) -> list[str]:
    """Overfull hbox warnings above `min_pt`: text running into the margin or the dates."""
    if not log.exists():
        return []
    pattern = re.compile(r"^Overfull \\hbox \(([\d.]+)pt too wide\).*$", re.M)
    text = log.read_text(errors="replace")
    return [m.group(0) for m in pattern.finditer(text) if float(m.group(1)) >= min_pt]


def page_count(pdf: Path) -> int:
    return len(PdfReader(pdf).pages)


def pdf_text(pdf: Path) -> str:
    """Extracted text layer, NFKC-normalized (folds ligature glyphs like `ﬁ`)."""
    with pdfplumber.open(pdf) as doc:
        text = "\n".join(page.extract_text() or "" for page in doc.pages)
    return unicodedata.normalize("NFKC", text)


def squash(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def ats_problems(pdf: Path, headings: list[str], must_contain: list[str]) -> list[str]:
    """Checks an ATS parser cares about. Returns a list of problems (empty = fine)."""
    text = pdf_text(pdf)
    flat = squash(text)
    problems = []
    if "(cid:" in text:
        problems.append("text layer has (cid:) sequences: a font encoding problem")
    for s in must_contain:
        if squash(s) not in flat:
            problems.append(f"{s!r} missing from the text layer")
    positions = []
    lines = [squash(line) for line in text.splitlines()]
    for h in headings:
        hits = [i for i, line in enumerate(lines) if line.upper() == h.upper()]
        if len(hits) != 1:
            problems.append(f"heading {h!r} appears {len(hits)} times as its own line")
        else:
            positions.append(hits[0])
    if positions != sorted(positions):
        problems.append("section headings are out of order in the text layer")
    return problems
