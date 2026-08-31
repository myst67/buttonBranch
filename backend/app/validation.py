"""Independent re-check of the finished roster.

The solver is asked for a roster that obeys the rules; this checks the roster it
actually returned. A bug in the model, the scores or the calendar expansion
shows up here as a listed violation instead of a wrong sheet going out.
"""
from __future__ import annotations

from .config import (MAX_CLIENTS_PER_EMPLOYEE, MIN_CLIENTS_PER_EMPLOYEE,
                     MIN_EMPLOYEES_PER_CLIENT, OFF_DAYS_PER_WEEK, OFF_LABEL)
from .roster import GeneratedRoster


def validate(roster: GeneratedRoster) -> dict:
    errors: list[str] = []
    days = roster.month.days
    day_count = len(days)

    for row in roster.rows:
        # Rule 3: one shift for the whole month, different from last month's.
        worked = {c for c in row.cells if c != OFF_LABEL}
        if len(worked) != 1:
            errors.append(f"{row.name}: works {len(worked)} different shifts this month.")
        elif worked != {row.shift}:
            errors.append(f"{row.name}: sheet shows {worked} but the shift is {row.shift}.")
        if row.previous_shift and row.shift == row.previous_shift:
            errors.append(f"{row.name}: assigned {row.shift}, the same shift as last month.")

        # Rule 4: the right number of week-offs, in every full week.
        expected_offs = OFF_DAYS_PER_WEEK[row.shift]
        if row.off_length != expected_offs:
            errors.append(f"{row.name} ({row.shift}): off block is {row.off_length} days, "
                          f"expected {expected_offs}.")
        if row.off_days == 0:
            errors.append(f"{row.name}: never gets a week off.")
        for start in range(0, day_count - 6):
            offs = sum(1 for c in row.cells[start:start + 7] if c == OFF_LABEL)
            if offs != expected_offs:
                errors.append(
                    f"{row.name} ({row.shift}): {offs} off day(s) in the 7 days from "
                    f"{days[start].label}; expected {expected_offs}.")
                break

        # Rule 4/5: off days consecutive, and so are the working days. Runs that
        # touch the first or last day of the month are legitimately clipped.
        errors.extend(_run_errors(row, day_count, expected_offs, days, off=True))
        errors.extend(_run_errors(row, day_count, 7 - expected_offs, days, off=False))

    # Rule 5: every client covered in every shift on every day.
    for entry in roster.coverage:
        for index, count in enumerate(entry.per_day):
            if count == 0:
                errors.append(f'Client "{entry.client}" has nobody on {entry.shift} '
                              f"on {days[index].label}.")

    # Rule 2: the shape of the team, restated against the produced sheet.
    counts: dict[str, int] = {}
    for row in roster.rows:
        if not MIN_CLIENTS_PER_EMPLOYEE <= len(row.clients) <= MAX_CLIENTS_PER_EMPLOYEE:
            errors.append(f"{row.name}: has {len(row.clients)} client(s); expected "
                          f"{MIN_CLIENTS_PER_EMPLOYEE}-{MAX_CLIENTS_PER_EMPLOYEE}.")
        for client in row.clients:
            counts[client] = counts.get(client, 0) + 1
    for client, count in sorted(counts.items()):
        if count < MIN_EMPLOYEES_PER_CLIENT:
            errors.append(f'Client "{client}" is served by only {count} employee(s).')

    return {
        "ok": not errors,
        "errors": errors,
        "checked": {
            "employees": len(roster.rows),
            "clients": len(counts),
            "days": day_count,
            "client_shift_day_slots": len(roster.coverage) * day_count,
        },
    }


def _run_errors(row, day_count: int, expected: int, days, off: bool) -> list[str]:
    """Off days (and working days) must come one after another."""
    errors: list[str] = []
    run_start = None
    for index in range(day_count + 1):
        in_run = index < day_count and ((row.cells[index] == OFF_LABEL) == off)
        if in_run and run_start is None:
            run_start = index
        elif not in_run and run_start is not None:
            length = index - run_start
            clipped = run_start == 0 or index == day_count
            if length > expected or (length < expected and not clipped):
                kind = "off day" if off else "working day"
                errors.append(
                    f"{row.name} ({row.shift}): a run of {length} consecutive {kind}(s) from "
                    f"{days[run_start].label}; the pattern allows {expected}.")
                break
            run_start = None
    return errors
