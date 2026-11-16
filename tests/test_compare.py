import pytest
from helpers import all_pass, make_run, make_suite, with_fail

from model_regression_detector.compare import (
    IMPROVEMENT,
    INCONCLUSIVE,
    NO_CHANGE,
    REGRESSION,
    compare_runs,
)
from model_regression_detector.config import Config
from model_regression_detector.formats import Suite

CFG = Config(bootstrap_samples=300, seed=1)


def run_compare(suite, base, cand, cfg=CFG):
    return compare_runs(suite, base, cand, cfg)


def test_regression_detected_with_exact_numbers():
    suite = make_suite()
    res = run_compare(suite, make_run("b", all_pass()), make_run("c", with_fail(all_pass(), range(8))))
    m = res.metrics[0]
    assert (m.n_worse, m.n_better) == (8, 0)
    assert m.p_value == pytest.approx(2 / 256)
    assert m.effect == pytest.approx(-0.4)
    assert m.ci_high < 0
    assert m.verdict == REGRESSION and res.verdict == REGRESSION
    assert len(res.cases["newly_failing"]) == 8


def test_improvement_is_symmetric():
    suite = make_suite()
    res = run_compare(suite, make_run("b", with_fail(all_pass(), range(8))), make_run("c", all_pass()))
    assert res.metrics[0].verdict == IMPROVEMENT and res.verdict == IMPROVEMENT
    assert len(res.cases["newly_passing"]) == 8


def test_balanced_noise_is_no_change():
    suite = make_suite()
    base = make_run("b", with_fail(all_pass(), [0, 1, 2]))
    cand = make_run("c", with_fail(all_pass(), [3, 4, 5]))
    res = run_compare(suite, base, cand)
    assert (res.metrics[0].n_worse, res.metrics[0].n_better) == (3, 3)
    assert res.metrics[0].p_value == 1.0
    assert res.verdict == NO_CHANGE


def test_identical_runs_are_no_change():
    suite = make_suite()
    res = run_compare(suite, make_run("b", all_pass()), make_run("c", all_pass()))
    assert res.verdict == NO_CHANGE and "no per-case differences" in res.metrics[0].reason


def test_too_few_discordant_pairs_is_inconclusive_and_says_why():
    suite = make_suite()
    res = run_compare(suite, make_run("b", all_pass()), make_run("c", with_fail(all_pass(), range(5))))
    m = res.metrics[0]
    assert m.verdict == INCONCLUSIVE and res.verdict == INCONCLUSIVE
    assert "at least 6" in m.reason
    # exactly six is enough
    res6 = run_compare(suite, make_run("b", all_pass()), make_run("c", with_fail(all_pass(), range(6))))
    assert res6.verdict == REGRESSION


def test_min_effect_blocks_tiny_but_significant_change():
    suite = make_suite(200)
    base, cand = make_run("b", all_pass(200)), make_run("c", with_fail(all_pass(200), range(10)))
    strict = run_compare(suite, base, cand, Config(bootstrap_samples=300, min_effect={"ok": 0.06}))
    assert strict.metrics[0].p_value < 0.05
    assert strict.metrics[0].verdict == NO_CHANGE and "below min_effect" in strict.metrics[0].reason
    exact = run_compare(suite, base, cand, Config(bootstrap_samples=300, min_effect={"ok": 0.05}))
    assert exact.metrics[0].verdict == REGRESSION


def test_alpha_is_respected():
    suite = make_suite()
    base, cand = make_run("b", all_pass()), make_run("c", with_fail(all_pass(), range(8)))
    res = run_compare(suite, base, cand, Config(alpha=0.001, bootstrap_samples=300))
    assert res.metrics[0].verdict == INCONCLUSIVE  # 2/256 can never beat 0.001 with 8 pairs


def test_missing_cases_listed_and_excluded():
    suite = make_suite()
    cand_results = {k: v for k, v in all_pass().items() if k != "c05"}
    res = run_compare(suite, make_run("b", all_pass()), make_run("c", cand_results))
    assert res.missing_in_candidate == ["c05"] and res.missing_in_baseline == []
    assert res.n_paired == 19 and res.verdict == NO_CHANGE


