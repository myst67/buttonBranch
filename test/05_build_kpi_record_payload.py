"""Playbook action 5 of 5 - shape the KPI application record.

Swimlane writes the record with its own native Create Record / Update Record
action, so this script makes no calls of any kind.  It produces:

  * ``fields``      a flat dict keyed by your KPI app field names
  * ``period_key``  the idempotency key, so re-running a period updates instead
                    of duplicating
  * ``action``      "update" when ``existing_record_id`` is supplied, else
                    "create" - wire this straight into the playbook's branch

Keep one KPI record per period.  The dashboard then reads the app, and the
history for the trend comes from the records themselves.

Turbine inputs
--------------
metrics             output of action 2
dashboard           output of action 4
trend               output of action 3
existing_record_id  optional id found by a preceding Search Records action
field_names         optional dict overriding the KPI app field keys below

Self-contained: the shared helpers this action needs are inlined below,
so the whole file pastes into one Turbine Python action.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

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

# ======================================================================
# Action
# ======================================================================

#: KPI application field keys.  Rename via the ``field_names`` input.
DEFAULT_FIELD_NAMES = {
    "period_key": "Period Key",
    "period_start": "Period Start",
    "period_end": "Period End",
    "generated_at": "Generated At",
    "new_count": "New Incidents",
    "closed_count": "Closed Incidents",
    "open_backlog": "Open Backlog",
    "opening_backlog": "Opening Backlog",
    "net_change": "Net Change",
    "closure_rate_pct": "Closure Rate %",
    "mttr_hours": "MTTR Hours",
    "median_resolution_hours": "Median Resolution Hours",
    "avg_age_days": "Avg Backlog Age Days",
    "oldest_open_days": "Oldest Open Days",
    "aged_over_30d": "Aged Over 30d",
    "unassigned_open": "Unassigned Open",
    "sla_compliance_pct": "SLA Compliance %",
    "sla_breached_open": "SLA Breached Open",
    "dashboard_json": "Dashboard JSON",
    "trend_json": "Trend JSON",
    "status": "Run Status",
}

def build_period_key(period):
    """Stable key like ``2026-08-01_2026-08-31`` for dedupe on re-runs."""
    start = parse_datetime((period or {}).get("start"))
    end = parse_datetime((period or {}).get("end"))
    if start is None or end is None:
        return "unknown-period"
    return "{}_{}".format(start.date().isoformat(), end.date().isoformat())

def build_fields(metrics, dashboard=None, trend=None, field_names=None):
    names = dict(DEFAULT_FIELD_NAMES)
    names.update(field_names or {})

    metrics = metrics or {}
    totals = metrics.get("totals", {})
    rates = metrics.get("rates", {})
    age = metrics.get("backlog_age", {})
    resolution = metrics.get("resolution", {})
    sla = metrics.get("sla", {})
    period = metrics.get("period", {})

    values = {
        "period_key": build_period_key(period),
        "period_start": period.get("start"),
        "period_end": period.get("end"),
        "generated_at": metrics.get("generated_at"),
        "new_count": totals.get("new"),
        "closed_count": totals.get("closed"),
        "open_backlog": totals.get("open_backlog"),
        "opening_backlog": totals.get("opening_backlog"),
        "net_change": totals.get("net_change"),
        "closure_rate_pct": rates.get("closure_rate_pct"),
        "mttr_hours": resolution.get("mttr_hours"),
        "median_resolution_hours": resolution.get("median_hours"),
        "avg_age_days": age.get("avg_days"),
        "oldest_open_days": age.get("oldest_days"),
        "aged_over_30d": age.get("over_30d"),
        "unassigned_open": age.get("unassigned"),
        "sla_compliance_pct": sla.get("compliance_pct"),
        "sla_breached_open": sla.get("breached_open"),
        # Stored as text so the app can render without another lookup.
        "dashboard_json": json.dumps(dashboard or {}, default=str),
        "trend_json": json.dumps(trend or {}, default=str),
        "status": "Success",
    }
    return {names[key]: value for key, value in values.items() if key in names}

def main(context=None):
    metrics = get_input(context, "metrics", {}) or {}
    existing_id = get_input(context, "existing_record_id")
    fields = build_fields(
        metrics,
        get_input(context, "dashboard", {}),
        get_input(context, "trend", {}),
        get_input(context, "field_names"),
    )
    return {
        "fields": fields,
        "period_key": build_period_key(metrics.get("period", {})),
        "action": "update" if existing_id else "create",
        "record_id": existing_id,
    }
