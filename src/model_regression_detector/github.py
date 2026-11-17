"""Small, dependency-free helpers for GitHub Actions file and command protocols."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .compare import INCONCLUSIVE, REGRESSION

SUMMARY_LIMIT = 1024 * 1024
TRUNCATION_NOTE = "\n\n> Report truncated to fit GitHub's 1 MiB job-summary limit.\n"


def running_on_github() -> bool:
    return os.environ.get("GITHUB_ACTIONS") == "true"


def _workflow_escape(value: Any) -> str:
    """Escape untrusted text for the workflow-command data field."""
    return str(value).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _single_line(value: Any) -> str:
    """Keep one output assignment on one line without interpreting its contents."""
    return str(value).replace("\r", " ").replace("\n", " ")


def append_step_summary(markdown: str, path: str | Path) -> None:
    """Append a report without letting the step summary grow past GitHub's limit."""
    destination = Path(path)
    used = destination.stat().st_size if destination.exists() else 0
    available = max(0, SUMMARY_LIMIT - used)
    payload = markdown.encode("utf-8")
    if len(payload) <= available:
        addition = payload
    else:
        note = TRUNCATION_NOTE.encode("utf-8")
        prefix_size = max(0, available - len(note))
        prefix = payload[:prefix_size].decode("utf-8", errors="ignore").encode("utf-8")
        addition = (prefix + note)[:available]
    if addition:
        with destination.open("ab") as handle:
            handle.write(addition)


def write_outputs(values: dict[str, Any], path: str | Path) -> None:
    destination = Path(path)
    with destination.open("a", encoding="utf-8", newline="\n") as handle:
        for name, value in values.items():
            handle.write(f"{name}={_single_line(value)}\n")


def publish_comparison(result: dict[str, Any], markdown: str, exit_code: int) -> None:
    """Publish a completed comparison when GitHub exposes its protocol files."""
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    output = os.environ.get("GITHUB_OUTPUT")
    if summary:
        append_step_summary(markdown, summary)
    if output:
        regressed = ",".join(
            _single_line(metric["name"])
            for metric in result["metrics"]
            if metric["verdict"] == REGRESSION
        )
        write_outputs(
            {
                "verdict": result["verdict"],
                "exit_code": exit_code,
                "regressed_metrics": regressed,
            },
            output,
        )
    if summary or output or running_on_github():
        if result["verdict"] == REGRESSION:
            print(f"::error::{_workflow_escape('; '.join(result['reasons']))}")
        elif result["verdict"] == INCONCLUSIVE:
            print(f"::warning::{_workflow_escape('; '.join(result['reasons']))}")
