import pytest

from robomcp_platform.stats import wilson_interval


@pytest.mark.parametrize(
    ("k", "n", "lo", "hi"),
    [
        # Reference values (Wilson score, z = 1.96), e.g. from statsmodels proportion_confint(method="wilson").
        (5, 10, 0.2366, 0.7634),
        (0, 10, 0.0, 0.2775),
        (10, 10, 0.7225, 1.0),
        (81, 263, 0.2553, 0.3662),
    ],
)
def test_matches_reference_values(k, n, lo, hi):
    got_lo, got_hi = wilson_interval(k, n)
    assert got_lo == pytest.approx(lo, abs=1e-4)
    assert got_hi == pytest.approx(hi, abs=1e-4)


def test_no_trials_gives_uninformative_interval():
    assert wilson_interval(0, 0) == (0.0, 1.0)


def test_interval_contains_point_estimate_and_stays_in_unit_range():
    for n in (1, 2, 7, 50):
        for k in range(n + 1):
            lo, hi = wilson_interval(k, n)
            assert 0.0 <= lo <= k / n <= hi <= 1.0


def test_interval_narrows_with_more_trials():
    lo_small, hi_small = wilson_interval(5, 10)
    lo_big, hi_big = wilson_interval(500, 1000)
    assert hi_big - lo_big < hi_small - lo_small


@pytest.mark.parametrize(("k", "n"), [(-1, 5), (6, 5), (0, -1)])
def test_rejects_impossible_counts(k, n):
    with pytest.raises(ValueError):
        wilson_interval(k, n)
