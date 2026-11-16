import json
import os
from pathlib import Path

from helpers import all_pass, make_run, make_suite, with_fail

from model_regression_detector.compare import compare_runs
from model_regression_detector.config import Config
from model_regression_detector.report import md_escape, render_json, render_markdown

GOLDEN = Path(__file__).parent / "golden" / "report.md"
CFG = Config(bootstrap_samples=300, seed=1)


def golden_result():
    suite = make_suite(20, tags={"a": range(10), "b": range(10, 20)}, score=True)
    sims_b = {f"c{i:02d}": 0.9 for i in range(20)}
    sims_c = {k: (0.5 if int(k[1:]) < 8 else 0.9) for k in sims_b}
    base_res = {k: [v, v] for k, v in all_pass().items()}
    cand_res = {k: [v, v] for k, v in with_fail(all_pass(), range(8)).items()}
    cand_res["c12"] = [True, False]  # flaky
    base = make_run("baseline", base_res, sims=sims_b,
                    latency={k: 100.0 for k in sims_b}, cost={k: 0.01 for k in sims_b},
                    outputs={f"c{i:02d}": f"answer {i}" for i in range(20)})
    cand = make_run("candidate", cand_res, sims=sims_c, errors={"c01"},
                    latency={k: 120.0 for k in sims_b}, cost={k: 0.011 for k in sims_b},
                    outputs={f"c{i:02d}": f"wrong {i}" for i in range(20)})
    return compare_runs(suite, base, cand, CFG).to_dict()


def test_markdown_matches_golden_file():
    text = render_markdown(golden_result())
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(text, encoding="utf-8")
    assert text == GOLDEN.read_text(encoding="utf-8")


def test_markdown_has_the_expected_sections():
    text = render_markdown(golden_result())
    assert text.startswith("# Model regression check: REGRESSION")
    for heading in ("## Metrics", "## Slices by tag", "## Newly failing cases (9)",
                    "## Flaky cases (1)", "## Errors (2)", "## Latency and cost", "## Settings"):
        assert heading in text


def test_json_roundtrip_renders_same_markdown():
    result = golden_result()
    assert render_markdown(json.loads(render_json(result))) == render_markdown(result)


def test_hostile_text_is_escaped():
    evil = "a | b `code` <script>alert(1)</script> [x](http://evil) **bold**\nnew line"
    suite = make_suite()
    outputs = {f"c{i:02d}": evil for i in range(20)}
    base = make_run("b", all_pass(), outputs=outputs)
    cand = make_run("c", with_fail(all_pass(), range(8)), outputs=outputs)
    result = compare_runs(suite, base, cand, CFG).to_dict()
    result["candidate"]["variant"] = "v`<b>|"
    text = render_markdown(result)
    assert "<script>" not in text and "<b>" not in text
    assert "&lt;script&gt;" in text
    row = next(line for line in text.splitlines() if line.startswith("| c00 |"))
    assert row.count("|") == 6  # 5 cells, no stray cell separators from the hostile text
    assert "`code`" not in text and "[x](" not in text and "**bold**" not in text
    assert "\n" not in md_escape(evil)


def test_escape_truncates():
    out = md_escape("x" * 500, limit=10)
    assert out == "x" * 10 + "&hellip;"
    assert md_escape({"k": "v"}) == "k=v"
    assert md_escape("a\x00b") == "a b"


def test_only_top_ten_newly_failing_shown():
    suite = make_suite()
    base, cand = make_run("b", all_pass()), make_run("c", with_fail(all_pass(), range(15)))
    text = render_markdown(compare_runs(suite, base, cand, CFG).to_dict())
    assert "Newly failing cases (15)" in text and "Showing 10 of 15" in text
    assert "| c09 |" in text and "| c10 |" not in text


def test_hostile_text_cannot_ping_link_or_escape_code_spans():
    evil = "@octocat see https://evil.example/x and www.evil.example #123 `x` ``y``"
    suite = make_suite()
    outputs = {f"c{i:02d}": evil for i in range(20)}
    base = make_run("b", all_pass(), outputs=outputs)
    cand = make_run("c", with_fail(all_pass(), range(8)), outputs=outputs)
    result = compare_runs(suite, base, cand, CFG).to_dict()
    result["candidate"]["variant"] = "v`@bob&"
    text = render_markdown(result)
    assert "@octocat" not in text and "@bob" not in text
    assert "https://" not in text and "www." not in text and "#123" not in text
    assert "@&#8203;octocat" in text
    head = text.splitlines()[2]
    assert "`" not in head  # untrusted names are plain escaped text, never inside a code span
    assert "&amp;" in head
