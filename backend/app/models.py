"""Plain data objects shared by the parser, the models, the solver and the API."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional

from .config import MONTH_ABBR, OFF_DAYS_PER_WEEK, WEEKDAYS, off_block


@dataclass
class EmployeeMonth:
    """What one person did in one month."""

    name: str
    clients: list[str]
    shift: Optional[str] = None
    off_start: Optional[int] = None       # 0 = Monday
    off_length: Optional[int] = None

    @property
    def off_days(self) -> list[str]:
        if self.off_start is None or not self.off_length:
            return []
        return [WEEKDAYS[d] for d in off_block(self.off_start, self.off_length)]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: dict) -> "EmployeeMonth":
        return cls(
            name=raw["name"],
            clients=list(raw.get("clients") or []),
            shift=raw.get("shift"),
            off_start=raw.get("off_start"),
            off_length=raw.get("off_length"),
        )


@dataclass
class MonthRoster:
    """A whole month of history: who worked which shift, with which week-off."""

    month: str                      # "2025-06"
    employees: list[EmployeeMonth]
    source: str = "upload"
    warnings: list[str] = field(default_factory=list)

    @property
    def year(self) -> int:
        return int(self.month.split("-")[0])

    @property
    def month_number(self) -> int:
        return int(self.month.split("-")[1])

    @property
    def label(self) -> str:
        return f"{MONTH_ABBR[self.month_number - 1]} {self.year}"

    @property
    def clients(self) -> list[str]:
        return sorted({c for e in self.employees for c in e.clients})

    def by_name(self) -> dict[str, EmployeeMonth]:
        return {e.name: e for e in self.employees}

    def next_month(self) -> str:
        year, month = self.year, self.month_number + 1
        if month == 13:
            year, month = year + 1, 1
        return f"{year}-{month:02d}"

    def to_dict(self) -> dict:
        return {
            "month": self.month,
            "source": self.source,
            "warnings": self.warnings,
            "employees": [e.to_dict() for e in self.employees],
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "MonthRoster":
        return cls(
            month=raw["month"],
            employees=[EmployeeMonth.from_dict(e) for e in raw["employees"]],
            source=raw.get("source", "upload"),
            warnings=list(raw.get("warnings") or []),
        )


@dataclass
class Assignment:
    """One person's plan for the month being generated."""

    name: str
    clients: list[str]
    previous_shift: Optional[str]
    shift: str
    off_start: int
    shift_score: float = 0.0
    off_score: float = 0.0
    reason: str = ""

    @property
    def off_length(self) -> int:
        return OFF_DAYS_PER_WEEK[self.shift]

    @property
    def off_days(self) -> list[str]:
        return [WEEKDAYS[d] for d in off_block(self.off_start, self.off_length)]

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "off_length": self.off_length,
            "off_days": self.off_days,
        }
