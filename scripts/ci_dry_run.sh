#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

run_pair() {
  local name="$1"
  local candidate="$2"
  local expected="$3"
  local expected_exit="$4"
  local summary="$tmp_dir/$name-summary.md"
  local output="$tmp_dir/$name-output.txt"

  set +e
  GITHUB_STEP_SUMMARY="$summary" GITHUB_OUTPUT="$output" \
    uv run --no-extra t2s mrd compare \
      --suite examples/t2s/suite.yaml \
      --baseline examples/t2s/baseline.jsonl \
      --candidate "$candidate" \
      --config examples/t2s/mrd.toml >/dev/null
  local status=$?
  set -e

  test "$status" = "$expected_exit"
  grep -Fqx "verdict=$expected" "$output"
  grep -Fqx "exit_code=$expected_exit" "$output"
  printf '%s outputs:\n' "$name"
  sed -n '1,3p' "$output"
  printf '%s summary:\n' "$name"
  sed -n '1,7p' "$summary"
}

cd "$repo_root"
run_pair regression examples/t2s/candidate_regress.jsonl REGRESSION 1
run_pair noise examples/t2s/candidate_noise.jsonl NO_CHANGE 0
