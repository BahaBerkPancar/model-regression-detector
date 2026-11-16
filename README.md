# model-regression-detector

Catches worse answers from prompt or model changes before they ship: runs an eval suite against a baseline and fails CI on statistically significant regressions (first target: text-to-sql-guardrails).

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
