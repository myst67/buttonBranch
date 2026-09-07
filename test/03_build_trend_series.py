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
"""

from __future__ import annotations

from datetime import timedelta

from kpi_common import (
    day_span,
    get_input,
    parse_datetime,
    start_of_day,
    to_iso,
)


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
