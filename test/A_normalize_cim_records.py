"""Script A of 3 - normalize CIM records and classify the three metric bases.

Runs once per day from the cron trigger. Everything downstream reads this
action's output, so this is the only script that knows your CIM column names.

Inputs
------
records                  raw CIM records from the day's Search Records action
backlog_records          optional second search: every record still open, with
                         no date filter. Required for the open-base metrics,
                         because a one-day slice cannot measure a backlog
data_scope               auto | full | day_created | day_updated |
                         day_plus_backlog  (default auto). Auto never assumes
                         "full"; declare it when the search has no date filter
period_mode              today | full_today | yesterday | date   (default today)
snapshot_date            ISO date, required when period_mode is "date"; also used
                         on its own to re-run a past day
now                      optional ISO run time, for deterministic re-runs
field_map                optional canonical name -> your CIM key(s)
closed_statuses          statuses that mean the record left the backlog
resolved_statuses        the subset that counts as genuinely resolved
false_positive_values    values that mark a false positive
false_positive_fields    which fields carry the verdict (default status,
                         classification, manual_verdict)
p1p2_values              severity values treated as P1/P2 (default critical, high)
record_hierarchy_filter  optional: keep only "Parent" or only "Child" rows
suspect_minutes_over     durations above this are treated as bad data

Outputs
-------
records   canonical records carrying in_open / in_new / in_closed
period    start, end, date, key - the day this snapshot is for
coverage  which canonical fields resolved, what was skipped, suspect durations,
          and which metric bases the fetched data can actually measure
summary   counts, so the playbook can stop early on an empty day
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


def _duration(record, fields, text_key, minutes_key, cap):
    """Minutes from the text column first, the numeric column second.

    Returns (minutes, was_suspect). A value above the cap is dropped rather than
    allowed into an average, because the numeric columns do not all agree on
    their unit.
    """
    minutes = parse_duration_minutes(
        pick_field(record, fields[text_key]),
        pick_field(record, fields[minutes_key]),
    )
    if minutes is None:
        return None, False
    if minutes > cap or minutes < 0:
        return None, True
    return minutes, False


#: What each scope can honestly measure. A base that is not measurable has its
#: metrics stored as null with a reason, rather than a number computed from a
#: slice of data that cannot support it.
SCOPE_RULES = {
    "full": (True, True, "search returns all records"),
    "day_plus_backlog": (True, True, "day slice plus a full open-backlog search"),
    "day_updated": (False, True,
                    "search returns one day filtered on last-updated, so records "
                    "left untouched today are absent and the backlog is unknown"),
    "day_created": (False, False,
                    "search returns one day filtered on created date, so neither "
                    "the standing backlog nor older records closed today are present"),
}


def resolve_scope(declared, has_backlog, records, start):
    """Work out what the fetched data can support, if it was not declared.

    Auto-detection never concludes "full". A day search filtered on last-updated
    returns records created months ago, so a full search and a one-day slice look
    identical from the data alone. Guessing "full" would silently compute a
    backlog from a partial fetch, which is the one failure worth designing out,
    so ``full`` has to be declared deliberately.
    """
    declared = (declared or "auto").strip().lower()
    if declared in SCOPE_RULES:
        return declared
    if has_backlog:
        return "day_plus_backlog"
    if records and all((parse_datetime(r.get("created_at")) or start) >= start
                       for r in records):
        return "day_created"
    return "day_updated"


def dedupe(records):
    """One row per record when the two searches overlap; newest update wins."""
    best = {}
    for record in records:
        key = record.get("tracking_id") or record.get("alert_uid")
        current = best.get(key)
        if current is None:
            best[key] = record
            continue
        a = parse_datetime(record.get("updated_at"))
        b = parse_datetime(current.get("updated_at"))
        if a is not None and (b is None or a > b):
            best[key] = record
    return list(best.values())


def normalize(raw_records, options):
    fields = merge_field_map(options.get("field_map"))
    closed_statuses = options.get("closed_statuses") or DEFAULT_CLOSED_STATUSES
    resolved_statuses = options.get("resolved_statuses") or DEFAULT_RESOLVED_STATUSES
    fp_values = options.get("false_positive_values") or DEFAULT_FALSE_POSITIVE_VALUES
    fp_fields = options.get("false_positive_fields") or DEFAULT_FALSE_POSITIVE_FIELDS
    p1p2_values = options.get("p1p2_values") or DEFAULT_P1P2_VALUES
    hierarchy_filter = _clean(options.get("record_hierarchy_filter"))
    cap = float(options.get("suspect_minutes_over") or DEFAULT_SUSPECT_MINUTES_OVER)

    start = options["start"]
    end = options["end"]

    normalized, skipped = [], []
    suspect_durations = 0
    filtered_out = 0

    for index, raw in enumerate(_as_list(raw_records)):
        if not isinstance(raw, dict):
            skipped.append({"index": index, "reason": "record is not an object"})
            continue

        hierarchy = _clean(pick_field(raw, fields["record_hierarchy"]))
        if hierarchy_filter and not in_set(hierarchy, [hierarchy_filter]):
            filtered_out += 1
            continue

        created_at = parse_datetime(pick_field(raw, fields["created_at"]))
        if created_at is None:
            skipped.append({
                "index": index,
                "id": _clean(pick_field(raw, fields["tracking_id"])),
                "reason": "missing or unparsable created date",
            })
            continue

        status = _clean(pick_field(raw, fields["status"]))
        classification = _clean(pick_field(raw, fields["classification"]))
        manual_verdict = _clean(pick_field(raw, fields["manual_verdict"]))
        updated_at = parse_datetime(pick_field(raw, fields["updated_at"]))
        closed_at = parse_datetime(pick_field(raw, fields["closed_at"]))
        remediated_at = parse_datetime(pick_field(raw, fields["remediated_at"]))
        state_changed_at = parse_datetime(pick_field(raw, fields["state_changed_at"]))

        is_closed_state = in_set(status, closed_statuses)
        is_resolved_state = in_set(status, resolved_statuses)

        verdict_values = {
            "status": status,
            "classification": classification,
            "manual_verdict": manual_verdict,
        }
        is_false_positive = any(in_set(verdict_values.get(name), fp_values)
                                for name in fp_fields)

        severity = _clean(pick_field(raw, fields["severity"]))
        is_p1p2 = in_set(severity, p1p2_values)

        # The spec's COALESCE(closed_at, updated_at); remediated_at sits between
        # them because a remediation time is a closure time when one is recorded.
        effective_closed_at = closed_at or remediated_at or updated_at

        tta_minutes, tta_suspect = _duration(raw, fields, "tta_text", "tta_minutes", cap)
        analyze_minutes, analyze_suspect = _duration(
            raw, fields, "analyze_text", "analyze_minutes", cap)
        remediate_minutes, remediate_suspect = _duration(
            raw, fields, "remediate_text", "remediate_minutes", cap)
        suspect_durations += sum([tta_suspect, analyze_suspect, remediate_suspect])

        # A zero duration with no matching timestamp is a default, not a
        # measurement, so it must not pull an average down to zero.
        if remediate_minutes == 0 and remediated_at is None:
            remediate_minutes = None

        # --- the three bases, exactly as specified -------------------------
        in_open = (
            created_at <= end
            and (closed_at is None or closed_at > end)
            and not (closed_at is None and is_closed_state)
        )
        in_new = start <= created_at <= end
        in_closed = (
            is_closed_state
            and effective_closed_at is not None
            and start <= effective_closed_at <= end
        )

        dwell_from = state_changed_at or updated_at or created_at

        normalized.append({
            "tracking_id": _clean(pick_field(raw, fields["tracking_id"])) or "row-{}".format(index),
            "alert_uid": _clean(pick_field(raw, fields["alert_uid"])),
            "title": _clean(pick_field(raw, fields["title"])),
            "assigned_to": _clean(pick_field(raw, fields["assigned_to"])),
            "severity": severity,
            "status": status,
            "type": _clean(pick_field(raw, fields["type"])),
            "record_hierarchy": hierarchy,
            "classification": classification,
            "manual_verdict": manual_verdict,
            "threat_type": _clean(pick_field(raw, fields["threat_type"])),
            "alert_categories": _clean(pick_field(raw, fields["alert_categories"])),
            "mitre_technique": _clean(pick_field(raw, fields["mitre_technique"])),
            "escalated": is_truthy(pick_field(raw, fields["escalated"])),

            "created_at": to_iso(created_at),
            "updated_at": to_iso(updated_at),
            "closed_at": to_iso(closed_at),
            "remediated_at": to_iso(remediated_at),
            "effective_closed_at": to_iso(effective_closed_at),

            "is_closed_state": is_closed_state,
            "is_resolved_state": is_resolved_state,
            "is_false_positive": is_false_positive,
            "is_p1p2": is_p1p2,
            "is_truly_resolved": is_resolved_state and not is_false_positive,

            "in_open": in_open,
            "in_new": in_new,
            "in_closed": in_closed,

            # Measured at the period end so a re-run of a past day describes
            # that day rather than today.
            "age_days": round((end - created_at).total_seconds() / 86400.0, 4),
            "days_since_update": (None if updated_at is None
                                  else round((end - updated_at).total_seconds() / 86400.0, 4)),
            "duration_hours": (None if effective_closed_at is None else
                               round((effective_closed_at - created_at).total_seconds() / 3600.0, 4)),
            "dwell_hours": round((end - dwell_from).total_seconds() / 3600.0, 4),
            "same_day_close": (effective_closed_at is not None
                               and effective_closed_at.date() == created_at.date()),

            "tta_minutes": tta_minutes,
            "analyze_minutes": analyze_minutes,
            "remediate_minutes": remediate_minutes,

            # Reserved. These resolve to None until the CIM record carries them;
            # Script B reports the metrics that need them as unavailable.
            "reassign_count": _to_number(pick_field(raw, fields["reassign_count"])),
            "risk_score": _to_number(pick_field(raw, fields["risk_score"])),
            "sla_breached": (None if pick_field(raw, fields["sla_breached"]) is None
                             else is_truthy(pick_field(raw, fields["sla_breached"]))),
        })

    return normalized, skipped, suspect_durations, filtered_out


def _to_number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_coverage(records, skipped, suspect_durations, filtered_out, scope):
    """Which canonical fields actually carried data, so Script B can be honest.

    A field that resolved on no record at all is reported missing, and every
    metric that depends on it is stored as null instead of a misleading zero.
    """
    tracked = [
        "created_at", "updated_at", "closed_at", "remediated_at", "status",
        "assigned_to", "severity", "classification", "manual_verdict",
        "record_hierarchy", "type", "threat_type", "mitre_technique",
        "tta_minutes", "analyze_minutes", "remediate_minutes",
        "reassign_count", "risk_score", "sla_breached", "state_changed_at",
    ]
    present, missing = [], []
    for field in tracked:
        if any(record.get(field) not in (None, "") for record in records):
            present.append(field)
        else:
            missing.append(field)
    open_ok, closed_ok, note = SCOPE_RULES[scope]
    return {
        "scope": {
            "data_scope": scope,
            "open_base_measurable": open_ok,
            "closed_base_measurable": closed_ok,
            "note": note,
        },
        "fields_present": present,
        "fields_missing": missing,
        "records_in": len(records) + len(skipped) + filtered_out,
        "records_used": len(records),
        "records_skipped": len(skipped),
        "records_filtered_by_hierarchy": filtered_out,
        "suspect_durations_dropped": suspect_durations,
        "skipped_detail": skipped[:50],
    }


def main(context=None):
    start, end, snapshot = resolve_day_window(
        get_input(context, "period_mode", "today"),
        get_input(context, "snapshot_date"),
        get_input(context, "now"),
    )

    options = {
        "start": start,
        "end": end,
        "field_map": get_input(context, "field_map"),
        "closed_statuses": get_input(context, "closed_statuses"),
        "resolved_statuses": get_input(context, "resolved_statuses"),
        "false_positive_values": get_input(context, "false_positive_values"),
        "false_positive_fields": get_input(context, "false_positive_fields"),
        "p1p2_values": get_input(context, "p1p2_values"),
        "record_hierarchy_filter": get_input(context, "record_hierarchy_filter"),
        "suspect_minutes_over": get_input(context, "suspect_minutes_over"),
    }

    day_records = _as_list(get_input(context, "records", []))
    backlog_records = _as_list(get_input(context, "backlog_records", []))

    records, skipped, suspect, filtered = normalize(
        day_records + backlog_records, options)
    records = dedupe(records)

    scope = resolve_scope(get_input(context, "data_scope", "auto"),
                          bool(backlog_records), records, start)
    coverage = build_coverage(records, skipped, suspect, filtered, scope)

    return {
        "records": records,
        "period": {
            "start": to_iso(start),
            "end": to_iso(end),
            "date": snapshot,
            "key": snapshot,
            "mode": get_input(context, "period_mode", "today"),
        },
        "coverage": coverage,
        "summary": {
            "total": len(records),
            "open": sum(1 for r in records if r["in_open"]),
            "new": sum(1 for r in records if r["in_new"]),
            "closed": sum(1 for r in records if r["in_closed"]),
            "has_records": bool(records),
        },
    }
