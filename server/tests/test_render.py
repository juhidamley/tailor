"""Escaping, template hygiene, and view-building tests (no compile)."""

from __future__ import annotations

import re

import pytest

from tailor import config
from tailor.bank import load_bank, load_profiles
from tailor.render import (
    RAW_ALLOWLIST,
    SAFE_MACROS,
    escape_tex,
    format_dates,
    full_bank_view,
    render_resume,
)

ESCAPES = [
    ("\\", r"\textbackslash{}"),
    ("&", r"\&"),
    ("%", r"\%"),
    ("$", r"\$"),
    ("#", r"\#"),
    ("_", r"\_"),
    ("{", r"\{"),
    ("}", r"\}"),
    ("~", r"\textasciitilde{}"),
    ("^", r"\textasciicircum{}"),
]


@pytest.mark.parametrize(("raw", "escaped"), ESCAPES)
def test_escape_table(raw: str, escaped: str) -> None:
    assert escape_tex(raw) == escaped


def test_escape_is_single_pass() -> None:
    # The braces produced for a backslash must not be escaped again.
    assert escape_tex("\\{") == r"\textbackslash{}\{"
    assert escape_tex(r"\textbf{x}") == r"\textbackslash{}textbf\{x\}"


def test_escape_leaves_unicode_and_plain_text() -> None:
    s = "naïve “quoted” — en–dash café"
    assert escape_tex(s) == s


def test_escape_breaks_dash_ligatures() -> None:
    assert escape_tex("a--b---c") == "a-{}-b-{}-{}-c"
    assert escape_tex("well-known") == "well-known"


def test_every_template_var_is_escaped() -> None:
    """A `\\VAR{}` must use |tex, be a RAW_ALLOWLIST number, or call a SAFE_MACRO."""
    for template in config.TEMPLATES_DIR.glob("*.j2"):
        for expr in re.findall(r"\\VAR\{([^}]*)\}", template.read_text(encoding="utf-8")):
            expr = expr.strip()
            ok = (
                expr.endswith("|tex")
                or expr in RAW_ALLOWLIST
                or (re.match(r"^(\w+)\(", expr) is not None and expr.split("(")[0] in SAFE_MACROS)
            )
            assert ok, f"{template.name}: unescaped \\VAR{{{expr}}}"


def test_format_dates() -> None:
    bank = load_bank(config.FIXTURE_BANK)
    assert format_dates(bank.experiences[0].dates) == "Jun 2025 – Present"
    assert format_dates(None) == ""


def test_approved_view_excludes_proposed() -> None:
    bank = load_bank(config.FIXTURE_BANK)
    texts = _all_texts(full_bank_view(bank))
    assert "Built a Python ingest service" in texts
    assert "GPA: 3.99/4.00" not in texts  # proposed detail
    assert "Made-Up Research Fellowship" not in texts  # proposed award
    assert "Made-up researcher" not in texts  # proposed tagline
    assert "Fortran" not in texts  # skill without evidence
    assert "C#" not in texts  # skill backed only by a proposed bullet


def test_include_proposed_view_has_everything_printable() -> None:
    bank = load_bank(config.FIXTURE_BANK)
    view = full_bank_view(bank, include_proposed=True)
    texts = _all_texts(view)
    for s in ["GPA: 3.99/4.00", "Made-Up Research Fellowship", "Fortran", "C#", "#imaginary"]:
        assert s in texts
    assert view.review_mode


def test_never_printed_fields_stay_out() -> None:
    bank = load_bank(config.FIXTURE_BANK)
    tex = render_resume(full_bank_view(bank))
    for hidden in ["Dr. Ada Fakename", "Team of 4", "printer at a fictional library", "fixture"]:
        assert hidden not in tex  # supervisor, context, stories, source
    assert "exp-acme-widgets" not in tex  # ids are never rendered
    assert "Review appendix" not in tex
    assert "PL 101" not in tex  # `course` details are evidence only


def test_review_appendix_only_with_include_proposed() -> None:
    bank = load_bank(config.FIXTURE_BANK)
    view = full_bank_view(bank, include_proposed=True)
    titles = [g.title for g in view.appendix]
    assert titles == [
        "Education: Example State University",
        "Experience: Acme Imaginary Widgets Inc.",
        "Experience: Fictional Research Lab, Example State University",
        "Projects: Widget Tracker",
        "Leadership: Pretend Coding Club",
        "Stories",
    ]
    acme = view.appendix[1].rows
    assert [(r.id, r.status) for r in acme] == [
        ("exp-acme-widgets-c1", "approved"),
        ("exp-acme-widgets-c2", "proposed"),
    ]
    stories = view.appendix[-1].rows
    assert stories[1].note == "use: cover_letter, awards"
    tex = render_resume(view)
    assert "Review appendix" in tex
    assert r"\texttt{exp-acme-widgets-c1} [approved]" in tex
    assert "fixture" not in tex  # source is still not rendered


def test_title_line_layout() -> None:
    bank = load_bank(config.FIXTURE_BANK)
    entries = full_bank_view(bank).sections[1].entries
    acme, lab = entries[0], entries[1]
    # title_line on top; italic line reads "role · org".
    assert acme.title == "Platform Team Intern"
    assert acme.subtitle == "Software Engineering Intern · Acme Imaginary Widgets Inc."
    assert acme.title_note == ""
    # No title_line: org on top, role below.
    assert lab.title == "Fictional Research Lab, Example State University"
    assert lab.subtitle == "Undergraduate Research Assistant"


def test_supervisor_shown_only_when_asked() -> None:
    bank = load_bank(config.FIXTURE_BANK)
    off = full_bank_view(bank).sections[1].entries
    assert all("Supervised" not in e.subtitle + e.title_note for e in off)
    acme, lab = full_bank_view(bank, show_supervisor=True).sections[1].entries
    assert acme.subtitle.endswith("· Acme Imaginary Widgets Inc. · Supervised by Dr. Ada Fakename")
    assert lab.title_note == "· Supervised by Prof. Bob Notreal"
    tex = render_resume(full_bank_view(bank, show_supervisor=True))
    assert r"\textnormal{\small · Supervised by Prof. Bob Notreal}" in tex


def test_profile_show_supervisor_defaults() -> None:
    profiles = load_profiles(config.PROFILES_PATH)
    assert {n for n, p in profiles.items() if p.show_supervisor} == {"research_quant"}


def _all_texts(view: object) -> str:
    return str(view.model_dump()) if hasattr(view, "model_dump") else str(view)


@pytest.mark.parametrize(
    ("raw", "curled"),
    [
        ('"mismatch"', "“mismatch”"),
        ('said "red, green" today', "said “red, green” today"),
        ('"a" and "b"', "“a” and “b”"),
        ('("x")', "(“x”)"),
        ('5" screen', "5” screen"),
        ('"unclosed', "“unclosed"),
    ],
)
def test_straight_double_quotes_are_curled(raw: str, curled: str) -> None:
    assert escape_tex(raw) == curled


def test_contact_items_cannot_break_internally() -> None:
    bank = load_bank(config.FIXTURE_BANK)
    tex = render_resume(full_bank_view(bank))
    assert r"\mbox{Springfield, ZZ}" in tex
