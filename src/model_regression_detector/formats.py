"""Suite and run formats: pydantic models plus loaders with readable errors."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class FormatError(Exception):
    """A file is malformed. The message always names the file and a line or case id."""


class Metric(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    kind: Literal["pass_fail", "score"]
    higher_is_better: bool = True
    weight: float = 1.0

    @model_validator(mode="after")
    def _check(self) -> Metric:
        if self.kind == "pass_fail" and not self.higher_is_better:
            raise ValueError("a pass_fail metric must have higher_is_better: true")
        return self


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    input: Any
    expected: Any = None
    tags: list[str] = Field(default_factory=list)


class Suite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1)
    metrics: list[Metric] = Field(min_length=1)
    cases: list[Case] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique(self) -> Suite:
        for label, items in (("metric name", [m.name for m in self.metrics]),
                             ("case id", [c.id for c in self.cases])):
            seen: set[str] = set()
            for item in items:
                if item in seen:
                    raise ValueError(f"duplicate {label} {item!r}")
                seen.add(item)
        return self

    def metric(self, name: str) -> Metric:
        return next(m for m in self.metrics if m.name == name)


class RunHeader(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: Literal["run"]
    suite: str
    variant: str
    created_at: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)


class RunRow(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: str
    repeat: int = Field(default=0, ge=0)
    output: Any = None
    scores: dict[str, Any] = Field(default_factory=dict)
    latency_ms: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    cost_usd: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    error: str | None = None


@dataclass
class Run:
    header: RunHeader
    rows: list[RunRow]
    lines: list[int] = field(default_factory=list)

    def by_case(self) -> dict[str, list[RunRow]]:
        out: dict[str, list[RunRow]] = {}
        for row in self.rows:
            out.setdefault(row.case_id, []).append(row)
        return out


def _describe(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "(root)"
        msg = err["msg"].removeprefix("Value error, ")
        parts.append(f"{loc}: {msg}")
    return "; ".join(parts)


def load_suite(path: str | Path) -> Suite:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FormatError(f"{path}: cannot read file: {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f"line {mark.line + 1}" if mark else "unknown line"
        raise FormatError(f"{path}: invalid YAML at {where}") from exc
    if not isinstance(raw, dict):
        raise FormatError(f"{path}: the suite must be a YAML mapping with name, metrics, cases")
    try:
        return Suite.model_validate(raw)
    except ValidationError as exc:
        parts = []
        cases = raw.get("cases") if isinstance(raw.get("cases"), list) else []
        for err in exc.errors():
            loc = err["loc"]
            msg = err["msg"].removeprefix("Value error, ")
            label = ".".join(str(p) for p in loc) or "(root)"
            if len(loc) >= 2 and loc[0] == "cases" and isinstance(loc[1], int):
                item = cases[loc[1]] if loc[1] < len(cases) else None
                cid = item.get("id") if isinstance(item, dict) else None
                label = f"case {cid!r} (#{loc[1] + 1})" + "".join(f".{p}" for p in loc[2:])
            parts.append(f"{label}: {msg}")
        raise FormatError(f"{path}: " + "; ".join(parts)) from exc


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def load_run(path: str | Path, suite: Suite | None = None) -> Run:
    path = Path(path)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise FormatError(f"{path}: cannot read file: {exc.strerror}") from exc
    header: RunHeader | None = None
    rows: list[RunRow] = []
    lines: list[int] = []
    seen: set[tuple[str, int]] = set()
    metrics = {m.name: m for m in suite.metrics} if suite else {}
    case_ids = {c.id for c in suite.cases} if suite else set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        where = f"{path}:{lineno}"
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            raise FormatError(f"{where}: invalid JSON: {exc.msg}") from exc
        if not isinstance(obj, dict):
            raise FormatError(f"{where}: each line must be a JSON object")
        if header is None:
            try:
                header = RunHeader.model_validate(obj)
            except ValidationError as exc:
                raise FormatError(f"{where}: bad run header: {_describe(exc)}") from exc
            if suite and header.suite != suite.name:
                raise FormatError(
                    f"{where}: run is for suite {header.suite!r}, expected {suite.name!r}"
                )
            continue
        try:
            row = RunRow.model_validate(obj)
        except ValidationError as exc:
            raise FormatError(f"{where}: bad result line: {_describe(exc)}") from exc
        key = (row.case_id, row.repeat)
        if key in seen:
            raise FormatError(f"{where}: duplicate result for case {row.case_id!r} repeat {row.repeat}")
        seen.add(key)
        if suite:
            if row.case_id not in case_ids:
                raise FormatError(f"{where}: case {row.case_id!r} is not in the suite")
            for name, value in row.scores.items():
                if name not in metrics:
                    raise FormatError(f"{where}: case {row.case_id!r}: unknown metric {name!r}")
                if metrics[name].kind == "pass_fail" and not isinstance(value, bool):
                    raise FormatError(
                        f"{where}: case {row.case_id!r}: metric {name!r} is pass_fail, "
                        f"expected true/false, got {value!r}"
                    )
                if metrics[name].kind == "score" and not _is_number(value):
                    raise FormatError(
                        f"{where}: case {row.case_id!r}: metric {name!r} is a score, "
                        f"expected a finite number, got {value!r}"
                    )
            if row.error is None:
                missing = [n for n in metrics if n not in row.scores]
                if missing:
                    raise FormatError(
                        f"{where}: case {row.case_id!r}: missing scores for {', '.join(missing)}"
                    )
        rows.append(row)
        lines.append(lineno)
    if header is None:
        raise FormatError(f"{path}:1: empty file, expected a run header line")
    return Run(header=header, rows=rows, lines=lines)