def test_more_than_ten_percent_missing_is_inconclusive():
    suite = make_suite()
    cand_results = {k: v for k, v in all_pass().items() if k not in ("c05", "c06", "c07")}
    res = run_compare(suite, make_run("b", all_pass()), make_run("c", cand_results))
    assert res.verdict == INCONCLUSIVE and any("missing" in r for r in res.reasons)
    # exactly 10% (2 of 20) is still fine
    ok = {k: v for k, v in all_pass().items() if k not in ("c05", "c06")}
    assert run_compare(suite, make_run("b", all_pass()), make_run("c", ok)).verdict == NO_CHANGE


def test_repeats_majority_and_flaky():
    suite = make_suite()
    base_r = all_pass()
    base = {k: [v, v, v] for k, v in base_r.items()}
    base["c00"] = [True, True, False]  # flaky, majority pass
    cand = {k: [v, v, v] for k, v in base_r.items()}
    cand["c00"] = [False, False, True]  # flaky, majority fail
    cand["c01"] = [False, False, False]
    res = run_compare(suite, make_run("b", base), make_run("c", cand))
    flaky = {(f["case_id"], f["run"]): f["pass_rate"] for f in res.cases["flaky"]}
    assert flaky == {("c00", "baseline"): pytest.approx(2 / 3), ("c00", "candidate"): pytest.approx(1 / 3)}
    assert {c["case_id"] for c in res.cases["newly_failing"]} == {"c00", "c01"}
    assert res.metrics[0].n_worse == 2


def test_errors_count_as_failures_and_are_listed():
    suite = make_suite()
    res = run_compare(suite, make_run("b", all_pass()),
                      make_run("c", all_pass(), errors={"c00", "c01"}))
    assert {c["case_id"] for c in res.cases["newly_failing"]} == {"c00", "c01"}
    assert [e["case_id"] for e in res.cases["errors"]] == ["c00", "c01"]
    assert res.cases["newly_failing"][0]["candidate_error"] == "boom"


def score_suite(higher=True):
    return Suite.model_validate({
        "name": "s",
        "metrics": [{"name": "ok", "kind": "pass_fail"},
                    {"name": "sim", "kind": "score", "higher_is_better": higher}],
        "cases": [{"id": f"c{i:02d}", "input": "q"} for i in range(20)]})


def test_score_metric_sign_flip_and_direction():
    sims_b = {f"c{i:02d}": 0.8 for i in range(20)}
    sims_c = {k: (v - 0.1 if int(k[1:]) < 8 else v) for k, v in sims_b.items()}
    base, cand = make_run("b", all_pass(), sims=sims_b), make_run("c", all_pass(), sims=sims_c)
    res = run_compare(score_suite(True), base, cand)
    sim = res.metrics[1]
    assert sim.effect == pytest.approx(-0.04) and sim.p_value == pytest.approx(2 / 256)
    assert sim.verdict == REGRESSION and res.verdict == REGRESSION
    # for a lower-is-better score the same change is an improvement
    res2 = run_compare(score_suite(False), base, cand)
    assert res2.metrics[1].verdict == IMPROVEMENT and res2.verdict == IMPROVEMENT


def test_slices_and_holm_correction():
    suite = make_suite(40, tags={f"t{k}": range(k * 10, k * 10 + 10) for k in range(4)})
    base = make_run("b", all_pass(40))
    cand = make_run("c", with_fail(all_pass(40), range(6)))  # 6 failures, all in t0
    res = run_compare(suite, base, cand)
    by_tag = {s.tag: s for s in res.slices}
    t0 = by_tag["t0"]
    assert t0.p_value == pytest.approx(2 / 64)  # raw p < 0.05
    assert t0.p_adjusted == pytest.approx(4 * 2 / 64)  # Holm over 4 slices
    assert t0.verdict == NO_CHANGE  # does not survive the correction
    assert by_tag["t1"].p_adjusted == 1.0
    assert res.metrics[0].verdict == REGRESSION  # the overall test is a single test
    # with 8 failures the slice survives: 2/256 * 4 = 0.031
    res8 = run_compare(suite, base, make_run("c", with_fail(all_pass(40), range(8))))
    assert {s.tag: s for s in res8.slices}["t0"].verdict == REGRESSION


