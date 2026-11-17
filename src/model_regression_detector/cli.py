"""The `mrd` command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn

from . import __version__
from .baseline import accept_baseline, show_baseline
from .compare import INCONCLUSIVE, REGRESSION, compare_runs
from .config import load_config
from .formats import FormatError, load_run, load_suite
from .github import publish_comparison, running_on_github
from .report import render_json, render_markdown

EXIT_OK, EXIT_REGRESSION, EXIT_INCONCLUSIVE, EXIT_USAGE = 0, 1, 2, 3


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        self.print_usage(sys.stderr)
        self.exit(EXIT_USAGE, f"{self.prog}: error: {message}\n")


def _build() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="mrd",
        description="Catches worse answers from prompt or model changes before they ship: "
        "compares an eval run against a baseline and fails CI on significant regressions.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    v = sub.add_parser("validate", help="check a suite file and optionally run files")
    v.add_argument("suite")
    v.add_argument("runs", nargs="*")

    c = sub.add_parser("compare", help="compare a candidate run against a baseline run")
    c.add_argument("--suite", required=True)
    c.add_argument("--baseline", required=True)
    c.add_argument("--candidate", required=True)
    c.add_argument("--config")
    c.add_argument("--md", help="write the Markdown report here")
    c.add_argument("--json", help="write the JSON report here")
    c.add_argument("--inconclusive-ok", action="store_true",
                   help="exit 0 instead of 2 when the result is INCONCLUSIVE")

    r = sub.add_parser("report", help="re-render the Markdown report from a JSON report")
    r.add_argument("--json", required=True)
    r.add_argument("--md", help="write here instead of stdout")

    run = sub.add_parser("run", help="execute an evaluation suite through an adapter")
    run.add_argument("--adapter", required=True, choices=["t2s"])
    run.add_argument("--generator", required=True)
    run.add_argument("--suite", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--repeats", type=int, default=1)
    run.add_argument("--variant", default="candidate")
    run.add_argument("--model", default="claude-sonnet-5-5")
    run.add_argument("--seed", type=int, default=17)
    run.add_argument("--yes-spend", action="store_true")

    t2s = sub.add_parser("t2s", help="text-to-sql-guardrails adapter utilities")
    t2ssub = t2s.add_subparsers(dest="t2s_command", required=True, parser_class=_Parser)
    export = t2ssub.add_parser("export-suite", help="export the t2s benchmark as an mrd suite")
    export.add_argument("--out", required=True)

    baseline = sub.add_parser("baseline", help="accept or inspect a stored baseline")
    bsub = baseline.add_subparsers(dest="baseline_command", required=True, parser_class=_Parser)
    accept = bsub.add_parser("accept", help="copy a run into the baseline with provenance")
    accept.add_argument("--run", required=True)
    accept.add_argument("--to", required=True)
    accept.add_argument("--suite", help="required when replacing an existing baseline")
    accept.add_argument("--config")
    show = bsub.add_parser("show", help="show a baseline header and acceptance provenance")
    show.add_argument("baseline")

    deepeval = sub.add_parser(
        "from-deepeval", help="convert an exported DeepEval result JSON file to mrd JSONL"
    )
    deepeval.add_argument("results")
    deepeval.add_argument("--out", help="write here instead of stdout")
    deepeval.add_argument("--suite", default="deepeval")
    deepeval.add_argument("--variant", default="candidate")
    deepeval.add_argument("--created-at")
    return parser


def _cmd_validate(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite)
    print(f"{args.suite}: ok ({len(suite.cases)} cases, {len(suite.metrics)} metrics)")
    for path in args.runs:
        run = load_run(path, suite)
        print(f"{path}: ok (variant {run.header.variant!r}, {len(run.rows)} results)")
    return EXIT_OK


def _cmd_compare(args: argparse.Namespace) -> int:
    suite = load_suite(args.suite)
    cfg = load_config(args.config)
    cfg.check_against(suite, args.config or "config")
    result = compare_runs(suite, load_run(args.baseline, suite), load_run(args.candidate, suite),
                          cfg).to_dict()
    markdown = render_markdown(result)
    exit_code = EXIT_OK
    if result["verdict"] == REGRESSION:
        exit_code = EXIT_REGRESSION
    elif result["verdict"] == INCONCLUSIVE and not args.inconclusive_ok:
        exit_code = EXIT_INCONCLUSIVE
    if args.md:
        Path(args.md).write_text(markdown, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(render_json(result), encoding="utf-8")
    if args.md or args.json or running_on_github():
        print(f"Verdict: {result['verdict']}")
        if not running_on_github():
            for reason in result["reasons"]:
                print(f"  - {reason}")
    else:
        print(markdown, end="")
    publish_comparison(result, markdown, exit_code)
    return exit_code


def _cmd_report(args: argparse.Namespace) -> int:
    try:
        result = json.loads(Path(args.json).read_text(encoding="utf-8"))
        markdown = render_markdown(result)
    except OSError as exc:
        raise FormatError(f"{args.json}: cannot read file: {exc.strerror}") from exc
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise FormatError(f"{args.json}: not a valid mrd JSON report ({exc})") from exc
    if args.md:
        Path(args.md).write_text(markdown, encoding="utf-8")
    else:
        print(markdown, end="")
    return EXIT_OK


def _cmd_t2s(args: argparse.Namespace) -> int:
    from .adapters.t2s import export_suite

    count = export_suite(args.out)
    print(f"Wrote {count} cases to {args.out}")
    return EXIT_OK


def _cmd_run(args: argparse.Namespace) -> int:
    if args.repeats < 1:
        raise ValueError("--repeats must be at least 1")
    from .adapters.t2s import estimate_anthropic, run

    if args.generator == "anthropic" and not args.yes_spend:
        estimate = estimate_anthropic(args.suite, args.model)
        cost = estimate["cost_usd"]
        shown = "unknown" if cost is None else f"${cost:.6f} USD"
        print("Cost estimate only; no model API call was made.")
        print(f"Estimated {estimate['calls']} calls; cost: {shown}")
        print("Re-run with --yes-spend to call the model.")
        return EXIT_USAGE
    count = run(
        suite_path=args.suite,
        output_path=args.out,
        generator_spec=args.generator,
        repeats=args.repeats,
        variant=args.variant,
        model=args.model,
        yes_spend=args.yes_spend,
        seed=args.seed,
    )
    print(f"Wrote {count} result rows to {args.out}")
    return EXIT_OK


def _cmd_baseline(args: argparse.Namespace) -> int:
    if args.baseline_command == "accept":
        provenance = accept_baseline(
            args.run, args.to, suite_path=args.suite, config_path=args.config
        )
        print(
            f"Accepted {provenance['variant']!r} for suite {provenance['suite']!r}: "
            f"{provenance['verdict_vs_previous']}"
        )
        print(f"Baseline: {args.to}")
        return EXIT_OK
    print(json.dumps(show_baseline(args.baseline), indent=2, sort_keys=True))
    return EXIT_OK


def _cmd_from_deepeval(args: argparse.Namespace) -> int:
    from .bridges.deepeval import export_json

    jsonl = export_json(
        args.results, suite=args.suite, variant=args.variant, created_at=args.created_at
    )
    if args.out:
        Path(args.out).write_text(jsonl, encoding="utf-8")
        print(f"Wrote {len(jsonl.splitlines()) - 1} result rows to {args.out}")
    else:
        print(jsonl, end="")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    args = _build().parse_args(argv)
    handlers = {
        "validate": _cmd_validate,
        "compare": _cmd_compare,
        "report": _cmd_report,
        "run": _cmd_run,
        "t2s": _cmd_t2s,
        "baseline": _cmd_baseline,
        "from-deepeval": _cmd_from_deepeval,
    }
    try:
        return handlers[args.command](args)
    except (FormatError, OSError, RuntimeError, ValueError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
