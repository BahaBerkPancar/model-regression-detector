"""Offline SQL generators used by the text-to-SQL adapter."""

from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any


def _types() -> tuple[type[Any], type[Any]]:
    try:
        from text_to_sql_guardrails.llm.base import Generation, LlmRefused
    except ImportError as exc:  # pragma: no cover - exercised through the adapter guard
        raise RuntimeError("install the t2s extra with `uv sync --extra t2s`") from exc
    return Generation, LlmRefused


class RecordedGenerator:
    """Replay question-keyed model generations from JSONL."""

    def __init__(self, path: str | Path, model: str = "recorded") -> None:
        self.model = model
        self.rows: dict[str, dict[str, Any]] = {}
        for lineno, line in enumerate(Path(path).read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict) or not isinstance(row.get("question"), str):
                raise TypeError(f"{path}:{lineno}: expected an object with a question")
            self.rows[row["question"]] = row

    def generate(self, question: str, schema_prompt: str, previous: list[Any]) -> Any:
        del schema_prompt, previous
        Generation, _ = _types()
        row = self.rows.get(question)
        if row is None:
            return Generation(None, "No recorded generation", self.model, 0, 0)
        refusal = row.get("refusal", row.get("cannot_answer"))
        sql = row.get("sql")
        if sql is not None and not isinstance(sql, str):
            raise ValueError(f"recorded SQL for {question!r} must be a string or null")
        if refusal is not None and not isinstance(refusal, str):
            raise ValueError(f"recorded refusal for {question!r} must be a string or null")
        if bool(sql) == bool(refusal):
            raise ValueError(f"recorded generation for {question!r} needs exactly one of sql/refusal")
        return Generation(sql, refusal, self.model, 0, 0)


def mutate_sql(sql: str, name: str, *, key: str = "", seed: int = 17) -> str:
    """Apply one deterministic, AST-based regression mutation."""
    from sqlglot import exp, parse_one

    tree = parse_one(sql, read="postgres")
    if name == "drop-order-by":
        tree.set("order", None)
    elif name == "off-by-one-limit":
        limit = tree.args.get("limit")
        if limit and isinstance(limit.expression, exp.Literal) and limit.expression.is_int:
            value = int(limit.expression.this)
            if value > 0:
                limit.set("expression", exp.Literal.number(value - 1))
    elif name == "wrong-join":
        join = next(tree.find_all(exp.Join), None)
        equality = next(join.find_all(exp.EQ), None) if join else None
        if equality and isinstance(equality.expression, exp.Column):
            right = equality.expression.copy()
            right.set("this", exp.Identifier(this="id"))
            equality.set("expression", right)
    elif name == "harmless-function":
        predicate = "REVERSE(REVERSE('mrd')) = 'mrd'"
        for select in tree.find_all(exp.Select):
            select.where(predicate, copy=False)
    elif name == "noise":
        selected = int.from_bytes(hashlib.sha256(f"{seed}:{key}".encode()).digest()[:2]) % 8 == 0
        if selected:
            tree.set("limit", exp.Limit(expression=exp.Literal.number(1)))
            return tree.sql(dialect="postgres")
        digest = hashlib.sha256(f"{seed}:{key}".encode()).digest()
        rng = random.Random(digest)
        if rng.randrange(10) < 2:
            return "  " + tree.sql(dialect="postgres", pretty=True) + "  "
    else:
        raise ValueError(f"unknown t2s mutation {name!r}")
    return tree.sql(dialect="postgres")


class MutatedGoldGenerator:
    """Generate gold SQL after deterministic prompt-regression mutations."""

    def __init__(self, questions: list[Any], names: list[str], seed: int = 17) -> None:
        self.questions = {item.question: item for item in questions}
        self.names = names
        self.seed = seed
        self.model = "mutated:" + "+".join(names)

    def generate(self, question: str, schema_prompt: str, previous: list[Any]) -> Any:
        del schema_prompt, previous
        Generation, _ = _types()
        item = self.questions.get(question)
        if item is None:
            if "leaky" in self.names:
                return Generation("SELECT email FROM customers", None, self.model, 0, 0)
            return Generation(None, "Request is outside the allowed schema", self.model, 0, 0)
        sql = item.gold_sql
        for name in self.names:
            if name == "leaky":
                continue
            if name == "wrong-join":
                chosen = int.from_bytes(
                    hashlib.sha256(f"{self.seed}:{item.id}:wrong-join".encode()).digest()[:2],
                    "big",
                ) % 2 == 0
                if item.category != "join" or not chosen:
                    continue
            sql = mutate_sql(sql, name, key=item.id, seed=self.seed)
        return Generation(sql, None, self.model, 0, 0)


def make_generator(spec: str, questions: list[Any], *, model: str, seed: int = 17) -> Any:
    """Build an offline generator. The paid generator is created by the runner only."""
    if spec == "gold":
        from text_to_sql_guardrails.bench.llm import GoldSqlGenerator

        return GoldSqlGenerator(questions, model)
    if spec.startswith("mutated:"):
        names = [part for part in spec.removeprefix("mutated:").split("+") if part]
        if not names:
            raise ValueError("mutated generator needs at least one mutation name")
        return MutatedGoldGenerator(questions, names, seed=seed)
    if spec.startswith("recorded:"):
        return RecordedGenerator(spec.removeprefix("recorded:"), model)
    raise ValueError(f"unknown t2s generator {spec!r}")
