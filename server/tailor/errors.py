"""Typed errors raised by pipeline stages."""

from __future__ import annotations


class TailorError(Exception):
    """Base class for errors with a human-readable message."""


class BankError(TailorError):
    """The bank or profiles file is missing, unparseable, or invalid."""

    def __init__(self, path: str, problems: list[str]) -> None:
        self.path = path
        self.problems = problems
        super().__init__(f"{path}: {len(problems)} problem(s)\n" + "\n".join(problems))


class CompileError(TailorError):
    """Tectonic failed to produce a PDF."""

    def __init__(self, first_error_line: str, context_lines: list[str]) -> None:
        self.first_error_line = first_error_line
        self.context_lines = context_lines
        super().__init__(first_error_line)


class LLMError(TailorError):
    """A model call failed: CLI missing, auth, timeout, error envelope, or invalid output."""

    def __init__(self, stage: str, detail: str, raw_excerpt: str = "") -> None:
        self.stage = stage
        self.detail = detail
        self.raw_excerpt = raw_excerpt
        super().__init__(f"{stage}: {detail}")


class MissingFixture(TailorError):
    """Replay mode found no recorded response. Replay never falls back to the real CLI."""

    def __init__(self, key: str, stage: str, prompt_head: str) -> None:
        self.key = key
        self.stage = stage
        self.prompt_head = prompt_head
        super().__init__(
            f"no replay fixture {key}.json for stage {stage!r} "
            f"(record with `make record-fixtures`); prompt starts: {prompt_head[:120]!r}"
        )


class RecordGuardError(TailorError):
    """Refused to record fixtures from anything but the fixture bank (the repo is public)."""
