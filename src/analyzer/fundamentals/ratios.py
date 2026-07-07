"""Derive fundamental ratios / growth metrics from raw statement series.

Pure helper functions (no I/O) so fetchers can reuse them and tests can pin them.
All series are ordered OLDEST -> NEWEST unless noted.
"""

from __future__ import annotations

from collections.abc import Sequence


def cagr(first: float | None, last: float | None, years: int) -> float | None:
    """Compound annual growth rate in percent. Requires positive endpoints."""
    if first is None or last is None or years <= 0:
        return None
    if first <= 0 or last <= 0:
        return None
    return ((last / first) ** (1 / years) - 1) * 100.0


def yoy_growth(prev: float | None, curr: float | None) -> float | None:
    """Year-over-year growth %. Uses abs(prev) as base so sign is meaningful even
    when the prior value is negative (turnaround from a loss)."""
    if prev is None or curr is None or prev == 0:
        return None
    return (curr - prev) / abs(prev) * 100.0


def safe_ratio(num: float | None, den: float | None) -> float | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def count_positive(values: Sequence[float | None]) -> int:
    return sum(1 for v in values if v is not None and v > 0)


def count_negative(values: Sequence[float | None]) -> int:
    return sum(1 for v in values if v is not None and v < 0)


def is_declining(values: Sequence[float | None]) -> bool | None:
    """True if the (oldest->newest) numeric series ends lower than it started."""
    nums = [v for v in values if v is not None]
    if len(nums) < 2:
        return None
    return nums[-1] < nums[0]


def average(values: Sequence[float | None]) -> float | None:
    nums = [v for v in values if v is not None]
    if not nums:
        return None
    return sum(nums) / len(nums)
