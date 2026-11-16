# Build plan: model-regression-detector

Written 2026-11-17 (away run). Source: vault `knowledge/project-ideas-backlog.md`, "Chosen" #2:
"automatically test prompt and model changes to catch worse answers before they reach users …
build it second, as a CI job that tests the Text-to-SQL project."

## What it is
A small, honest regression gate for LLM features. You keep an eval suite (cases with expected
answers). Each prompt or model change produces a **run** (one scored result per case, optionally
repeated). The tool compares a candidate run against a baseline run **case by case** and says
PASS / REGRESSION / IMPROVEMENT / INCONCLUSIVE with real statistics (paired tests, confidence
intervals, per-slice breakdowns, newly failing cases, flaky cases), writes a Markdown report for the
PR, and exits non-zero on a regression so CI blocks the merge.

Why it stands out: most "eval in CI" demos compare two averages. Paired, per-case comparison with
significance and slices is what tells a real regression apart from noise on a 40-case suite.

## Ground rules
- **No paid API calls during the build.** MF has no API key in use (same rule as t2s M4b). Live
  model runs are built but not run; demos use recorded runs and deterministic generators.
- Never read any `.env`. Tests never touch the network.
- First target is `../text-to-sql-guardrails` (local path dependency for the adapter, optional
  extra so the core installs without it).
- Builders: Codex via `~/.mf/bin/codex-task` (Sonnet fallback when Codex is limited); reviews by
  the `reviewer` agent; hub commits locally; pushes only with MF's OK. The repo was created with
  `--local` during an away run: **no GitHub repo yet** (MF creates it / says push).

## Milestones
| # | Name | Contents |
|---|------|----------|
| M1 | Core engine | Suite + run formats (YAML/JSONL, validated), scorers, paired comparison (McNemar exact for pass/fail, paired bootstrap CI for scores, slices by tag, repeats + flaky detection), verdict rules from a config, Markdown/JSON reports, `mrd` CLI (`validate`, `compare`, `report`), exit codes. Fully offline, synthetic fixtures with known answers. |
| M2 | Text-to-SQL adapter | `mrd run --adapter t2s`: runs t2s questions through its pipeline with a chosen generator (gold, mutated-gold "bad prompt" variants, recorded outputs, or live model behind `--yes-spend`), scores execution accuracy against gold result sets on the t2s Postgres, plus guardrail metrics (attack prompts blocked, false blocks). Recorded baseline + two candidate runs (one real regression, one noise-only) committed as the demo. |
| M3 | CI gate | Reusable GitHub Action / workflow: run the suite on the PR, fetch the baseline (committed file or artifact from main), compare, write the job summary, fail on REGRESSION. A demo workflow in this repo against the recorded runs; a ready-to-copy workflow for t2s (not committed into t2s without MF). Baseline update flow (`mrd baseline accept`). |
| M4 | Showcase | README (problem, how the stats work in plain words, screenshot of a PR summary, limitations), optional DeepEval scorer bridge (off by default; LLM-judge metrics need a key), docs/architecture.svg. |

## Later
Failure Forensics (backlog) could reuse the run format as its trace store.
