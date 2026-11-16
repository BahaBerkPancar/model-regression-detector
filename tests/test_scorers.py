import pytest

from model_regression_detector import scorers as sc


def test_exact_match_normalisation():
    assert sc.exact_match("  Paris \n", "Paris")
    assert not sc.exact_match("paris", "Paris")
    assert sc.exact_match("paris", "Paris", casefold=True)
    assert not sc.exact_match("a  b", "a b")
    assert sc.exact_match("a  b", "a b", collapse_whitespace=True)
    assert not sc.exact_match(" x", "x", strip=False)
    assert sc.exact_match(3, 3)


def test_numeric_tolerance():
    assert sc.numeric_tolerance("3.14", 3.14)
    assert sc.numeric_tolerance(" 100 ", 100.4, abs_tol=0.5)
    assert not sc.numeric_tolerance(100, 101, abs_tol=0.5)
    assert sc.numeric_tolerance(1000, 1010, rel_tol=0.02)
    assert not sc.numeric_tolerance("abc", 1)
    assert not sc.numeric_tolerance(True, 1)
    assert not sc.numeric_tolerance("nan", "nan")


def test_regex():
    assert sc.regex_match("order #123 shipped", r"#\d+")
    assert not sc.regex_match("order #123 shipped", r"#\d+", full=True)
    assert sc.regex_match("ABC", "abc", ignore_case=True, full=True)


def test_json_fields():
    out = '{"a": {"b": [1, 2.0]}, "ok": true}'
    assert sc.json_field_equals(out, {"a.b.1": 2, "ok": True})
    assert not sc.json_field_equals(out, {"a.b.5": 1})
    assert not sc.json_field_equals("not json", {"a": 1})
    assert sc.json_field_equals({"x": 1}, {"x": 1.0})
    assert not sc.json_field_equals({"x": 1}, {"x": 2})


def test_rows_equal():
    a = [[1, "x"], [2, "y"]]
    assert sc.rows_equal(a, [[2, "y"], [1, "x"]])
    assert not sc.rows_equal(a, [[2, "y"], [1, "x"]], ordered=True)
    assert sc.rows_equal(a, [[1.0, "x"], [2, "y"]], ordered=True)
    dup = [[1], [1]]
    assert not sc.rows_equal(dup, [[1]])  # multiset
    assert sc.rows_equal(dup, [[1]], distinct=True)  # set
    assert not sc.rows_equal("nope", a)


def test_registry():
    assert "exact_match" in sc.scorer_names()
    assert sc.get_scorer("regex") is sc.regex_match

    @sc.register_scorer("always_true_test")
    def _always(output, expected):
        return True

    assert sc.get_scorer("always_true_test")("a", "b") is True
    with pytest.raises(ValueError):
        sc.register_scorer("always_true_test")(_always)
    with pytest.raises(KeyError, match="unknown scorer"):
        sc.get_scorer("missing_scorer")
