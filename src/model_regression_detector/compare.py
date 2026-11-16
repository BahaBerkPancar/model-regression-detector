"""Paired comparison of a candidate run against a baseline run."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from .config import Config
from .formats import Metric, Run, RunRow, Suite
from .stats import (
    EPS,
    bootstrap_ci,
    holm_adjust,
    mcnemar_exact,
    mean,
    min_discordant,
    percentile,
    sign_flip_pvalue,
)

REGRESSION = "REGRESSION"
IMPROVEMENT = "IMPROVEMENT"
NO_CHANGE = "NO_CHANGE"
INCONCLUSIVE = "INCONCLUSIVE"

MAX_MISSING_FRACTION = 0.10
OUTPUT_LIMIT = 500


@dataclass
class MetricResult:
    name: str
    kind: str
    tag: str | None
    n: int
    baseline: float
    candidate: float
    effect: float  # candidate - baseline, raw sign
    ci_low: float
    ci_high: float
    p_value: float
    p_adjusted: float | None
    alpha: float
    min_effect: float
    n_worse: int
    n_better: int
    verdict: str = NO_CHANGE
    reason: str = ""
    higher_is_better: bool = True
    unusable_baseline: list[str] = field(default_factory=list)
    unusable_candidate: list[str] = field(default_factory=list)


@dataclass
class Comparison:
    suite: str
    baseline: dict[str, Any]
    candidate: dict[str, Any]
    settings: dict[str, Any]
    n_suite_cases: int
    n_paired: int
    missing_in_baseline: list[str]
    missing_in_candidate: list[str]
    verdict: str = NO_CHANGE
    reasons: list[str] = field(default_factory=list)
    metrics: list[MetricResult] = field(default_factory=list)
    slices: list[MetricResult] = field(default_factory=list)
    cases: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    latency: dict[str, Any] | None = None
    cost: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > OUTPUT_LIMIT:
        return value[:OUTPUT_LIMIT] + "..."
    return value


def _passes(rows: list[RunRow], metric: str) -> list[bool]:
    return [False if r.error else bool(r.scores.get(metric)) for r in rows]


def _scores(rows: list[RunRow], metric: str) -> list[float]:
    return [float(r.scores[metric]) for r in rows if not r.error and metric in r.scores]


def _majority(flags: list[bool]) -> bool:
    return sum(flags) / len(flags) > 0.5


def _is_flaky(flags: list[bool]) -> bool:
    return any(flags) and not all(flags)


def _stat(metric: Metric, tag: str | None, base: list[float], cand: list[float],
          cfg: Config) -> MetricResult:
    alpha = cfg.alpha_for(tag)
    min_effect = cfg.min_effect_for(metric.name, metric.kind, tag)
    diffs = [c - b for b, c in zip(base, cand, strict=True)]
    sign = 1 if metric.higher_is_better else -1
    n_worse = sum(1 for d in diffs if d * sign < -EPS)
    n_better = sum(1 for d in diffs if d * sign > EPS)
    if not diffs:
        return MetricResult(metric.name, metric.kind, tag, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0,
                            None, alpha, min_effect, 0, 0, INCONCLUSIVE, "no paired cases",
                            metric.higher_is_better)
    if metric.kind == "pass_fail":
        p = mcnemar_exact(n_worse, n_better)
    else:
        p = sign_flip_pvalue(diffs, cfg.bootstrap_samples, cfg.seed)
    lo, hi = bootstrap_ci(diffs, cfg.bootstrap_samples, cfg.seed)
    return MetricResult(metric.name, metric.kind, tag, len(diffs), mean(base), mean(cand),
                        mean(diffs), lo, hi, p, None, alpha, min_effect, n_worse, n_better,
                        higher_is_better=metric.higher_is_better)


def _decide(r: MetricResult, p: float) -> None:
    """Fill in the verdict from the p-value to use (raw, or Holm-adjusted for slices)."""
    differing = r.n_worse + r.n_better
    needed = min_discordant(r.alpha)
    if r.n == 0:
        return
    if r.n < needed:
        r.verdict = INCONCLUSIVE
        r.reason = (f"only {r.n} paired case(s); at least {needed} are needed "
                    f"to ever reach p below {r.alpha}")
        return
    if differing == 0:
        r.verdict, r.reason = NO_CHANGE, "no per-case differences"
        return
    if differing < needed:
        # Too few changed cases to test. Only worth flagging if the change would matter.
        if r.min_effect > 0 and abs(r.effect) >= r.min_effect - EPS:
            r.verdict = INCONCLUSIVE
            r.reason = (f"only {differing} case(s) differ, too few to test (at least {needed} "
                        f"needed for p below {r.alpha}), but the effect {abs(r.effect):.4g} "
                        f"reaches min_effect {r.min_effect}")
        else:
            r.verdict = NO_CHANGE
            if r.min_effect > 0:
                r.reason = f"only {differing} case(s) differ, and the effect is below min_effect"
            else:
                r.reason = (f"only {differing} case(s) differ; set min_effect for {r.name} "
                            "to gate small samples")
        return
    if p >= r.alpha:
        r.verdict, r.reason = NO_CHANGE, f"not significant (p = {p:.4g}, alpha {r.alpha})"
    elif abs(r.effect) < r.min_effect - EPS:
        r.verdict = NO_CHANGE
        r.reason = f"significant (p = {p:.4g}) but the effect {abs(r.effect):.4g} is below min_effect {r.min_effect}"
    else:
        better = (r.effect > 0) == r.higher_is_better
        r.verdict = IMPROVEMENT if better else REGRESSION
        r.reason = f"p = {p:.4g} is below alpha {r.alpha} and the effect {abs(r.effect):.4g} reaches min_effect {r.min_effect}"


def _percentile_block(a: list[float], b: list[float]) -> dict[str, Any]:
    block: dict[str, Any] = {
        "baseline": {"p50": percentile(a, 50), "p95": percentile(a, 95), "n": len(a)},
        "candidate": {"p50": percentile(b, 50), "p95": percentile(b, 95), "n": len(b)},
    }
    block["p50_change_pct"] = _pct(block["baseline"]["p50"], block["candidate"]["p50"])
    block["p95_change_pct"] = _pct(block["baseline"]["p95"], block["candidate"]["p95"])
    return block


def _pct(old: float, new: float) -> float | None:
    return None if old <= 0 else (new - old) / old * 100


def _apply_unusable(r: MetricResult, n_paired: int) -> None:
    """Cases with no usable score (all repeats errored) must not silently vanish."""
    bad = sorted(set(r.unusable_baseline) | set(r.unusable_candidate))
    if not bad or n_paired == 0:
        return
    shown = ", ".join(bad[:5]) + (f" and {len(bad) - 5} more" if len(bad) > 5 else "")
    note = (f"{len(bad)} of {n_paired} paired case(s) have no usable score "
            f"(baseline {len(r.unusable_baseline)}, candidate {len(r.unusable_candidate)}): "
            f"{shown}")
    if len(bad) / n_paired <= MAX_MISSING_FRACTION:
        r.reason = f"{r.reason}; {note}" if r.reason else note
        return
    if r.verdict == REGRESSION:
        r.reason = f"{r.reason}; {note}"
    elif len(set(r.unusable_candidate) - set(r.unusable_baseline)) / n_paired > MAX_MISSING_FRACTION:
        r.verdict = REGRESSION
        r.reason = f"more than {MAX_MISSING_FRACTION:.0%} of cases errored in the candidate only (not in the baseline): {note}"
    else:
        r.verdict = INCONCLUSIVE
        r.reason = f"more than {MAX_MISSING_FRACTION:.0%} of cases are unusable: {note}"


def compare_runs(suite: Suite, baseline: Run, candidate: Run, cfg: Config) -> Comparison:
    brows, crows = baseline.by_case(), candidate.by_case()
    order = [c.id for c in suite.cases]
    case_by_id = {c.id: c for c in suite.cases}
    paired = [i for i in order if i in brows and i in crows]
    miss_b = [i for i in order if i not in brows]
    miss_c = [i for i in order if i not in crows]

    res = Comparison(
        suite=suite.name,
        baseline={"variant": baseline.header.variant, "meta": baseline.header.meta,
                  "created_at": baseline.header.created_at},
        candidate={"variant": candidate.header.variant, "meta": candidate.header.meta,
                   "created_at": candidate.header.created_at},
        settings=cfg.model_dump(),
        n_suite_cases=len(order),
        n_paired=len(paired),
        missing_in_baseline=miss_b,
        missing_in_candidate=miss_c,
    )

    # Per case and metric values, aligned over paired cases.
    values: dict[str, dict[str, tuple[float, float]]] = {m.name: {} for m in suite.metrics}
    flaky: list[dict[str, Any]] = []
    newly_failing: list[dict[str, Any]] = []
    newly_passing: list[dict[str, Any]] = []
    still_failing: list[dict[str, Any]] = []
    unusable: dict[str, tuple[list[str], list[str]]] = {m.name: ([], []) for m in suite.metrics}
    for cid in paired:
        for m in suite.metrics:
            if m.kind == "pass_fail":
                bf, cf = _passes(brows[cid], m.name), _passes(crows[cid], m.name)
                for run_name, flags in (("baseline", bf), ("candidate", cf)):
                    if _is_flaky(flags):
                        flaky.append({"case_id": cid, "metric": m.name, "run": run_name,
                                      "pass_rate": sum(flags) / len(flags)})
                bm, cm = _majority(bf), _majority(cf)
                values[m.name][cid] = (float(bm), float(cm))
                entry = {"case_id": cid, "metric": m.name, "tags": case_by_id[cid].tags}
                if bm and not cm:
                    failing_row = next((r for r in crows[cid] if r.error or not r.scores.get(m.name)),
                                       crows[cid][0])
                    newly_failing.append({
                        **entry,
                        "input": _clip(case_by_id[cid].input),
                        "expected": _clip(case_by_id[cid].expected),
                        "baseline_output": _clip(brows[cid][0].output),
                        "candidate_output": _clip(failing_row.output),
                        "candidate_error": failing_row.error,
                    })
                elif cm and not bm:
                    newly_passing.append(entry)
                elif not bm and not cm:
                    still_failing.append(entry)
            else:
                bs, cs = _scores(brows[cid], m.name), _scores(crows[cid], m.name)
                if not bs:
                    unusable[m.name][0].append(cid)
                if not cs:
                    unusable[m.name][1].append(cid)
                if bs and cs:
                    values[m.name][cid] = (mean(bs), mean(cs))
    res.cases = {"newly_failing": newly_failing, "newly_passing": newly_passing,
                 "still_failing": still_failing, "flaky": flaky,
                 "errors": [{"case_id": r.case_id, "repeat": r.repeat, "run": name,
                             "error": r.error}
                            for name, run in (("baseline", baseline), ("candidate", candidate))
                            for r in run.rows if r.error]}

    # Overall metrics.
    for m in suite.metrics:
        pairs = [values[m.name][c] for c in paired if c in values[m.name]]
        r = _stat(m, None, [p[0] for p in pairs], [p[1] for p in pairs], cfg)
        if r.n:
            _decide(r, r.p_value)
        r.unusable_baseline, r.unusable_candidate = unusable[m.name]
        _apply_unusable(r, len(paired))
        res.metrics.append(r)

    # Slices by tag; Holm across the slices of each metric.
    tags = sorted({t for cid in paired for t in case_by_id[cid].tags})
    for m in suite.metrics:
        group: list[MetricResult] = []
        for tag in tags:
            ids = [c for c in paired if tag in case_by_id[c].tags and c in values[m.name]]
            if not ids:
                continue
            group.append(_stat(m, tag, [values[m.name][c][0] for c in ids],
                               [values[m.name][c][1] for c in ids], cfg))
        for r, adj in zip(group, holm_adjust([g.p_value for g in group]), strict=True):
            r.p_adjusted = adj
            _decide(r, adj)
        res.slices.extend(group)

    # Latency and cost on paired cases.
    def lat_of(runrows: dict[str, list[RunRow]], cid: str) -> list[float]:
        return [r.latency_ms for r in runrows[cid] if r.latency_ms is not None]

    both = [c for c in paired if lat_of(brows, c) and lat_of(crows, c)]
    if both:
        res.latency = _percentile_block([x for c in both for x in lat_of(brows, c)],
                                        [x for c in both for x in lat_of(crows, c)])
        res.latency["n_cases"] = len(both)

    def case_cost(runrows: dict[str, list[RunRow]], cid: str) -> float | None:
        vals = [r.cost_usd for r in runrows[cid] if r.cost_usd is not None]
        return mean(vals) if vals else None

    costed = [c for c in paired if case_cost(brows, c) is not None
              and case_cost(crows, c) is not None]
    if costed:
        tb = sum(case_cost(brows, c) for c in costed)  # type: ignore[misc]
        tc = sum(case_cost(crows, c) for c in costed)  # type: ignore[misc]
        res.cost = {"baseline_total": tb, "candidate_total": tc, "n_cases": len(costed),
                    "change_pct": _pct(tb, tc)}

    _overall(res, cfg)
    return res


def _overall(res: Comparison, cfg: Config) -> None:
    reasons: list[str] = []
    gated = False
    regress = [m for m in res.metrics if m.verdict == REGRESSION]
    improve = [m for m in res.metrics if m.verdict == IMPROVEMENT]
    for m in regress:
        reasons.append(f"{m.name} regressed: {m.reason}")
    if cfg.fail_on == "any_case_newly_failing" and res.cases["newly_failing"]:
        n = len(res.cases["newly_failing"])
        reasons.append(f"fail_on = any_case_newly_failing and {n} case(s) newly fail")
        gated = True
    if res.latency and cfg.max_latency_regression_pct is not None:
        pct = res.latency["p95_change_pct"]
        if pct is not None and pct > cfg.max_latency_regression_pct:
            reasons.append(f"p95 latency up {pct:.1f}% (limit {cfg.max_latency_regression_pct}%)")
            gated = True
    if res.cost and cfg.max_cost_regression_pct is not None:
        pct = res.cost["change_pct"]
        if pct is not None and pct > cfg.max_cost_regression_pct:
            reasons.append(f"total cost up {pct:.1f}% (limit {cfg.max_cost_regression_pct}%)")
            gated = True

    miss_c = len(res.missing_in_candidate)
    too_many_missing = miss_c / res.n_suite_cases > MAX_MISSING_FRACTION
    if too_many_missing:
        reasons.append(f"{miss_c} of {res.n_suite_cases} suite cases are missing from the "
                       f"candidate run (more than {MAX_MISSING_FRACTION:.0%})")
    elif miss_c:
        reasons.append(f"{miss_c} suite case(s) missing from the candidate run (excluded)")
    if res.missing_in_baseline:
        reasons.append(f"{len(res.missing_in_baseline)} suite case(s) missing from the baseline "
                       "run (excluded; not counted toward the 10% rule)")

    if regress or gated:
        res.verdict = REGRESSION
    elif too_many_missing or res.n_paired == 0:
        res.verdict = INCONCLUSIVE
    elif improve:
        res.verdict = IMPROVEMENT
        reasons += [f"{m.name} improved: {m.reason}" for m in improve]
    elif any(m.verdict == INCONCLUSIVE for m in res.metrics):
        res.verdict = INCONCLUSIVE
        reasons += [f"{m.name} inconclusive: {m.reason}" for m in res.metrics
                    if m.verdict == INCONCLUSIVE]
    else:
        res.verdict = NO_CHANGE
        reasons.append("no metric changed significantly")
    res.reasons = reasons
