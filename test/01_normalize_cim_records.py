"""Playbook action 1 of 5 - normalize raw CIM records.

Every downstream script reads this action's output, so this is the only place
that has to know what your CIM fields are actually called.  Point ``field_map``
at your own keys and nothing else needs to change.

Turbine inputs
--------------
records          list of raw CIM records (or a JSON string of that list)
field_map        optional dict: canonical name -> your CIM key(s)
closed_statuses  optional list of status values that mean "not in backlog"
period           named window: today | last_7_days | last_30_days | month_to_date
                 | last_month | last_90_days | year_to_date  (default last_30_days)
period_start     optional explicit ISO start, overrides ``period``
period_end       optional explicit ISO end, overrides ``period``
now              optional ISO "as of" time, for deterministic re-runs

Turbine outputs
---------------
records          canonical records, JSON-safe
period           the resolved window
summary          quick counts so the playbook can branch on an empty run
skipped          records that had no usable created date, for triage
"""

from __future__ import annotations

import json
from datetime import datetime

from kpi_common import (
    DEFAULT_CLOSED_STATUSES,
    UTC,
    day_key,
    get_input,
    hours_between,
    merge_field_map,
    parse_datetime,
    pick_field,
    resolve_period,
    to_iso,
)


def _as_list(value):
    """Turbine sometimes hands a JSON string where a list is expected."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        for key in ("records", "results", "items", "data", "value"):
            if isinstance(value.get(key), list):
                return value[key]
        return [value]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            return _as_list(json.loads(text))
        except (TypeError, ValueError):
            return []
    return []


def _clean(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def normalize_records(raw_records, field_map=None, closed_statuses=None, now=None):
    """Map raw CIM records onto the canonical shape used by every later script."""
    fields = merge_field_map(field_map)
    closed_set = {str(s).strip().lower()
                  for s in (closed_statuses or DEFAULT_CLOSED_STATUSES)}
    as_of = parse_datetime(now) or datetime.now(UTC)

    normalized, skipped = [], []
    for index, raw in enumerate(_as_list(raw_records)):
        if not isinstance(raw, dict):
            skipped.append({"index": index, "reason": "record is not an object"})
            continue

        created = parse_datetime(pick_field(raw, fields["created"]))
        if created is None:
            skipped.append({
                "index": index,
                "id": _clean(pick_field(raw, fields["id"])),
                "reason": "missing or unparsable created date",
            })
            continue

        status = _clean(pick_field(raw, fields["status"])) or "Unknown"
        closed_at = parse_datetime(pick_field(raw, fields["closed"]))
        is_closed = status.strip().lower() in closed_set or closed_at is not None

        # A closed status with no timestamp still has to leave the backlog on a
        # specific day, otherwise the trend series never draws it down.
        if is_closed and closed_at is None:
            closed_at = parse_datetime(pick_field(raw, fields["updated"])) or as_of
        if not is_closed:
            closed_at = None

        sla_due = parse_datetime(pick_field(raw, fields["sla_due"]))
        age_end = closed_at if is_closed else as_of
        resolution_hours = hours_between(created, closed_at) if is_closed else None

        sla_breached = False
        if sla_due is not None:
            sla_breached = (closed_at or as_of) > sla_due

        normalized.append({
            "id": _clean(pick_field(raw, fields["id"])) or "row-{}".format(index),
            "tracking_id": _clean(pick_field(raw, fields["tracking_id"])),
            "title": _clean(pick_field(raw, fields["title"])) or "(untitled)",
            "status": status,
            "priority": _clean(pick_field(raw, fields["priority"])) or "Unspecified",
            "severity": _clean(pick_field(raw, fields["severity"])) or "Unspecified",
            "assignee": _clean(pick_field(raw, fields["assignee"])) or "Unassigned",
            "team": _clean(pick_field(raw, fields["team"])) or "Unassigned",
            "category": _clean(pick_field(raw, fields["category"])) or "Uncategorized",
            "source": _clean(pick_field(raw, fields["source"])) or "Unknown",
            "created": to_iso(created),
            "closed": to_iso(closed_at),
            "updated": to_iso(pick_field(raw, fields["updated"])),
            "sla_due": to_iso(sla_due),
            "created_day": day_key(created),
            "closed_day": day_key(closed_at),
            "is_closed": is_closed,
            "is_open": not is_closed,
            "age_days": round((age_end - created).total_seconds() / 86400.0, 2),
            "resolution_hours": None if resolution_hours is None else round(resolution_hours, 2),
            "sla_due_set": sla_due is not None,
            "sla_breached": sla_breached,
        })

    return normalized, skipped


def main(context=None):
    period_start, period_end = resolve_period(
        get_input(context, "period", "last_30_days"),
        get_input(context, "period_start"),
        get_input(context, "period_end"),
        get_input(context, "now"),
    )

    records, skipped = normalize_records(
        get_input(context, "records", []),
        get_input(context, "field_map"),
        get_input(context, "closed_statuses"),
        get_input(context, "now"),
    )

    open_count = sum(1 for r in records if r["is_open"])
    return {
        "records": records,
        "period": {
            "start": to_iso(period_start),
            "end": to_iso(period_end),
            "label": get_input(context, "period", "last_30_days"),
        },
        "summary": {
            "total": len(records),
            "open": open_count,
            "closed": len(records) - open_count,
            "skipped": len(skipped),
            "has_records": bool(records),
        },
        "skipped": skipped,
    }
