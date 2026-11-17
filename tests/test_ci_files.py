import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
ACTION = ROOT / "action.yml"
WORKFLOWS = [
    ROOT / ".github/workflows/test.yml",
    ROOT / ".github/workflows/demo-gate.yml",
    ROOT / "examples/ci/t2s-gate.yml",
]
SHA = re.compile(r"^[0-9a-f]{40}$")


def _load(path):
    return yaml.safe_load(path.read_text())


def _steps(document):
    if document.get("runs", {}).get("steps"):
        yield from document["runs"]["steps"]
    for job in document.get("jobs", {}).values():
        yield from job.get("steps", [])


def test_composite_action_contract_and_safe_shell_inputs():
    action = _load(ACTION)
    assert action["runs"]["using"] == "composite"
    assert set(action["inputs"]) == {
        "suite", "baseline", "candidate", "config", "inconclusive-ok", "python-version"
    }
    assert set(action["outputs"]) == {"verdict", "exit_code", "regressed_metrics"}
    for step in _steps(action):
        assert "${{ inputs." not in step.get("run", "")
    compare = next(step for step in _steps(action) if step.get("id") == "compare")
    assert compare["env"]["MRD_PYTHON"] == "${{ inputs.python-version }}"
    for fragment in (
        'uv run --project "$GITHUB_ACTION_PATH"',
        "--frozen",
        "--no-extra t2s",
        '--python "$MRD_PYTHON"',
    ):
        assert fragment in compare["run"]
    assert all("uv tool install" not in step.get("run", "") for step in _steps(action))


def test_workflows_have_minimal_permissions_and_expected_jobs():
    documents = {path.name: _load(path) for path in WORKFLOWS}
    for document in documents.values():
        assert document["permissions"] == {"contents": "read"}
    assert {"test"} == set(documents["test.yml"]["jobs"])
    core_runs = [step["run"] for step in _steps(documents["test.yml"]) if "run" in step]
    assert all("--no-extra t2s" in command for command in core_runs)
    demo = documents["demo-gate.yml"]["jobs"]["gate"]
    cases = demo["strategy"]["matrix"]["include"]
    assert {(case["expected"], case["expected_exit"]) for case in cases} == {
        ("REGRESSION", "1"), ("NO_CHANGE", "0")
    }
    assert documents["t2s-gate.yml"]["jobs"]["regression-gate"]["services"]["postgres"]
    t2s = documents["t2s-gate.yml"]
    triggers = t2s.get("on", t2s.get(True))["pull_request"]["paths"]
    assert set(triggers) == {
        "src/text_to_sql_guardrails/llm/**",
        "src/text_to_sql_guardrails/pipeline.py",
        "src/text_to_sql_guardrails/guard/**",
        "config/**",
        "bench/mrd-suite.yaml",
        "bench/recorded_generations.jsonl",
        "baselines/t2s.jsonl",
    }
    steps = list(_steps(t2s))
    recorded = next(step for step in steps if step["name"] == "Generate candidate from recorded outputs")
    live = next(step for step in steps if step["name"] == "Generate candidate from live model")
    assert recorded["if"] == "vars.MRD_ALLOW_SPEND != '1'"
    assert "ANTHROPIC_API_KEY" not in recorded["env"]
    assert recorded["env"]["MRD_T2S_ROOT"] == "${{ github.workspace }}"
    assert "--frozen" in recorded["run"] and "--yes-spend" not in recorded["run"]
    assert live["if"] == "vars.MRD_ALLOW_SPEND == '1'"
    assert live["env"]["ANTHROPIC_API_KEY"] == "${{ secrets.ANTHROPIC_API_KEY }}"
    assert live["env"]["MRD_T2S_ROOT"] == "${{ github.workspace }}"
    assert "--frozen" in live["run"] and "--yes-spend" in live["run"]
    assert "@main" not in (ROOT / "examples/ci/t2s-gate.yml").read_text()
    assert (ROOT / "examples/ci/t2s-gate.yml").read_text().count(
        "@0000000000000000000000000000000000000000"
    ) == 3


def test_all_third_party_actions_are_pinned_to_full_commit_shas():
    for path in [ACTION, *WORKFLOWS]:
        for step in _steps(_load(path)):
            uses = step.get("uses", "")
            if not uses or uses.startswith("./"):
                continue
            _, _, ref = uses.partition("@")
            assert SHA.fullmatch(ref), f"{path}: unpinned action {uses}"
