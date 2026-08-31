"""Scheduling rules and tunables, in one place."""
from __future__ import annotations

import os
from pathlib import Path

SHIFTS = ["Morning", "Afternoon", "Evening", "Night"]
SHIFT_INDEX = {shift: i for i, shift in enumerate(SHIFTS)}

#: Rule 4 - Night works 4 consecutive days with 3 week-offs, everyone else 5 with 2.
OFF_DAYS_PER_WEEK = {"Morning": 2, "Afternoon": 2, "Evening": 2, "Night": 3}

#: Rule 5 - a client must be staffed in every shift on every day. One person is
#: off 2-3 days a week, so a client/shift pair needs at least two people before
#: the week-offs can be staggered to cover all seven days.
MIN_PER_CLIENT_SHIFT = 2

#: Rule 2 - shape of the input data.
MIN_CLIENTS_PER_EMPLOYEE = 2
MAX_CLIENTS_PER_EMPLOYEE = 4
MIN_EMPLOYEES_PER_CLIENT = 6  # "more than 5"

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

OFF_LABEL = "Off"
#: Spellings of "day off" seen in hand-maintained rosters.
OFF_SYNONYMS = {"off", "wo", "w/o", "w.o", "weekoff", "week off", "week-off",
                "leave", "rest", "-", "x", "o"}

#: How the parser recognises shift names people actually type.
SHIFT_SYNONYMS = {
    "morning": "Morning", "m": "Morning", "mor": "Morning", "am": "Morning",
    "first": "Morning", "s1": "Morning", "shift 1": "Morning", "day": "Morning",
    "afternoon": "Afternoon", "a": "Afternoon", "aft": "Afternoon", "noon": "Afternoon",
    "second": "Afternoon", "s2": "Afternoon", "shift 2": "Afternoon", "mid": "Afternoon",
    "evening": "Evening", "e": "Evening", "eve": "Evening", "pm": "Evening",
    "third": "Evening", "s3": "Evening", "shift 3": "Evening", "swing": "Evening",
    "night": "Night", "n": "Night", "nite": "Night", "fourth": "Night",
    "s4": "Night", "shift 4": "Night", "graveyard": "Night",
}

#: Where uploaded history, the trained model and generated workbooks are kept.
#: Point ROSTER_DATA_DIR somewhere outside the repo to keep state across
#: re-clones, or on a backed-up volume.
DATA_DIR = Path(os.environ.get("ROSTER_DATA_DIR")
                or Path(__file__).resolve().parent.parent / "data")
HISTORY_DIR = DATA_DIR / "history"
MODEL_DIR = DATA_DIR / "models"
EXPORT_DIR = DATA_DIR / "exports"


def off_days_for(shift: str) -> int:
    return OFF_DAYS_PER_WEEK[shift]


def works_on(off_start: int, off_length: int, weekday: int) -> bool:
    """Weekly off block starting on ``off_start`` wraps the week (Sat-Sun-Mon),
    which keeps both the off days and the working days consecutive."""
    return (weekday - off_start) % 7 >= off_length


def off_block(off_start: int, off_length: int) -> list[int]:
    return [(off_start + i) % 7 for i in range(off_length)]
