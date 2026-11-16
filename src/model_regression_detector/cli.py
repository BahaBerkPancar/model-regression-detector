import argparse

from . import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="model-regression-detector",
        description="Catches worse answers from prompt or model changes before they ship: runs an eval suite against a baseline and fails CI on statistically significant regressions (first target: text-to-sql-guardrails).",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.parse_args(argv)
    print("Hello from model-regression-detector")
    return 0
