"""Read last month's roster out of whatever the client actually sends.

Accepts the wide roster layout produced by this tool (and by most hand-kept
sheets)::

    Name       | Client            | Mon-01-Jul | Tue-02-Jul | ...
    Person 1   | Client A, Client B| Night      | Off        | ...

and also a simple one-row-per-employee list::

    employee | last_month_shift | client
    Person 1 | Morning          | a, b, c

CSV, XLSX and JSON all go through the same normalisation, because real files
come with title rows, odd date formats and "W/O" instead of "Off".
"""
from __future__ import annotations

import datetime as dt
import io
import json
import re
from typing import Any, Optional

import pandas as pd

from .config import (MONTH_ABBR, OFF_DAYS_PER_WEEK, OFF_SYNONYMS, SHIFTS,
                     SHIFT_SYNONYMS, WEEKDAYS)
from .models import EmployeeMonth, MonthRoster

NAME_HEADERS = ("name", "employee", "person", "staff", "agent", "resource", "engineer")
CLIENT_HEADERS = ("client", "account", "project", "customer", "process")
SHIFT_HEADERS = ("shift", "last_month_shift", "last month shift", "current shift")
SPLIT_CLIENTS = re.compile(r"[,;/|]")
MONTH_LOOKUP = {name.lower(): i + 1 for i, name in enumerate(MONTH_ABBR)}
MONTH_LOOKUP.update({
    dt.date(2000, i + 1, 1).strftime("%B").lower(): i + 1 for i in range(12)
})
WEEKDAY_TOKENS = {w.lower() for w in WEEKDAYS} | {
    dt.date(2024, 1, 1 + i).strftime("%A").lower() for i in range(7)
}


class RosterParseError(ValueError):
    """The uploaded file could not be understood well enough to use."""


# --------------------------------------------------------------- helpers ----
def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    if value is pd.NaT:
        return ""
    return str(value).strip()


def _norm(value: Any) -> str:
    return re.sub(r"[\s_]+", " ", _text(value).lower()).strip()


def normalise_shift(value: Any) -> Optional[str]:
    """"NIGHT", "n", "Shift 4" -> "Night". Returns None if it is not a shift."""
    text = _norm(value)
    if not text:
        return None
    if text in {s.lower() for s in SHIFTS}:
        return text.capitalize() if text != "afternoon" else "Afternoon"
    return SHIFT_SYNONYMS.get(text)


def is_off_value(value: Any) -> bool:
    text = _norm(value).replace(".", "")
    return bool(text) and text in OFF_SYNONYMS


def parse_day_header(value: Any) -> tuple[Optional[int], Optional[int], Optional[int]]:
    """"Mon-01-Jul" -> (1, 7, None). Returns (day, month, year), any may be None."""
    if isinstance(value, (dt.datetime, dt.date, pd.Timestamp)):
        return value.day, value.month, value.year

    text = _text(value)
    if not text:
        return None, None, None

    # ISO first, so "2025-07-01" is not read day-first as 7 January.
    iso = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", text)
    if iso:
        year, month, day = (int(g) for g in iso.groups())
        if 1 <= month <= 12 and 1 <= day <= 31:
            return day, month, year

    tokens = [t for t in re.split(r"[\s\-_/.,]+", text) if t]
    day = month = year = None
    numeric: list[int] = []

    for token in tokens:
        low = token.lower()
        if low in WEEKDAY_TOKENS:
            continue
        if low in MONTH_LOOKUP:
            month = MONTH_LOOKUP[low]
            continue
        if low.isdigit():
            number = int(low)
            if len(low) == 4:
                year = number
            else:
                numeric.append(number)
            continue
        stripped = re.sub(r"(st|nd|rd|th)$", "", low)
        if stripped.isdigit():
            numeric.append(int(stripped))

    if month is None and len(numeric) >= 2:
        # A bare "01/07" style header: roster sheets are day-first.
        day, month = numeric[0], numeric[1]
        if month > 12 >= day:
            day, month = month, day
    elif numeric:
        day = numeric[0]

    if day is not None and not 1 <= day <= 31:
        return None, None, None
    if month is not None and not 1 <= month <= 12:
        return None, None, None
    return day, month, year


