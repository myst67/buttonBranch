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

Self-contained: the shared helpers this action needs are inlined below,
so the whole file pastes into one Turbine Python action.
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone

# ======================================================================
# Helpers
# ======================================================================

UTC = timezone.utc

#: Canonical field -> candidate keys on the raw CIM record, first match wins.
#: Keys are matched case-insensitively and dotted paths are supported.
DEFAULT_FIELD_MAP = {
    "id": ["id", "recordId", "record_id", "Id"],
    "tracking_id": ["trackingId", "tracking_id", "trackingFull", "Tracking Id"],
    "title": ["title", "name", "summary", "shortDescription", "Alert Name"],
    "status": ["status", "state", "Status", "incidentStatus"],
    "priority": ["priority", "Priority", "urgency"],
    "severity": ["severity", "Severity", "criticality"],
    "created": ["created", "createdDate", "createdAt", "opened_at", "Created"],
    "closed": ["closed", "closedDate", "resolvedDate", "resolved_at", "Closed"],
    "updated": ["modified", "updated", "updatedAt", "lastModified"],
    "assignee": ["assignee", "assignedTo", "owner", "Assigned To"],
    "team": ["team", "group", "assignmentGroup", "queue"],
    "category": ["category", "type", "incidentType", "classification"],
    "source": ["source", "sourceSystem", "detectionSource", "sensor"],
    "sla_due": ["slaDue", "sla_due", "dueDate", "sla_target"],
}

#: Status values that mean "this record is no longer in the backlog".
DEFAULT_CLOSED_STATUSES = [
    "closed",
    "resolved",
    "completed",
    "done",
    "cancelled",
    "canceled",
    "false positive",
    "false-positive",
    "closed - benign",
    "benign",
    "duplicate",
    "rejected",
]

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

def _flatten(record, prefix="", out=None):
    """Flatten nested dicts into ``a.b.c`` keys so dotted paths resolve."""
    if out is None:
        out = {}
    if not isinstance(record, dict):
        return out
    for key, value in record.items():
        path = "{}.{}".format(prefix, key) if prefix else str(key)
        out[path] = value
        if isinstance(value, dict):
            _flatten(value, path, out)
    return out

def pick_field(record, candidates, default=None):
    """First non-empty value among ``candidates`` (case-insensitive keys)."""
    if not isinstance(record, dict):
        return default
    flat = _flatten(record)
    lowered = {k.lower(): v for k, v in flat.items()}
    for candidate in candidates or []:
        for key in (candidate, str(candidate).lower()):
            if key in flat and flat[key] not in (None, ""):
                return flat[key]
            if key in lowered and lowered[key] not in (None, ""):
                return lowered[key]
    return default

def merge_field_map(overrides):
    """Layer playbook overrides on top of :data:`DEFAULT_FIELD_MAP`.

    An override may be a single key or a list of candidate keys; either way the
    override is tried *before* the built-in candidates so nothing is lost.
    """
    merged = {k: list(v) for k, v in DEFAULT_FIELD_MAP.items()}
    for field, candidates in (overrides or {}).items():
        if isinstance(candidates, str):
            candidates = [candidates]
        existing = merged.get(field, [])
        merged[field] = list(candidates) + [c for c in existing if c not in candidates]
    return merged

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

def day_key(value):
    """``YYYY-MM-DD`` bucket key for a timestamp."""
    parsed = parse_datetime(value)
    return None if parsed is None else parsed.astimezone(UTC).date().isoformat()

def resolve_period(period, period_start, period_end, now=None):
    """Turn a named period (``last_7_days`` etc.) into a concrete UTC window.

    Explicit ``period_start`` / ``period_end`` inputs always win, so the same
    playbook can run on a schedule or be re-run for a specific month.
    """
    now = parse_datetime(now) or datetime.now(UTC)
    explicit_start = parse_datetime(period_start)
    explicit_end = parse_datetime(period_end)
    if explicit_start and explicit_end:
        return explicit_start, explicit_end

    name = (period or "last_30_days").strip().lower().replace("-", "_").replace(" ", "_")
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now

    if name in ("today", "day", "last_24_hours", "24h"):
        start = today_start if name in ("today", "day") else now - timedelta(hours=24)
    elif name in ("yesterday",):
        start = today_start - timedelta(days=1)
        end = today_start - timedelta(microseconds=1)
    elif name in ("last_7_days", "7d", "week", "this_week"):
        start = today_start - timedelta(days=6)
    elif name in ("last_14_days", "14d"):
        start = today_start - timedelta(days=13)
    elif name in ("last_30_days", "30d", "month"):
        start = today_start - timedelta(days=29)
    elif name in ("last_90_days", "90d", "quarter"):
        start = today_start - timedelta(days=89)
    elif name in ("month_to_date", "mtd"):
        start = today_start.replace(day=1)
    elif name in ("last_month", "previous_month"):
        first_this_month = today_start.replace(day=1)
        end = first_this_month - timedelta(microseconds=1)
        start = (first_this_month - timedelta(days=1)).replace(day=1)
    elif name in ("year_to_date", "ytd"):
        start = today_start.replace(month=1, day=1)
    else:
        start = today_start - timedelta(days=29)

    return (explicit_start or start), (explicit_end or end)

def hours_between(start, end):
    a, b = parse_datetime(start), parse_datetime(end)
    if a is None or b is None:
        return None
    return (b - a).total_seconds() / 3600.0

# ======================================================================
# Action
# ======================================================================

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
