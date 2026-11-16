"""Statistics, pure Python (no scipy): exact McNemar, paired bootstrap, sign-flip test, Holm."""

from __future__ import annotations

import random
from math import comb

EPS = 1e-12


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts b and c.

    Under H0 each discordant pair is a fair coin flip, so b ~ Binomial(b + c, 1/2).
    p = min(1, 2 * P(X <= min(b, c))). Integer arithmetic until the final division.
    """
    n = b + c
    if n == 0:
        return 1.0
    tail = sum(comb(n, i) for i in range(min(b, c) + 1))
    return min(1.0, 2 * tail / 2**n)


def min_discordant(alpha: float) -> int:
    """Fewest discordant pairs that can ever give p < alpha (all of them one-sided).

    The smallest p with n discordant pairs is 2 / 2**n, which has to be below alpha.
    """
    n = 1
    while 2.0 ** (1 - n) >= alpha:
        n += 1
    return n


def mean(values: list[float]) -> float:
    return sum(values) / len(values)


def bootstrap_ci(
    diffs: list[float], samples: int, seed: int, level: float = 0.95
) -> tuple[float, float]:
    """Percentile bootstrap CI of the mean paired difference, resampling cases."""
    if not diffs:
        return (0.0, 0.0)
    rng = random.Random(seed)
    n = len(diffs)
    means = sorted(sum(rng.choices(diffs, k=n)) / n for _ in range(samples))
    tail = (1 - level) / 2
    lo = means[int(tail * samples)]
    hi = means[min(samples - 1, int((1 - tail) * samples))]
    return (lo, hi)


def sign_flip_pvalue(diffs: list[float], samples: int, seed: int, exact_limit: int = 16) -> float:
    """Two-sided paired permutation (sign-flip) test on the mean difference.

    Zero differences carry no information and are dropped. With at most `exact_limit`
    non-zero differences all 2**m sign patterns are enumerated (exact); otherwise
    `samples` random patterns are drawn with the (count + 1) / (samples + 1) correction.
    """
    nz = [d for d in diffs if abs(d) > EPS]
    m = len(nz)
    if m == 0:
        return 1.0
    observed = abs(sum(nz))
    if m <= exact_limit:
        hits = 0
        for mask in range(2**m):
            total = sum(d if (mask >> i) & 1 else -d for i, d in enumerate(nz))
            if abs(total) >= observed - EPS:
                hits += 1
        return hits / 2**m
    rng = random.Random(seed)
    hits = 0
    for _ in range(samples):
        total = sum(d if rng.random() < 0.5 else -d for d in nz)
        if abs(total) >= observed - EPS:
            hits += 1
    return (hits + 1) / (samples + 1)


def holm_adjust(pvalues: list[float]) -> list[float]:
    """Holm-Bonferroni adjusted p-values, returned in the input order."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


def percentile(values: list[float], q: float) -> float:
    """Linear-interpolation percentile, q in [0, 100]."""
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    pos = (len(s) - 1) * q / 100
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)
