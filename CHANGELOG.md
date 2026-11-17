# Changelog

## Unreleased
- Added the M3 CI gate: a composite GitHub Action, pinned test and demo workflows, GitHub job-summary/output/annotation integration with hostile-text escaping and a 1 MiB cap, plus an offline two-outcome dry run.
- Added `mrd baseline accept` and `mrd baseline show`; accepted JSONL stays unchanged while a source-backed sidecar records Git SHA, acceptance time, variant, previous baseline, and comparison verdict.
- Added a ready-to-copy text-to-SQL pull-request workflow with minimal permissions, recorded generations by default, disposable PostgreSQL, and a three-part opt-in before any paid live model call.
- Documented CI setup, action pin updates, baseline review, cost safety, and flaky repeats; workflow files are parsed and policy-checked in offline tests.
- Made the PostgreSQL equivalence test prepare its own schema so it no longer depends on test order.
- M3 review fixes: the action now runs reproducibly from `uv.lock`; the t2s template watches the real source paths, points the adapter at the checkout, pins placeholder refs, and isolates live-model secrets from recorded CI; GitHub logs no longer print the full report as workflow-command input.
- Added the optional text-to-SQL adapter: suite export, guarded runner, deterministic mutated-gold and recorded generators, offline demo runs/reports, and a paid Anthropic path that requires explicit `--yes-spend`.
- M2 review fixes: core tests skip cleanly without the optional extra; demos now use an imperfect seeded baseline, balanced noise, and a PostgreSQL-valid policy over-block; offline metadata/costs are explicit; runs checksum the database for writes; mutation semantics, sorting tags, and configurable t2s roots are documented and tested.
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
