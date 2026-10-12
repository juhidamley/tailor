"""Bank and profile schema (pydantic) plus the cross-reference validator.

Schema follows plan.md section 3, extended to match bank/master.yaml:
`status` and `source` on every bullet, context item, detail, tagline, award,
interest, and story; `title_line`, `supervisor`, `stack_line`, and `link` on
entries; `kind` on education details; top-level `taglines`, `stories`, and
`interests`.

Text is plain: `% $ & # _ ~ ^` are allowed as written and escaped by
render.escape_tex. LaTeX markup (a backslash or braces) is rejected.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from tailor.errors import BankError

Status = Literal["approved", "proposed"]
SectionName = Literal[
    "education", "experiences", "projects", "leadership", "skills", "awards", "interests"
]
# `course` is a single course kept as skill evidence; render prints `coursework` lines.
DetailKind = Literal["coursework", "course", "gpa", "honors"]
StoryUse = Literal["cover_letter", "awards"]

_MARKUP = re.compile(r"[\\{}]")
_YEAR_MONTH = re.compile(r"^(\d{4})(?:-(\d{2}))?$")
_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _no_markup(value: str) -> str:
    found = sorted(set(_MARKUP.findall(value)))
    if found:
        raise ValueError(
            f"contains LaTeX markup characters {' '.join(found)!s}; write plain text "
            f"(render.py escapes % $ & # _ ~ ^ itself)"
        )
    return value


def _year_month(value: str) -> str:
    m = _YEAR_MONTH.match(value)
    if not m or not 1 <= int(m.group(2) or 1) <= 12:
        raise ValueError(f"date {value!r} must be YYYY-MM or YYYY")
    return value


def _to_str(value: object) -> object:
    # YAML reads a bare year (2025) as an int.
    return str(value) if isinstance(value, int) and not isinstance(value, bool) else value


PlainText = Annotated[str, Field(min_length=1), AfterValidator(_no_markup)]
YearMonth = Annotated[str, BeforeValidator(_to_str), AfterValidator(_year_month)]


def ym_key(value: str) -> tuple[int, int]:
    """Sort key for a YearMonth string. A bare year sorts as January."""
    m = _YEAR_MONTH.match(value)
    assert m is not None, value
    return int(m.group(1)), int(m.group(2) or 1)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Dates(_Model):
    start: YearMonth
    end: YearMonth | Literal["present"]

    @model_validator(mode="after")
    def _ordered(self) -> Dates:
        if self.end != "present" and ym_key(self.end) < ym_key(self.start):
            raise ValueError(f"end {self.end} is before start {self.start}")
        return self


class Contact(_Model):
    name: PlainText
    email: PlainText
    phone: PlainText | None = None
    location: PlainText | None = None
    website: PlainText | None = None
    github: PlainText | None = None
    linkedin: PlainText | None = None


class Tagged(_Model):
    """An item with a review status and provenance."""

    id: str
    text: PlainText
    status: Status
    source: str = Field(min_length=1)


class Tagline(Tagged):
    pass


class ContextItem(Tagged):
    """Facts a rewrite may draw on. Never printed."""


class Detail(Tagged):
    kind: DetailKind


class Bullet(Tagged):
    tags: list[str] = []
    skills: list[PlainText] = []
    strength: int = Field(ge=1, le=5)
    min_keep: bool = False


class Education(_Model):
    id: str
    school: PlainText
    location: PlainText | None = None
    degree: PlainText
    dates: Dates
    details: list[Detail] = []
    context: list[ContextItem] = []


class Experience(_Model):
    """Used for both `experiences` and `leadership`."""

    id: str
    org: PlainText
    role: PlainText
    title_line: PlainText | None = None
    supervisor: PlainText | None = None
    location: PlainText | None = None
    dates: Dates
    link: PlainText | None = None
    tags: list[str] = []
    context: list[ContextItem] = []
    bullets: list[Bullet] = []


class Project(_Model):
    id: str
    name: PlainText
    link: PlainText | None = None
    stack_line: PlainText | None = None
    dates: Dates | None = None
    tags: list[str] = []
    context: list[ContextItem] = []
    bullets: list[Bullet] = []


class SkillItem(_Model):
    name: PlainText
    evidence: list[str] = []


class SkillCategory(_Model):
    category: PlainText
    items: list[SkillItem]


class Award(Tagged):
    date: YearMonth | None = None
    tags: list[str] = []


class Interest(Tagged):
    pass


class Story(Tagged):
    """Personal anecdotes for cover letters. Never printed on the resume."""

    tags: list[str] = []
    use: list[StoryUse] = Field(min_length=1)


class Bank(_Model):
    contact: Contact
    taglines: list[Tagline] = []
    education: list[Education] = []
    experiences: list[Experience] = []
    projects: list[Project] = []
    leadership: list[Experience] = []
    skills: list[SkillCategory] = []
    awards: list[Award] = []
    interests: list[Interest] = []
    stories: list[Story] = []

    def entries(self) -> Iterator[tuple[str, Education | Experience | Project]]:
        for e in self.education:
            yield "education", e
        for x in self.experiences:
            yield "experiences", x
        for p in self.projects:
            yield "projects", p
        for lead in self.leadership:
            yield "leadership", lead

    def status_items(self) -> Iterator[tuple[str, Tagged]]:
        """Every item that carries a status, labelled by kind."""
        for t in self.taglines:
            yield "taglines", t
        for _, entry in self.entries():
            if isinstance(entry, Education):
                for d in entry.details:
                    yield "details", d
            else:
                for b in entry.bullets:
                    yield "bullets", b
            for c in entry.context:
                yield "context", c
        for a in self.awards:
            yield "awards", a
        for i in self.interests:
            yield "interests", i
        for s in self.stories:
            yield "stories", s


class Profile(_Model):
    description: str
    tag_weights: dict[str, Annotated[float, Field(gt=0)]] = {}
    section_order: list[SectionName] = Field(min_length=1)
    skills_categories: list[str] = []
    max_bullets_per_entry: int = Field(ge=1)
    tagline: str | None = None
    show_supervisor: bool = False

    @model_validator(mode="after")
    def _unique_sections(self) -> Profile:
        dupes = [s for s, n in Counter(self.section_order).items() if n > 1]
        if dupes:
            raise ValueError(f"section_order repeats {dupes}")
        return self


Profiles = dict[str, Profile]


# --------------------------------------------------------------------------- loading


def _read_yaml(path: Path) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        raise BankError(str(path), [f"cannot read file: {e}"]) from e
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise BankError(str(path), [f"YAML parse error: {e}"]) from e


def _format_loc(loc: tuple[int | str, ...], data: Any) -> str:
    """Render a pydantic error location, naming list items by their id when they have one."""
    parts: list[str] = []
    node = data
    for key in loc:
        try:
            node = node[key]
        except (KeyError, IndexError, TypeError):
            node = None
        if isinstance(key, int):
            ident = node.get("id") if isinstance(node, dict) else None
            parts.append(f"[{ident}]" if ident else f"[{key}]")
        else:
            parts.append(f".{key}" if parts else str(key))
    return "".join(parts)


def _pydantic_problems(err: ValidationError, data: Any) -> list[str]:
    problems = []
    for e in err.errors():
        where = _format_loc(tuple(e["loc"]), data)
        msg = e["msg"]
        if e["type"] == "extra_forbidden":
            key = str(e["loc"][-1])
            msg = f"unknown field {key!r}"
            if re.match(r"^\d+\)?$", key) or " " in key:
                msg += (
                    " (likely an unquoted comma or colon inside a { ... } flow mapping "
                    "split a value; put that value in quotes)"
                )
        problems.append(f"{where}: {msg}")
    return problems


def load_bank(path: Path) -> Bank:
    data = _read_yaml(path)
    try:
        return Bank.model_validate(data)
    except ValidationError as e:
        raise BankError(str(path), _pydantic_problems(e, data)) from e


def load_profiles(path: Path) -> Profiles:
    data = _read_yaml(path)
    if not isinstance(data, dict):
        raise BankError(str(path), ["top level must be a mapping of profile name to profile"])
    profiles: Profiles = {}
    problems: list[str] = []
    for name, raw in data.items():
        try:
            profiles[str(name)] = Profile.model_validate(raw)
        except ValidationError as e:
            problems += [f"{name}.{p}" for p in _pydantic_problems(e, raw)]
    if problems:
        raise BankError(str(path), problems)
    return profiles


# --------------------------------------------------------------------------- validation


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts: dict[str, Counter[str]] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


_ENTRY_PREFIX = {
    "education": "edu-",
    "experiences": "exp-",
    "projects": "proj-",
    "leadership": "lead-",
}
_ITEM_PREFIX = {
    "taglines": "tag-",
    "awards": "award-",
    "interests": "int-",
    "stories": "story-",
}


def _check_ids(bank: Bank, report: Report) -> set[str]:
    seen: Counter[str] = Counter()

    def visit(ident: str, prefix: str, what: str) -> None:
        seen[ident] += 1
        if not _KEBAB.match(ident):
            report.errors.append(f"{ident}: {what} id must be kebab-case")
        elif not ident.startswith(prefix):
            report.errors.append(f"{ident}: {what} id must start with {prefix!r}")

    for section, entry in bank.entries():
        prefix = _ENTRY_PREFIX[section]
        visit(entry.id, prefix, section)
        children: list[tuple[str, str, str]] = [(c.id, "c", "context") for c in entry.context]
        if isinstance(entry, Education):
            children += [(d.id, "", "detail") for d in entry.details]
        else:
            children += [(b.id, "b", "bullet") for b in entry.bullets]
        for ident, suffix, what in children:
            visit(ident, prefix, what)
            if suffix and not re.search(rf"-{suffix}\d+$", ident):
                report.errors.append(f"{ident}: {what} id must end in -{suffix}N")
            elif suffix and not ident.startswith(entry.id + "-"):
                report.warnings.append(f"{ident}: {what} id doesn't start with its entry id")

    for kind, item in bank.status_items():
        if kind in _ITEM_PREFIX:
            visit(item.id, _ITEM_PREFIX[kind], kind.rstrip("s"))

    for ident, n in seen.items():
        if n > 1:
            report.errors.append(f"{ident}: id is used {n} times")
    return set(seen)


def _check_skills(bank: Bank, ids: set[str], report: Report) -> None:
    approved = {item.id for _, item in bank.status_items() if item.status == "approved"}
    # Entries carry no status, so evidence pointing at a whole entry counts as approved.
    approved |= {entry.id for _, entry in bank.entries()}
    names: Counter[str] = Counter()
    for cat in bank.skills:
        for skill in cat.items:
            names[skill.name.lower()] += 1
            if not skill.evidence:
                report.warnings.append(f"skill {skill.name!r} ({cat.category}) has no evidence")
                continue
            missing = [ev for ev in skill.evidence if ev not in ids]
            if missing:
                report.errors.append(
                    f"skill {skill.name!r}: evidence {', '.join(missing)} doesn't resolve"
                )
            elif not any(ev in approved for ev in skill.evidence):
                report.warnings.append(f"skill {skill.name!r} is backed only by proposed items")
    for name, n in names.items():
        if n > 1:
            report.warnings.append(f"skill {name!r} is listed {n} times")


def _check_profiles(bank: Bank, profiles: Profiles, report: Report) -> None:
    taglines = {t.id: t for t in bank.taglines}
    categories = {c.category for c in bank.skills}
    for name, prof in profiles.items():
        if prof.tagline is not None:
            tag = taglines.get(prof.tagline)
            if tag is None:
                report.errors.append(f"profile {name}: tagline {prof.tagline!r} not in bank")
            elif tag.status != "approved":
                report.warnings.append(f"profile {name}: tagline {prof.tagline!r} is proposed")
        for cat in prof.skills_categories:
            if cat not in categories:
                report.warnings.append(f"profile {name}: skills category {cat!r} not in bank")


def _count(bank: Bank, report: Report) -> None:
    by_kind: dict[str, Counter[str]] = {}
    for kind, item in bank.status_items():
        by_kind.setdefault(kind, Counter())[item.status] += 1
    report.counts = by_kind


def validate_bank(bank: Bank, profiles: Profiles | None = None) -> Report:
    """Cross-reference checks that a single pydantic model can't see."""
    report = Report()
    ids = _check_ids(bank, report)
    _check_skills(bank, ids, report)
    if profiles is not None:
        _check_profiles(bank, profiles, report)
    _count(bank, report)
    return report


