"""Expanding one month's assignments into the day-by-day table."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .calendar_utils import Month, build_month
from .config import OFF_LABEL, SHIFTS, works_on
from .models import Assignment


@dataclass
class RosterRow:
    name: str
    clients: list[str]
    shift: str
    previous_shift: Optional[str]
    off_start: int
    off_length: int
    cells: list[str]
    reason: str = ""
    shift_score: float = 0.0
    off_score: float = 0.0

    @property
    def client_label(self) -> str:
        return ", ".join(self.clients)

    @property
    def working_days(self) -> int:
        return sum(1 for c in self.cells if c != OFF_LABEL)

    @property
    def off_days(self) -> int:
        return sum(1 for c in self.cells if c == OFF_LABEL)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "clients": self.clients,
            "client_label": self.client_label,
            "shift": self.shift,
            "previous_shift": self.previous_shift,
            "off_start": self.off_start,
            "off_length": self.off_length,
            "cells": self.cells,
            "reason": self.reason,
            "shift_score": self.shift_score,
            "off_score": self.off_score,
            "working_days": self.working_days,
            "off_days": self.off_days,
        }


@dataclass
class CoverageRow:
    client: str
    shift: str
    headcount: int
    per_day: list[int]

    @property
    def minimum(self) -> int:
        return min(self.per_day) if self.per_day else 0

    def to_dict(self) -> dict:
        return {"client": self.client, "shift": self.shift, "headcount": self.headcount,
                "per_day": self.per_day, "min": self.minimum}


@dataclass
class GeneratedRoster:
    month: Month
    rows: list[RosterRow]
    coverage: list[CoverageRow]
    header: list[str]
    meta: dict = field(default_factory=dict)
    validation: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "month": self.month.key,
            "month_label": self.month.label,
            "header": self.header,
            "days": [{"label": d.label, "weekday": d.weekday, "date": d.date.isoformat()}
                     for d in self.month.days],
            "rows": [r.to_dict() for r in self.rows],
            "coverage": [c.to_dict() for c in self.coverage],
            "clients": sorted({c for r in self.rows for c in r.clients}),
            "meta": self.meta,
            "validation": self.validation,
        }


def build_roster(assignments: list[Assignment], month_spec: str,
                 meta: Optional[dict] = None) -> GeneratedRoster:
    """Lay the weekly pattern over the real calendar of the target month."""
    month = build_month(month_spec)

    rows = []
    for assignment in assignments:
        cells = [
            assignment.shift if works_on(assignment.off_start, assignment.off_length, day.weekday)
            else OFF_LABEL
            for day in month.days
        ]
        rows.append(RosterRow(
            name=assignment.name,
            clients=list(assignment.clients),
            shift=assignment.shift,
            previous_shift=assignment.previous_shift,
            off_start=assignment.off_start,
            off_length=assignment.off_length,
            cells=cells,
            reason=assignment.reason,
            shift_score=assignment.shift_score,
            off_score=assignment.off_score,
        ))

    header = ["Name", "Client"] + [day.label for day in month.days]
    return GeneratedRoster(month=month, rows=rows, coverage=coverage_matrix(rows, month),
                           header=header, meta=meta or {})


def coverage_matrix(rows: list[RosterRow], month: Month) -> list[CoverageRow]:
    """Per client and shift, how many people are on duty on each day."""
    clients = sorted({c for row in rows for c in row.clients})
    coverage = []
    for client in clients:
        for shift in SHIFTS:
            staff = [r for r in rows if r.shift == shift and client in r.clients]
            per_day = [sum(1 for r in staff if r.cells[index] == shift)
                       for index in range(len(month.days))]
            coverage.append(CoverageRow(client=client, shift=shift,
                                        headcount=len(staff), per_day=per_day))
    return coverage
