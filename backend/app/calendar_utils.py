"""Turning "2025-07" into the Mon-01-Jul columns of the output sheet."""
from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass

from .config import MONTH_ABBR, WEEKDAYS

_MONTH_RE = re.compile(r"^(\d{4})-(\d{1,2})$")


@dataclass(frozen=True)
class Day:
    date: dt.date
    weekday: int          # 0 = Monday

    @property
    def label(self) -> str:
        return (f"{WEEKDAYS[self.weekday]}-{self.date.day:02d}-"
                f"{MONTH_ABBR[self.date.month - 1]}")


@dataclass(frozen=True)
class Month:
    year: int
    month: int
    days: list[Day]

    @property
    def key(self) -> str:
        return f"{self.year}-{self.month:02d}"

    @property
    def label(self) -> str:
        return f"{MONTH_ABBR[self.month - 1]} {self.year}"


def build_month(month_spec: str) -> Month:
    match = _MONTH_RE.match(str(month_spec).strip())
    if not match:
        raise ValueError(f'Month must look like "2025-07", got "{month_spec}".')
    year, month = int(match.group(1)), int(match.group(2))
    if not 1 <= month <= 12:
        raise ValueError(f"Month {month} is out of range.")
    _, day_count = calendar.monthrange(year, month)
    days = [Day(dt.date(year, month, day), dt.date(year, month, day).weekday())
            for day in range(1, day_count + 1)]
    return Month(year=year, month=month, days=days)


def next_month(month_spec: str) -> str:
    month = build_month(month_spec)
    year, number = month.year, month.month + 1
    if number == 13:
        year, number = year + 1, 1
    return f"{year}-{number:02d}"
