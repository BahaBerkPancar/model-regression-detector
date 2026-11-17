"""Accept and inspect baseline runs with source-backed provenance."""

from __future__ import annotations

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .compare import compare_runs
from .config import load_config
from .formats import FormatError, load_run, load_suite


def provenance_path(baseline: str | Path) -> Path:
    path = Path(baseline)
    return path.with_name(path.name + ".provenance.json")


def _git_sha(source: Path, meta: dict[str, Any]) -> str | None:
    for key in ("git_sha", "commit_sha", "t2s_git_sha"):
        if meta.get(key):
            return str(meta[key])
    completed = subprocess.run(
        ["git", "-C", str(source.parent), "rev-parse", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def accept_baseline(
    run_path: str | Path,
    destination: str | Path,
    *,
    suite_path: str | Path | None = None,
    config_path: str | Path | None = None,
) -> dict[str, Any]:
    source = Path(run_path)
    target = Path(destination)
    candidate = load_run(source)
    previous = load_run(target) if target.exists() else None
    if previous and previous.header.suite != candidate.header.suite:
        raise FormatError(
            f"{source}: run is for suite {candidate.header.suite!r}, but {target} stores "
            f"suite {previous.header.suite!r}"
        )

    verdict = "NOT_APPLICABLE"
    previous_variant = None
    if previous:
        if suite_path is None:
            raise ValueError("--suite is required when replacing an existing baseline")
        suite = load_suite(suite_path)
        cfg = load_config(config_path)
        cfg.check_against(suite, str(config_path or "config"))
        previous = load_run(target, suite)
        candidate = load_run(source, suite)
        verdict = compare_runs(suite, previous, candidate, cfg).verdict
        previous_variant = previous.header.variant
    elif suite_path is not None:
        suite = load_suite(suite_path)
        load_run(source, suite)

    provenance = {
        "accepted_at": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(source, candidate.header.meta),
        "suite": candidate.header.suite,
        "variant": candidate.header.variant,
        "source": str(source),
        "previous_variant": previous_variant,
        "verdict_vs_previous": verdict,
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    provenance_path(target).write_text(
        json.dumps(provenance, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return provenance


def show_baseline(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    run = load_run(target)
    sidecar = provenance_path(target)
    provenance = None
    if sidecar.exists():
        try:
            provenance = json.loads(sidecar.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise FormatError(f"{sidecar}: invalid JSON: {exc.msg}") from exc
    return {
        "path": str(target),
        "suite": run.header.suite,
        "variant": run.header.variant,
        "created_at": run.header.created_at,
        "rows": len(run.rows),
        "provenance": provenance,
    }
