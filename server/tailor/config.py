"""Paths and tunable defaults."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_DIR = REPO_ROOT / "server"
TEMPLATES_DIR = SERVER_DIR / "templates"
BANK_DIR = REPO_ROOT / "bank"
MASTER_BANK = BANK_DIR / "master.yaml"
FIXTURE_BANK = BANK_DIR / "fixture.yaml"
PROFILES_PATH = BANK_DIR / "profiles.yaml"
APPLICATIONS_DIR = REPO_ROOT / "applications"
STATE_DIR = Path.home() / ".resume-tailor"

# Layout defaults and the bounds fit.py may move them within (plan.md 4.8).
FONT_SIZE_PT = 11
FONT_SIZE_BOUNDS = (10, 11)  # article class supports 10pt and 11pt
MARGIN_IN = 0.5
MARGIN_BOUNDS = (0.5, 0.75)
ITEM_SEP_PT = 2.0


def default_bank_path() -> Path:
    """The real bank when present, otherwise the fixture."""
    return MASTER_BANK if MASTER_BANK.exists() else FIXTURE_BANK
