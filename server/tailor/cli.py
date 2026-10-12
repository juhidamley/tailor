"""Command-line entry point: `python -m tailor <command>`."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from tailor import __version__
from tailor.checks import ToolStatus, check_tool, warm_tectonic

STATE_DIR = Path.home() / ".resume-tailor"

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
        tectonic = await warm_tectonic(STATE_DIR / "check")
    else:
        tectonic = await check_tool("tectonic")
    claude = await check_tool("claude")
    _report(tectonic)
    _report(claude)
    return 0 if tectonic.ok and claude.ok else 1


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
    sub.add_parser("serve", help="run the local server (M6)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "check":
        return asyncio.run(_check(warm=args.warm))
    if args.command == "serve":
        return _not_yet("M6")
    raise AssertionError(f"unhandled command {args.command!r}")
