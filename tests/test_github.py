from pathlib import Path

from model_regression_detector.cli import main
from model_regression_detector.github import (
    SUMMARY_LIMIT,
    TRUNCATION_NOTE,
    _workflow_escape,
    append_step_summary,
    publish_comparison,
)

ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / "examples" / "qa"


def _args(candidate):
    return [
        "compare", "--suite", str(QA / "suite.yaml"),
        "--baseline", str(QA / "baseline.jsonl"),
        "--candidate", str(QA / candidate),
        "--config", str(QA / "mrd.toml"),
    ]


def test_compare_writes_github_summary_outputs_and_annotation(tmp_path, monkeypatch, capsys):
    summary = tmp_path / "summary.md"
    output = tmp_path / "output.txt"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    assert main(_args("candidate_regress.jsonl")) == 1
    assert summary.read_text().startswith("# Model regression check: REGRESSION")
    assert output.read_text().splitlines() == [
        "verdict=REGRESSION", "exit_code=1", "regressed_metrics=correct,similarity"
    ]
    stdout = capsys.readouterr().out
    assert "Verdict: REGRESSION" in stdout
    assert "# Model regression check" not in stdout
    assert "::error::" in stdout


def test_inconclusive_ok_output_reports_effective_exit_code(tmp_path, monkeypatch):
    lines = (QA / "baseline.jsonl").read_text().splitlines()
    candidate = tmp_path / "short.jsonl"
    candidate.write_text("\n".join(lines[:4]) + "\n")
    output = tmp_path / "output.txt"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    args = [
        "compare", "--suite", str(QA / "suite.yaml"),
        "--baseline", str(QA / "baseline.jsonl"), "--candidate", str(candidate),
        "--inconclusive-ok",
    ]
    assert main(args) == 0
    assert "verdict=INCONCLUSIVE\nexit_code=0\n" in output.read_text()


def test_hostile_workflow_command_text_is_one_escaped_command(capsys, tmp_path):
    hostile = "bad%\r\n::error::injected"
    assert _workflow_escape(hostile) == "bad%25%0D%0A::error::injected"
    result = {
        "verdict": "REGRESSION",
        "reasons": [hostile],
        "metrics": [{"name": "x\r\ny", "verdict": "REGRESSION"}],
    }
    output = tmp_path / "output.txt"
    publish_comparison(result, "report", 1)
    assert capsys.readouterr().out == ""
    # Supplying a protocol file activates annotations and flattens output values.
    import os

    os.environ["GITHUB_OUTPUT"] = str(output)
    try:
        publish_comparison(result, "report", 1)
    finally:
        os.environ.pop("GITHUB_OUTPUT")
    assert capsys.readouterr().out.splitlines() == [
        "::error::bad%25%0D%0A::error::injected"
    ]
    assert "regressed_metrics=x  y" in output.read_text()


def test_summary_is_capped_with_truncation_note(tmp_path):
    summary = tmp_path / "summary.md"
    append_step_summary("x" * (SUMMARY_LIMIT + 100), summary)
    assert summary.stat().st_size == SUMMARY_LIMIT
    assert TRUNCATION_NOTE.strip() in summary.read_text()
