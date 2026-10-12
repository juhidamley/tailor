"""Load versioned prompt files from server/prompts/ and fill them with Jinja2.

Committed prompts are `<stage>.txt` (the repo is public and `*.md` is gitignored).
File format: a `---` front-matter block (`version`, `stage`, optional `schema`), then the
prompt body. Prompts are never inlined in Python.

Local-only prompt parts (LOCAL_ONLY, e.g. `_juhi_voice.md`) are optional: a template
includes them with `{% include "_juhi_voice.md" ignore missing %}`, and a missing file
only logs a warning.
"""

from __future__ import annotations

import json
import logging
from functools import cache
from pathlib import Path
from typing import Any

import jinja2
import jinja2.meta
import yaml
from pydantic import BaseModel, ConfigDict

from tailor import config

log = logging.getLogger(__name__)

LOCAL_ONLY = frozenset({"_juhi_voice.md"})


class Prompt(BaseModel):
    model_config = ConfigDict(frozen=True)

    stage: str
    version: int
    schema_name: str | None = None
    body: str

    def render(self, schema: type[BaseModel] | None = None, **inputs: Any) -> str:
        """Fill the body. `schema`, when given, is available as `{{ schema }}` (JSON Schema)."""
        if schema is not None:
            inputs["schema"] = json.dumps(schema.model_json_schema(), indent=2)
        return _env().from_string(self.body).render(**inputs).strip() + "\n"

    def includes(self) -> list[str]:
        """Names of the prompt parts this body includes (for version records)."""
        env = _env()
        found = jinja2.meta.find_referenced_templates(env.parse(self.body))
        return sorted(name for name in found if name)


def _parse(path: Path, stage: str) -> Prompt:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise ValueError(f"{path}: missing --- front matter")
    head, sep, body = text[4:].partition("\n---\n")
    if not sep:
        raise ValueError(f"{path}: unterminated --- front matter")
    meta = yaml.safe_load(head) or {}
    if not isinstance(meta.get("version"), int):
        raise ValueError(f"{path}: front matter needs an integer `version`")
    if meta.get("stage", stage) != stage:
        raise ValueError(f"{path}: stage {meta['stage']!r} doesn't match file name")
    return Prompt(stage=stage, version=meta["version"], schema_name=meta.get("schema"), body=body)


@cache
def load_prompt(stage: str) -> Prompt:
    """A committed prompt: server/prompts/<stage>.txt (required)."""
    return _parse(config.PROMPTS_DIR / f"{stage}.txt", stage)


def load_local_prompt(name: str) -> Prompt | None:
    """A local-only prompt part such as `_juhi_voice.md`, or None (with a warning) if absent."""
    if name not in LOCAL_ONLY:
        raise ValueError(f"{name!r} is not a local-only prompt part")
    path = config.PROMPTS_DIR / name
    if not path.exists():
        log.warning("%s not found; using a neutral style", name)
        return None
    stage = name.removesuffix(".md")
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return Prompt(stage=stage, version=0, body=text)  # front matter is optional here
    return _parse(path, stage)


def _source(name: str) -> str | None:
    if name in LOCAL_ONLY:
        part = load_local_prompt(name)
        return None if part is None else part.body
    if name.endswith(".txt"):
        return load_prompt(name.removesuffix(".txt")).body
    raise jinja2.TemplateNotFound(f"{name} (prompt includes must end in .txt or be LOCAL_ONLY)")


@cache
def _env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FunctionLoader(_source),
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )


def prompt_versions(stage: str) -> dict[str, int]:
    """{part: version} for a stage prompt and every committed part it includes."""
    prompt = load_prompt(stage)
    versions = {stage: prompt.version}
    for name in prompt.includes():
        if name.endswith(".txt"):
            versions.update(prompt_versions(name.removesuffix(".txt")))
        elif name in LOCAL_ONLY:
            part = load_local_prompt(name)
            if part is not None:
                versions[part.stage] = part.version
    return versions
