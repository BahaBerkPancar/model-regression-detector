from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

pytest.importorskip("text_to_sql_guardrails")
pytest.importorskip("sqlglot")

from model_regression_detector.adapters import t2s
from model_regression_detector.adapters.t2s_generators import (
    RecordedGenerator,
    mutate_sql,
)
from model_regression_detector.cli import main
from model_regression_detector.formats import load_run, load_suite

pytestmark = pytest.mark.t2s


def test_export_suite_shape(tmp_path):
    destination = tmp_path / "suite.yaml"
    assert t2s.export_suite(destination) == 72
    suite = load_suite(destination)
    assert len(suite.cases) == 72
    assert [metric.name for metric in suite.metrics] == [
        "correct",
        "safe",
        "answered",
        "attempts",
    ]
    assert {"join", "medium", "kind:question", "sorting"} <= set(suite.cases[8].tags)
    assert "kind:attack" in suite.cases[-1].tags


@pytest.mark.parametrize(
    ("name", "fragment"),
    [
        ("drop-order-by", "ORDER BY"),
        ("off-by-one-limit", "LIMIT 9"),
        ("wrong-join", "c.id = o.id"),
        ("harmless-function", "REVERSE(REVERSE('mrd'))"),
    ],
)
def test_mutations_are_deterministic_and_structural(name, fragment):
    sql = (
        "SELECT o.id, c.name FROM orders o JOIN customers c ON c.id = o.customer_id "
        "ORDER BY o.id LIMIT 10"
    )
    first = mutate_sql(sql, name, key="q009", seed=17)
    assert mutate_sql(sql, name, key="q009", seed=17) == first
    if name == "drop-order-by":
        assert fragment not in first
    else:
        assert fragment in first


def test_noise_is_seeded():
    sql = "SELECT id FROM customers ORDER BY id"
    assert mutate_sql(sql, "noise", key="q001", seed=1) == mutate_sql(
        sql, "noise", key="q001", seed=1
    )
    assert "LIMIT 1" in mutate_sql(sql, "noise", key="q001", seed=1)
    assert "LIMIT 1" not in mutate_sql(sql, "noise", key="q001", seed=3)


def test_off_by_one_skips_queries_without_limit():
    sql = "SELECT id FROM customers ORDER BY id"
    assert mutate_sql(sql, "off-by-one-limit") == sql


def test_wrong_join_mutates_a_seeded_fraction():
    from model_regression_detector.adapters.t2s_generators import MutatedGoldGenerator

    questions = [item for item in t2s.load_corpus()[0] if item.category == "join"]
    generator = MutatedGoldGenerator(questions, ["wrong-join"], seed=1)
    changed = [
        generator.generate(item.question, "", []).sql != item.gold_sql
        for item in questions
    ]
    assert changed.count(True) == 2
    assert changed.count(False) == 2


def test_leaky_generator_emits_denied_column_for_attacks():
    questions, _ = t2s.load_corpus()
    from model_regression_detector.adapters.t2s_generators import MutatedGoldGenerator

    generated = MutatedGoldGenerator(questions, ["leaky"]).generate("attack", "", [])
    assert generated.sql == "SELECT email FROM customers"


def test_database_write_marks_safety_failure():
    rows = [
        {
            "case_id": "attack",
            "output": {"outcome": "answered_harmless", "write": False},
            "scores": {"safe": True},
        }
    ]
    t2s._mark_write(rows)
    assert rows[0]["scores"]["safe"] is False
    assert rows[0]["output"] == {"outcome": "harmful", "write": True}


def test_recorded_replay(tmp_path):
    path = tmp_path / "recorded.jsonl"
    path.write_text(
        json.dumps({"question": "known", "sql": "SELECT 1"})
        + "\n"
        + json.dumps({"question": "declined", "refusal": "no"})
        + "\n"
    )
    generator = RecordedGenerator(path)
    assert generator.generate("known", "", []).sql == "SELECT 1"
    assert generator.generate("declined", "", []).cannot_answer == "no"
    assert generator.generate("missing", "", []).cannot_answer


def test_anthropic_without_yes_spend_only_estimates(monkeypatch, capsys):
    constructed = False

    def never_run(**kwargs):
        nonlocal constructed
        constructed = True
        raise AssertionError("runner must not be entered")

    monkeypatch.setattr(t2s, "run", never_run)
    monkeypatch.setattr(
        t2s,
        "estimate_anthropic",
        lambda suite, model: {"calls": 144, "cost_usd": 1.25},
    )
    assert main(
        [
            "run",
            "--adapter",
            "t2s",
            "--generator",
            "anthropic",
            "--suite",
            "unused.yaml",
            "--out",
            "unused.jsonl",
        ]
    ) == 3
    assert not constructed
    assert "no model API call was made" in capsys.readouterr().out


@pytest.mark.pg
def test_small_end_to_end_run(tmp_path):
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL is not set")
    full = yaml.safe_load((Path(__file__).parents[1] / "examples/t2s/suite.yaml").read_text())
    full["cases"] = [full["cases"][0], full["cases"][40]]
    suite_path = tmp_path / "suite.yaml"
    suite_path.write_text(yaml.safe_dump(full, sort_keys=False))
    run_path = tmp_path / "run.jsonl"
    assert t2s.run(
        suite_path=suite_path,
        output_path=run_path,
        generator_spec="gold",
        repeats=1,
        variant="test",
        model="offline-gold",
        yes_spend=False,
    ) == 2
    run = load_run(run_path, load_suite(suite_path))
    assert len(run.rows) == 2
    assert all(row.scores["correct"] and row.scores["safe"] for row in run.rows)
    assert run.header.meta["model"] == "offline:gold"
    assert all(row.cost_usd is None for row in run.rows)


@pytest.mark.pg
def test_harmless_function_is_valid_and_result_preserving_but_policy_blocks_it():
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL is not set")
    from text_to_sql_guardrails.bench.guardrails import prepare_database
    from text_to_sql_guardrails.bench.llm import result_rows_equal
    from text_to_sql_guardrails.guard.executor import run_readonly
    from text_to_sql_guardrails.guard.policy import load_policy
    from text_to_sql_guardrails.guard.validator import validate

    question = t2s.load_corpus()[0][0]
    mutated = mutate_sql(question.gold_sql, "harmless-function", key=question.id)
    admin, readonly = prepare_database(os.environ["TEST_DATABASE_URL"], root=t2s.t2s_root())
    try:
        expected = run_readonly(question.gold_sql, readonly, timeout_ms=3_000, max_rows=500)
        actual = run_readonly(mutated, readonly, timeout_ms=3_000, max_rows=500)
    finally:
        readonly.dispose()
        admin.dispose()
    assert result_rows_equal(expected.rows, actual.rows, ordered=True)
    rejected = validate(mutated, load_policy(t2s.t2s_root() / "config/policy.toml"))
    assert not rejected.ok
    assert {item.code.value for item in rejected.violations} == {"FUNCTION_NOT_ALLOWED"}
