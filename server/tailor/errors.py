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
