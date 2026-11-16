# Changelog

## Unreleased
- Project created.
- Core engine (M1): suite YAML, run JSONL and `mrd.toml` formats with validation errors that name the file and line or case id.
- Paired comparison: McNemar exact test for pass/fail metrics, paired bootstrap CI and sign-flip permutation test for scores, slices by tag with Holm correction, flaky and newly failing/passing case lists, latency and cost deltas.
- Verdicts REGRESSION / IMPROVEMENT / NO_CHANGE / INCONCLUSIVE from a config (alpha, min_effect, fail_on, latency and cost limits).
- Markdown (PR-comment ready, hostile text escaped) and JSON reports.
- `mrd` CLI: `validate`, `compare`, `report`; exit codes 0/1/2/3.
- Scorers: exact match, numeric tolerance, regex, JSON fields, row sets, plus a registry.
- `examples/qa` toy suite with a regressed and a noise-only candidate.
- Fix round 1: INCONCLUSIVE only when too few cases are paired, or when too few cases changed but the effect reaches an explicit `min_effect` (> 0); otherwise NO_CHANGE ("only k cases differ").
- Score cases with no usable score (all repeats errored) are counted per metric: over 10% gives INCONCLUSIVE, or REGRESSION when only the candidate has them.
- Only candidate-missing cases count toward the 10% missing rule; a significant regression still wins.
- `mrd` exits 3 (not 1) on I/O and value errors; latency and cost reject Infinity/NaN; latency uses cases present in both runs.
- Reports no longer put untrusted text in code spans and neutralise @mentions, #refs and autolinks.