def header_weekday(value: Any) -> Optional[int]:
    """The "Mon" in "Mon-01-Jul", as 0-6. None when the header names no weekday."""
    if isinstance(value, (dt.datetime, dt.date, pd.Timestamp)):
        return value.weekday()
    for token in re.split(r"[\s\-_/.,]+", _text(value)):
        low = token.lower()
        if low in WEEKDAY_TOKENS:
            return next(i for i in range(7) if WEEKDAYS[i].lower() == low[:3])
    return None


def _infer_year(month: int, today: Optional[dt.date] = None) -> int:
    """Pick the most recent past occurrence of ``month`` when the file omits the year."""
    today = today or dt.date.today()
    return today.year if month <= today.month else today.year - 1


def _load_frame(content: bytes, filename: str) -> pd.DataFrame:
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xlsm", ".xls")):
        return pd.read_excel(io.BytesIO(content), header=None, dtype=object)
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return pd.read_csv(io.BytesIO(content), header=None, dtype=object,
                               encoding=encoding, keep_default_na=False,
                               skip_blank_lines=False, engine="python")
        except (UnicodeDecodeError, pd.errors.ParserError):
            continue
    raise RosterParseError("The file is not readable as CSV or Excel.")


def _locate_header(frame: pd.DataFrame) -> int:
    """Rosters often start with a title row - find the row that names the columns."""
    for index in range(min(8, len(frame))):
        cells = [_norm(v) for v in frame.iloc[index].tolist()]
        if any(any(key in cell for key in NAME_HEADERS) for cell in cells if cell):
            return index
    return 0


def _find_column(headers: list[Any], keys: tuple[str, ...]) -> Optional[int]:
    for index, header in enumerate(headers):
        text = _norm(header)
        if text and any(key in text for key in keys):
            return index
    return None


def _split_clients(value: Any) -> list[str]:
    text = _text(value)
    if not text:
        return []
    if text.startswith("["):
        try:
            return [str(c).strip() for c in json.loads(text) if str(c).strip()]
        except json.JSONDecodeError:
            pass
    seen: dict[str, None] = {}
    for part in SPLIT_CLIENTS.split(text):
        part = part.strip()
        if part:
            seen.setdefault(part, None)
    return list(seen)


def fit_off_block(off_by_weekday: list[list[bool]], default_length: int
                  ) -> tuple[Optional[int], int, int]:
    """Fit a repeating weekly off block to what the sheet actually shows.

    ``off_by_weekday[weekday]`` holds one bool per occurrence of that weekday in
    the month. Hand-kept rosters are rarely perfectly regular, so this picks the
    (start, length) with the fewest disagreements instead of demanding a match.
    Returns (start, length, mismatches); start is None when nothing is marked off.
    """
    observed = [sum(days) for days in off_by_weekday]
    totals = [len(days) for days in off_by_weekday]
    if not any(observed):
        return None, default_length, 0

    best: Optional[tuple[int, int, int, int]] = None  # (mismatch, penalty, start, length)
    for length in (2, 3):
        for start in range(7):
            block = {(start + i) % 7 for i in range(length)}
            mismatch = 0
            for weekday in range(7):
                if weekday in block:
                    mismatch += totals[weekday] - observed[weekday]
                else:
                    mismatch += observed[weekday]
            penalty = 0 if length == default_length else 1
            candidate = (mismatch, penalty, start, length)
            if best is None or candidate < best:
                best = candidate
    mismatch, _, start, length = best
    return start, length, mismatch


