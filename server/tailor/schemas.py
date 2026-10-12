"""Pydantic models that LLM stages return. Named by each prompt's `schema:` front matter."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict


class _Out(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Ping(_Out):
    reply: Literal["pong"]
    sum: int
