"""Command-line entry point: `python -m tailor <command>`."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from tailor import __version__, config
from tailor.bank import Report, check_bank_file, load_profiles
from tailor.checks import ToolStatus, check_tool, warm_tectonic
from tailor.compile import ats_problems, compile_tex, overfull_lines, page_count
from tailor.errors import BankError, CompileError, LLMError, MissingFixture, RecordGuardError
from tailor.llm.base import LLM
from tailor.llm.ping import ping
from tailor.llm.replay import ReplayLLM
from tailor.render import full_bank_view, render_resume

INSTALL_HINTS = {
    "tectonic": "brew install tectonic",
    "claude": "install Claude Code, then run `claude` once in a terminal to sign in",
}


def _report(status: ToolStatus) -> None:
    if status.ok:
        print(f"  ok    {status.name}: {status.version} ({status.path})")
    else:
        print(f"  FAIL  {status.name}: {status.error}")
        hint = INSTALL_HINTS.get(status.name)
        if hint:
            print(f"        install: {hint}")


async def _check(warm: bool) -> int:
    print(f"resume-tailor {__version__}")
    if warm:
        print("  warming the Tectonic cache (the first run downloads packages)...")
        tectonic = await warm_tectonic(config.STATE_DIR / "check")
    else:
        tectonic = await check_tool("tectonic")
    claude = await check_tool("claude")
    _report(tectonic)
    _report(claude)
    return 0 if tectonic.ok and claude.ok else 1


def _print_report(path: Path, report: Report) -> None:
    print(f"bank: {path}")
    if report.counts:
        print(f"  {'':<10} {'approved':>8} {'proposed':>8}")
        for kind, c in report.counts.items():
            print(f"  {kind:<10} {c['approved']:>8} {c['proposed']:>8}")
    if report.warnings:
        print(f"warnings ({len(report.warnings)}):")
        for w in report.warnings:
            print(f"  - {w}")
    if report.errors:
        print(f"errors ({len(report.errors)}):")
        for e in report.errors:
            print(f"  - {e}")
    print("OK" if report.ok else "FAILED")


def _bank_validate(path: Path, profiles: Path | None) -> int:
    _, report = check_bank_file(path, profiles)
    _print_report(path, report)
    return 0 if report.ok else 1


async def _render_all(
    bank_path: Path, include_proposed: bool, outdir: Path, profile: str | None
) -> int:
    bank, report = check_bank_file(bank_path, None)
    if bank is None or not report.ok:
        _print_report(bank_path, report)
        return 1
    show_supervisor = False
    if profile is not None:
        try:
            profiles = load_profiles(config.PROFILES_PATH)
        except BankError as e:
            print(e)
            return 1
        if profile not in profiles:
            print(f"unknown profile {profile!r}; choose from {', '.join(profiles)}")
            return 1
        show_supervisor = profiles[profile].show_supervisor
    view = full_bank_view(bank, include_proposed=include_proposed, show_supervisor=show_supervisor)
    stem = bank_path.stem + ("-all-items" if include_proposed else "-approved")
    tex = outdir / f"{stem}.tex"
    outdir.mkdir(parents=True, exist_ok=True)
    tex.write_text(render_resume(view), encoding="utf-8")
    try:
        pdf = await compile_tex(tex)
    except CompileError as e:
        print(f"compile failed: {e.first_error_line}")
        for line in e.context_lines:
            print(f"  {line}")
        print(f"tex: {tex}")
        return 1
    headings = [s.title for s in view.sections]
    problems = ats_problems(pdf, headings, [bank.contact.name, bank.contact.email])
    print(f"bank: {bank_path} ({'all items' if include_proposed else 'approved only'})")
    print(f"pdf:  {pdf} ({page_count(pdf)} pages)")
    print(f"tex:  {tex}")
    for p in problems:
        print(f"  ATS warning: {p}")
    overfull = overfull_lines(tex.with_suffix(".log"))
    if overfull:
        print(f"  layout warning: {len(overfull)} overfull line(s); see {tex.with_suffix('.log')}")
    return 0


def _real_llm(model: str | None) -> LLM:
    from tailor.llm.claude_cli import ClaudeCLI

    return ClaudeCLI(model=model)


async def _llm_ping(model: str | None, replay: bool) -> int:
    try:
        llm = ReplayLLM("replay") if replay else _real_llm(model)
        result = await ping(llm)
    except (LLMError, MissingFixture) as e:
        print(f"llm-ping FAILED: {e}")
        return 1
    for call in result.calls:
        u = call.usage
        cached = u.get("cache_read_input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
        tokens = u.get("input_tokens", 0) + cached, u.get("output_tokens", "?")
        cost = f", ${call.cost_usd:.4f}" if call.cost_usd is not None else ""
        print(
            f"  attempt {call.attempt}: {'ok' if call.ok else 'failed'} in {call.duration_s:.1f}s"
            f" (model {call.requested_model or '?'} -> {call.model or 'replay'},"
            f" tokens in/out {tokens[0]}/{tokens[1]}{cost})"
        )
    print(f"  answer: {result.answer.model_dump()} (ping prompt v{result.prompt_version})")
    print("llm-ping OK" if result.ok else "llm-ping FAILED: wrong sum")
    return 0 if result.ok else 1


async def _record_fixtures(bank: Path | None, stages: list[str] | None, model: str | None) -> int:
    from tailor.llm.record import record_fixtures
    from tailor.llm.replay import assert_fixture_bank

    try:
        assert_fixture_bank(bank)  # refuse before touching the real CLI
        assert bank is not None
        recorded = await record_fixtures(bank, _real_llm(model), stages)
    except (RecordGuardError, LLMError, ValueError) as e:
        print(f"record-fixtures refused/failed: {e}")
        return 1
    for status in ("new", "changed", "unchanged"):
        keys = sorted(k for k, v in recorded.items() if v == status)
        print(f"  {status} ({len(keys)}): {', '.join(keys) or '-'}")
    return 0


def _not_yet(milestone: str) -> int:
    print(f"not implemented yet (planned for {milestone}; see plan.md)")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tailor", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check", help="check that Tectonic and the claude CLI are installed")
    check.add_argument(
        "--warm", action="store_true", help="also compile a test document to warm the TeX cache"
    )

    bank = sub.add_parser("bank", help="content bank tools")
    bank_sub = bank.add_subparsers(dest="bank_command", required=True)
    validate = bank_sub.add_parser("validate", help="validate a bank file and profiles.yaml")
    validate.add_argument("path", nargs="?", type=Path, help="default: master.yaml, else fixture")
    validate.add_argument("--profiles", type=Path, default=config.PROFILES_PATH)
    validate.add_argument("--no-profiles", action="store_true", help="skip profile checks")

    render = sub.add_parser("render", help="render the bank to a PDF")
    render.add_argument("--all", action="store_true", help="render every printable item")
    render.add_argument(
        "--include-proposed", action="store_true", help="include proposed items (shown in gray)"
    )
    render.add_argument("--bank", type=Path, help="default: master.yaml, else fixture")
    render.add_argument("--profile", help="apply a profile's display options (show_supervisor)")
    render.add_argument(
        "--out", type=Path, default=config.APPLICATIONS_DIR / "_bank-render", help="output dir"
    )

    llm_ping = sub.add_parser("llm-ping", help="one tiny call through the LLM backend")
    llm_ping.add_argument("--model", help=f"default: {config.model_for('ping')} (per-stage config)")
    llm_ping.add_argument("--replay", action="store_true", help="use the recorded fixture")

    llm = sub.add_parser("llm", help="LLM backend tools")
    llm_sub = llm.add_subparsers(dest="llm_command", required=True)
    record = llm_sub.add_parser(
        "record-fixtures", help="record replay fixtures with the real CLI (fixture bank only)"
    )
    record.add_argument("--bank", type=Path, help="must be bank/fixture.yaml")
    record.add_argument("--stage", action="append", help="limit to a stage (repeatable)")
    record.add_argument("--model", help="override every stage's model")

    sub.add_parser("serve", help="run the local server (M6)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        return asyncio.run(_check(warm=args.warm))
    if args.command == "bank":
        path = args.path or config.default_bank_path()
        return _bank_validate(path, None if args.no_profiles else args.profiles)
    if args.command == "render":
        if not args.all:
            return _not_yet("M3 (tailored render); use `render --all` for the whole bank")
        bank_path = args.bank or config.default_bank_path()
        return asyncio.run(_render_all(bank_path, args.include_proposed, args.out, args.profile))
    if args.command == "llm-ping":
        return asyncio.run(_llm_ping(args.model, args.replay))
    if args.command == "llm":
        return asyncio.run(_record_fixtures(args.bank, args.stage, args.model))
    if args.command == "serve":
        return _not_yet("M6")
    raise AssertionError(f"unhandled command {args.command!r}")