def test_per_tag_override_changes_slice_min_effect():
    suite = make_suite(40, tags={"t0": range(10), "t1": range(10, 20)})
    base, cand = make_run("b", all_pass(40)), make_run("c", with_fail(all_pass(40), range(8)))
    cfg = Config(bootstrap_samples=300, tags={"t0": {"min_effect": {"ok": 0.95}}})
    t0 = {s.tag: s for s in run_compare(suite, base, cand, cfg).slices}["t0"]
    assert t0.verdict == NO_CHANGE and "below min_effect" in t0.reason


def test_fail_on_any_case_newly_failing():
    suite = make_suite()
    base, cand = make_run("b", all_pass()), make_run("c", with_fail(all_pass(), [3]))
    assert run_compare(suite, base, cand).verdict == INCONCLUSIVE
    strict = run_compare(suite, base, cand,
                         Config(bootstrap_samples=300, fail_on="any_case_newly_failing"))
    assert strict.verdict == REGRESSION and "newly fail" in strict.reasons[0]


def test_latency_and_cost_gates():
    suite = make_suite()
    ids = list(all_pass())
    base = make_run("b", all_pass(), latency={i: 100.0 for i in ids}, cost={i: 0.01 for i in ids})
    cand = make_run("c", all_pass(), latency={i: 200.0 for i in ids}, cost={i: 0.02 for i in ids})
    plain = run_compare(suite, base, cand)
    assert plain.verdict == NO_CHANGE
    assert plain.latency["p95_change_pct"] == pytest.approx(100.0)
    assert plain.latency["baseline"]["p50"] == 100.0
    assert plain.cost["baseline_total"] == pytest.approx(0.2)
    assert plain.cost["change_pct"] == pytest.approx(100.0)
    lat = run_compare(suite, base, cand, Config(bootstrap_samples=300, max_latency_regression_pct=50))
    assert lat.verdict == REGRESSION and "latency" in lat.reasons[0]
    cost = run_compare(suite, base, cand, Config(bootstrap_samples=300, max_cost_regression_pct=50))
    assert cost.verdict == REGRESSION and "cost" in cost.reasons[0]
    ok = run_compare(suite, base, cand, Config(bootstrap_samples=300, max_latency_regression_pct=150))
    assert ok.verdict == NO_CHANGE


def test_result_is_deterministic_and_json_safe():
    import json

    suite = make_suite()
    base, cand = make_run("b", all_pass()), make_run("c", with_fail(all_pass(), range(8)))
    a = json.dumps(run_compare(suite, base, cand).to_dict())
    assert a == json.dumps(run_compare(suite, base, cand).to_dict())


def test_one_flip_on_a_big_suite_is_not_inconclusive():
    suite = make_suite(200)
    res = run_compare(suite, make_run("b", all_pass(200)), make_run("c", with_fail(all_pass(200), [3])))
    m = res.metrics[0]
    assert m.verdict == NO_CHANGE and "only 1 case(s) differ" in m.reason
    assert res.verdict == NO_CHANGE


def test_few_flips_with_a_big_effect_stay_inconclusive_and_tiny_suites_too():
    suite = make_suite(20)
    res = run_compare(suite, make_run("b", all_pass()), make_run("c", with_fail(all_pass(), range(3))))
    assert res.verdict == INCONCLUSIVE and "too few to test" in res.metrics[0].reason
    tiny = make_suite(4)
    res = run_compare(tiny, make_run("b", all_pass(4)), make_run("c", with_fail(all_pass(4), [0])))
    assert res.metrics[0].verdict == INCONCLUSIVE and "paired case" in res.metrics[0].reason


def only_score_suite():
    return Suite.model_validate({
        "name": "s", "metrics": [{"name": "sim", "kind": "score"}],
        "cases": [{"id": f"c{i:02d}", "input": "q"} for i in range(20)]})


def score_run(variant, errors=(), sims=None):
    from model_regression_detector.formats import Run, RunHeader, RunRow

    rows = [RunRow(case_id=f"c{i:02d}", scores={} if f"c{i:02d}" in errors else {"sim": 0.8},
                   error="crash" if f"c{i:02d}" in errors else None) for i in range(20)]
    return Run(header=RunHeader(type="run", suite="s", variant=variant), rows=rows)


def test_candidate_crashes_on_a_score_only_suite_are_a_regression():
    errs = {f"c{i:02d}" for i in range(6)}  # 30%
    res = run_compare(only_score_suite(), score_run("b"), score_run("c", errs))
    m = res.metrics[0]
    assert m.verdict == REGRESSION and res.verdict == REGRESSION
    assert "candidate only" in m.reason and "c00" in m.reason
    assert m.unusable_candidate == sorted(errs) and m.unusable_baseline == []


