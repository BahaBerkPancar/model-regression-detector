import importlib.util
import json
from pathlib import Path

import pytest

from model_regression_detector import __version__
from model_regression_detector.cli import main

ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / "examples" / "qa"


def compare_args(candidate, *extra):
    return ["compare", "--suite", str(QA / "suite.yaml"), "--baseline", str(QA / "baseline.jsonl"),
            "--candidate", str(QA / candidate), "--config", str(QA / "mrd.toml"), *extra]


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_usage_errors_exit_3(capsys):
    for argv in ([], ["bogus"], ["compare"], ["compare", "--suite", "x"]):
        with pytest.raises(SystemExit) as exc:
            main(argv)
        assert exc.value.code == 3
    capsys.readouterr()


def test_example_regression_exits_1(capsys):
    assert main(compare_args("candidate_regress.jsonl")) == 1
    out = capsys.readouterr().out
    assert out.startswith("# Model regression check: REGRESSION")
    assert "math-02" in out


def test_example_noise_exits_0(capsys):
    assert main(compare_args("candidate_noise.jsonl")) == 0
    assert capsys.readouterr().out.startswith("# Model regression check: NO_CHANGE")


def test_writes_md_and_json_and_report_rerenders(tmp_path, capsys):
    md, js = tmp_path / "out.md", tmp_path / "out.json"
    assert main(compare_args("candidate_regress.jsonl", "--md", str(md), "--json", str(js))) == 1
    assert "Verdict: REGRESSION" in capsys.readouterr().out
    data = json.loads(js.read_text())
    assert data["verdict"] == "REGRESSION" and data["n_paired"] == 40
    again = tmp_path / "again.md"
    assert main(["report", "--json", str(js), "--md", str(again)]) == 0
    assert again.read_text() == md.read_text()
    assert main(["report", "--json", str(js)]) == 0
    assert capsys.readouterr().out == md.read_text()


def test_inconclusive_exit_codes(tmp_path):
    lines = (QA / "baseline.jsonl").read_text().splitlines()
    kept = [ln for ln in lines if '"case_id": "math-0' not in ln and '"case_id": "facts-0' not in ln]
    cand = tmp_path / "cand.jsonl"
    cand.write_text("\n".join(kept) + "\n")  # 18 of 40 cases missing
    args = ["compare", "--suite", str(QA / "suite.yaml"), "--baseline", str(QA / "baseline.jsonl"),
            "--candidate", str(cand)]
    assert main(args) == 2
    assert main([*args, "--inconclusive-ok"]) == 0


def test_validate(capsys):
    assert main(["validate", str(QA / "suite.yaml"), str(QA / "baseline.jsonl"),
                 str(QA / "candidate_noise.jsonl")]) == 0
    assert capsys.readouterr().out.count(": ok") == 3


def test_format_errors_exit_3(tmp_path, capsys):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"type": "run", "suite": "qa-toy", "variant": "v"}\n{oops\n')
    assert main(["validate", str(QA / "suite.yaml"), str(bad)]) == 3
    assert "bad.jsonl:2: invalid JSON" in capsys.readouterr().err
    assert main(["validate", str(tmp_path / "missing.yaml")]) == 3
    missing_cfg = compare_args("candidate_noise.jsonl")
    missing_cfg[missing_cfg.index("--config") + 1] = str(tmp_path / "nope.toml")
    assert main(missing_cfg) == 3
    notjson = tmp_path / "x.json"
    notjson.write_text("[]")
    assert main(["report", "--json", str(notjson)]) == 3


def test_examples_are_reproducible_from_the_generator(tmp_path):
    spec = importlib.util.spec_from_file_location("make_runs", ROOT / "examples" / "make_runs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.write(tmp_path)
    for f in ("suite.yaml", "mrd.toml", "baseline.jsonl", "candidate_regress.jsonl",
              "candidate_noise.jsonl"):
        assert (tmp_path / f).read_text() == (QA / f).read_text(), f


def test_unwritable_output_exits_3_not_1(tmp_path, capsys):
    out = tmp_path / "no_such_dir" / "r.md"
    assert main(compare_args("candidate_regress.jsonl", "--md", str(out))) == 3
    assert "error:" in capsys.readouterr().err
    assert main(compare_args("candidate_regress.jsonl", "--json", str(out))) == 3


def test_infinite_latency_exits_3(tmp_path, capsys):
    lines = (QA / "baseline.jsonl").read_text().splitlines()[:1]
    lines.append('{"case_id": "math-01", "scores": {"correct": true, "similarity": 1.0}, '
                 '"latency_ms": Infinity}')
    bad = tmp_path / "bad.jsonl"
    bad.write_text("\n".join(lines) + "\n")
    assert main(["validate", str(QA / "suite.yaml"), str(bad)]) == 3
    assert "bad result line" in capsys.readouterr().err


def test_exit_3_message_includes_exception_type(tmp_path, capsys):
    assert main(compare_args("candidate_regress.jsonl", "--md", str(tmp_path / "x" / "r.md"))) == 3
    assert "error: FileNotFoundError:" in capsys.readouterr().err
