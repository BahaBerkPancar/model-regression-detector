# model-regression-detector

Catches worse answers from prompt or model changes before they ship: runs an eval suite against a baseline and fails CI on statistically significant regressions (first target: text-to-sql-guardrails).

## What it does

You keep an eval suite (cases with expected answers). Every prompt or model change produces a run: one scored result per case. `mrd compare` pairs the candidate run with the baseline run case by case and says REGRESSION, IMPROVEMENT, NO_CHANGE or INCONCLUSIVE, with a Markdown report for the pull request and an exit code CI can fail on. It runs fully offline and makes no model calls.

Why per case: comparing two averages on a 40-case suite often cannot tell a real drop from noise. Looking at the same cases in both runs, and at which ones flipped, can.

## Quick start

```bash
uv sync
uv run mrd validate examples/qa/suite.yaml examples/qa/baseline.jsonl examples/qa/candidate_regress.jsonl

# a real regression (8 of 10 math cases broke): REGRESSION, exit code 1
uv run mrd compare --suite examples/qa/suite.yaml --baseline examples/qa/baseline.jsonl \
  --candidate examples/qa/candidate_regress.jsonl --config examples/qa/mrd.toml

# noise only (3 cases got worse, 3 got better): NO_CHANGE, exit code 0
uv run mrd compare --suite examples/qa/suite.yaml --baseline examples/qa/baseline.jsonl \
  --candidate examples/qa/candidate_noise.jsonl --config examples/qa/mrd.toml
```

Add `--md report.md --json report.json` to write the reports (`mrd report --json report.json` renders the Markdown again). The example files are produced by `examples/make_runs.py` (seeded), so they never change by accident.

Exit codes: 0 no regression, 1 REGRESSION, 2 INCONCLUSIVE (pass `--inconclusive-ok` to make it 0), 3 usage or file format error.

For the regression example the headline looks like this:

```
# Model regression check: REGRESSION
- correct regressed: p = 0.007812 is below alpha 0.05 and the effect 0.2 reaches min_effect 0.05
| correct | pass_fail | 0.850 | 0.650 | -0.200 | [-0.325, -0.075] | 0.0078 | 8/0 | **REGRESSION** |
| math | correct | 10 | 1.000 | 0.200 | -0.800 | [-1.000, -0.500] | 0.0078 | 0.0312 | REGRESSION |
```

## How the statistics work

- **Pass/fail metrics: McNemar exact test.** Only the cases that changed matter. If 10 cases newly fail and 2 newly pass, the question is whether 10 of 12 is too lopsided for a fair coin. Here p = 79/2048 = 0.0386. No approximations, so it holds for small counts.
- **Score metrics: sign-flip permutation test.** If nothing changed, the sign of each per-case difference is arbitrary. The test flips signs and counts how often the average moves as far as it did (all combinations for up to 16 changed cases, random ones beyond that).
- **Confidence intervals.** The 95% interval for the change comes from resampling the cases with a fixed seed, so the same inputs give the same report.
- **A verdict needs both** p below alpha and an effect at least `min_effect` (a 1-point drop can be significant on a huge suite and still not worth blocking a merge).
- **INCONCLUSIVE** means the suite cannot decide. It happens when fewer cases are paired than a test needs (6 at alpha 0.05), when fewer than 6 cases changed but the change is at least an explicit `min_effect` above 0 (big enough to matter, too few cases to test), when more than 10% of the suite is missing from the candidate run, or when more than 10% of cases have no usable score for a score metric. A few flips on a large suite are simply NO_CHANGE ("only k cases differ"). Cases missing from the baseline only are reported and excluded. A significant regression always wins over these doubts.
- **Errors in score metrics.** A case whose repeats all errored has no score, so it is counted as unusable for that metric and listed in the reason. If more than 10% are unusable it is INCONCLUSIVE, or REGRESSION when only the candidate has them (it started crashing).
- **Latency and cost limits are plain thresholds**, not statistical tests: `max_latency_regression_pct` compares the raw p95 latency (cases with latency in both runs only), `max_cost_regression_pct` compares total cost.
- **Repeats and flaky cases.** With several repeats per case the majority result is used, and cases that both pass and fail within one run are listed as flaky.
- **Slices by tag** repeat the tests per tag. They are exploratory; p-values are corrected across tags with Holm's method, and the verdict per slice uses the corrected value.