# An unquoted value followed by ` #word` loses everything from the `#` on: YAML reads it
# as a comment. Real comments almost always have a space after the `#`.
_HIDDEN_COMMENT = re.compile(r"^\s*(?:-\s+)?[A-Za-z_]+:\s+[^\s\"'|>\[{#][^#]*\s#\S")


def yaml_pitfalls(text: str) -> list[str]:
    """Line-level warnings for YAML that parses but silently drops text."""
    return [
        f"line {n}: unquoted value contains ' #', so YAML drops the rest of the line "
        f"as a comment; put the value in quotes"
        for n, line in enumerate(text.splitlines(), start=1)
        if _HIDDEN_COMMENT.match(line)
    ]


def check_bank_file(path: Path, profiles_path: Path | None) -> tuple[Bank | None, Report]:
    """Load and validate; schema problems become report errors instead of raising."""
    report = Report()
    try:
        bank = load_bank(path)
    except BankError as e:
        report.errors += e.problems
        return None, report
    report.warnings += yaml_pitfalls(path.read_text(encoding="utf-8"))
    profiles = None
    if profiles_path is not None:
        try:
            profiles = load_profiles(profiles_path)
        except BankError as e:
            report.errors += [f"{profiles_path.name}: {p}" for p in e.problems]
    full = validate_bank(bank, profiles)
    full.errors = report.errors + full.errors
    full.warnings = report.warnings + full.warnings
    return bank, full
