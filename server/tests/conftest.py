from __future__ import annotations

import copy
import os
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from tailor import config
from tailor.llm.claude_cli import FORBID_ENV

# Invariant 5: tests never call the real claude CLI. Constructing a ClaudeCLI that would
# resolve `claude` from PATH raises for the whole session; tests use ReplayLLM or a fake
# executable passed explicitly.
os.environ[FORBID_ENV] = "1"
# Model selection must not depend on the developer's own config or shell.
os.environ["TAILOR_CONFIG"] = "/nonexistent/resume-tailor-test-config.toml"
os.environ.pop("TAILOR_LLM_MODEL", None)

FIXTURE = config.FIXTURE_BANK
PROFILES = config.PROFILES_PATH

requires_tectonic = pytest.mark.skipif(
    shutil.which("tectonic") is None, reason="tectonic not installed"
)

_FIXTURE_DATA: dict[str, Any] = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def fixture_data() -> dict[str, Any]:
    """A fresh, mutable copy of the fixture bank as plain data."""
    return copy.deepcopy(_FIXTURE_DATA)


def write_yaml(tmp_path: Path, data: Any, name: str = "bank.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path
