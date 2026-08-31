"""Feature engineering.

Two decisions are learned from history:

* which **shift** a person should move to, given the shift they just worked;
* which **week-off block** they should get.

Both are framed as ranking problems: score every legal candidate, label the one
the historical roster actually used as 1 and the rest as 0. :class:`Aggregates`
carries the running per-employee and global statistics the features are built
from, and is only ever updated with months *earlier* than the one being scored,
so training never peeks at its own answer.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Optional

from .config import SHIFTS, SHIFT_INDEX, off_block
from .models import MonthRoster

SHIFT_FEATURES = [
    "rotation_distance",     # 1..3 steps forward around Morning->...->Night
    "is_forward_rotation",
    "candidate_is_night",
    "previous_was_night",
    "employee_share_of_candidate",
    "employee_months_seen",
    "months_since_candidate",
    "employee_night_share",
    "global_transition_prob",
    "global_share_of_candidate",
    "client_count",
]

OFF_FEATURES = [
    "start_sin",
    "start_cos",
    "covers_saturday",
    "covers_sunday",
    "covers_full_weekend",
    "employee_share_of_start",
    "months_since_start",
    "employee_weekend_off_share",
    "global_share_of_start",
    "shift_is_night",
    "off_length",
    "same_start_as_last_month",
    "client_count",
]

_CAP_MONTHS = 12.0


def _counter() -> defaultdict:
    """Module-level factory: a lambda here would make Aggregates unpicklable,
    and the whole model is persisted with joblib between requests."""
    return defaultdict(int)


class Aggregates:
    """Running history statistics, updated month by month."""

    def __init__(self) -> None:
        self.month_count = 0
        self.employee_shift_counts: dict[str, dict[str, int]] = defaultdict(_counter)
        self.employee_months: dict[str, int] = defaultdict(int)
        self.employee_last_shift_month: dict[tuple[str, str], int] = {}
        self.employee_start_counts: dict[str, dict[int, int]] = defaultdict(_counter)
        self.employee_last_start_month: dict[tuple[str, int], int] = {}
        self.employee_weekend_offs: dict[str, int] = defaultdict(int)
        self.employee_off_months: dict[str, int] = defaultdict(int)
        self.employee_last_start: dict[str, Optional[int]] = {}
        self.transition_counts: dict[tuple[str, str], int] = defaultdict(int)
        self.global_shift_counts: dict[str, int] = defaultdict(int)
        self.global_start_counts: dict[int, int] = defaultdict(int)
        self._previous_shift: dict[str, str] = {}

    # -- building ---------------------------------------------------------
    def update(self, roster: MonthRoster) -> None:
        index = self.month_count
        for employee in roster.employees:
            name = employee.name
            if employee.shift:
                previous = self._previous_shift.get(name)
                if previous:
                    self.transition_counts[(previous, employee.shift)] += 1
                self._previous_shift[name] = employee.shift
                self.employee_shift_counts[name][employee.shift] += 1
                self.employee_last_shift_month[(name, employee.shift)] = index
                self.global_shift_counts[employee.shift] += 1
                self.employee_months[name] += 1
            if employee.off_start is not None and employee.off_length:
                start = employee.off_start
                self.employee_start_counts[name][start] += 1
                self.employee_last_start_month[(name, start)] = index
                self.employee_last_start[name] = start
                self.global_start_counts[start] += 1
                self.employee_off_months[name] += 1
                if any(day >= 5 for day in off_block(start, employee.off_length)):
                    self.employee_weekend_offs[name] += 1
        self.month_count += 1

    def previous_shift(self, name: str) -> Optional[str]:
        return self._previous_shift.get(name)

    # -- lookups ----------------------------------------------------------
    def _employee_share(self, name: str, shift: str) -> float:
        months = self.employee_months.get(name, 0)
        if not months:
            return 0.0
        return self.employee_shift_counts[name][shift] / months

    def _months_since_shift(self, name: str, shift: str) -> float:
        last = self.employee_last_shift_month.get((name, shift))
        if last is None:
            return 1.0
        return min(self.month_count - last, _CAP_MONTHS) / _CAP_MONTHS

    def _transition_prob(self, previous: str, candidate: str) -> float:
        total = sum(self.transition_counts[(previous, s)] for s in SHIFTS)
        return (self.transition_counts[(previous, candidate)] + 0.5) / (total + 2.0)

    def _global_shift_share(self, shift: str) -> float:
        total = sum(self.global_shift_counts.values())
        return self.global_shift_counts[shift] / total if total else 0.25

    def _start_share(self, name: str, start: int) -> float:
        months = self.employee_off_months.get(name, 0)
        if not months:
            return 0.0
        return self.employee_start_counts[name][start] / months

    def _months_since_start(self, name: str, start: int) -> float:
        last = self.employee_last_start_month.get((name, start))
        if last is None:
            return 1.0
        return min(self.month_count - last, _CAP_MONTHS) / _CAP_MONTHS

    def _weekend_off_share(self, name: str) -> float:
        months = self.employee_off_months.get(name, 0)
        return self.employee_weekend_offs[name] / months if months else 0.0

    def _global_start_share(self, start: int) -> float:
        total = sum(self.global_start_counts.values())
        return self.global_start_counts[start] / total if total else 1 / 7

    def night_share(self, name: str) -> float:
        return self._employee_share(name, "Night")

    # -- feature vectors --------------------------------------------------
    def shift_features(self, name: str, previous_shift: str, candidate: str,
                       client_count: int) -> list[float]:
        distance = (SHIFT_INDEX[candidate] - SHIFT_INDEX[previous_shift]) % len(SHIFTS)
        return [
            distance / 3.0,
            1.0 if distance == 1 else 0.0,
            1.0 if candidate == "Night" else 0.0,
            1.0 if previous_shift == "Night" else 0.0,
            self._employee_share(name, candidate),
            min(self.employee_months.get(name, 0), _CAP_MONTHS) / _CAP_MONTHS,
            self._months_since_shift(name, candidate),
            self.night_share(name),
            self._transition_prob(previous_shift, candidate),
            self._global_shift_share(candidate),
            min(client_count, 4) / 4.0,
        ]

    def off_features(self, name: str, shift: str, start: int, off_length: int,
                     client_count: int) -> list[float]:
        block = off_block(start, off_length)
        angle = 2 * math.pi * start / 7
        last_start = self.employee_last_start.get(name)
        return [
            math.sin(angle),
            math.cos(angle),
            1.0 if 5 in block else 0.0,
            1.0 if 6 in block else 0.0,
            1.0 if 5 in block and 6 in block else 0.0,
            self._start_share(name, start),
            self._months_since_start(name, start),
            self._weekend_off_share(name),
            self._global_start_share(start),
            1.0 if shift == "Night" else 0.0,
            off_length / 3.0,
            1.0 if last_start == start else 0.0,
            min(client_count, 4) / 4.0,
        ]