# ------------------------------------------------------------ the parser ----
def parse_roster_file(content: bytes, filename: str = "roster.xlsx",
                      month_hint: Optional[str] = None) -> MonthRoster:
    """Turn an uploaded last-month roster into a :class:`MonthRoster`."""
    if (filename or "").lower().endswith(".json"):
        return _parse_json(content, month_hint)

    frame = _load_frame(content, filename)
    if frame.empty:
        raise RosterParseError("The uploaded file is empty.")

    header_row = _locate_header(frame)
    headers = frame.iloc[header_row].tolist()
    body = frame.iloc[header_row + 1:]

    name_col = _find_column(headers, NAME_HEADERS)
    if name_col is None:
        raise RosterParseError(
            "No employee-name column found. The sheet needs a column headed "
            "Name / Employee / Person.")
    client_col = _find_column(headers, CLIENT_HEADERS)

    day_columns: list[tuple[int, int, Optional[int], Optional[int], Optional[int]]] = []
    for index, header in enumerate(headers):
        if index in (name_col, client_col):
            continue
        day, month, year = parse_day_header(header)
        if day is not None:
            day_columns.append((index, day, month, year, header_weekday(header)))

    if day_columns:
        return _parse_wide(body, headers, name_col, client_col, day_columns, month_hint)
    return _parse_simple(body, headers, name_col, client_col, month_hint)


def _resolve_month(day_columns, month_hint: Optional[str]) -> tuple[int, int]:
    if month_hint:
        year, month = (int(p) for p in month_hint.split("-"))
        return year, month
    months = [m for _, _, m, _, _ in day_columns if m]
    years = [y for _, _, _, y, _ in day_columns if y]
    if not months:
        raise RosterParseError(
            "The date columns do not say which month this is. Use headers like "
            "Mon-01-Jul, or pass the month explicitly.")
    month = max(set(months), key=months.count)
    if years:
        return max(set(years), key=years.count), month
    return _year_from_weekdays(day_columns, month), month


def _year_from_weekdays(day_columns, month: int, today: Optional[dt.date] = None) -> int:
    """Sheets rarely carry the year, but "Mon-01-Jul" pins it down anyway.

    Only one recent year has 1 July falling on a Monday, so the weekday names in
    the headers identify the year - and getting that right matters, because the
    week-off pattern is read off the real weekday of each column.
    """
    today = today or dt.date.today()
    labelled = [(day, weekday) for _, day, col_month, _, weekday in day_columns
                if weekday is not None and (col_month or month) == month]
    fallback = _infer_year(month, today)
    if not labelled:
        return fallback

    best_year, best_score = fallback, -1
    for year in range(today.year + 1, today.year - 4, -1):
        score = 0
        for day, weekday in labelled:
            try:
                score += dt.date(year, month, day).weekday() == weekday
            except ValueError:
                continue
        if score > best_score:
            best_year, best_score = year, score
    # A sheet whose weekday names match no year at all is mislabelled; fall back
    # rather than trusting a poor match.
    return best_year if best_score >= 0.8 * len(labelled) else fallback