def test_unusable_in_both_runs_is_inconclusive_and_a_few_are_only_noted():
    errs = {f"c{i:02d}" for i in range(6)}
    res = run_compare(only_score_suite(), score_run("b", errs), score_run("c"))
    assert res.metrics[0].verdict == INCONCLUSIVE and res.verdict == INCONCLUSIVE
    one = run_compare(only_score_suite(), score_run("b"), score_run("c", {"c00"}))  # 5%
    assert one.metrics[0].verdict == NO_CHANGE and "no usable score" in one.metrics[0].reason


def test_missing_from_baseline_is_reported_but_not_inconclusive():
    suite = make_suite()
    base = {k: v for k, v in all_pass().items() if k not in ("c05", "c06", "c07")}
    res = run_compare(suite, make_run("b", base), make_run("c", all_pass()))
    assert res.missing_in_baseline == ["c05", "c06", "c07"]
    assert res.verdict == NO_CHANGE and any("missing from the baseline" in r for r in res.reasons)


def test_significant_regression_wins_over_missing_and_shows_the_missing_reason():
    suite = make_suite()
    cand = with_fail({k: v for k, v in all_pass().items() if k not in ("c18", "c19")}, range(8))
    res = run_compare(suite, make_run("b", all_pass()), make_run("c", cand))
    assert res.verdict == REGRESSION  # 8 worse of 18 paired
    cand3 = {k: v for k, v in cand.items() if k != "c17"}  # 3 of 20 missing: over 10%
    res3 = run_compare(suite, make_run("b", all_pass()), make_run("c", cand3))
    assert res3.verdict == REGRESSION
    assert any("missing from the candidate run (more than 10%)" in r for r in res3.reasons)


def test_latency_uses_only_cases_with_latency_in_both_runs():
    suite = make_suite()
    ids = list(all_pass())
    base = make_run("b", all_pass(), latency={i: 100.0 for i in ids[:10]})
    cand = make_run("c", all_pass(), latency={i: 100.0 for i in ids[5:]})
    res = run_compare(suite, base, cand)
    assert res.latency["n_cases"] == 5  # c05..c09
    assert res.latency["candidate"]["n"] == 5


def test_few_changes_branch_needs_an_explicit_min_effect():
    sims_b = {f"c{i:02d}": 0.8 for i in range(20)}
    sims_c = dict(sims_b) | {"c00": 0.79}
    base = make_run("b", all_pass(), sims=sims_b)
    cand = make_run("c", all_pass(), sims=sims_c)
    # min_effect 0 (score default): one tiny difference is NO_CHANGE with a hint
    res = run_compare(score_suite(), base, cand)
    assert res.metrics[1].verdict == NO_CHANGE and res.verdict == NO_CHANGE
    assert "set min_effect for sim" in res.metrics[1].reason
    # explicit min_effect the change reaches: too few to test, big enough to matter
    sims_big = dict(sims_b) | {f"c{i:02d}": 0.0 for i in range(3)}
    big = make_run("c", all_pass(), sims=sims_big)
    cfg = Config(bootstrap_samples=300, min_effect={"sim": 0.05})
    res = run_compare(score_suite(), base, big, cfg)
    assert res.metrics[1].verdict == INCONCLUSIVE and res.verdict == INCONCLUSIVE
    # explicit min_effect the change does not reach: NO_CHANGE
    res = run_compare(score_suite(), base, cand, cfg)
    assert res.metrics[1].verdict == NO_CHANGE and "below min_effect" in res.metrics[1].reason


def test_candidate_only_crashes_still_regress_when_baseline_has_one_crash():
    cand_errs = {f"c{i:02d}" for i in range(1, 7)}  # 30%, none of them the baseline's
    res = run_compare(only_score_suite(), score_run("b", {"c00"}), score_run("c", cand_errs | {"c00"}))
    assert res.metrics[0].verdict == REGRESSION
    # a candidate-only share of 5% plus 10% baseline-only crashes is merely inconclusive
    res = run_compare(only_score_suite(), score_run("b", {"c00", "c01"}), score_run("c", {"c02"}))
    assert res.metrics[0].verdict == INCONCLUSIVE
