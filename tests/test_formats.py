import json

import pytest

from model_regression_detector.config import Config, load_config
from model_regression_detector.formats import FormatError, load_run, load_suite

SUITE = """name: s
metrics:
  - {name: ok, kind: pass_fail}
  - {name: sim, kind: score}
cases:
  - {id: a, input: q1, expected: x, tags: [t1]}
  - {id: b, input: q2}
"""


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p


def test_valid_suite(tmp_path):
    suite = load_suite(write(tmp_path, "s.yaml", SUITE))
    assert [c.id for c in suite.cases] == ["a", "b"]
    assert suite.cases[1].tags == [] and suite.cases[1].expected is None
    assert suite.metric("sim").higher_is_better is True


def test_suite_errors_name_file_and_case(tmp_path):
    dup = SUITE.replace("id: b", "id: a")
    with pytest.raises(FormatError, match=r"s\.yaml.*duplicate case id 'a'"):
        load_suite(write(tmp_path, "s.yaml", dup))
    bad = SUITE.replace("{id: b, input: q2}", "{id: b, input: q2, tagz: [x]}")
    with pytest.raises(FormatError, match=r"case 'b' \(#2\)\.tagz"):
        load_suite(write(tmp_path, "s.yaml", bad))
    with pytest.raises(FormatError, match="kind"):
        load_suite(write(tmp_path, "s.yaml", SUITE.replace("score", "banana")))
    with pytest.raises(FormatError, match="higher_is_better"):
        load_suite(write(tmp_path, "s.yaml", SUITE.replace(
            "{name: ok, kind: pass_fail}", "{name: ok, kind: pass_fail, higher_is_better: false}")))
    with pytest.raises(FormatError, match="invalid YAML at line"):
        load_suite(write(tmp_path, "s.yaml", "name: [unclosed\n"))
    with pytest.raises(FormatError, match="YAML mapping"):
        load_suite(write(tmp_path, "s.yaml", "- just\n- a list\n"))
    with pytest.raises(FormatError, match="cannot read"):
        load_suite(tmp_path / "nope.yaml")


def header(**kw):
    return json.dumps({"type": "run", "suite": "s", "variant": "v", **kw})


def row(**kw):
    base = {"case_id": "a", "output": "x", "scores": {"ok": True, "sim": 0.5}}
    return json.dumps({**base, **kw})


@pytest.fixture
def suite(tmp_path):
    return load_suite(write(tmp_path, "s.yaml", SUITE))


def test_valid_run(tmp_path, suite):
    p = write(tmp_path, "r.jsonl", "\n".join([header(meta={"model": "m"}), row(), "",
                                              row(case_id="b", error="timeout", scores={})]))
    run = load_run(p, suite)
    assert run.header.meta == {"model": "m"}
    assert len(run.rows) == 2 and run.rows[1].error == "timeout"
    assert run.lines == [2, 4]


@pytest.mark.parametrize("lines, pattern", [
    ([header(), "{not json"], r"r\.jsonl:2: invalid JSON"),
    ([row()], r"r\.jsonl:1: bad run header"),
    ([header(suite="other")], r"r\.jsonl:1: run is for suite 'other'"),
    ([header(), row(case_id="zzz")], r"r\.jsonl:2: case 'zzz' is not in the suite"),
    ([header(), row(), row()], r"r\.jsonl:3: duplicate result for case 'a' repeat 0"),
    ([header(), row(scores={"ok": True})], r"r\.jsonl:2: case 'a': missing scores for sim"),
    ([header(), row(scores={"ok": "yes", "sim": 1})], r"pass_fail, expected true/false"),
    ([header(), row(scores={"ok": True, "sim": True})], r"is a score, expected a finite number"),
    ([header(), row(scores={"ok": True, "sim": 1, "zz": 1})], r"unknown metric 'zz'"),
    ([header(), row(latency_ms=-1)], r"r\.jsonl:2: bad result line"),
    ([header(), "[1, 2]"], r"each line must be a JSON object"),
    ([], r"empty file"),
])
def test_run_errors(tmp_path, suite, lines, pattern):
    with pytest.raises(FormatError, match=pattern):
        load_run(write(tmp_path, "r.jsonl", "\n".join(lines)), suite)


def test_config_defaults_and_overrides(tmp_path, suite):
    cfg = load_config(None)
    assert cfg.alpha == 0.05 and cfg.bootstrap_samples == 10000 and cfg.fail_on == "regression"
    p = write(tmp_path, "mrd.toml", """alpha = 0.1
seed = 5
[min_effect]
sim = 0.2
[tags.t1]
alpha = 0.2
[tags.t1.min_effect]
ok = 0.5
""")
    cfg = load_config(p)
    assert cfg.min_effect_for("sim", "score") == 0.2
    assert cfg.min_effect_for("ok", "pass_fail") == 0.05
    assert cfg.min_effect_for("ok", "pass_fail", "t1") == 0.5
    assert cfg.min_effect_for("other", "score") == 0.0
    assert cfg.alpha_for("t1") == 0.2 and cfg.alpha_for("zz") == 0.1
    cfg.check_against(suite)


def test_config_errors(tmp_path, suite):
    with pytest.raises(FormatError, match="invalid TOML"):
        load_config(write(tmp_path, "a.toml", "alpha = = 1"))
    with pytest.raises(FormatError, match="alpha"):
        load_config(write(tmp_path, "a.toml", "alpha = 2"))
    with pytest.raises(FormatError, match="fail_on"):
        load_config(write(tmp_path, "a.toml", 'fail_on = "sometimes"'))
    with pytest.raises(FormatError, match="nope"):
        load_config(write(tmp_path, "a.toml", "nope = 1"))
    with pytest.raises(FormatError, match="unknown metric"):
        Config(min_effect={"ghost": 0.1}).check_against(suite)


@pytest.mark.parametrize("field", ["latency_ms", "cost_usd"])
def test_infinite_numbers_rejected(tmp_path, suite, field):
    p = write(tmp_path, "r.jsonl", "\n".join([header(), row(**{field: float("inf")})]))
    # json.dumps writes Infinity, which json.loads accepts; the model must refuse it
    assert "Infinity" in p.read_text()
    with pytest.raises(FormatError, match=r"r\.jsonl:2: bad result line"):
        load_run(p, suite)
