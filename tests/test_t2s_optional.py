from __future__ import annotations

import builtins

import pytest

from model_regression_detector.adapters import t2s


def test_optional_dependency_has_readable_guard(monkeypatch):
    real_import = builtins.__import__

    def guarded(name, *args, **kwargs):
        if name == "text_to_sql_guardrails":
            raise ImportError("simulated missing extra")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded)
    with pytest.raises(RuntimeError, match="uv sync --extra t2s"):
        t2s.require_t2s()
