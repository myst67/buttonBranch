"""Playbook action 3 of 5 - daily/weekly series for the dashboard charts.

Produces the "new vs closed vs backlog" line that the Glass-style dashboards
draw.  Backlog is carried forward day by day from the true opening balance, so
the last point of the series equals the open-backlog tile exactly.

Turbine inputs
--------------
records     output of action 1
period      output of action 1
granularity "day" (default) or "week"
max_points  safety cap on the number of buckets (default 180)

Turbine outputs
---------------
trend       series + the flat arrays a chart widget wants

Self-contained: the shared helpers this action needs are inlined below,
so the whole file pastes into one Turbine Python action.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

# ======================================================================
# Helpers
# ======================================================================

UTC = timezone.utc

_DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%d/%m/%Y %H:%M:%S",
]

def get_inputs(context):
    """Return the action's input dict regardless of Turbine context shape."""
    if context is None:
        return {}
    inputs = getattr(context, "inputs", None)
    if isinstance(inputs, dict):
        return inputs
    if isinstance(context, dict):
        if isinstance(context.get("inputs"), dict):
            return context["inputs"]
        return context
    getter = getattr(context, "get", None)
    if callable(getter):
        try:
            found = getter("inputs")
        except TypeError:
            found = None
        if isinstance(found, dict):
            return found
    return {}

def get_input(context, name, default=None):
    """Read one input by name, falling back to ``default`` when blank."""
    value = get_inputs(context).get(name, default)
    if value is None or value == "" or value == []:
        return default
    return value

def parse_datetime(value):
    """Parse the many date shapes CIM records carry. Returns UTC-aware or None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 1e11:  # milliseconds
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, tz=UTC)
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None
    if re.fullmatch(r"-?\d{10,13}", text):
        return parse_datetime(int(text))

    normalized = text.replace("Z", "+00:00").replace("z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    except ValueError:
        pass

    # Trim fractional seconds longer than 6 digits, which %f rejects.
    trimmed = re.sub(r"(\.\d{6})\d+", r"\1", text)
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(trimmed, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None

def to_iso(value):
    """UTC ISO-8601 string, or None. Safe to hand straight to a Swimlane field."""
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")

def start_of_day(value):
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    return parsed.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)

def day_span(start, end, max_days=400):
    """Inclusive list of ``date`` objects from ``start`` to ``end``."""
    first = start_of_day(start)
    last = start_of_day(end)
    if first is None or last is None or last < first:
        return []
    total = (last - first).days + 1
    total = min(total, max_days)
    return [(first + timedelta(days=offset)).date() for offset in range(total)]

# ======================================================================
# Action
# ======================================================================

def _open_at(record, moment):
    created = parse_datetime(record.get("created"))
    if created is None or created > moment:
        return False
    closed = parse_datetime(record.get("closed"))
    return closed is None or closed > moment

def build_series(records, period_start, period_end, granularity="day", max_points=180):
    records = records or []
    start = start_of_day(period_start)
    end = parse_datetime(period_end)
    if start is None or end is None:
        return {"granularity": granularity, "points": [], "labels": [],
                "new": [], "closed": [], "backlog": []}

    days = day_span(start, end, max_days=max_points)
    if not days:
        return {"granularity": granularity, "points": [], "labels": [],
                "new": [], "closed": [], "backlog": []}

    new_by_day, closed_by_day = {}, {}
    for record in records:
        if record.get("created_day"):
            new_by_day[record["created_day"]] = new_by_day.get(record["created_day"], 0) + 1
        if record.get("closed_day"):
            closed_by_day[record["closed_day"]] = closed_by_day.get(record["closed_day"], 0) + 1

    # Opening balance: everything already open the instant the window starts.
    backlog = sum(1 for r in records if _open_at(r, start))

    points = []
    for day in days:
        key = day.isoformat()
        opened = new_by_day.get(key, 0)
        resolved = closed_by_day.get(key, 0)
        backlog = backlog + opened - resolved
        points.append({
            "date": key,
            "new": opened,
            "closed": resolved,
            "net": opened - resolved,
            "backlog": backlog,
        })

    if str(granularity).lower().startswith("week"):
        points = _roll_up_weekly(points)

    return {
        "granularity": "week" if str(granularity).lower().startswith("week") else "day",
        "points": points,
        # Flat arrays so a chart widget can bind without reshaping.
        "labels": [p["date"] for p in points],
        "new": [p["new"] for p in points],
        "closed": [p["closed"] for p in points],
        "backlog": [p["backlog"] for p in points],
        "peak_backlog": max((p["backlog"] for p in points), default=0),
        "busiest_day": max(points, key=lambda p: p["new"])["date"] if points else None,
    }

def _roll_up_weekly(points):
    """Sum new/closed per ISO week; backlog takes the week's closing value."""
    weeks = {}
    order = []
    for point in points:
        monday = (parse_datetime(point["date"]) - timedelta(
            days=parse_datetime(point["date"]).weekday())).date().isoformat()
        if monday not in weeks:
            weeks[monday] = {"date": monday, "new": 0, "closed": 0, "net": 0, "backlog": 0}
            order.append(monday)
        bucket = weeks[monday]
        bucket["new"] += point["new"]
        bucket["closed"] += point["closed"]
        bucket["net"] = bucket["new"] - bucket["closed"]
        bucket["backlog"] = point["backlog"]
    return [weeks[key] for key in order]

def main(context=None):
    period = get_input(context, "period", {}) or {}
    trend = build_series(
        get_input(context, "records", []),
        period.get("start"),
        period.get("end"),
        get_input(context, "granularity", "day"),
        int(get_input(context, "max_points", 180)),
    )
    trend["period"] = {"start": to_iso(period.get("start")), "end": to_iso(period.get("end"))}
    return {"trend": trend}
