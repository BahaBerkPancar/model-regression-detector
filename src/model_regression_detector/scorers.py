"""Pure scoring functions plus a registry so adapters can add their own.

Every scorer takes (output, expected, **options) and returns a bool (pass_fail) or a
float (score).
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Callable
from typing import Any

Scorer = Callable[..., bool | float]
_REGISTRY: dict[str, Scorer] = {}


def register_scorer(name: str) -> Callable[[Scorer], Scorer]:
    def deco(fn: Scorer) -> Scorer:
        if name in _REGISTRY:
            raise ValueError(f"scorer {name!r} is already registered")
        _REGISTRY[name] = fn
        return fn

    return deco


def get_scorer(name: str) -> Scorer:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise KeyError(f"unknown scorer {name!r}; known: {', '.join(sorted(_REGISTRY))}") from None


def scorer_names() -> list[str]:
    return sorted(_REGISTRY)


@register_scorer("exact_match")
def exact_match(
    output: Any,
    expected: Any,
    *,
    strip: bool = True,
    casefold: bool = False,
    collapse_whitespace: bool = False,
) -> bool:
    def norm(value: Any) -> Any:
        if not isinstance(value, str):
            return value
        if strip:
            value = value.strip()
        if collapse_whitespace:
            value = " ".join(value.split())
        if casefold:
            value = value.casefold()
        return value

    return bool(norm(output) == norm(expected))


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value.strip() if isinstance(value, str) else value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


@register_scorer("numeric_tolerance")
def numeric_tolerance(
    output: Any, expected: Any, *, abs_tol: float = 0.0, rel_tol: float = 0.0
) -> bool:
    a, b = _to_float(output), _to_float(expected)
    if a is None or b is None:
        return False
    return math.isclose(a, b, abs_tol=abs_tol, rel_tol=rel_tol)


@register_scorer("regex")
def regex_match(
    output: Any, expected: Any, *, full: bool = False, ignore_case: bool = False
) -> bool:
    """`expected` is the pattern. Searches by default, anchors the whole string if full."""
    flags = re.IGNORECASE if ignore_case else 0
    text = output if isinstance(output, str) else str(output)
    pattern = re.compile(str(expected), flags)
    return bool(pattern.fullmatch(text) if full else pattern.search(text))


def _dig(obj: Any, path: str) -> tuple[bool, Any]:
    cur = obj
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return False, None
    return True, cur


@register_scorer("json_fields")
def json_field_equals(output: Any, expected: Any) -> bool:
    """`expected` maps dotted paths to wanted values; `output` is JSON text or parsed JSON."""
    if isinstance(output, str):
        try:
            output = json.loads(output)
        except json.JSONDecodeError:
            return False
    if not isinstance(expected, dict):
        return False
    for path, wanted in expected.items():
        found, value = _dig(output, str(path))
        if not found or _canon(value) != _canon(wanted):
            return False
    return True


def _canon(value: Any) -> str:
    """Canonical JSON text so 1 and 1.0 compare equal and key order does not matter."""

    def fix(v: Any) -> Any:
        if isinstance(v, float) and v.is_integer():
            return int(v)
        if isinstance(v, dict):
            return {str(k): fix(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [fix(x) for x in v]
        return v

    return json.dumps(fix(value), sort_keys=True, default=str)


@register_scorer("rows_equal")
def rows_equal(
    output: Any, expected: Any, *, ordered: bool = False, distinct: bool = False
) -> bool:
    """Compare lists of rows. Unordered compares as multisets; distinct=True ignores
    duplicates (true set equality). ordered=True needs the same sequence."""
    if not isinstance(output, (list, tuple)) or not isinstance(expected, (list, tuple)):
        return False
    a = [_canon(r) for r in output]
    b = [_canon(r) for r in expected]
    if ordered:
        return a == b
    if distinct:
        return set(a) == set(b)
    return Counter(a) == Counter(b)
