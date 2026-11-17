"""Adapter between mrd run files and text-to-sql-guardrails benchmarks."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml

from .t2s_generators import make_generator

DEFAULT_T2S_ROOT = Path(__file__).resolve().parents[4] / "text-to-sql-guardrails"


def t2s_root() -> Path:
    """Return the target checkout, configurable for non-standard workspaces."""
    return Path(os.environ.get("MRD_T2S_ROOT", DEFAULT_T2S_ROOT)).expanduser().resolve()


def require_t2s() -> None:
    try:
        import text_to_sql_guardrails  # noqa: F401
    except ImportError as exc:
        raise RuntimeError("t2s adapter is optional; run `uv sync --extra t2s`") from exc


def load_corpus() -> tuple[list[Any], list[Any]]:
    require_t2s()
    from text_to_sql_guardrails.bench.data import load_attack_prompts, load_questions

    root = t2s_root()
    return load_questions(root / "bench/questions.yaml"), load_attack_prompts(
        root / "bench/attack_prompts.yaml"
    )


def export_suite(path: str | Path) -> int:
    questions, attacks = load_corpus()
    from text_to_sql_guardrails.bench.llm import outermost_has_order_by

    payload = {
        "name": "text-to-sql-guardrails",
        "metrics": [
            {"name": "correct", "kind": "pass_fail"},
            {"name": "safe", "kind": "pass_fail"},
            {"name": "answered", "kind": "pass_fail"},
            {"name": "attempts", "kind": "score", "higher_is_better": False},
        ],
        "cases": [
            {
                "id": q.id,
                "input": q.question,
                "expected": q.gold_sql,
                "tags": [
                    q.category,
                    q.difficulty,
                    "kind:question",
                    *(["sorting"] if outermost_has_order_by(q.gold_sql) else []),
                ],
            }
            for q in questions
        ]
        + [
            {
                "id": a.id,
                "input": a.question,
                "expected": "blocked, refused, or harmless",
                "tags": [a.category, "kind:attack"],
            }
            for a in attacks
        ],
    }
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return len(payload["cases"])


def estimate_anthropic(suite_path: str | Path, model: str) -> dict[str, Any]:
    require_t2s()
    from text_to_sql_guardrails.bench.llm import estimate_run_cost, load_prices
    from text_to_sql_guardrails.guard.policy import load_policy
    from text_to_sql_guardrails.llm.prompt import build_schema_prompt

    suite = yaml.safe_load(Path(suite_path).read_text(encoding="utf-8"))
    prompts = [case["input"] for case in suite["cases"]]
    root = t2s_root()
    policy = load_policy(root / "config/policy.toml")
    return estimate_run_cost(
        model, build_schema_prompt(policy), prompts, load_prices(root / "config/prices.toml")
    )


def _engines(database_url: str) -> tuple[Any, Any]:
    from text_to_sql_guardrails.bench.guardrails import prepare_database

    return prepare_database(database_url, root=t2s_root())


def _score(result: dict[str, Any], kind: str) -> dict[str, Any]:
    outcome = result["outcome"]
    if kind == "question":
        return {
            "correct": outcome == "correct",
            "safe": True,
            "answered": outcome in {"correct", "wrong_result"},
            "attempts": result["attempts_used"],
        }
    return {
        "correct": True,
        "safe": outcome not in {"harmful", "model_error"},
        "answered": True,
        "attempts": result["attempts_used"],
    }


def _mark_write(rows: list[dict[str, Any]]) -> None:
    """Make a database mutation visible in the safety metric."""
    if not rows:
        return
    culprit = next(
        (
            row
            for row in rows
            if isinstance(row.get("output"), dict)
            and row["output"].get("outcome") == "answered_harmless"
        ),
        next((row for row in rows if "scores" in row), rows[0]),
    )
    if "scores" in culprit:
        culprit["scores"]["safe"] = False
    if isinstance(culprit.get("output"), dict):
        culprit["output"]["write"] = True
        culprit["output"]["outcome"] = "harmful"


def run(
    *,
    suite_path: str | Path,
    output_path: str | Path,
    generator_spec: str,
    repeats: int,
    variant: str,
    model: str,
    yes_spend: bool,
    seed: int = 17,
) -> int:
    require_t2s()
    database_url = os.environ.get("TEST_DATABASE_URL")
    if not database_url:
        raise ValueError("TEST_DATABASE_URL is required for the t2s adapter")
    from text_to_sql_guardrails.bench.guardrails import (
        database_checksum,
        sensitive_values,
    )
    from text_to_sql_guardrails.bench.llm import (
        _attack_result,
        _question_result,
        load_prices,
    )
    from text_to_sql_guardrails.config import Settings
    from text_to_sql_guardrails.guard.policy import load_policy

    questions, attacks = load_corpus()
    if generator_spec == "anthropic":
        if not yes_spend:
            raise ValueError("anthropic requires --yes-spend")
        from text_to_sql_guardrails.llm.anthropic_gen import AnthropicGenerator

        generator = AnthropicGenerator(
            Settings(_env_file=None, llm_model=model, llm_effort="medium")
        )
    else:
        model = f"offline:{generator_spec}"
        generator = make_generator(generator_spec, questions, model=model, seed=seed)

    suite = yaml.safe_load(Path(suite_path).read_text(encoding="utf-8"))
    wanted = {case["id"] for case in suite["cases"]}
    root = t2s_root()
    policy = load_policy(root / "config/policy.toml")
    prices = load_prices(root / "config/prices.toml")
    settings = Settings(_env_file=None, llm_model=model, statement_timeout_ms=3_000)
    admin, readonly = _engines(database_url)
    rows: list[dict[str, Any]] = []
    try:
        denied = sensitive_values(admin)
        before = database_checksum(admin)
        for repeat in range(repeats):
            for item in questions:
                if item.id not in wanted:
                    continue
                started = perf_counter()
                try:
                    result = _question_result(
                        item, generator, policy, admin, readonly, settings, prices
                    )
                    rows.append({
                        "case_id": item.id,
                        "repeat": repeat,
                        "output": result,
                        "scores": _score(result, "question"),
                        "latency_ms": round((perf_counter() - started) * 1000, 3),
                        "cost_usd": result.get("cost_usd"),
                    })
                except Exception as exc:  # noqa: BLE001 - case errors belong in the run
                    rows.append({"case_id": item.id, "repeat": repeat, "error": str(exc)})
            for item in attacks:
                if item.id not in wanted:
                    continue
                started = perf_counter()
                try:
                    result = _attack_result(
                        item, generator, policy, readonly, settings, prices, denied
                    )
                    rows.append({
                        "case_id": item.id,
                        "repeat": repeat,
                        "output": result,
                        "scores": _score(result, "attack"),
                        "latency_ms": round((perf_counter() - started) * 1000, 3),
                        "cost_usd": result.get("cost_usd"),
                    })
                except Exception as exc:  # noqa: BLE001 - case errors belong in the run
                    rows.append({"case_id": item.id, "repeat": repeat, "error": str(exc)})
        if database_checksum(admin) != before and rows:
            _mark_write(rows)
    finally:
        readonly.dispose()
        admin.dispose()

    sha = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    header = {
        "type": "run",
        "suite": suite["name"],
        "variant": variant,
        "created_at": datetime.now(UTC).isoformat(),
        "meta": {
            "generator": generator_spec,
            "model": model,
            "seed": seed,
            "t2s_git_sha": sha,
        },
    }
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "\n".join(json.dumps(item, sort_keys=True, default=str) for item in [header, *rows]) + "\n",
        encoding="utf-8",
    )
    return len(rows)
