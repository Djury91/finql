from datetime import date

import pytest

from finql.pipelines.seed.reference import easter_sunday, hungarian_holidays
from finql.pipelines.seed.scales import SCALES, Scale


@pytest.mark.parametrize(
    ("year", "expected"),
    [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)), (2026, date(2026, 4, 5))],
)
def test_easter_sunday(year: int, expected: date) -> None:
    assert easter_sunday(year) == expected


def test_hungarian_holidays_include_movable_feasts() -> None:
    holidays = hungarian_holidays(2026)

    assert date(2026, 4, 3) in holidays  # Good Friday
    assert date(2026, 4, 6) in holidays  # Easter Monday
    assert date(2026, 5, 25) in holidays  # Whit Monday
    assert date(2026, 10, 23) in holidays
    assert len(holidays) == 11


def test_scale_period_is_whole_months_ending_with_the_business_date() -> None:
    tiny, small = SCALES["tiny"], SCALES["small"]

    assert (tiny.period_start, tiny.business_date) == (date(2025, 7, 1), date(2026, 9, 30))
    assert (small.period_start, small.business_date) == (date(2024, 10, 1), date(2026, 9, 30))


def test_scale_period_across_year_end() -> None:
    scale = Scale("x", 1, 1, months=2, branches=1, merchants=1, end_month=date(2026, 12, 1))

    assert (scale.period_start, scale.business_date) == (date(2026, 11, 1), date(2026, 12, 31))
