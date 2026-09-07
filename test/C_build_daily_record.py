"""Script C of 3 - build the daily KPI record payload.

Swimlane writes the record with its own Create Record / Update Record action, so
this script makes no calls. It flattens the catalog into one field per stored
number and decides whether today's record is a create or an update.

The record is keyed on the snapshot date, so the cron job re-running on the same
day corrects that day's record instead of adding a second one.

Inputs
------
metrics             Script B's metrics
coverage            Script B's coverage
existing_record_id  id from the KPI-app search on Snapshot Date; empty if none
field_prefix        optional prefix for the generated metric field names
include_payload     store Dashboard JSON and Coverage JSON (default true)

Outputs
-------
fields      flat dict keyed by KPI application field name
period_key  the snapshot date, the idempotency key
action      "update" when existing_record_id was supplied, else "create"
record_id   passthrough of existing_record_id
dashboard   tiles, breakdowns and the oldest-open table
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone

# ==========================================================================
# shared helper block - keep byte-identical across scripts A, B and C
# if your tenant supports a reusable Python component, lift this block
# out of all three and reference the component instead
# ==========================================================================

UTC = timezone.utc

# --------------------------------------------------------------------------
# Field map - canonical name -> the CIM columns, first non-empty match wins.
# Keys match case-insensitively and dotted paths reach into nested objects.
# --------------------------------------------------------------------------

DEFAULT_FIELD_MAP = {
    "id": ["id", "recordId", "Tracking Id", "trackingId"],
    "tracking_id": ["Tracking Id", "trackingId", "trackingFull"],
    "alert_uid": ["Alert UID", "alertUid", "alert_uid"],
    "title": ["Title", "title", "name"],
    "assigned_to": ["Current Owner", "currentOwner", "assignedTo", "assignee"],
    "severity": ["Severity", "severity", "priority", "Priority"],
    "status": ["Status", "status", "state", "currentState"],
    "type": ["Type", "type", "recordType"],
    "record_hierarchy": ["Record-hierarchy", "recordHierarchy", "record_hierarchy"],
    "classification": ["Classification", "classification"],
    "manual_verdict": ["Manual Verdict", "manualVerdict", "manual_verdict"],
    "alert_categories": ["Alert Categories", "alertCategories"],
    "escalated": ["Escalated?", "Escalated", "escalated"],
    "escalate_to": ["Escalate to?", "Escalate to", "escalateTo"],
    "threat_type": ["Threat Type", "threatType"],
    "mitre_technique": ["MITRE ATT&CK Technique", "mitreTechnique", "MITRE ATT&CK Techniques"],
    "mitre_technique_count": ["MITRE ATT&CK Technique Count", "mitreTechniqueCount"],

    "created_at": ["First Created", "firstCreated", "created", "createdDate"],
    "updated_at": ["Last Updated", "lastUpdated", "modified", "updated"],
    "closed_at": ["Time Resolved", "timeResolved", "closed", "closedDate"],
    "remediated_at": ["Time of Remediation", "timeOfRemediation", "remediatedAt"],

    # Durations: the text column carries sub-minute precision, the numeric one
    # is truncated, so the text is preferred when both are present.
    "tta_text": ["Time to Acknowledge", "timeToAcknowledge"],
    "tta_minutes": ["Time to Acknowledge Minutes", "timeToAcknowledgeMinutes"],
    "analyze_text": ["Time to Analyze (excluding pending)", "Time to Analyze", "timeToAnalyze"],
    "analyze_minutes": ["Time to Analyze Minutes", "timeToAnalyzeMinutes"],
    "remediate_text": ["Time to Remediate", "timeToRemediate"],
    "remediate_minutes": ["Time to Remediate Minutes", "timeToRemediateMinutes"],

    # Not present in the CIM table today. Map them here if you ever add them
    # and the metrics that need them start reporting instead of going null.
    "reassign_count": ["Reassign Count", "reassignCount"],
    "risk_score": ["Risk Score", "riskScore"],
    "sla_breached": ["SLA Breached", "slaBreached"],
    "state_changed_at": ["State Changed", "stateChangedAt"],
}

#: Status values that mean the record has left the backlog.
DEFAULT_CLOSED_STATUSES = [
    "closed", "resolved", "completed", "done", "cancelled", "canceled",
    "false positive", "false-positive", "duplicate", "rejected", "closed - benign",
]

#: The subset of closed statuses that count as genuinely worked and resolved.
DEFAULT_RESOLVED_STATUSES = ["closed", "resolved", "completed", "done"]

#: Values that mark a record as a false positive, in any of the verdict fields.
DEFAULT_FALSE_POSITIVE_VALUES = [
    "false positive", "false-positive", "fp", "benign", "closed - benign", "not malicious",
]

#: Fields checked for a false-positive verdict, in order.
DEFAULT_FALSE_POSITIVE_FIELDS = ["status", "classification", "manual_verdict"]

#: Severity values treated as P1/P2 for the high-risk metrics.
DEFAULT_P1P2_VALUES = ["critical", "high", "p1", "p2", "1", "2"]

#: A duration above this many minutes (one year) is treated as a bad value and
#: excluded from the averages rather than being allowed to wreck them.
DEFAULT_SUSPECT_MINUTES_OVER = 525600

PRIORITY_ORDER = ["critical", "high", "medium", "low", "informational", "info"]

_DATE_FORMATS = [
    "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%b %d, %Y %I:%M %p", "%b %d, %Y %I:%M:%S %p", "%b %d, %Y",
    "%d %b %Y %H:%M", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y",
]

_DURATION_RE = re.compile(
    r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>ms|milliseconds?|s|secs?|seconds?|"
    r"m|mins?|minutes?|h|hrs?|hours?|d|days?)\b",
    re.IGNORECASE,
)

_DURATION_MINUTES = {
    "ms": 1.0 / 60000.0, "millisecond": 1.0 / 60000.0, "milliseconds": 1.0 / 60000.0,
    "s": 1.0 / 60.0, "sec": 1.0 / 60.0, "secs": 1.0 / 60.0,
    "second": 1.0 / 60.0, "seconds": 1.0 / 60.0,
    "m": 1.0, "min": 1.0, "mins": 1.0, "minute": 1.0, "minutes": 1.0,
    "h": 60.0, "hr": 60.0, "hrs": 60.0, "hour": 60.0, "hours": 60.0,
    "d": 1440.0, "day": 1440.0, "days": 1440.0,
}


# --------------------------------------------------------------------------
# Turbine context plumbing
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# Field resolution
# --------------------------------------------------------------------------

def _flatten(record, prefix="", out=None):
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
    """Layer playbook overrides on top of the defaults, overrides tried first."""
    merged = {k: list(v) for k, v in DEFAULT_FIELD_MAP.items()}
    for field, candidates in (overrides or {}).items():
        if isinstance(candidates, str):
            candidates = [candidates]
        existing = merged.get(field, [])
        merged[field] = list(candidates) + [c for c in existing if c not in candidates]
    return merged


def in_set(value, allowed):
    """Case-insensitive membership test that tolerates None and stray spaces."""
    if value is None:
        return False
    return str(value).strip().lower() in {str(a).strip().lower() for a in (allowed or [])}


def is_truthy(value):
    """Read a Swimlane yes/no, checkbox or boolean field."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "yes", "y", "1", "checked")


