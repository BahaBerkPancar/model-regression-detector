"""Generate the toy qa example: a suite, a baseline run and two candidates.

Deterministic (seeded). Run `uv run python examples/make_runs.py` to regenerate the
committed files in examples/qa/.

- candidate_regress: 8 of the 10 `math` cases that used to pass now fail (a real regression).
- candidate_noise: 3 cases flip to failing and 3 flip to passing, spread over all tags
  (noise only: no real change).
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import yaml

TAGS = ["math", "facts", "format", "reasoning"]
CONFIG = """alpha = 0.05
default_min_effect = 0.05
bootstrap_samples = 10000
seed = 7
fail_on = "regression"
max_latency_regression_pct = 50
max_cost_regression_pct = 50

[min_effect]
similarity = 0.02
"""


def build_suite() -> dict:
    cases = []
    for t, tag in enumerate(TAGS):
        for i in range(10):
            n = t * 10 + i + 1
            cases.append({"id": f"{tag}-{i + 1:02d}", "input": f"Question {n} ({tag})",
                          "expected": f"answer-{n}", "tags": [tag]})
    return {"name": "qa-toy",
            "metrics": [{"name": "correct", "kind": "pass_fail"},
                        {"name": "similarity", "kind": "score"}],
            "cases": cases}


def _row(rng: random.Random, case: dict, ok: bool, slow: float = 1.0) -> dict:
    sim = rng.uniform(0.85, 1.0) if ok else rng.uniform(0.2, 0.5)
    return {"case_id": case["id"], "repeat": 0,
            "output": case["expected"] if ok else f"wrong answer for {case['id']}",
            "scores": {"correct": ok, "similarity": round(sim, 3)},
            "latency_ms": round(rng.uniform(300, 600) * slow, 1),
            "cost_usd": round(rng.uniform(0.0008, 0.0012), 5)}


def build_runs() -> dict[str, list[dict]]:
    suite = build_suite()
    cases = suite["cases"]
    rng = random.Random(2024)
    # Baseline passes everything except 6 cases outside `math`.
    non_math = [c["id"] for c in cases if "math" not in c["tags"]]
    base_fail = set(rng.sample(non_math, 6))
    base_ok = {c["id"]: c["id"] not in base_fail for c in cases}

    def run(variant: str, outcomes: dict[str, bool], seed: int, meta: dict) -> list[dict]:
        r = random.Random(seed)
        header = {"type": "run", "suite": suite["name"], "variant": variant,
                  "created_at": "2026-11-17T00:00:00Z", "meta": meta}
        return [header] + [_row(r, c, outcomes[c["id"]]) for c in cases]

    math_ids = [c["id"] for c in cases if "math" in c["tags"]]
    broken = set(rng.sample(math_ids, 8))
    regress = {k: (v and k not in broken) for k, v in base_ok.items()}

    passing = [k for k, v in base_ok.items() if v]
    failing = [k for k, v in base_ok.items() if not v]
    drop = set(rng.sample(passing, 3))
    gain = set(rng.sample(failing, 3))
    noise = {k: (v and k not in drop) or k in gain for k, v in base_ok.items()}

    return {
        "baseline": run("baseline", base_ok, 1, {"model": "toy-1", "prompt_version": "v1"}),
        "candidate_regress": run("candidate-regress", regress, 1,
                                 {"model": "toy-1", "prompt_version": "v2-shorter"}),
        "candidate_noise": run("candidate-noise", noise, 2,
                               {"model": "toy-1", "prompt_version": "v1-reworded"}),
    }


def write(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "suite.yaml").write_text(
        yaml.safe_dump(build_suite(), sort_keys=False, allow_unicode=True), encoding="utf-8")
    (out / "mrd.toml").write_text(CONFIG, encoding="utf-8")
    for name, lines in build_runs().items():
        (out / f"{name}.jsonl").write_text(
            "".join(json.dumps(x, sort_keys=False) + "\n" for x in lines), encoding="utf-8")


if __name__ == "__main__":
    write(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "qa")
