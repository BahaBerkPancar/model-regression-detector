"""The `mrd` command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import NoReturn

from . import __version__
from .compare import INCONCLUSIVE, REGRESSION, compare_runs
from .config import load_config
from .formats import FormatError, load_run, load_suite
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
    if args.md:
        Path(args.md).write_text(markdown, encoding="utf-8")
    if args.json:
        Path(args.json).write_text(render_json(result), encoding="utf-8")
    if args.md or args.json:
        print(f"Verdict: {result['verdict']}")
        for reason in result["reasons"]:
            print(f"  - {reason}")
    else:
        print(markdown, end="")
    if result["verdict"] == REGRESSION:
        return EXIT_REGRESSION
    if result["verdict"] == INCONCLUSIVE and not args.inconclusive_ok:
        return EXIT_INCONCLUSIVE
    return EXIT_OK


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


def main(argv: list[str] | None = None) -> int:
    args = _build().parse_args(argv)
    handlers = {"validate": _cmd_validate, "compare": _cmd_compare, "report": _cmd_report}
    try:
        return handlers[args.command](args)
    except (FormatError, OSError, ValueError) as exc:
        print(f"error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_USAGE


if __name__ == "__main__":
    sys.exit(main())
