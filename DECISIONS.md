# Decisions

Newest first. One entry per decision: date, what was decided, why, and what was rejected.

## 2026-11-17 – Fix round 1: INCONCLUSIVE rule, unusable scores, missing cases
- **INCONCLUSIVE is narrower.** The first rule flagged any run with fewer than 6 changed cases, so a 200-case suite with one flip failed CI. Now: INCONCLUSIVE only when fewer cases are paired than a test needs, or when fewer than 6 cases changed AND the effect is at least `min_effect` (it would matter, but there are too few cases to test). Otherwise NO_CHANGE with "only k cases differ". Same for score metrics. The few-changes INCONCLUSIVE branch applies only when `min_effect` > 0 (an explicit "this size matters"); with min_effect 0 (the score default) it is NO_CHANGE, "only k case(s) differ; set min_effect ... to gate small samples".
- **Unusable scores are counted, not dropped.** A case whose repeats all errored has no score for a score metric. It is listed per metric; over 10% of paired cases unusable gives INCONCLUSIVE, or REGRESSION when only the candidate has them (it started crashing). A significant regression keeps its verdict.
- **Missing cases.** Only cases missing from the candidate count toward the 10% rule. Cases absent from the baseline (new to the suite) are reported and excluded. A significant regression still wins, and the missing reason is shown next to it.
- **Latency gate** uses only cases with latency in both runs and is a raw p95 threshold, not a statistical test.
- **Reports.** Untrusted text is never placed in code spans (escaped entities would show literally); @mentions, `#123` references and http(s)/www autolinks are broken with a zero-width space entity.
- **CLI.** OSError and ValueError (for example an unwritable `--md` path) exit 3, never 1. `latency_ms` and `cost_usd` reject Infinity and NaN.

## 2026-11-17 – M1 statistics: paired tests, written down
- **Paired tests, not two averages.** Both runs score the same cases, so the comparison is per case. Comparing two means throws that pairing away and needs far more cases to see the same change. Pass/fail uses McNemar's exact test on the discordant pairs; scores use a sign-flip permutation test on the per-case differences.
- **McNemar exact, two-sided binomial.** With b cases newly failing and c newly passing, b is Binomial(b+c, 1/2) under "no change"; p = min(1, 2 * P(X <= min(b, c))), computed with integer `math.comb`. No continuity-corrected chi-square approximation, so it stays valid for the small counts a 40-case suite produces. Checked by hand: b=10, c=2 gives 79/2048 = 0.0386.
- **Majority result across repeats.** A case passes if more than half its repeats pass (a tie counts as failing, the cautious choice for a gate). A case that both passes and fails within one run is reported as flaky. Score metrics use the mean over non-error repeats.
- **Errors.** A row with `error` fails every pass_fail metric and is listed. For score metrics it is skipped (there is no honest number to use).
- **Bootstrap CI, seeded.** 95% percentile bootstrap of the mean paired difference, resampling cases, with a `random.Random(seed)` created per call, so the same inputs always give the same report. Default 10000 samples, configurable.
- **Sign-flip test is exact up to 16 non-zero differences** (all 2^m patterns), Monte Carlo with the (count+1)/(B+1) correction beyond that. Zero differences are dropped.
- **INCONCLUSIVE rule (superseded by fix round 1).** With n discordant pairs the smallest possible two-sided p is 2/2^n, so p < alpha needs n >= 6 at alpha 0.05 (`min_discordant`). Fewer differing cases than that gives INCONCLUSIVE with the reason; zero differences gives NO_CHANGE. Verdict = significant AND |effect| >= min_effect; direction decides REGRESSION or IMPROVEMENT (`higher_is_better` for scores).
- **Holm across slices.** Per-tag slices run the same tests; Holm-Bonferroni adjusts p within each metric across its slices, and the slice verdict uses the adjusted p. Slices are labelled exploratory and do not change the overall verdict (a regression in one tag shows up in the overall test if it is big enough; gating on slices is a later option).
- **Missing cases (superseded by fix round 1).** Cases absent from either run are listed and excluded. More than 10% of the suite missing gives INCONCLUSIVE, unless a metric still shows a significant regression, which wins (a regression found on the cases we do have is still a regression).
- **No scipy.** Everything needed (exact binomial tail, bootstrap, permutation, Holm) is a few lines of standard-library Python, and it keeps the install small and the tests free of a large numeric dependency. Added dependencies: pydantic (validation with clear errors) and pyyaml (suite files). Config is TOML via the standard `tomllib`.
- **Markdown escaping.** Model outputs are untrusted text in a PR comment: they are truncated, flattened to one line and entity-encoded (`|`, backticks, `<`, `>`, `&`, `[`, `]`, `*`, `~`, `\\`).
- **CLI exit codes.** 0 PASS/NO_CHANGE/IMPROVEMENT, 1 REGRESSION, 2 INCONCLUSIVE (0 with `--inconclusive-ok`), 3 usage or format error (argparse's own exit 2 is overridden so 2 always means INCONCLUSIVE).

## 2026-11-17 – Project created from the `python-app` template
Why: same layout, test setup and CI as the other projects, so nothing has to be set up by hand.
