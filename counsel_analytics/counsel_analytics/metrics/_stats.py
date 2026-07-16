"""Tiny stdlib-only stats helpers shared by the metrics modules.

Kept deliberately dependency-free (no numpy/scipy) since the MVP pipeline
has no need for anything beyond mean/median/a linear trend slope.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median as _median


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def median(values: list[float]) -> float:
    return _median(values) if values else 0.0


def linear_trend_slope(xs: list[float], ys: list[float]) -> float:
    """Least-squares slope of y vs x. Returns 0.0 for <2 points or when x
    has no variance (can't fit a trend to a single x value)."""
    n = len(xs)
    if n < 2:
        return 0.0
    mean_x, mean_y = mean(xs), mean(ys)
    covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    variance = sum((x - mean_x) ** 2 for x in xs)
    return covariance / variance if variance else 0.0


def business_days_between(start: datetime, end: datetime) -> float:
    """Whole weekdays strictly between `start`'s date and `end`'s date
    (inclusive of the end date), ignoring intraday hours. MVP approximation
    — swap for a real holiday calendar if precision matters later."""
    if end <= start:
        return 0.0
    total_days = (end.date() - start.date()).days
    business_days = 0
    for offset in range(1, total_days + 1):
        if (start.date() + timedelta(days=offset)).weekday() < 5:
            business_days += 1
    return float(business_days)
