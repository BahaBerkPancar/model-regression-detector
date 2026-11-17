from __future__ import annotations

import builtins
import importlib
import json
import sys
from types import SimpleNamespace

import pytest

from model_regression_detector.bridges.deepeval import (
    export_json,
    load_export,
    results_to_run,
)
from model_regression_detector.cli import main
from model_regression_detector.formats import FormatError, load_run


def test_module_import_does_not_import_deepeval(monkeypatch):
    sys.modules.pop("model_regression_detector.bridges.deepeval", None)
    real_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "deepeval" or name.startswith("deepeval."):
            raise AssertionError("the bridge tried to import deepeval")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    module = importlib.import_module("model_regression_detector.bridges.deepeval")
    assert callable(module.results_to_run)


def test_duck_typed_objects_map_scores_and_repeats():
    metric = SimpleNamespace(name="answer relevancy", score=0.8, success=True)
    binary = SimpleNamespace(name="faithful", score=None, success=False)
    results = [
        SimpleNamespace(name="case-a", success=True, score=0.9, metrics_data=[metric, binary]),
        SimpleNamespace(name="case-a", success=False, score=None, metrics_data=[]),
    ]

    run = results_to_run(results, suite="support", variant="prompt-v2")

    assert run.header.suite == "support"
    assert run.header.meta == {"source": "deepeval", "bridge": "duck-typed"}
    assert [row.repeat for row in run.rows] == [0, 1]
    assert run.rows[0].scores == {
        "success": True,
        "score": 0.9,
        "answer relevancy": 0.8,
        "faithful": False,
    }
    assert run.rows[1].scores == {"success": False}


def test_json_export_and_cli_produce_valid_mrd_jsonl(tmp_path, capsys):
    source = tmp_path / "deepeval.json"
    source.write_text(json.dumps({"testResults": [{
        "name": "case-a",
        "success": True,
        "score": 0.75,
        "metricsData": [{"name": "faithful", "score": 1.0, "success": True}],
    }]}))
    out = tmp_path / "candidate.jsonl"

    assert main([
        "from-deepeval", str(source), "--suite", "support", "--variant", "v2",
        "--created-at", "2026-11-17T00:00:00Z", "--out", str(out),
    ]) == 0

    assert "Wrote 1 result rows" in capsys.readouterr().out
    run = load_run(out)
    assert run.header.suite == "support" and run.header.variant == "v2"
    assert run.header.created_at == "2026-11-17T00:00:00Z"
    assert run.rows[0].scores == {"success": True, "score": 0.75, "faithful": 1.0}


def test_bare_list_can_render_to_stdout(tmp_path, capsys):
    source = tmp_path / "deepeval.json"
    source.write_text('[{"name":"one","success":true,"metrics_data":[]}]')
    assert main(["from-deepeval", str(source)]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert json.loads(lines[0])["suite"] == "deepeval"
    assert json.loads(lines[1])["case_id"] == "one"
    assert export_json(source) == "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ({"other": []}, "expected a test_results"),
        ({"test_results": []}, "results are empty"),
        ({"test_results": [{"name": "x", "success": "yes"}]}, "must be true or false"),
        ({"test_results": [{"name": "x", "success": True, "score": float("inf")}]},
         "must be finite"),
        ({"test_results": [{"name": "x", "success": True,
                            "metrics_data": [{"name": "success", "score": 1.0}]}]},
         "collides"),
    ],
)
def test_bad_exports_fail_clearly(tmp_path, payload, message):
    source = tmp_path / "bad.json"
    source.write_text(json.dumps(payload))
    with pytest.raises((FormatError, ValueError), match=message):
        export_json(source)


def test_load_export_reports_invalid_json(tmp_path):
    source = tmp_path / "bad.json"
    source.write_text("{")
    with pytest.raises(FormatError, match="invalid JSON at line 1"):
        load_export(source)