## Gating text-to-sql-guardrails

The optional t2s adapter exports the neighboring project's 40 benchmark questions and 32 attack prompts, then runs them through its real validation and read-only execution pipeline. The committed offline demos show a SQL regression (`REGRESSION`, exit 1), false blocking (`REGRESSION`, exit 1), and seeded noise (`NO_CHANGE`, exit 0).

```bash
uv sync --extra t2s
export TEST_DATABASE_URL=postgresql+psycopg://app:app@127.0.0.1:55432/app
examples/t2s/make_demo.sh
```

**Warning:** `make_demo.sh` uses t2s's benchmark setup, which drops and recreates the `public` schema at `TEST_DATABASE_URL` before each run. Point it only at the disposable t2s test database.

Use `--generator gold`, `mutated:<name>`, or `recorded:path/to/generations.jsonl`. Mutations are `drop-order-by`, `off-by-one-limit` (only existing limits), `wrong-join` (a seeded half of join cases), `harmless-function` (valid result-preserving SQL rejected by the function allowlist), `leaky`, and `noise`; compose them with `+` and select deterministic cases with `--seed`. Recorded files contain one JSON object per prompt, such as `{"question":"...","sql":"SELECT ..."}` or `{"question":"...","refusal":"..."}`; this lets a separately captured real-model run be rescored without network access. `--generator anthropic` only prints a cost estimate and exits 3 unless the caller explicitly supplies `--yes-spend`.

The neighboring checkout defaults to `../text-to-sql-guardrails`; set `MRD_T2S_ROOT` to use another read-only checkout.

## Formats

Suite (YAML):

```yaml
name: qa-toy
metrics:
  - {name: correct, kind: pass_fail}
  - {name: similarity, kind: score, higher_is_better: true}
cases:
  - {id: math-01, input: "What is 6 * 7?", expected: "42", tags: [math]}
```

Run (JSONL): a header line, then one line per case and repeat.

```json
{"type": "run", "suite": "qa-toy", "variant": "baseline", "created_at": "2026-11-17T00:00:00Z", "meta": {"model": "m", "prompt_version": "v1", "git_sha": "abc"}}
{"case_id": "math-01", "repeat": 0, "output": "42", "scores": {"correct": true, "similarity": 0.97}, "latency_ms": 410.0, "cost_usd": 0.001}
```

A line with `"error": "..."` counts as failing every pass_fail metric and is listed in the report.

Config (`mrd.toml`, all optional):

```toml
alpha = 0.05
default_min_effect = 0.05        # absolute change in pass rate, for pass_fail metrics
                                 # score metrics default to 0.0 (any significant change counts); set [min_effect] per metric
bootstrap_samples = 10000
seed = 7
fail_on = "regression"           # or "any_case_newly_failing"
max_latency_regression_pct = 50  # p95 latency
max_cost_regression_pct = 50     # total cost

[min_effect]
similarity = 0.02

[tags.math]                      # per-tag override for the slice
alpha = 0.1
[tags.math.min_effect]
correct = 0.1
```

Scorers for later adapters live in `scorers.py` (exact match, numeric tolerance, regex, JSON fields, row sets, plus `register_scorer`).

## Limits

Statistics cannot fix a bad suite: a few dozen cases only catch big regressions, and the tool says INCONCLUSIVE instead of guessing. Slice results do not gate the build.

## Setup

```bash
uv sync
```

## Development

Run the tests:

```bash
uv run pytest && uv run ruff check .
```

## How this repo is organised

- `AGENTS.md` – rules for coding agents (Claude Code reads it through `CLAUDE.md`)
- `DECISIONS.md` – why things are the way they are
- `CHANGELOG.md` – what changed in each release
