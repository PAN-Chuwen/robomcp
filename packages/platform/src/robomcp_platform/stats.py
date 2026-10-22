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
