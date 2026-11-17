"""Convert DeepEval-style result objects or exported JSON into an mrd run.

The bridge deliberately does not import DeepEval.  It reads the small result
surface it needs by attribute/key name, so callers can use it with exported
JSON or with compatible result objects without adding DeepEval to mrd's core.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from ..formats import FormatError, Run, RunHeader, RunRow

_MISSING = object()


def _field(value: Any, *names: str, default: Any = _MISSING) -> Any:
    for name in names:
        if isinstance(value, Mapping) and name in value:
            return value[name]
        if hasattr(value, name):
            return getattr(value, name)
    if default is not _MISSING:
        return default
    raise ValueError(f"missing field {names[0]!r}")


def _finite_number(value: Any, label: str) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{label} must be a number, got {value!r}")
    if not math.isfinite(value):
        raise ValueError(f"{label} must be finite, got {value!r}")
    return value


def _success(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise TypeError(f"{label} must be true or false, got {value!r}")
    return value


def _metric_value(metric: Any, result_index: int, metric_index: int) -> tuple[str, bool | int | float]:
    where = f"result {result_index} metric {metric_index}"
    name = _field(metric, "name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{where} name must be a non-empty string")

    score = _field(metric, "score", default=None)
    if score is not None:
        return name, _finite_number(score, f"{where} score")
    success = _field(metric, "success", default=_MISSING)
    if success is _MISSING:
        raise ValueError(f"{where} must have a score or success value")
    return name, _success(success, f"{where} success")


def results_to_run(
    test_results: Iterable[Any],
    *,
    suite: str = "deepeval",
    variant: str = "candidate",
    created_at: str | None = None,
) -> Run:
    """Convert duck-typed DeepEval test results into an in-memory mrd run.

    Repeated result names are represented as mrd repeats in input order.
    Metric scores take precedence over metric success flags; a success flag is
    used when the metric does not expose a numeric score.
    """
    if not suite:
        raise ValueError("suite must not be empty")
    if not variant:
        raise ValueError("variant must not be empty")

    repeats: defaultdict[str, int] = defaultdict(int)
    rows: list[RunRow] = []
    for result_index, result in enumerate(test_results, start=1):
        try:
            name = _field(result, "name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError("name must be a non-empty string")

            scores: dict[str, bool | int | float] = {
                "success": _success(_field(result, "success"), f"result {result_index} success")
            }
            score = _field(result, "score", default=None)
            if score is not None:
                scores["score"] = _finite_number(score, f"result {result_index} score")

            metrics = _field(result, "metrics_data", "metricsData", default=[])
            if metrics is None:
                metrics = []
            if isinstance(metrics, (str, bytes, Mapping)) or not isinstance(metrics, Iterable):
                raise TypeError("metrics_data must be a list")
            for metric_index, metric in enumerate(metrics, start=1):
                metric_name, metric_value = _metric_value(metric, result_index, metric_index)
                if metric_name in scores:
                    raise ValueError(f"metric name {metric_name!r} collides with another score")
                scores[metric_name] = metric_value

            repeat = repeats[name]
            repeats[name] += 1
            rows.append(RunRow(case_id=name, repeat=repeat, scores=scores))
        except (TypeError, ValueError) as exc:
            raise ValueError(f"DeepEval result {result_index}: {exc}") from exc

    if not rows:
        raise ValueError("DeepEval results are empty")
    header = RunHeader(
        type="run",
        suite=suite,
        variant=variant,
        created_at=created_at,
        meta={"source": "deepeval", "bridge": "duck-typed"},
    )
    return Run(header=header, rows=rows)


def load_export(path: str | Path) -> list[Any]:
    """Read the supported DeepEval JSON export shapes from *path*."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise FormatError(f"{path}: cannot read file: {exc.strerror}") from exc
    except json.JSONDecodeError as exc:
        raise FormatError(f"{path}: invalid JSON at line {exc.lineno}: {exc.msg}") from exc

    if isinstance(raw, dict):
        raw = raw.get("test_results", raw.get("testResults", _MISSING))
        if raw is _MISSING:
            raise FormatError(f"{path}: expected a test_results or testResults list")
    if not isinstance(raw, list):
        raise FormatError(f"{path}: expected a JSON list of DeepEval test results")
    return raw


def render_jsonl(run: Run) -> str:
    """Serialize an mrd run using the repository's JSONL schema."""
    objects = [run.header.model_dump(exclude_none=True)]
    objects.extend(row.model_dump(exclude_none=True) for row in run.rows)
    return "".join(json.dumps(obj, ensure_ascii=False, separators=(",", ":")) + "\n" for obj in objects)


def export_json(
    source: str | Path,
    *,
    suite: str = "deepeval",
    variant: str = "candidate",
    created_at: str | None = None,
) -> str:
    """Convert a supported DeepEval JSON export to mrd JSONL text."""
    return render_jsonl(
        results_to_run(load_export(source), suite=suite, variant=variant, created_at=created_at)
    )
