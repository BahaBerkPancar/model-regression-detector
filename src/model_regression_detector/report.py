"""Markdown rendering (from the JSON-able result dict) and JSON output."""

from __future__ import annotations

import json
import re
from typing import Any

TOP_FAILING = 10
CELL_LIMIT = 120
_ESCAPE = {"&": "&amp;", "<": "&lt;", ">": "&gt;", "|": "&#124;", "`": "&#96;", "[": "&#91;",
           "]": "&#93;", "*": "&#42;", "~": "&#126;", "\\": "&#92;", "@": "@&#8203;",
           "#": "#&#8203;"}
_AUTOLINK = re.compile(r"(?i)\b(https?|ftp)://")
_WWW = re.compile(r"(?i)\bwww\.")


def md_escape(value: Any, limit: int = CELL_LIMIT) -> str:
    """Make untrusted text safe inside a Markdown table cell: truncate, flatten whitespace,
    and entity-encode everything that could open HTML, code, links or a new table cell."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if isinstance(value, dict):
        text = ", ".join(f"{k}={v}" for k, v in value.items())
    text = "".join(ch if ch.isprintable() or ch == "\n" else " " for ch in text)
    text = " ".join(text.split())
    truncated = len(text) > limit
    text = text[:limit]
    out = "".join(_ESCAPE.get(ch, ch) for ch in text)
    out = _AUTOLINK.sub(lambda m: f"{m.group(1)}:&#8203;//", out)
    out = _WWW.sub("www&#8203;.", out)
    return out + ("&hellip;" if truncated else "")


def _num(x: float | None, digits: int = 3) -> str:
    return "n/a" if x is None else f"{x:.{digits}f}"


def _signed(x: float) -> str:
    return f"{x:+.3f}"


def _p(x: float | None) -> str:
    if x is None:
        return "-"
    return "<0.0001" if x < 0.0001 else f"{x:.4f}"


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    return [_row(header), _row(["---"] * len(header)), *(_row(r) for r in rows)]


def render_json(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n"


def render_markdown(res: dict[str, Any]) -> str:
    out: list[str] = []
    out.append(f"# Model regression check: {res['verdict']}")
    out.append("")
    missing = sorted(set(res["missing_in_baseline"]) | set(res["missing_in_candidate"]))
    out.append(
        f"Suite {md_escape(res['suite'])}. Baseline {md_escape(res['baseline']['variant'])} "
        f"vs candidate {md_escape(res['candidate']['variant'])}. "
        f"{res['n_paired']} of {res['n_suite_cases']} cases paired, {len(missing)} missing."
    )
    out.append("")
    for reason in res["reasons"]:
        out.append(f"- {md_escape(reason, 300)}")
    out.append("")

    out.append("## Metrics")
    out.append("")
    rows = []
    for m in res["metrics"]:
        rows.append([md_escape(m["name"]), m["kind"], _num(m["baseline"]), _num(m["candidate"]),
                     _signed(m["effect"]), f"[{_signed(m['ci_low'])}, {_signed(m['ci_high'])}]",
                     _p(m["p_value"]), f"{m['n_worse']}/{m['n_better']}", f"**{m['verdict']}**"])
    out += _table(["Metric", "Kind", "Baseline", "Candidate", "Delta", "95% CI", "p",
                   "Worse/better", "Verdict"], rows)
    out.append("")
    for m in res["metrics"]:
        out.append(f"- {md_escape(m['name'])}: {md_escape(m['reason'], 300)}")
    out.append("")

    if res["slices"]:
        out.append("## Slices by tag")
        out.append("")
        out.append("Exploratory. The p (Holm) column is corrected for the number of slices "
                   "tested per metric and is the one the slice verdict uses.")
        out.append("")
        rows = []
        for s in res["slices"]:
            rows.append([md_escape(s["tag"]), md_escape(s["name"]), str(s["n"]),
                         _num(s["baseline"]), _num(s["candidate"]), _signed(s["effect"]),
                         f"[{_signed(s['ci_low'])}, {_signed(s['ci_high'])}]",
                         _p(s["p_value"]), _p(s["p_adjusted"]), s["verdict"]])
        out += _table(["Tag", "Metric", "n", "Baseline", "Candidate", "Delta", "95% CI", "p",
                       "p (Holm)", "Verdict"], rows)
        out.append("")

    cases = res["cases"]
    nf = cases["newly_failing"]
    out.append(f"## Newly failing cases ({len(nf)})")
    out.append("")
    if nf:
        rows = [[md_escape(c["case_id"]), md_escape(c["metric"]), md_escape(c["expected"]),
                 md_escape(c["baseline_output"]),
                 md_escape(c["candidate_error"] and f"ERROR: {c['candidate_error']}"
                           or c["candidate_output"])] for c in nf[:TOP_FAILING]]
        out += _table(["Case", "Metric", "Expected", "Baseline output", "Candidate output"], rows)
        if len(nf) > TOP_FAILING:
            out.append("")
            out.append(f"Showing {TOP_FAILING} of {len(nf)}. More are in the JSON report.")
    else:
        out.append("None.")
    out.append("")

    def ids(entries: list[dict[str, Any]]) -> str:
        if not entries:
            return "None."
        return ", ".join(md_escape(e["case_id"]) for e in entries)

    out.append(f"## Newly passing cases ({len(cases['newly_passing'])})")
    out.append("")
    out.append(ids(cases["newly_passing"]))
    out.append("")
    out.append(f"## Still failing cases ({len(cases['still_failing'])})")
    out.append("")
    out.append(ids(cases["still_failing"]))
    out.append("")
    out.append(f"## Flaky cases ({len(cases['flaky'])})")
    out.append("")
    if cases["flaky"]:
        out.append("Passed and failed within one run, so the majority result was used.")
        out.append("")
        out += _table(["Case", "Metric", "Run", "Pass rate"],
                      [[md_escape(f["case_id"]), md_escape(f["metric"]), f["run"],
                        _num(f["pass_rate"], 2)] for f in cases["flaky"]])
    else:
        out.append("None.")
    out.append("")
    if cases["errors"]:
        out.append(f"## Errors ({len(cases['errors'])})")
        out.append("")
        out += _table(["Run", "Case", "Repeat", "Error"],
                      [[e["run"], md_escape(e["case_id"]), str(e["repeat"]), md_escape(e["error"])]
                       for e in cases["errors"]])
        out.append("")

    if res["latency"] or res["cost"]:
        out.append("## Latency and cost")
        out.append("")
        lat = res["latency"]
        if lat:
            def pct(x: float | None) -> str:
                return "n/a" if x is None else f"{x:+.1f}%"

            out.append(f"- Latency p50: {lat['baseline']['p50']:.1f} ms to "
                       f"{lat['candidate']['p50']:.1f} ms ({pct(lat['p50_change_pct'])})")
            out.append(f"- Latency p95: {lat['baseline']['p95']:.1f} ms to "
                       f"{lat['candidate']['p95']:.1f} ms ({pct(lat['p95_change_pct'])})")
        cost = res["cost"]
        if cost:
            change = "n/a" if cost["change_pct"] is None else f"{cost['change_pct']:+.1f}%"
            out.append(f"- Total cost: ${cost['baseline_total']:.4f} to "
                       f"${cost['candidate_total']:.4f} ({change})")
        out.append("")

    s = res["settings"]
    out.append("## Settings")
    out.append("")
    out.append(f"- alpha {s['alpha']}, bootstrap samples {s['bootstrap_samples']}, "
               f"seed {s['seed']}, fail_on `{s['fail_on']}`")
    out.append(f"- min_effect: default {s['default_min_effect']} for pass_fail metrics"
               + (f", overrides {md_escape(s['min_effect'], 300)}" if s["min_effect"] else ""))
    out.append("- Tests: McNemar exact (pass_fail), sign-flip permutation (score), "
               "percentile bootstrap CI, Holm across slices.")
    for label in ("baseline", "candidate"):
        meta = res[label]["meta"]
        if meta:
            out.append(f"- {label} meta: {md_escape(meta, 300)}")
    return "\n".join(out) + "\n"
