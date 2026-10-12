"""LaTeX rendering: the single escaping function, the Jinja environment, and view models.

Invariant 1: all LaTeX comes from server/templates/*.j2, and every string from the
bank or the model passes through `escape_tex` (the `|tex` filter) exactly once.
"""

from __future__ import annotations

import re
from typing import Literal
from urllib.parse import quote

import jinja2
from pydantic import BaseModel, ConfigDict

from tailor import config
from tailor.bank import Bank, Dates, Education, Experience, Project, Tagged

# One pass over a character class, so no output is ever escaped twice.
_TEX_SPECIALS = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
}
_TEX_RE = re.compile("[" + re.escape("".join(_TEX_SPECIALS)) + "]")
# XeTeX reads UTF-8, so curly quotes, dashes, and accents stay as Unicode. These two
# would otherwise be swallowed by TeX's ligature rules (`--` becomes an en dash).
_TEX_LIGATURES = re.compile(r"-(?=-)")


def escape_tex(text: str) -> str:
    """Escape plain text for LaTeX. The only escaping function in the codebase."""
    out = _TEX_RE.sub(lambda m: _TEX_SPECIALS[m.group(0)], text)
    return _TEX_LIGATURES.sub("-{}", out)


# Template variables that may appear without `|tex`. Numbers only, built by code.
RAW_ALLOWLIST = frozenset({"font_size", "margin_in", "item_sep"})
# Template macros whose output is already escaped inside the macro body.
SAFE_MACROS = frozenset({"text", "linked", "item_list"})


def make_env() -> jinja2.Environment:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(config.TEMPLATES_DIR),
        block_start_string=r"\BLOCK{",
        block_end_string="}",
        variable_start_string=r"\VAR{",
        variable_end_string="}",
        comment_start_string=r"\#{",
        comment_end_string="}",
        trim_blocks=True,
        lstrip_blocks=True,
        autoescape=False,
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
    )
    env.filters["tex"] = escape_tex
    return env


# --------------------------------------------------------------------------- view models


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Link(_View):
    text: str
    url: str | None = None


class Item(_View):
    text: str
    proposed: bool = False


class Entry(_View):
    """One heading block. `kind` picks the Jake's macro."""

    kind: Literal["subheading", "project"]
    title: str
    title_url: str | None = None
    title_note: str = ""  # normal weight, after the bold title
    right: str = ""  # dates
    subtitle: str = ""  # role / degree / project stack
    sub_right: str = ""  # location
    rows: list[Item] = []


class SkillLine(_View):
    category: str
    names: str


class Section(_View):
    key: str
    title: str
    entries: list[Entry] = []
    skills: list[SkillLine] = []
    rows: list[Item] = []


class AppendixRow(_View):
    id: str
    status: str
    text: str
    note: str = ""


class AppendixGroup(_View):
    title: str
    rows: list[AppendixRow]


class ResumeView(_View):
    name: str
    contact: list[Link]
    taglines: list[Item] = []
    sections: list[Section]
    review_mode: bool = False
    # Review-only: never-printed items (context, stories) with ids. Empty on real resumes.
    appendix: list[AppendixGroup] = []
    font_size: int = config.FONT_SIZE_PT
    margin_in: float = config.MARGIN_IN
    item_sep: float = config.ITEM_SEP_PT


SECTION_TITLES = {
    "education": "Education",
    "experiences": "Experience",
    "projects": "Projects",
    "leadership": "Leadership",
    "skills": "Technical Skills",
    "awards": "Awards",
    "interests": "Interests",
}
ALL_SECTIONS = list(SECTION_TITLES)

_MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def format_ym(value: str) -> str:
    if value == "present":
        return "Present"
    year, _, month = value.partition("-")
    return f"{_MONTHS[int(month) - 1]} {year}" if month else year


def format_dates(dates: Dates | None) -> str:
    if dates is None:
        return ""
    return f"{format_ym(dates.start)} – {format_ym(dates.end)}"


# Characters a URL may keep as-is. Everything else is percent-encoded, so a link target
# never needs TeX escaping beyond what escape_tex does for `% # & _` (a `~` would
# otherwise reach the PDF as `~{}`).
_URL_SAFE = "/:?=&#%@+.,;!*'()$_-"


def url_for(link: str) -> str:
    """Link target for `\\href`: adds a scheme when the bank omits it, then percent-encodes."""
    if not link.startswith(("http://", "https://", "mailto:")):
        link = "https://" + link
    # quote() never encodes `~`, so do it by hand.
    return quote(link, safe=_URL_SAFE).replace("~", "%7E").replace("--", "-%2D")


def display_url(link: str) -> str:
    return re.sub(r"^https?://(www\.)?", "", link).rstrip("/")


def _item(t: Tagged) -> Item:
    return Item(text=t.text, proposed=t.status == "proposed")


def _keep(t: Tagged, include_proposed: bool) -> bool:
    return include_proposed or t.status == "approved"


