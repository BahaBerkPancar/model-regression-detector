"""Config (mrd.toml) loading."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .formats import FormatError, Suite


class TagOverride(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alpha: float | None = Field(default=None, gt=0, lt=1)
    min_effect: dict[str, float] = Field(default_factory=dict)


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    alpha: float = Field(default=0.05, gt=0, lt=1)
    min_effect: dict[str, float] = Field(default_factory=dict)
    default_min_effect: float = Field(default=0.05, ge=0)
    bootstrap_samples: int = Field(default=10000, ge=100)
    seed: int = 0
    fail_on: Literal["regression", "any_case_newly_failing"] = "regression"
    max_latency_regression_pct: float | None = None
    max_cost_regression_pct: float | None = None
    tags: dict[str, TagOverride] = Field(default_factory=dict)

    def min_effect_for(self, metric: str, kind: str, tag: str | None = None) -> float:
        if tag is not None and metric in self.tags.get(tag, TagOverride()).min_effect:
            return self.tags[tag].min_effect[metric]
        if metric in self.min_effect:
            return self.min_effect[metric]
        return self.default_min_effect if kind == "pass_fail" else 0.0

    def alpha_for(self, tag: str | None = None) -> float:
        if tag is not None and self.tags.get(tag) and self.tags[tag].alpha is not None:
            return self.tags[tag].alpha  # type: ignore[return-value]
        return self.alpha

    def check_against(self, suite: Suite, path: str | Path = "config") -> None:
        names = {m.name for m in suite.metrics}
        unknown = set(self.min_effect) | {m for t in self.tags.values() for m in t.min_effect}
        if unknown - names:
            raise FormatError(
                f"{path}: min_effect names unknown metric(s): {', '.join(sorted(unknown - names))}"
            )


def load_config(path: str | Path | None) -> Config:
    if path is None:
        return Config()
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FormatError(f"{path}: cannot read file: {exc.strerror}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise FormatError(f"{path}: invalid TOML: {exc}") from exc
    try:
        return Config.model_validate(raw)
    except ValidationError as exc:
        parts = [
            f"{'.'.join(str(p) for p in e['loc']) or '(root)'}: {e['msg']}" for e in exc.errors()
        ]
        raise FormatError(f"{path}: " + "; ".join(parts)) from exc
