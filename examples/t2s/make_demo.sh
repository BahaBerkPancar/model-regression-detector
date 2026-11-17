#!/bin/sh
set -eu

cd "$(dirname "$0")/../.."

uv run mrd t2s export-suite --out examples/t2s/suite.yaml
uv run mrd run --adapter t2s --generator mutated:noise --seed 1 --variant baseline \
  --suite examples/t2s/suite.yaml --out examples/t2s/baseline.jsonl
uv run mrd run --adapter t2s --generator mutated:noise+drop-order-by+wrong-join --seed 1 \
  --variant candidate-regress --suite examples/t2s/suite.yaml \
  --out examples/t2s/candidate_regress.jsonl
uv run mrd run --adapter t2s --generator mutated:noise+harmless-function --seed 1 \
  --variant candidate-overblock --suite examples/t2s/suite.yaml \
  --out examples/t2s/candidate_overblock.jsonl
uv run mrd run --adapter t2s --generator mutated:noise --seed 25 \
  --variant candidate-noise --suite examples/t2s/suite.yaml \
  --out examples/t2s/candidate_noise.jsonl

set +e
uv run mrd compare --suite examples/t2s/suite.yaml --baseline examples/t2s/baseline.jsonl \
  --candidate examples/t2s/candidate_regress.jsonl --config examples/t2s/mrd.toml \
  --md examples/t2s/report_regress.md
regress=$?
uv run mrd compare --suite examples/t2s/suite.yaml --baseline examples/t2s/baseline.jsonl \
  --candidate examples/t2s/candidate_overblock.jsonl --config examples/t2s/mrd.toml \
  --md examples/t2s/report_overblock.md
overblock=$?
uv run mrd compare --suite examples/t2s/suite.yaml --baseline examples/t2s/baseline.jsonl \
  --candidate examples/t2s/candidate_noise.jsonl --config examples/t2s/mrd.toml \
  --md examples/t2s/report_noise.md
noise=$?
set -e

[ "$regress" -eq 1 ] && [ "$overblock" -eq 1 ] && [ "$noise" -eq 0 ]
