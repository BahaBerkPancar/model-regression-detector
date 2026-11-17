# CI regression gate

The composite action runs `mrd compare`, appends the complete Markdown report to the GitHub job
summary, and exposes `verdict`, `exit_code`, and `regressed_metrics`. A REGRESSION exits 1 and fails
the step. INCONCLUSIVE exits 2 unless `inconclusive-ok: true`; all other verdicts exit 0. The action
uses the committed `uv.lock` with `--frozen --no-extra t2s` and the requested Python version, so a
consumer does not need the optional neighboring t2s checkout.

```yaml
- uses: BahaBerkPancar/model-regression-detector@<full-release-commit-sha>
  with:
    suite: bench/mrd-suite.yaml
    baseline: baselines/t2s.jsonl
    candidate: candidate.jsonl
    config: config/mrd.toml
```

Inputs are passed through environment variables and quoted shell arrays, never interpolated from
`${{ inputs.* }}` into shell source. The summary is capped at GitHub's 1 MiB limit and ends with a
truncation note when necessary. REGRESSION and INCONCLUSIVE also create escaped workflow-command
annotations. The action does not comment on pull requests.

## Updating action pins

Every external action in this repository is pinned to a full 40-character commit SHA. Dependabot or
the action's release page can identify an updated release: review its changelog and source diff,
replace the SHA and adjacent version comment together, then run the offline YAML tests. Do not use a
mutable tag such as `@v4`. This repository has not been published yet, so the t2s copyable example
uses an all-zero placeholder for its first-party action and install references. Replace every
placeholder with the first reviewed release commit SHA before enabling that workflow.

## Baseline update flow

The first acceptance copies the run byte-for-byte and writes
`<baseline>.provenance.json` with the acceptance time, source variant, suite, and Git SHA:

```bash
uv run mrd baseline accept --run candidate.jsonl --to baselines/t2s.jsonl
uv run mrd baseline show baselines/t2s.jsonl
```

Replacing a baseline requires the suite so the provenance records a genuine verdict against the
previous baseline. Use the same config as CI and review that verdict before committing both files:

```bash
uv run mrd baseline accept --run candidate.jsonl --to baselines/t2s.jsonl \
  --suite bench/mrd-suite.yaml --config config/mrd.toml
git diff -- baselines/t2s.jsonl baselines/t2s.jsonl.provenance.json
```

Acceptance refuses a run whose header names a different suite from the stored baseline.

## Recorded runs, live runs, and cost safety

`examples/ci/t2s-gate.yml` is ready to copy into text-to-sql-guardrails after replacing all three
all-zero refs with the published mrd commit SHA. It runs only for pull requests that touch the real
generator, pipeline, guard, config, recorded generations, suite, or baseline paths. PostgreSQL is
disposable and the workflow grants only `contents: read`, which checkout needs; there are no write
permissions for comments, checks, issues, or repository contents.

The t2s repository must add these four inputs:

- `bench/mrd-suite.yaml`: run `MRD_T2S_ROOT="$PWD" uv run mrd t2s export-suite --out bench/mrd-suite.yaml` after installing the pinned mrd revision.
- `bench/recorded_generations.jsonl`: capture one reviewed provider response per suite prompt as `{"question":"...","sql":"SELECT ..."}` or `{"question":"...","refusal":"..."}`. Capture is intentionally separate from CI; review the file and remove secrets before committing it.
- `config/mrd.toml`: start by copying `examples/t2s/mrd.toml` from the pinned mrd revision, then review the alpha and minimum effects for the project.
- `baselines/t2s.jsonl`: against a disposable PostgreSQL database, run the recorded generator to a candidate file, then accept it with `mrd baseline accept --run candidate.jsonl --to baselines/t2s.jsonl --suite bench/mrd-suite.yaml --config config/mrd.toml`. Commit the generated provenance sidecar too.

Recorded generations are the default. They make pull requests repeatable, credential-free, and
safe for forks, and that step never receives `ANTHROPIC_API_KEY`. A separate live step is selected
only by repository variable `MRD_ALLOW_SPEND=1`; it requires a non-empty `MRD_LIVE_MODEL` variable
and `ANTHROPIC_API_KEY` secret and always spells out `--yes-spend`. Keep protected environments or
repository rules around those settings, and review the CLI's cost estimate before enabling them.

## Flaky evaluations

Use `--repeats 3` (or another odd number) when a generator is nondeterministic. mrd uses the
per-case majority for pass/fail metrics, averages usable score repeats, and lists cases that both
pass and fail. Do not hide widespread flakiness with `inconclusive-ok`; stabilize the prompt or
increase the suite before accepting a new baseline. Recorded outputs are preferable when the gate
is intended to test scoring or guardrail changes rather than provider variability.

## Offline checks

`scripts/ci_dry_run.sh` points GitHub's summary and output variables at temporary files and checks
both committed t2s pairs: the regression exits 1 with REGRESSION, while balanced noise exits 0 with
NO_CHANGE. `tests/test_ci_files.py` parses the action and workflows, verifies their contract and
permissions, rejects unpinned third-party actions, and ensures action inputs are not inserted
directly into shell source. Core CI passes `--no-extra t2s` so uv does not resolve the optional
neighboring path checkout. If `actionlint` is already installed, run `actionlint`; it is optional
and should not be downloaded just for this check.
