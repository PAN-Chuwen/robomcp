"""Statistics for success rates."""

from __future__ import annotations

import math

Z_95 = 1.959963984540054  # two-sided 95% normal quantile


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """Wilson score interval for a binomial proportion.

    Unlike the normal approximation it stays inside [0, 1] and is informative at k = 0 or k = n,
    which is the common case for small agent evals. With no trials the interval is the whole [0, 1].
    """
    if n < 0 or not 0 <= successes <= n:
        raise ValueError(f"need 0 <= successes <= n, got successes={successes}, n={n}")
    if n == 0:
        return 0.0, 1.0
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z2 / (4 * n * n)) / denom
    # The bounds are exactly 0 at k = 0 and exactly 1 at k = n; avoid float cancellation residue there.
    lo = 0.0 if successes == 0 else max(0.0, centre - half)
    hi = 1.0 if successes == n else min(1.0, centre + half)
    return lo, hi


def pass_hat_k(successes: int, n: int, k: int) -> float:
    """Unbiased estimate of pass^k (all of k independent trials succeed) from c successes in n trials.

    τ-bench's estimator C(c, k) / C(n, k): reliability, not best-of-k. Needs 1 <= k <= n.
    """
    if not 1 <= k <= n or not 0 <= successes <= n:
        raise ValueError(f"need 1 <= k <= n and 0 <= successes <= n, got c={successes}, n={n}, k={k}")
    return math.comb(successes, k) / math.comb(n, k)


def mcnemar_exact_p(only_a: int, only_b: int) -> float:
    """Two-sided exact McNemar p-value from the discordant pairs of a paired comparison.

    Pairs where both runs agree carry no information about which is better; under the null the
    discordant ones split 50/50, so the test is a binomial test on them.
    """
    n = only_a + only_b
    if n == 0:
        return 1.0
    k = min(only_a, only_b)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)
