"""Bank schema and validator tests. Uses bank/fixture.yaml only."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import FIXTURE, PROFILES, write_yaml

from tailor import cli
from tailor.bank import (
    Bank,
    BankError,
    check_bank_file,
    load_bank,
    load_profiles,
    validate_bank,
    yaml_pitfalls,
)


def _report(data: dict[str, Any]) -> list[str]:
    return validate_bank(Bank.model_validate(data)).errors


def _schema_errors(tmp_path: Path, data: dict[str, Any]) -> list[str]:
    with pytest.raises(BankError) as exc:
        load_bank(write_yaml(tmp_path, data))
    return exc.value.problems


# --------------------------------------------------------------------------- the fixture


def test_fixture_is_valid_with_expected_warnings() -> None:
    bank, report = check_bank_file(FIXTURE, PROFILES)
    assert bank is not None
    assert report.errors == []
    assert "skill 'Fortran' (Languages) has no evidence" in report.warnings
    assert "skill 'C#' is backed only by proposed items" in report.warnings


def test_fixture_counts() -> None:
    _, report = check_bank_file(FIXTURE, None)
    assert report.counts["bullets"]["approved"] == 10
    assert report.counts["bullets"]["proposed"] == 3
    assert set(report.counts) == {
        "taglines", "details", "context", "bullets", "awards", "interests", "stories"
    }  # fmt: skip


def test_fixture_exercises_every_optional_field() -> None:
    bank = load_bank(FIXTURE)
    exp = bank.experiences[0]
    assert exp.title_line and exp.supervisor and exp.link and exp.dates.end == "present"
    assert {d.kind for d in bank.education[0].details} == {"coursework", "course", "gpa", "honors"}
    assert any(p.dates is None for p in bank.projects)
    assert all(p.stack_line and p.link for p in bank.projects)
    assert {u for s in bank.stories for u in s.use} == {"cover_letter", "awards"}
    assert bank.interests and bank.taglines and bank.leadership[0].link
    assert any(b.min_keep for _, e in bank.entries() for b in getattr(e, "bullets", []))
    assert {a.date for a in bank.awards} == {"2025", "2024-05", None}


def test_profiles_load() -> None:
    profiles = load_profiles(PROFILES)
    assert set(profiles) == {"swe_ml", "fde", "pm", "research_quant"}
    assert profiles["pm"].section_order[1] == "leadership"


def test_cli_validate_exit_codes(tmp_path: Path, fixture_data: dict[str, Any]) -> None:
    assert cli.main(["bank", "validate", str(FIXTURE)]) == 0
    fixture_data["awards"][0]["id"] = fixture_data["awards"][1]["id"]
    assert cli.main(["bank", "validate", str(write_yaml(tmp_path, fixture_data))]) == 1


# --------------------------------------------------------------------------- ids


def test_duplicate_ids(fixture_data: dict[str, Any]) -> None:
    exp = fixture_data["experiences"][0]
    exp["bullets"][1]["id"] = exp["bullets"][0]["id"]
    assert "exp-acme-widgets-b1: id is used 2 times" in _report(fixture_data)


def test_duplicate_id_across_kinds(fixture_data: dict[str, Any]) -> None:
    fixture_data["experiences"][0]["context"][0]["id"] = "exp-acme-widgets-b1"
    errors = _report(fixture_data)
    assert "exp-acme-widgets-b1: id is used 2 times" in errors


@pytest.mark.parametrize(
    ("path", "bad_id", "expected"),
    [
        (("experiences", 0, "id"), "acme", "must start with 'exp-'"),
        (("projects", 0, "id"), "Proj-Widget", "must be kebab-case"),
        (("awards", 1, "id"), "prize-pretend", "must start with 'award-'"),
        (("stories", 0, "id"), "tale-x", "must start with 'story-'"),
        (("taglines", 0, "id"), "tagline-x", "must start with 'tag-'"),
        (("interests", 0, "id"), "interest-x", "must start with 'int-'"),
    ],
)
def test_id_prefixes(
    fixture_data: dict[str, Any], path: tuple[Any, ...], bad_id: str, expected: str
) -> None:
    node: Any = fixture_data
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = bad_id
    assert any(expected in e for e in _report(fixture_data))


def test_bullet_and_context_suffixes(fixture_data: dict[str, Any]) -> None:
    exp = fixture_data["experiences"][0]
    exp["bullets"][0]["id"] = "exp-acme-widgets-x1"
    exp["context"][0]["id"] = "exp-acme-widgets-b9"
    errors = _report(fixture_data)
    assert "exp-acme-widgets-x1: bullet id must end in -bN" in errors
    assert "exp-acme-widgets-b9: context id must end in -cN" in errors


def test_bullet_id_from_other_entry_warns(fixture_data: dict[str, Any]) -> None:
    fixture_data["experiences"][0]["bullets"][1]["id"] = "exp-other-b2"
    report = validate_bank(Bank.model_validate(fixture_data))
    assert report.errors == []
    assert "exp-other-b2: bullet id doesn't start with its entry id" in report.warnings


# --------------------------------------------------------------------------- skills


def test_unresolved_evidence_is_error(fixture_data: dict[str, Any]) -> None:
    fixture_data["skills"][0]["items"][0]["evidence"] = ["exp-acme-widgets-b1", "exp-nope-b1"]
    assert "skill 'Python': evidence exp-nope-b1 doesn't resolve" in _report(fixture_data)


def test_empty_evidence_is_warning_not_error(fixture_data: dict[str, Any]) -> None:
    fixture_data["skills"][0]["items"][0]["evidence"] = []
    report = validate_bank(Bank.model_validate(fixture_data))
    assert report.errors == []
    assert "skill 'Python' (Languages) has no evidence" in report.warnings


def test_evidence_can_point_at_an_entry(fixture_data: dict[str, Any]) -> None:
    fixture_data["skills"][0]["items"][0]["evidence"] = ["edu-example-u"]
    assert _report(fixture_data) == []


# --------------------------------------------------------------------------- dates


@pytest.mark.parametrize("bad", ["2024-13", "24-01", "2024/01", "June 2024", "2024-1"])
def test_bad_dates(tmp_path: Path, fixture_data: dict[str, Any], bad: str) -> None:
    fixture_data["experiences"][0]["dates"]["start"] = bad
    problems = _schema_errors(tmp_path, fixture_data)
    assert any("experiences[exp-acme-widgets].dates.start" in p for p in problems), problems


def test_end_before_start(tmp_path: Path, fixture_data: dict[str, Any]) -> None:
    fixture_data["experiences"][1]["dates"] = {"start": "2025-05", "end": "2024-01"}
    problems = _schema_errors(tmp_path, fixture_data)
    assert any("end 2024-01 is before start 2025-05" in p for p in problems)


def test_bare_year_award_date_parses(fixture_data: dict[str, Any]) -> None:
    fixture_data["awards"][1]["date"] = 2023
    assert Bank.model_validate(fixture_data).awards[1].date == "2023"


# --------------------------------------------------------------------------- text


@pytest.mark.parametrize("bad", [r"Used \textbf{Python}", "Built {stuff}", r"50\% faster"])
def test_latex_markup_rejected(tmp_path: Path, fixture_data: dict[str, Any], bad: str) -> None:
    fixture_data["experiences"][0]["bullets"][0]["text"] = bad
    problems = _schema_errors(tmp_path, fixture_data)
    assert any("exp-acme-widgets-b1].text" in p and "LaTeX markup" in p for p in problems)


def test_plain_specials_allowed(fixture_data: dict[str, Any]) -> None:
    fixture_data["experiences"][0]["bullets"][0]["text"] = (
        "Cut 50% of $2M R&D #1 snake_case ~3x a^2"
    )
    assert _report(fixture_data) == []


def test_markup_rejected_in_headings_too(tmp_path: Path, fixture_data: dict[str, Any]) -> None:
    fixture_data["projects"][0]["name"] = r"\href{x}{y}"
    assert _schema_errors(tmp_path, fixture_data)


# --------------------------------------------------------------------------- schema shape


def test_status_required_and_enumerated(tmp_path: Path, fixture_data: dict[str, Any]) -> None:
    fixture_data["experiences"][0]["bullets"][0]["status"] = "draft"
    del fixture_data["awards"][1]["status"]
    problems = _schema_errors(tmp_path, fixture_data)
    assert any("[exp-acme-widgets-b1].status" in p for p in problems)
    assert any("[award-pretend-scholarship].status" in p for p in problems)


def test_source_required(tmp_path: Path, fixture_data: dict[str, Any]) -> None:
    del fixture_data["stories"][0]["source"]
    assert any("source" in p for p in _schema_errors(tmp_path, fixture_data))


def test_unknown_fields_rejected(tmp_path: Path, fixture_data: dict[str, Any]) -> None:
    fixture_data["experiences"][0]["bullets"][0]["strenght"] = 3
    problems = _schema_errors(tmp_path, fixture_data)
    assert any("unknown field 'strenght'" in p for p in problems)


def test_strength_bounds(tmp_path: Path, fixture_data: dict[str, Any]) -> None:
    fixture_data["experiences"][0]["bullets"][0]["strength"] = 6
    assert _schema_errors(tmp_path, fixture_data)


def test_unquoted_comma_in_flow_mapping_gets_a_hint(tmp_path: Path) -> None:
    text = FIXTURE.read_text(encoding="utf-8").replace(
        'text: "First Place, Imaginary Hackathon ($1,000 prize)"',
        "text: First Place Imaginary Hackathon ($1,000 prize)",
    )
    path = tmp_path / "bank.yaml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(BankError) as exc:
        load_bank(path)
    (problem,) = exc.value.problems
    assert problem.startswith("awards[award-fake-hackathon]")
    assert "flow mapping" in problem


def test_hidden_comment_warning() -> None:
    text = "  text: Ran #1 ranked team\n  strength: 4  # a normal comment\n  text: 'ok #1'\n"
    assert [w.split(":")[0] for w in yaml_pitfalls(text)] == ["line 1"]


def test_profile_tagline_must_resolve(fixture_data: dict[str, Any]) -> None:
    fixture_data["taglines"] = fixture_data["taglines"][:1]
    report = validate_bank(Bank.model_validate(fixture_data), load_profiles(PROFILES))
    assert "profile research_quant: tagline 'tag-ai-polisci-opt' not in bank" in report.errors


def test_profile_rejects_unknown_section(tmp_path: Path) -> None:
    path = write_yaml(
        tmp_path,
        {"x": {"description": "d", "section_order": ["hobbies"], "max_bullets_per_entry": 2}},
    )
    with pytest.raises(BankError):
        load_profiles(path)
