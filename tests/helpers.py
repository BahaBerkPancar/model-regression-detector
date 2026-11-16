"""Builders for synthetic suites and runs with known answers."""

from __future__ import annotations

from model_regression_detector.formats import Run, RunHeader, RunRow, Suite


def make_suite(n: int = 20, tags: dict[str, range] | None = None, score: bool = False) -> Suite:
    metrics = [{"name": "ok", "kind": "pass_fail"}]
    if score:
        metrics.append({"name": "sim", "kind": "score"})
    cases = []
    for i in range(n):
        case_tags = [t for t, r in (tags or {}).items() if i in r]
        cases.append({"id": f"c{i:02d}", "input": f"q{i}", "expected": f"a{i}", "tags": case_tags})
    return Suite.model_validate({"name": "s", "metrics": metrics, "cases": cases})


def make_run(variant: str, results: dict[str, list[bool] | bool], *,
             sims: dict[str, float] | None = None, errors: set[str] | None = None,
             latency: dict[str, float] | None = None, cost: dict[str, float] | None = None,
             outputs: dict[str, str] | None = None) -> Run:
    rows: list[RunRow] = []
    for cid, flags in results.items():
        flags = [flags] if isinstance(flags, bool) else flags
        for rep, ok in enumerate(flags):
            scores: dict = {"ok": ok}
            if sims is not None:
                scores["sim"] = sims[cid]
            rows.append(RunRow(
                case_id=cid, repeat=rep, scores=scores,
                output=(outputs or {}).get(cid, "x"),
                error="boom" if errors and cid in errors else None,
                latency_ms=(latency or {}).get(cid), cost_usd=(cost or {}).get(cid)))
    header = RunHeader(type="run", suite="s", variant=variant)
    return Run(header=header, rows=rows)


def all_pass(n: int = 20) -> dict[str, bool]:
    return {f"c{i:02d}": True for i in range(n)}


def with_fail(base: dict[str, bool], ids: list[int]) -> dict[str, bool]:
    out = dict(base)
    for i in ids:
        out[f"c{i:02d}"] = False
    return out