def _entry_view(
    entry: Education | Experience | Project, include_proposed: bool, show_supervisor: bool
) -> Entry:
    if isinstance(entry, Education):
        return Entry(
            kind="subheading",
            title=entry.school,
            right=format_dates(entry.dates),
            subtitle=entry.degree,
            sub_right=entry.location or "",
            rows=[
                _item(d) for d in entry.details if d.kind != "course" and _keep(d, include_proposed)
            ],
        )
    items = [_item(b) for b in entry.bullets if _keep(b, include_proposed)]
    if isinstance(entry, Project):
        return Entry(
            kind="project",
            title=entry.name,
            title_url=url_for(entry.link) if entry.link else None,
            right=format_dates(entry.dates),
            subtitle=entry.stack_line or "",
            rows=items,
        )
    # With a title_line: it goes on top and the italic line reads "role · org".
    # Without: org on top, role below. The supervisor note follows the org either way.
    supervisor = f"Supervised by {entry.supervisor}" if show_supervisor and entry.supervisor else ""
    if entry.title_line:
        title, title_note = entry.title_line, ""
        subtitle = " · ".join(p for p in (entry.role, entry.org, supervisor) if p)
    else:
        title, title_note = entry.org, f"· {supervisor}" if supervisor else ""
        subtitle = entry.role
    return Entry(
        kind="subheading",
        title=title,
        title_url=url_for(entry.link) if entry.link else None,
        title_note=title_note,
        right=format_dates(entry.dates),
        subtitle=subtitle,
        sub_right=entry.location or "",
        rows=items,
    )


def _skill_lines(bank: Bank, include_proposed: bool) -> list[SkillLine]:
    """A skill is listed only when it has evidence that is itself printable."""
    printable = {e.id for _, e in bank.entries()}
    printable |= {i.id for _, i in bank.status_items() if _keep(i, include_proposed)}
    lines = []
    for cat in bank.skills:
        names = [
            s.name
            for s in cat.items
            if (include_proposed and not s.evidence) or any(ev in printable for ev in s.evidence)
        ]
        if names:
            lines.append(SkillLine(category=cat.category, names=", ".join(names)))
    return lines


def contact_links(bank: Bank) -> list[Link]:
    c = bank.contact
    links: list[Link] = []
    if c.phone:
        links.append(Link(text=c.phone))
    links.append(Link(text=c.email, url=url_for(f"mailto:{c.email}")))
    for value in (c.website, c.linkedin, c.github):
        if value:
            links.append(Link(text=display_url(value), url=url_for(value)))
    if c.location:
        links.append(Link(text=c.location))
    return links


def _entry_title(entry: Education | Experience | Project) -> str:
    if isinstance(entry, Education):
        return entry.school
    return entry.name if isinstance(entry, Project) else entry.org


def review_appendix(bank: Bank) -> list[AppendixGroup]:
    """Context items grouped by entry, then stories, with ids and status."""
    groups = [
        AppendixGroup(
            title=f"{SECTION_TITLES[key]}: {_entry_title(entry)}",
            rows=[AppendixRow(id=c.id, status=c.status, text=c.text) for c in entry.context],
        )
        for key, entry in bank.entries()
        if entry.context
    ]
    if bank.stories:
        rows = [
            AppendixRow(id=s.id, status=s.status, text=s.text, note="use: " + ", ".join(s.use))
            for s in bank.stories
        ]
        groups.append(AppendixGroup(title="Stories", rows=rows))
    return groups


def full_bank_view(
    bank: Bank, include_proposed: bool = False, show_supervisor: bool = False
) -> ResumeView:
    """Everything printable in the bank, in bank order: the `render --all` review view.

    With include_proposed, a review appendix lists the never-printed context and stories.
    """
    sections: list[Section] = []
    for key in ALL_SECTIONS:
        title = SECTION_TITLES[key]
        if key == "skills":
            skills = _skill_lines(bank, include_proposed)
            if skills:
                sections.append(Section(key=key, title=title, skills=skills))
        elif key in ("awards", "interests"):
            source: list[Tagged] = list(bank.awards if key == "awards" else bank.interests)
            items = [
                Item(text=_award_text(t), proposed=t.status == "proposed")
                for t in source
                if _keep(t, include_proposed)
            ]
            if items:
                sections.append(Section(key=key, title=title, rows=items))
        else:
            entries = [
                _entry_view(e, include_proposed, show_supervisor)
                for k, e in bank.entries()
                if k == key
            ]
            if entries:
                sections.append(Section(key=key, title=title, entries=entries))
    return ResumeView(
        name=bank.contact.name,
        contact=contact_links(bank),
        taglines=[_item(t) for t in bank.taglines if _keep(t, include_proposed)],
        sections=sections,
        review_mode=include_proposed,
        appendix=review_appendix(bank) if include_proposed else [],
    )


def _award_text(item: Tagged) -> str:
    date = getattr(item, "date", None)
    return f"{item.text} ({format_ym(date)})" if date else item.text


def render_resume(view: ResumeView) -> str:
    return make_env().get_template("resume.tex.j2").render(**view.model_dump())
