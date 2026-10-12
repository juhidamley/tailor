"""Compile tests: escaping round-trips through Tectonic, and the full-bank render.

These run the real Tectonic (never the claude CLI) and are skipped if it's missing.
"""

from __future__ import annotations

import asyncio
import contextlib
from pathlib import Path

import pytest
from conftest import FIXTURE, requires_tectonic
from pypdf import PdfReader

from tailor import cli
from tailor.bank import load_bank
from tailor.compile import ats_problems, compile_tex, page_count, pdf_text, squash
from tailor.errors import CompileError
from tailor.render import (
    Item,
    Link,
    ResumeView,
    Section,
    full_bank_view,
    render_resume,
    url_for,
)

pytestmark = requires_tectonic

ROUND_TRIP = [
    "C#",
    "R&D",
    "50%",
    "$2M",
    "snake_case",
    "~3x",
    "a^2",
    "{json}",
    "back\\slash",
    "naïve",
    "“quoted”",
    "a--b",
]


def _one_bullet_view(text: str) -> ResumeView:
    section = Section(key="awards", title="Awards", rows=[Item(text=text)])
    return ResumeView(name="Round Trip", contact=[], sections=[section])


def _compile(tmp_path: Path, tex_source: str) -> Path:
    tex = tmp_path / "resume.tex"
    tex.write_text(tex_source, encoding="utf-8")
    return asyncio.run(compile_tex(tex))


@pytest.mark.parametrize("text", ROUND_TRIP)
def test_escape_round_trip(tmp_path: Path, text: str) -> None:
    pdf = _compile(tmp_path, render_resume(_one_bullet_view(f"before {text} after")))
    assert f"before {text} after" in squash(pdf_text(pdf))


def test_fixture_render_all(tmp_path: Path) -> None:
    bank = load_bank(FIXTURE)
    view = full_bank_view(bank, include_proposed=True)
    pdf = _compile(tmp_path, render_resume(view))
    assert page_count(pdf) >= 1
    headings = [s.title for s in view.sections]
    assert headings == [
        "Education", "Experience", "Projects", "Leadership", "Technical Skills", "Awards",
        "Interests",
    ]  # fmt: skip
    must = [bank.contact.name, bank.contact.email, "github.com/pat-placeholder-fake"]
    assert ats_problems(pdf, headings, must) == []
    text = squash(pdf_text(pdf)).lower()
    name, email = bank.contact.name.lower(), bank.contact.email.lower()
    assert text.index(name) < text.index(email) < text.index("education")


def test_compile_error_reports_first_error(tmp_path: Path) -> None:
    src = "\\documentclass{article}\\begin{document}\\undefinedmacro\\end{document}\n"
    with pytest.raises(CompileError) as exc:
        _compile(tmp_path, src)
    assert "Undefined control sequence" in exc.value.first_error_line


def test_shell_escape_is_blocked(tmp_path: Path) -> None:
    marker = tmp_path / "pwned"
    src = (
        "\\documentclass{article}\\begin{document}"
        f"\\immediate\\write18{{touch {marker}}}ok\\end{{document}}\n"
    )
    with contextlib.suppress(CompileError):
        _compile(tmp_path, src)
    assert not marker.exists()


def test_cli_render_all(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    args = ["render", "--all", "--bank", str(FIXTURE), "--out", str(tmp_path)]
    assert cli.main(args) == 0
    assert cli.main([*args, "--include-proposed"]) == 0
    out = capsys.readouterr().out
    assert "ATS warning" not in out
    assert (tmp_path / "fixture-approved.pdf").exists()
    assert (tmp_path / "fixture-all-items.pdf").exists()


def test_cli_render_all_with_profile(tmp_path: Path) -> None:
    base = ["render", "--all", "--bank", str(FIXTURE), "--out", str(tmp_path)]
    assert cli.main([*base, "--profile", "research_quant"]) == 0
    text = squash(pdf_text(tmp_path / "fixture-approved.pdf"))
    # The long fixture heading wraps, so the dates land mid-line in the text layer.
    assert "Supervised by Prof. Bob" in text and "Notreal" in text
    assert cli.main([*base, "--profile", "nope"]) == 1


def test_appendix_compiles_and_follows_the_resume(tmp_path: Path) -> None:
    view = full_bank_view(load_bank(FIXTURE), include_proposed=True)
    pdf = _compile(tmp_path, render_resume(view))
    text = squash(pdf_text(pdf))
    assert text.index("Interests") < text.index("Review appendix")
    assert "exp-acme-widgets-c2 [proposed]: The previous batch job" in text


@pytest.mark.parametrize(
    ("link", "target"),
    [
        ("x.example.com/a_b", "https://x.example.com/a_b"),
        ("https://x.example.com/p#frag", "https://x.example.com/p#frag"),
        ("https://x.example.com/~me", "https://x.example.com/%7Eme"),
        ("https://x.example.com/q?a=1&b=50%25", "https://x.example.com/q?a=1&b=50%25"),
        ("https://x.example.com/a--b", "https://x.example.com/a-%2Db"),
        ("mailto:pat.p@example.com", "mailto:pat.p@example.com"),
    ],
)
def test_link_targets_survive(tmp_path: Path, link: str, target: str) -> None:
    view = ResumeView(name="L", contact=[Link(text=link, url=url_for(link))], sections=[])
    pdf = _compile(tmp_path, render_resume(view))
    (annot,) = PdfReader(pdf).pages[0]["/Annots"]
    assert annot.get_object()["/A"]["/URI"] == target


def test_overfull_lines_reported(tmp_path: Path) -> None:
    from tailor.compile import overfull_lines

    src = (
        "\\documentclass{article}\\begin{document}"
        "\\hbox to 2in{\\hbox{" + "W" * 80 + "}}\\end{document}\n"
    )
    pdf = _compile(tmp_path, src)
    assert overfull_lines(pdf.with_suffix(".log"))


def test_fixture_render_has_no_overfull_lines(tmp_path: Path) -> None:
    from tailor.compile import overfull_lines

    for supervisor in (False, True):
        view = full_bank_view(load_bank(FIXTURE), show_supervisor=supervisor)
        pdf = _compile(tmp_path, render_resume(view))
        assert overfull_lines(pdf.with_suffix(".log")) == [], supervisor
