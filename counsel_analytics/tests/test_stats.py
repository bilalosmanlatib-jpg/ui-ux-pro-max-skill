from datetime import datetime

from counsel_analytics.metrics._stats import business_days_between, linear_trend_slope


def test_business_days_between_same_week():
    # Monday to Friday, same week -> 4 business days
    start = datetime(2026, 1, 5)  # Monday
    end = datetime(2026, 1, 9)  # Friday
    assert business_days_between(start, end) == 4.0


def test_business_days_between_spans_weekend():
    start = datetime(2026, 1, 9)  # Friday
    end = datetime(2026, 1, 12)  # Monday
    assert business_days_between(start, end) == 1.0


def test_business_days_between_end_before_start_is_zero():
    start = datetime(2026, 1, 12)
    end = datetime(2026, 1, 5)
    assert business_days_between(start, end) == 0.0


def test_linear_trend_slope_increasing():
    slope = linear_trend_slope([1, 2, 3, 4], [1, 2, 3, 4])
    assert slope == 1.0


def test_linear_trend_slope_single_point_is_zero():
    assert linear_trend_slope([1.0], [5.0]) == 0.0
