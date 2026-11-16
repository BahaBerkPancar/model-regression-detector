import math
import random

import pytest

from model_regression_detector.stats import (
    bootstrap_ci,
    holm_adjust,
    mcnemar_exact,
    min_discordant,
    percentile,
    sign_flip_pvalue,
)


def test_mcnemar_hand_computed():
    # b=10, c=2: n=12, P(X<=2) = (1 + 12 + 66) / 4096, two-sided = 79 / 2048
    assert mcnemar_exact(10, 2) == pytest.approx(79 / 2048)
    assert mcnemar_exact(10, 2) == pytest.approx(0.0386, abs=5e-5)
    assert mcnemar_exact(2, 10) == mcnemar_exact(10, 2)


def test_mcnemar_edges():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(5, 5) == 1.0  # capped at 1
    assert mcnemar_exact(8, 0) == pytest.approx(2 / 256)
    assert mcnemar_exact(6, 0) == pytest.approx(2 / 64)
    assert mcnemar_exact(5, 0) == pytest.approx(2 / 32)
    assert mcnemar_exact(3, 1) == pytest.approx(2 * (1 + 4) / 16)


def test_min_discordant():
    assert min_discordant(0.05) == 6  # 2/32 = 0.0625 >= 0.05, 2/64 = 0.031 < 0.05
    assert min_discordant(0.01) == 8
    assert mcnemar_exact(5, 0) >= 0.05 > mcnemar_exact(6, 0)


def test_sign_flip_known_cases():
    # three positive diffs: only all-plus and all-minus reach |sum| = 6 -> 2/8
    assert sign_flip_pvalue([1, 2, 3], 1000, 0) == pytest.approx(0.25)
    # six equal diffs: 2/64
    assert sign_flip_pvalue([1.0] * 6, 1000, 0) == pytest.approx(2 / 64)
    # symmetric diffs have observed sum 0 -> every pattern qualifies
    assert sign_flip_pvalue([1, -1], 1000, 0) == 1.0
    # zeros are ignored, and no signal at all gives 1
    assert sign_flip_pvalue([0, 0, 0], 1000, 0) == 1.0
    assert sign_flip_pvalue([0, 1, 2, 3], 1000, 0) == pytest.approx(0.25)


def test_sign_flip_monte_carlo_close_to_exact_value():
    diffs = [1.0] * 20  # m = 20 > exact limit; true p = 2 / 2**20, MC floor is 1/(B+1)
    p = sign_flip_pvalue(diffs, 2000, 3)
    assert p == pytest.approx(1 / 2001)
    mixed = [1.0] * 12 + [-1.0] * 8  # sum 4, p around 0.5
    assert 0.3 < sign_flip_pvalue(mixed, 5000, 3) < 0.8


def test_bootstrap_is_seeded_and_brackets_the_mean():
    diffs = [1.0, 0.0, 1.0, 1.0, 0.0, 1.0, 0.0, 1.0]
    a = bootstrap_ci(diffs, 2000, 11)
    assert a == bootstrap_ci(diffs, 2000, 11)
    assert a != bootstrap_ci(diffs, 2000, 12)
    assert a[0] <= sum(diffs) / len(diffs) <= a[1]
    assert bootstrap_ci([], 100, 0) == (0.0, 0.0)


def test_bootstrap_ci_coverage_sanity():
    rng = random.Random(123)
    true_mean, hits, trials = 0.5, 0, 150
    for t in range(trials):
        sample = [rng.gauss(true_mean, 1.0) for _ in range(30)]
        lo, hi = bootstrap_ci(sample, 400, t)
        hits += lo <= true_mean <= hi
    # nominal 95%; small samples under-cover a little, so accept 85%+
    assert hits / trials >= 0.85


def test_holm():
    # classic example: m=3, sorted p = .01,.02,.04 -> .03, .04, .04
    adj = holm_adjust([0.04, 0.01, 0.02])
    assert adj == pytest.approx([0.04, 0.03, 0.04])
    assert holm_adjust([0.5]) == [0.5]
    assert holm_adjust([0.6, 0.9]) == pytest.approx([1.0, 1.0])
    assert holm_adjust([]) == []
    assert all(a >= p for a, p in zip(holm_adjust([0.001, 0.2, 0.03]), [0.001, 0.2, 0.03],
                                      strict=True))


def test_percentile():
    assert percentile([10], 95) == 10
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert math.isclose(percentile([0, 100], 95), 95)