# --------------------------------------------------------------------------
# Dates and durations
# --------------------------------------------------------------------------

def parse_datetime(value):
    """Parse the date shapes CIM records carry. Returns UTC-aware or None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        seconds = float(value)
        if seconds > 1e11:
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

    # Long-form display timestamps, plus fractional seconds longer than %f allows.
    trimmed = re.sub(r"(\.\d{6})\d+", r"\1", text).replace(" ", " ")
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(trimmed, fmt)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            continue
    return None


def to_iso(value):
    """UTC ISO-8601 string, or None."""
    parsed = parse_datetime(value)
    return None if parsed is None else parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")


def day_key(value):
    parsed = parse_datetime(value)
    return None if parsed is None else parsed.astimezone(UTC).date().isoformat()


def start_of_day(value):
    parsed = parse_datetime(value)
    if parsed is None:
        return None
    return parsed.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)


def hours_between(start, end):
    a, b = parse_datetime(start), parse_datetime(end)
    return None if a is None or b is None else (b - a).total_seconds() / 3600.0


def days_between(start, end):
    hours = hours_between(start, end)
    return None if hours is None else hours / 24.0


def parse_duration_minutes(text_value, numeric_value=None):
    """Minutes from a compound "1h 2m 3s" string, else from a numeric column.

    The text column keeps sub-minute precision that the numeric column throws
    away, so it wins when both are present.
    """
    if text_value not in (None, ""):
        text = str(text_value).strip()
        matches = _DURATION_RE.findall(text)
        if matches:
            total = 0.0
            for value, unit in matches:
                total += float(value) * _DURATION_MINUTES[unit.lower()]
            return round(total, 4)
        # A bare number in the text column is already minutes.
        try:
            return round(float(text), 4)
        except ValueError:
            pass
    if numeric_value not in (None, ""):
        try:
            return round(float(numeric_value), 4)
        except (TypeError, ValueError):
            return None
    return None


def day_span(start, end, max_days=400):
    first, last = start_of_day(start), start_of_day(end)
    if first is None or last is None or last < first:
        return []
    total = min((last - first).days + 1, max_days)
    return [(first + timedelta(days=offset)).date() for offset in range(total)]


def resolve_period(period, period_start, period_end, now=None):
    """Turn a named period into a concrete UTC window; explicit dates win."""
    now = parse_datetime(now) or datetime.now(UTC)
    explicit_start = parse_datetime(period_start)
    explicit_end = parse_datetime(period_end)
    if explicit_start and explicit_end:
        return explicit_start, explicit_end

    name = (period or "last_30_days").strip().lower().replace("-", "_").replace(" ", "_")
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = now

    if name in ("today", "day"):
        start = today_start
    elif name in ("last_24_hours", "24h"):
        start = now - timedelta(hours=24)
    elif name == "yesterday":
        start = today_start - timedelta(days=1)
        end = today_start - timedelta(microseconds=1)
    elif name in ("last_7_days", "7d", "week"):
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


# --------------------------------------------------------------------------
# Stats
# --------------------------------------------------------------------------

def mean(values):
    clean = [v for v in values if v is not None]
    return round(sum(clean) / len(clean), 2) if clean else None


def median(values):
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return round(clean[mid], 2)
    return round((clean[mid - 1] + clean[mid]) / 2.0, 2)


def percentile(values, pct_rank):
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    rank = max(1, min(len(clean), int(round((pct_rank / 100.0) * len(clean) + 0.5))))
    return round(clean[rank - 1], 2)


def pct(part, whole, digits=2):
    if not whole:
        return 0.0
    return round((float(part) / float(whole)) * 100.0, digits)


def stats(values, digits=2):
    """Sum/mean/min/max/p50/p90 for the metrics defined as a value, not a count.

    ``count`` is how many records actually carried the value, which is not the
    same as the size of the base when a column is sparsely populated.
    """
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return {"count": 0, "sum": None, "avg": None, "min": None,
                "max": None, "p50": None, "p90": None}
    return {
        "count": len(clean),
        "sum": round(sum(clean), digits),
        "avg": round(sum(clean) / len(clean), digits),
        "min": round(min(clean), digits),
        "max": round(max(clean), digits),
        "p50": median(clean),
        "p90": percentile(clean, 90),
    }


def count_by(records, key, top=None, order=None):
    counts = {}
    for record in records:
        value = record.get(key) or "Unassigned"
        counts[str(value)] = counts.get(str(value), 0) + 1

    def sort_key(item):
        label, total = item
        if order:
            try:
                return (0, order.index(label.strip().lower()), -total, label)
            except ValueError:
                return (1, 0, -total, label)
        return (0, 0, -total, label)

    ranked = sorted(counts.items(), key=sort_key)
    if top:
        ranked = ranked[:top]
    return [{"label": label, "count": total} for label, total in ranked]


def resolve_day_window(period_mode, snapshot_date=None, now=None):
    """The window for one daily snapshot, plus the date that names the record.

    ``today``      00:00 today  -> the moment the job runs (a partial day)
    ``full_today`` 00:00 today  -> 23:59:59.999999 today
    ``yesterday``  the complete previous day
    ``date``       the complete day given by ``snapshot_date``

    The returned ``date`` is what the KPI record is keyed on, so a re-run on the
    same day updates that day's record instead of adding a second one.
    """
    run_at = parse_datetime(now) or datetime.now(UTC)
    mode = (period_mode or "today").strip().lower().replace("-", "_")
    midnight = run_at.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = timedelta(days=1) - timedelta(microseconds=1)

    explicit = parse_datetime(snapshot_date)
    if mode == "date" or explicit is not None:
        if explicit is None:
            raise ValueError("period_mode 'date' needs a snapshot_date input")
        start = explicit.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        return start, start + day_end, start.date().isoformat()
    if mode == "yesterday":
        start = midnight - timedelta(days=1)
        return start, start + day_end, start.date().isoformat()
    if mode == "full_today":
        return midnight, midnight + day_end, midnight.date().isoformat()
    return midnight, run_at, midnight.date().isoformat()

# ==========================================================================
# end shared helper block
# ==========================================================================


#: Which sub-values of a value metric get their own stored field. The full
#: distribution still travels in Dashboard JSON.
VALUE_PARTS = ["avg", "sum", "p90", "count"]

#: Tiles the daily dashboard leads with, in order.
TILE_SPEC = [
    ("open_inc_total", "Open Backlog", None, "lower_is_better"),
    ("new_inc_total", "New Today", None, "neutral"),
    ("closed_inc_total", "Closed Today", None, "higher_is_better"),
    ("true_positive_count", "True Positives", None, "neutral"),
    ("false_positive_count", "False Positives", None, "lower_is_better"),
    ("fp_rate", "FP Rate", "%", "lower_is_better"),
    ("mtta_hours", "MTTA", "hours", "lower_is_better"),
    ("mttr_hours", "MTTR", "hours", "lower_is_better"),
    ("open_more_than_five_days", "Open over 5d", None, "lower_is_better"),
    ("open_more_than_thirty_days", "Open over 30d", None, "lower_is_better"),
    ("oldest_open_age", "Oldest Open", "days", "lower_is_better"),
    ("distinct_agents", "Active Owners", None, "neutral"),
]

#: Shown next to the backlog tile so a mismatch with yesterday is visible.
CONTINUITY_KEYS = ["expected_open_backlog", "drift", "days_since_previous",
                   "is_seed_day", "continuous", "note"]


def _title(key):
    """open_more_than_five_days -> Open More Than Five Days."""
    return " ".join(part.capitalize() for part in key.split("_"))


def _tile_value(entry):
    """A tile shows one number: the mean for a distribution, else the value."""
    if entry is None:
        return None
    value = entry.get("value")
    if isinstance(value, dict):
        return value.get("avg")
    return value


def build_fields(metrics, coverage=None, prefix="", include_payload=True):
    metrics = metrics or {}
    catalog = metrics.get("catalog", {})
    continuity = metrics.get("continuity") or {}
    fields = {
        "Snapshot Date": metrics.get("snapshot_date"),
        "Period Start": metrics.get("period", {}).get("start"),
        "Period End": metrics.get("period", {}).get("end"),
        "Run Status": "Success",
        # Feed Previous Open Backlog back into Script B tomorrow, so each day
        # checks its measured backlog against yesterday's carry-forward.
        "Previous Open Backlog": continuity.get("previous_open_backlog"),
        "Expected Open Backlog": continuity.get("expected_open_backlog"),
        "Backlog Drift": continuity.get("drift"),
        "Days Since Previous": continuity.get("days_since_previous"),
        "Is Seed Day": continuity.get("is_seed_day"),
        "Series Continuous": continuity.get("continuous"),
    }

    for key in sorted(catalog):
        entry = catalog[key]
        label = "{}{}".format(prefix, _title(key))
        value = entry.get("value")
        # Expansion is decided by the metric's kind, not by whether it happens
        # to have a value today. A metric blocked on a missing CIM field still
        # writes its full set of columns as null, so the KPI app schema does not
        # change shape the day that field is added.
        if str(entry.get("kind", "")).startswith("value"):
            parts = value if isinstance(value, dict) else {}
            for part in VALUE_PARTS:
                fields["{} {}".format(label, part.upper() if part == "p90"
                                      else part.capitalize())] = parts.get(part)
        else:
            fields[label] = value

    if include_payload:
        fields["Coverage JSON"] = json.dumps(coverage or {}, default=str)
    return fields


def build_dashboard(metrics):
    metrics = metrics or {}
    catalog = metrics.get("catalog", {})

    tiles = []
    for key, label, unit, intent in TILE_SPEC:
        entry = catalog.get(key)
        if entry is None:
            continue
        tiles.append({
            "key": key,
            "label": label,
            "value": _tile_value(entry),
            "unit": unit,
            "intent": intent,
            "status": entry.get("status"),
            "reason": entry.get("reason"),
        })

    breakdowns = metrics.get("breakdowns", {})
    charts = [
        {"key": name, "type": "bar", "title": _title(name),
         "x": [row["label"] for row in rows],
         "series": [{"name": "Count", "data": [row["count"] for row in rows]}]}
        for name, rows in breakdowns.items()
    ]

    continuity = metrics.get("continuity") or {}
    return {
        "title": "CIM Daily KPI",
        "snapshot_date": metrics.get("snapshot_date"),
        "continuity": {k: continuity.get(k) for k in CONTINUITY_KEYS},
        "tiles": tiles,
        "charts": charts,
        "tables": [{
            "key": "oldest_open",
            "title": "Oldest Open Records",
            "columns": ["Tracking Id", "Severity", "Owner", "Status", "Age (days)"],
            "rows": [[r.get("tracking_id"), r.get("severity"), r.get("assigned_to"),
                      r.get("status"), r.get("age_days")]
                     for r in metrics.get("oldest_open", [])],
        }],
    }


def main(context=None):
    metrics = get_input(context, "metrics", {}) or {}
    coverage = get_input(context, "coverage", {}) or {}
    existing_id = get_input(context, "existing_record_id")
    include_payload = get_input(context, "include_payload", True)

    dashboard = build_dashboard(metrics)
    fields = build_fields(metrics, coverage, get_input(context, "field_prefix", ""),
                          include_payload)
    if include_payload:
        fields["Dashboard JSON"] = json.dumps(dashboard, default=str)

    return {
        "fields": fields,
        "period_key": metrics.get("snapshot_date"),
        "action": "update" if existing_id else "create",
        "record_id": existing_id,
        "dashboard": dashboard,
    }