def _parse_wide(body, headers, name_col, client_col, day_columns, month_hint) -> MonthRoster:
    year, month = _resolve_month(day_columns, month_hint)
    warnings: list[str] = []

    # Resolve every date column to a real date so we know its weekday.
    dated: list[tuple[int, dt.date]] = []
    for index, day, col_month, col_year, _ in day_columns:
        use_month = col_month or month
        use_year = col_year or (year if use_month == month else _infer_year(use_month))
        try:
            dated.append((index, dt.date(use_year, use_month, day)))
        except ValueError:
            warnings.append(f"Ignored an unreadable date column: {headers[index]!r}.")

    if not dated:
        raise RosterParseError("None of the date columns could be resolved to a date.")

    employees: list[EmployeeMonth] = []
    for _, row in body.iterrows():
        name = _text(row.iloc[name_col])
        if not name or _norm(name) in NAME_HEADERS:
            continue

        clients = _split_clients(row.iloc[client_col]) if client_col is not None else []
        shift_counts: dict[str, int] = {}
        off_by_weekday: list[list[bool]] = [[] for _ in range(7)]
        unknown = 0

        for index, date in dated:
            value = row.iloc[index] if index < len(row) else None
            weekday = date.weekday()
            if is_off_value(value):
                off_by_weekday[weekday].append(True)
                continue
            shift = normalise_shift(value)
            if shift:
                shift_counts[shift] = shift_counts.get(shift, 0) + 1
                off_by_weekday[weekday].append(False)
            elif _text(value):
                unknown += 1

        if not shift_counts:
            warnings.append(f"{name}: no recognisable shift in any day column - row skipped.")
            continue

        shift = max(shift_counts, key=shift_counts.get)
        if len(shift_counts) > 1:
            others = ", ".join(f"{k} x{v}" for k, v in shift_counts.items() if k != shift)
            warnings.append(
                f"{name}: worked more than one shift last month ({others}); "
                f"took {shift} as the last-month shift.")
        if unknown:
            warnings.append(f"{name}: {unknown} cell(s) were neither a shift nor a day off.")

        start, length, mismatch = fit_off_block(off_by_weekday, OFF_DAYS_PER_WEEK[shift])
        if start is None:
            warnings.append(f"{name}: no week-offs found last month.")
        elif mismatch:
            warnings.append(
                f"{name}: week-offs were irregular last month ({mismatch} day(s) off-pattern); "
                f"read as {length} days from {WEEKDAYS[start]}.")
        if not clients:
            warnings.append(f"{name}: no clients listed.")

        employees.append(EmployeeMonth(name=name, clients=clients, shift=shift,
                                       off_start=start, off_length=length))

    if not employees:
        raise RosterParseError("No employee rows were found in the file.")

    return MonthRoster(month=f"{year}-{month:02d}", employees=employees, warnings=warnings)


def _parse_simple(body, headers, name_col, client_col, month_hint) -> MonthRoster:
    shift_col = _find_column(headers, SHIFT_HEADERS)
    if shift_col is None:
        raise RosterParseError(
            "The file has no date columns and no shift column, so there is "
            "nothing to learn from. Expected either a day-by-day roster or a "
            "Name / Client / Last month shift list.")

    warnings = ["The file had no day columns, so week-off history is unknown; "
                "only the last-month shift was used."]
    employees = []
    for _, row in body.iterrows():
        name = _text(row.iloc[name_col])
        if not name or _norm(name) in NAME_HEADERS:
            continue
        shift = normalise_shift(row.iloc[shift_col])
        if shift is None:
            warnings.append(f"{name}: unrecognised shift {_text(row.iloc[shift_col])!r} - row skipped.")
            continue
        clients = _split_clients(row.iloc[client_col]) if client_col is not None else []
        employees.append(EmployeeMonth(name=name, clients=clients, shift=shift))

    if not employees:
        raise RosterParseError("No employee rows were found in the file.")

    month = month_hint or _previous_month()
    return MonthRoster(month=month, employees=employees, warnings=warnings)


def _parse_json(content: bytes, month_hint: Optional[str]) -> MonthRoster:
    payload = json.loads(content.decode("utf-8"))
    rows = payload["employees"] if isinstance(payload, dict) else payload
    employees = []
    for row in rows:
        name = _text(row.get("employee") or row.get("name"))
        shift = normalise_shift(row.get("last_month_shift") or row.get("shift"))
        clients = row.get("client") or row.get("clients") or []
        if isinstance(clients, str):
            clients = _split_clients(clients)
        if name and shift:
            employees.append(EmployeeMonth(name=name, clients=[str(c) for c in clients],
                                           shift=shift,
                                           off_start=row.get("off_start"),
                                           off_length=row.get("off_length")))
    if not employees:
        raise RosterParseError("The JSON payload contained no usable employee rows.")
    month = month_hint or (payload.get("month") if isinstance(payload, dict) else None) \
        or _previous_month()
    return MonthRoster(month=month, employees=employees)


def _previous_month() -> str:
    today = dt.date.today()
    first = today.replace(day=1)
    previous = first - dt.timedelta(days=1)
    return f"{previous.year}-{previous.month:02d}"
