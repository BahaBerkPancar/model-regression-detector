import json
from pathlib import Path

from model_regression_detector.baseline import provenance_path
from model_regression_detector.cli import main

ROOT = Path(__file__).resolve().parent.parent
QA = ROOT / "examples" / "qa"


def test_accept_and_show_baseline_preserves_run_and_records_provenance(tmp_path, capsys):
    target = tmp_path / "accepted.jsonl"
    source = QA / "baseline.jsonl"
    assert main(["baseline", "accept", "--run", str(source), "--to", str(target)]) == 0
    assert target.read_bytes() == source.read_bytes()
    provenance = json.loads(provenance_path(target).read_text())
    assert provenance["suite"] == "qa-toy"
    assert provenance["variant"] == "baseline"
    assert provenance["git_sha"]
    assert provenance["verdict_vs_previous"] == "NOT_APPLICABLE"

    capsys.readouterr()
    assert main(["baseline", "show", str(target)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["rows"] == 40
    assert shown["provenance"]["variant"] == "baseline"


def test_replacing_baseline_records_real_verdict(tmp_path, capsys):
    target = tmp_path / "accepted.jsonl"
    assert main([
        "baseline", "accept", "--run", str(QA / "baseline.jsonl"), "--to", str(target)
    ]) == 0
    capsys.readouterr()
    assert main([
        "baseline", "accept",
        "--run", str(QA / "candidate_regress.jsonl"),
        "--to", str(target),
        "--suite", str(QA / "suite.yaml"),
        "--config", str(QA / "mrd.toml"),
    ]) == 0
    provenance = json.loads(provenance_path(target).read_text())
    assert provenance["previous_variant"] == "baseline"
    assert provenance["verdict_vs_previous"] == "REGRESSION"
    assert target.read_bytes() == (QA / "candidate_regress.jsonl").read_bytes()


def test_replacement_requires_suite_and_rejects_different_suite(tmp_path, capsys):
    target = tmp_path / "accepted.jsonl"
    assert main([
        "baseline", "accept", "--run", str(QA / "baseline.jsonl"), "--to", str(target)
    ]) == 0
    assert main([
        "baseline", "accept", "--run", str(QA / "candidate_noise.jsonl"), "--to", str(target)
    ]) == 3
    assert "--suite is required" in capsys.readouterr().err

    other = tmp_path / "other.jsonl"
    other.write_text('{"type":"run","suite":"other","variant":"x"}\n')
    assert main(["baseline", "accept", "--run", str(other), "--to", str(target)]) == 3
    assert "stores suite 'qa-toy'" in capsys.readouterr().err
