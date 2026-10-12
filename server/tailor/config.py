"""Paths and tunable defaults."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO_ROOT / "server"
TEMPLATES_DIR = SERVER_DIR / "templates"
PROMPTS_DIR = SERVER_DIR / "prompts"
LLM_FIXTURES_DIR = SERVER_DIR / "tests" / "fixtures" / "llm"
BANK_DIR = REPO_ROOT / "bank"
MASTER_BANK = BANK_DIR / "master.yaml"
FIXTURE_BANK = BANK_DIR / "fixture.yaml"
PROFILES_PATH = BANK_DIR / "profiles.yaml"
APPLICATIONS_DIR = REPO_ROOT / "applications"
STATE_DIR = Path.home() / ".resume-tailor"

# Headless Claude Code backend (llm/claude_cli.py).
LLM_CWD = STATE_DIR / "llm-cwd"  # empty dir, so no CLAUDE.md or settings leak into prompts
LLM_TIMEOUT_S = float(os.environ.get("TAILOR_LLM_TIMEOUT_S", "120"))
LLM_CONCURRENCY = 3

# Layout defaults and the bounds fit.py may move them within (plan.md 4.8).
FONT_SIZE_PT = 11
FONT_SIZE_BOUNDS = (10, 11)  # article class supports 10pt and 11pt
MARGIN_IN = 0.5
MARGIN_BOUNDS = (0.5, 0.75)
ITEM_SEP_PT = 2.0


# Model per LLM stage. Precedence: TAILOR_LLM_MODEL (all stages) > the [models] table in
# the user config file > these defaults > DEFAULT_MODEL.
STAGE_MODELS: dict[str, str] = {
    "jobspec": "sonnet",
    "rank": "sonnet",
    "rewrite": "opus",
    "repair": "opus",
    "verifier": "opus",
    "cover_letter": "opus",
    "ping": "sonnet",
}
DEFAULT_MODEL = "opus"


def user_config_path() -> Path:
    return Path(os.environ.get("TAILOR_CONFIG", STATE_DIR / "config.toml"))


def user_config() -> dict[str, Any]:
    """~/.resume-tailor/config.toml (or $TAILOR_CONFIG), or {} when absent."""
    path = user_config_path()
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def model_for(stage: str) -> str:
    override = os.environ.get("TAILOR_LLM_MODEL")
    if override:
        return override
    models = user_config().get("models", {})
    if not isinstance(models, dict):
        raise ValueError(f"{user_config_path()}: [models] must be a table")
    return str(models.get(stage) or STAGE_MODELS.get(stage) or DEFAULT_MODEL)


def default_bank_path() -> Path:
    """The real bank when present, otherwise the fixture."""
    return MASTER_BANK if MASTER_BANK.exists() else FIXTURE_BANK
