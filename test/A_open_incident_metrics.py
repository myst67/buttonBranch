"""Script A - OPEN incident metrics.

Feed this the records array from the Search Records action that finds the open
backlog:

    Status NOT IN (your closed statuses)   and NO date filter

The date filter matters. Open backlog is a stock, not a flow: it is every record
still open, whenever it was raised. Filter that search to the current day and it
returns only today's open records, which is a different and much smaller number.

Every output is a plain value, ready to map straight into an application field.

Inputs
------
records                 the open search results
period_mode             today | full_today | yesterday | date  (default full_today)
snapshot_date           the day being recorded; also used to re-run a past day
now                     optional run time, for reproducible re-runs
previous_open_backlog   yesterday's open_inc_total, for the drift check
previous_snapshot_date  yesterday's snapshot_date
new_inc_total           today's value from Script B, for the drift check
closed_inc_total        today's value from Script C, for the drift check
field_map, closed_statuses, resolved_statuses, false_positive_values,
false_positive_fields, p1p2_values, record_hierarchy_filter,
suspect_minutes_over    see the helper block for the defaults

Outputs
-------
open_inc_total, open_more_than_five_days, open_more_than_thirty_days,
stale_open_no_update_5d, distinct_agents, oldest_open_age,
age_open_inc_{avg,sum,p90,count}, age_last_update_open_inc_{...},
state_dwell_hours_{...}, reassign_count_open_inc_{...},
reassigned_open_count, reassign_count_hist_open_{...}

expected_open_backlog, backlog_drift, is_seed_day, series_continuous,
days_since_previous

snapshot_date, coverage, breakdowns, oldest_open, metrics
"""

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
    "tracking_id": ["Tracking Id", "tracking-id", "trackingId", "trackingFull"],
    "alert_uid": ["Alert UID", "alert-uid", "alertUid", "alert_uid"],
    "title": ["Title", "title", "name"],
    "assigned_to": ["Current Owner", "current-owner", "currentOwner", "assignedTo", "assignee"],
    "severity": ["Severity", "severity", "priority", "Priority"],
    "status": ["Status", "status", "state", "currentState"],
    "type": ["Type", "type", "recordType"],
    "record_hierarchy": ["Record-hierarchy", "record-hierarchy", "recordHierarchy"],
    "classification": ["Classification", "classification"],
    "manual_verdict": ["Manual Verdict", "manual-verdict", "manualVerdict"],
    "alert_categories": ["Alert Categories", "alert-categories", "alertCategories"],
    "escalated": ["Escalated?", "escalated", "Escalated"],
    "escalate_to": ["Escalate to?", "Escalate to", "escalateTo"],
    "threat_type": ["Threat Type", "threat-type", "threatType"],
    "mitre_technique": ["MITRE ATT&CK Technique", "mitre-attack-technique",
                        "mitreTechnique"],
    "mitre_technique_count": ["MITRE ATT&CK Technique Count", "mitreTechniqueCount"],

    "created_at": ["First Created", "first-created", "firstCreated", "created", "createdDate"],
    "updated_at": ["Last Updated", "last-updated", "lastUpdated", "modified", "updated"],
    "closed_at": ["Time Resolved", "time-resolved", "timeResolved", "closed-date",
                  "closed", "closedDate", "resolved-date"],
    "remediated_at": ["Time of Remediation", "time-of-remediation", "timeOfRemediation"],

    # Durations: the text column carries sub-minute precision, the numeric one
    # is truncated, so the text is preferred when both are present.
    "tta_text": ["Time to Acknowledge", "timeToAcknowledge"],
    # The signal-* columns carry the measured durations directly, in minutes.
    "tta_minutes": ["signal-mtta-minutes", "Time to Acknowledge Minutes",
                    "timeToAcknowledgeMinutes"],
    "analyze_text": ["Time to Analyze (excluding pending)", "Time to Analyze", "timeToAnalyze"],
    "analyze_minutes": ["signal-mtti-minutes", "Time to Analyze Minutes",
                        "timeToAnalyzeMinutes"],
    "remediate_text": ["Time to Remediate", "timeToRemediate"],
    "remediate_minutes": ["signal-mttr-minutes", "Time to Remediate Minutes",
                          "timeToRemediateMinutes"],

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

def get_inputs(context=None):
    """Return the action's inputs.

    Turbine's Script action injects a global ``action_inputs`` dict, which is
    the documented contract and is checked first. The context shapes below are
    kept so the same file still runs under a test harness or a custom action.
    """
    scope = globals()
    if isinstance(scope.get("action_inputs"), dict):
        return scope["action_inputs"]
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


def normalize_key(name):
    """Reduce a field name to letters and digits, lowercased.

    CIM records can arrive keyed by display name, camelCase, snake_case or
    kebab-case depending on how the search returns them. Comparing on the
    reduced form means "First Created", "firstCreated" and "first-created" all
    match the same candidate, so a naming convention change cannot silently
    empty out the metrics.
    """
    return "".join(ch for ch in str(name).lower() if ch.isalnum())


def pick_field(record, candidates, default=None):
    """First non-empty value among ``candidates``, matching names loosely."""
    if not isinstance(record, dict):
        return default
    flat = _flatten(record)

    reduced = {}
    for key, value in flat.items():
        reduced.setdefault(normalize_key(key), value)

    for candidate in candidates or []:
        if candidate in flat and flat[candidate] not in (None, ""):
            return flat[candidate]
        found = reduced.get(normalize_key(candidate))
        if found not in (None, ""):
            return found
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


def normalize_records(raw_records, options, end):
    """Map raw CIM records onto canonical names and derive the per-record values.

    ``end`` is the period end: ages and dwell times are measured against it, so a
    re-run of a past day describes that day rather than today.

    Returns (records, skipped, suspect_durations, filtered_out).
    """
    fields = merge_field_map(options.get("field_map"))
    closed_statuses = options.get("closed_statuses") or DEFAULT_CLOSED_STATUSES
    resolved_statuses = options.get("resolved_statuses") or DEFAULT_RESOLVED_STATUSES
    fp_values = options.get("false_positive_values") or DEFAULT_FALSE_POSITIVE_VALUES
    fp_fields = options.get("false_positive_fields") or DEFAULT_FALSE_POSITIVE_FIELDS
    p1p2_values = options.get("p1p2_values") or DEFAULT_P1P2_VALUES
    hierarchy_filter = clean_text(options.get("record_hierarchy_filter"))
    cap = float(options.get("suspect_minutes_over") or DEFAULT_SUSPECT_MINUTES_OVER)

    records, skipped = [], []
    suspect_durations = 0
    filtered_out = 0

    for index, raw in enumerate(as_list(raw_records)):
        if not isinstance(raw, dict):
            skipped.append({"index": index, "reason": "record is not an object"})
            continue

        hierarchy = clean_text(pick_field(raw, fields["record_hierarchy"]))
        if hierarchy_filter and not in_set(hierarchy, [hierarchy_filter]):
            filtered_out += 1
            continue

        created_at = parse_datetime(pick_field(raw, fields["created_at"]))
        if created_at is None:
            skipped.append({
                "index": index,
                "id": clean_text(pick_field(raw, fields["tracking_id"])),
                "reason": "missing or unparsable created date",
            })
            continue

        status = clean_text(pick_field(raw, fields["status"]))
        classification = clean_text(pick_field(raw, fields["classification"]))
        manual_verdict = clean_text(pick_field(raw, fields["manual_verdict"]))
        updated_at = parse_datetime(pick_field(raw, fields["updated_at"]))
        closed_at = parse_datetime(pick_field(raw, fields["closed_at"]))
        remediated_at = parse_datetime(pick_field(raw, fields["remediated_at"]))
        state_changed_at = parse_datetime(pick_field(raw, fields["state_changed_at"]))

        verdicts = {"status": status, "classification": classification,
                    "manual_verdict": manual_verdict}
        is_false_positive = any(in_set(verdicts.get(name), fp_values)
                                for name in fp_fields)
        is_closed_state = in_set(status, closed_statuses)
        is_resolved_state = in_set(status, resolved_statuses)
        severity = clean_text(pick_field(raw, fields["severity"]))

        # The spec's COALESCE(closed_at, updated_at); a remediation time sits
        # between them because it is a closure time when one was recorded.
        effective_closed_at = closed_at or remediated_at or updated_at

        tta, tta_bad = duration_minutes(raw, fields, "tta_text", "tta_minutes", cap)
        analyze, analyze_bad = duration_minutes(
            raw, fields, "analyze_text", "analyze_minutes", cap)
        remediate, remediate_bad = duration_minutes(
            raw, fields, "remediate_text", "remediate_minutes", cap)
        suspect_durations += sum([tta_bad, analyze_bad, remediate_bad])

        # A zero duration with no matching timestamp is a default, not a
        # measurement, so it must not pull an average down to zero.
        if remediate == 0 and remediated_at is None:
            remediate = None

        dwell_from = state_changed_at or updated_at or created_at

        records.append({
            "tracking_id": clean_text(pick_field(raw, fields["tracking_id"])) or "row-{}".format(index),
            "alert_uid": clean_text(pick_field(raw, fields["alert_uid"])),
            "title": clean_text(pick_field(raw, fields["title"])),
            "assigned_to": clean_text(pick_field(raw, fields["assigned_to"])),
            "severity": severity,
            "status": status,
            "type": clean_text(pick_field(raw, fields["type"])),
            "record_hierarchy": hierarchy,
            "classification": classification,
            "manual_verdict": manual_verdict,
            "threat_type": clean_text(pick_field(raw, fields["threat_type"])),
            "mitre_technique": clean_text(pick_field(raw, fields["mitre_technique"])),
            "escalated": is_truthy(pick_field(raw, fields["escalated"])),

            "created_at": to_iso(created_at),
            "updated_at": to_iso(updated_at),
            "closed_at": to_iso(closed_at),
            "effective_closed_at": to_iso(effective_closed_at),

            "is_closed_state": is_closed_state,
            "is_resolved_state": is_resolved_state,
            "is_false_positive": is_false_positive,
            "is_p1p2": in_set(severity, p1p2_values),
            "is_truly_resolved": is_resolved_state and not is_false_positive,

            "age_days": round((end - created_at).total_seconds() / 86400.0, 4),
            "days_since_update": (None if updated_at is None else
                                  round((end - updated_at).total_seconds() / 86400.0, 4)),
            "duration_hours": (None if effective_closed_at is None else
                               round((effective_closed_at - created_at).total_seconds() / 3600.0, 4)),
            "dwell_hours": round((end - dwell_from).total_seconds() / 3600.0, 4),
            "same_day_close": (effective_closed_at is not None
                               and effective_closed_at.date() == created_at.date()),

            "tta_minutes": tta,
            "analyze_minutes": analyze,
            "remediate_minutes": remediate,

            # Reserved: these stay None until the CIM record carries them, and
            # the metrics that need them report as unavailable rather than 0.
            "reassign_count": to_number(pick_field(raw, fields["reassign_count"])),
            "risk_score": to_number(pick_field(raw, fields["risk_score"])),
            "sla_breached": (None if pick_field(raw, fields["sla_breached"]) is None
                             else is_truthy(pick_field(raw, fields["sla_breached"]))),
        })

    return records, skipped, suspect_durations, filtered_out


def as_list(value):
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
            return as_list(json.loads(text))
        except (TypeError, ValueError):
            return []
    return []


def clean_text(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def to_number(value):
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def duration_minutes(record, fields, text_key, minutes_key, cap):
    """Minutes from the text column first, the numeric column second.

    Returns (minutes, was_suspect). A value beyond the cap is dropped rather than
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


def read_options(context):
    """The configuration inputs every one of the three scripts shares."""
    return {
        "field_map": get_input(context, "field_map"),
        "closed_statuses": get_input(context, "closed_statuses"),
        "resolved_statuses": get_input(context, "resolved_statuses"),
        "false_positive_values": get_input(context, "false_positive_values"),
        "false_positive_fields": get_input(context, "false_positive_fields"),
        "p1p2_values": get_input(context, "p1p2_values"),
        "record_hierarchy_filter": get_input(context, "record_hierarchy_filter"),
        "suspect_minutes_over": get_input(context, "suspect_minutes_over"),
    }


def field_coverage(records, needed):
    """Which reserved fields carried data, so a metric can say why it is null."""
    return {name: any(r.get(name) not in (None, "") for r in records)
            for name in needed}


def blocked(reason):
    """A metric that cannot be computed: null plus the reason, never 0."""
    return {"value": None, "status": "unavailable", "reason": reason}


def ok(value, note=None):
    return {"value": value, "status": "proxy" if note else "ok", "reason": note}


def flatten_metrics(metrics, prefix=""):
    """Flatten the catalog into the scalars an application field can hold.

    A value metric expands to Avg/Sum/P90/Count. A metric that is unavailable
    still writes every one of its columns as null, so the application's field
    set does not change shape on the day a source field is added.
    """
    flat = {}
    for key in sorted(metrics):
        entry = metrics[key]
        value = entry.get("value")
        if entry.get("kind", "").startswith("value"):
            parts = value if isinstance(value, dict) else {}
            for part in ("avg", "sum", "p90", "count"):
                flat["{}{}_{}".format(prefix, key, part)] = parts.get(part)
        else:
            flat[prefix + key] = value
    return flat


def emit_outputs(result):
    """Publish the result the way Turbine's Script action collects it.

    ``action_outputs`` is the documented sink: the sandbox may pre-create it, so
    it is updated in place when it already exists and assigned otherwise. The
    other names are written too, harmlessly, so the same file still reports its
    values under a test harness.
    """
    scope = globals()
    existing = scope.get("action_outputs")
    if isinstance(existing, dict):
        existing.update(result)
    else:
        scope["action_outputs"] = dict(result)

    scope["outputs"] = result
    scope["output"] = result
    scope["result"] = result

    ctx = scope.get("context")
    if ctx is not None:
        existing = getattr(ctx, "outputs", None)
        if isinstance(existing, dict):
            existing.update(result)
        else:
            try:
                ctx.outputs = result
            except (AttributeError, TypeError):
                pass
        if isinstance(ctx, dict):
            ctx.setdefault("outputs", {})
            if isinstance(ctx["outputs"], dict):
                ctx["outputs"].update(result)
    return result


#: Input names this script understands, used when the sandbox injects inputs as
#: plain globals rather than through a context object.
KNOWN_INPUT_NAMES = [
    "records", "open_records", "new_records", "closed_records", "backlog_records",
    "period_mode", "snapshot_date", "now", "field_map", "closed_statuses",
    "resolved_statuses", "false_positive_values", "false_positive_fields",
    "p1p2_values", "record_hierarchy_filter", "suspect_minutes_over",
    "previous_open_backlog", "previous_snapshot_date", "new_inc_total",
    "closed_inc_total", "base_assignment", "data_scope", "top_n",
]


def resolve_context():
    """Find the inputs however this sandbox chose to hand them over.

    Three conventions are covered: a ``context`` object or dict, a bare
    ``inputs`` dict, and each input injected as its own global variable. If none
    of them is present the script still runs, on empty inputs, so the action
    produces its full set of keys instead of nothing.
    """
    scope = globals()
    if isinstance(scope.get("action_inputs"), dict):
        return {"inputs": scope["action_inputs"]}
    if "context" in scope and scope["context"] is not None:
        return scope["context"]
    if isinstance(scope.get("inputs"), dict):
        return {"inputs": scope["inputs"]}
    injected = {name: scope[name] for name in KNOWN_INPUT_NAMES if name in scope}
    return {"inputs": injected}


def run_on_import(entry):
    """Run the action as soon as the file is executed, and publish the result.

    This runs unconditionally rather than only when a context is present. An
    action whose result comes back empty cannot be told apart from one that
    never ran, so the script always produces its keys: with no inputs the
    counts are zero, which at least proves it executed.

    A tenant that also calls main() itself is unaffected. The work is pure
    computation over the inputs, so running twice costs a little time and
    changes nothing.
    """
    try:
        return emit_outputs(entry(resolve_context()))
    except Exception as error:  # never fail silently
        message = "{}: {}".format(type(error).__name__, error)
        scope = globals()
        existing_error = scope.get("action_error")
        if isinstance(existing_error, dict):
            existing_error["message"] = message
        else:
            scope["action_error"] = {"message": message}
        return emit_outputs({"error": message, "snapshot_date": None})


#: Dimensions every metric is broken down by, when the records carry them.
BREAKDOWN_DIMENSIONS = ["severity", "status", "assigned_to", "classification",
                        "threat_type", "type"]


#: One line per metric, carried in the output so a tile or tooltip can explain
#: itself without the widget hard-coding the wording.
METRIC_DESCRIPTIONS = {
    # Open base
    "open_inc_total": "Records still open at the end of the day.",
    "open_more_than_five_days": "Open records raised more than 5 days ago.",
    "open_more_than_thirty_days": "Open records raised more than 30 days ago.",
    "stale_open_no_update_5d": "Open records not touched in more than 5 days.",
    "unassigned_open_count": "Open records with nobody assigned.",
    "distinct_agents": "Distinct owners holding open records.",
    "oldest_open_age": "Age in days of the oldest open record.",
    "age_open_inc": "Age in days of each open record, measured at the end of the day.",
    "age_last_update_open_inc": "Days since each open record was last updated.",
    "state_dwell_hours": "Hours each open record has sat without a change.",
    "reassign_count_open_inc": "Times each open record has been reassigned.",
    "reassigned_open_count": "Open records reassigned at least once.",
    "reassign_count_hist_open": "Reassignments per open record, from assignment history.",

    # New base
    "new_inc_total": "Records created during the day.",
    "new_inc_p1p2_count": "New records at P1 or P2 severity.",
    "new_inc_escalated_count": "New records flagged as escalated.",
    "new_inc_acknowledged_count": "New records with an acknowledgement time recorded.",
    "mtta_minutes": "Minutes from creation to acknowledgement.",
    "mtta_hours": "Hours from creation to acknowledgement.",
    "sla_breached_count": "New records that breached their SLA.",
    "sla_breach_rate": "Percentage of new records that breached SLA.",
    "sla_compliance_rate": "Percentage of new records that met SLA.",

    # Closed base
    "closed_inc_total": "Records closed during the day.",
    "closed_inc_not_resolved": "Closed records whose status is not a resolved one.",
    "closed_inc_same_day_open": "Records opened and closed on the same day.",
    "closed_inc_on_first_attempt": "Closed records that were never reassigned.",
    "false_positive_count": "Closed records judged false positive.",
    "false_positive_high_risk_count": "False positives at P1 or P2 severity.",
    "true_positive_count": "Closed records genuinely resolved, false positives excluded.",
    "duration_closed_inc": "Hours from creation to closure.",
    "duration_false_positive_closed_inc": "Hours from creation to closure, false positives only.",
    "mttr_hours": "Hours from creation to closure, genuinely resolved records only.",
    "risk_score_closed_inc": "Risk score of each closed record.",
    "risk_score_false_positive_inc": "Risk score of closed false positives.",
    "risk_score_high_risk_fp_inc": "Risk score of P1 or P2 false positives.",
    "fp_rate": "Percentage of closed records that were false positives.",
    "same_day_close_rate": "Percentage of closed records opened and closed the same day.",
    "true_positive_rate": "Percentage of closed records genuinely resolved.",
    "first_close_rate": "Percentage of closed records never reassigned.",

    # Continuity, carried alongside the metrics
    "snapshot_date": "The day these metrics describe.",
    "is_seed_day": "True on the first run, which seeds the backlog series.",
    "expected_open_backlog": "Yesterday's backlog plus today's new, minus today's closed.",
    "backlog_drift": "Measured backlog minus expected. Normally zero.",
    "series_continuous": "False when a day is missing between this record and the last.",
    "days_since_previous": "Days since the previous record. One on a healthy series.",
    "continuity_note": "How the expected backlog was arrived at.",
}


def count_breakdown(records, dims=None, top=10):
    """Compose a count metric as a flat array of rows.

    One row per dimension value, each tagged with the dimension it came from, so
    a widget can filter to a single dimension or chart them all. A dimension no
    record carries is left out rather than filling the array with rows that all
    read "Unassigned".
    """
    rows = []
    for dim in (dims or BREAKDOWN_DIMENSIONS):
        if not any(r.get(dim) for r in records):
            continue
        for row in count_by(records, dim, top=top):
            rows.append({"dimension": dim, "label": row["label"],
                         "count": row["count"]})
    return rows


def value_breakdown(records, field, dims=None, top=10):
    """Compose a value metric as a flat array: count, mean and sum per value."""
    rows = []
    for dim in (dims or BREAKDOWN_DIMENSIONS):
        if not any(r.get(dim) for r in records):
            continue
        grouped = {}
        for record in records:
            if record.get(field) is None:
                continue
            grouped.setdefault(str(record.get(dim) or "Unassigned"), []).append(
                float(record[field]))
        ranked = sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0]))
        for label, values in ranked[:top]:
            rows.append({
                "dimension": dim,
                "label": label,
                "count": len(values),
                "avg": round(sum(values) / len(values), 2),
                "sum": round(sum(values), 2),
            })
    return rows


def metric_entry(value, kind, records=None, field=None, note=None, reason=None):
    """One metric: its value, and the breakdown of what went into it."""
    entry = {
        "value": value,
        "kind": kind,
        "status": "unavailable" if reason else ("proxy" if note else "ok"),
        "reason": reason or note,
    }
    if reason is None and records is not None:
        entry["breakdown"] = (value_breakdown(records, field) if field
                              else count_breakdown(records))
    else:
        entry["breakdown"] = []
    return entry


def shape_output(metrics, extras=None, coverage=None, include_coverage=False):
    """The action's result: a single ``metrics`` object, nothing else.

    Each entry is keyed by metric name and carries its value, kind, status, the
    reason it is unavailable when it is, and a ``breakdown`` object describing
    what the value is made of.

    ``extras`` are folded in as metrics of their own rather than sitting beside
    them, so everything in the output is a metric. Coverage stays out unless
    asked for; it is diagnostics, not a metric.
    """
    combined = {}
    for key, entry in metrics.items():
        combined[key] = dict(entry)
    for key, value in (extras or {}).items():
        combined[key] = {"value": value, "kind": "info", "status": "ok",
                         "reason": None, "breakdown": []}

    # Each entry carries the day it describes. Without it a metric object is
    # not self-describing, and anything that reads one field on its own - a
    # report grouped by that field, an export, a chart - has no way to place the
    # value in time.
    snapshot = (extras or {}).get("snapshot_date")

    # Every entry explains itself, so a tile or tooltip does not have to carry
    # its own copy of the wording.
    for key, entry in combined.items():
        entry["description"] = METRIC_DESCRIPTIONS.get(key, "")
        entry["snapshot_date"] = snapshot

    result = {"metrics": combined}
    if include_coverage and coverage is not None:
        result["coverage"] = coverage
    return result

# ==========================================================================
# end shared helper block
# ==========================================================================


#: Count metrics as a predicate over the open records, so the value and the
#: breakdown always describe exactly the same subset.
COUNT_METRICS = [
    ("open_inc_total", lambda r: True),
    ("open_more_than_five_days", lambda r: (r.get("age_days") or 0) > 5),
    ("open_more_than_thirty_days", lambda r: (r.get("age_days") or 0) > 30),
    ("stale_open_no_update_5d", lambda r: (r.get("days_since_update") or 0) > 5),
    ("unassigned_open_count", lambda r: not r.get("assigned_to")),
]

#: Value metrics as the record field they average.
VALUE_METRICS = [
    ("age_open_inc", "age_days", "value_days", None),
    ("age_last_update_open_inc", "days_since_update", "value_days", None),
    ("state_dwell_hours", "dwell_hours", "value_hours",
     "hours since last update, not since the state change"),
]


def compute_open_metrics(records, end):
    """The open-base metrics, each carrying the breakdown of what it counted."""
    have = field_coverage(records, ["reassign_count"])
    metrics = {}

    for key, predicate in COUNT_METRICS:
        subset = [r for r in records if predicate(r)]
        metrics[key] = metric_entry(len(subset), "count", subset)

    for key, field, kind, note in VALUE_METRICS:
        subset = [r for r in records if r.get(field) is not None]
        metrics[key] = metric_entry(
            stats([r.get(field) for r in subset]), kind, subset, field, note)

    owners = [r for r in records if r.get("assigned_to")]
    metrics["distinct_agents"] = metric_entry(
        len({r["assigned_to"] for r in owners}), "count", owners)

    ages = [r.get("age_days") for r in records]
    oldest = [max(records, key=lambda r: r.get("age_days") or 0)] if records else []
    metrics["oldest_open_age"] = metric_entry(
        round(max(ages), 2) if ages else None, "days", oldest)

    if have["reassign_count"]:
        counted = [r for r in records if r.get("reassign_count") is not None]
        reassigned = [r for r in counted if (r.get("reassign_count") or 0) > 0]
        metrics["reassign_count_open_inc"] = metric_entry(
            stats([r.get("reassign_count") for r in counted]), "value",
            counted, "reassign_count")
        metrics["reassign_count_hist_open"] = metric_entry(
            stats([r.get("reassign_count") for r in counted]), "value",
            counted, "reassign_count")
        metrics["reassigned_open_count"] = metric_entry(
            len(reassigned), "count", reassigned)
    else:
        why = "needs a reassign count field on the CIM record"
        metrics["reassign_count_open_inc"] = metric_entry(None, "value", reason=why)
        metrics["reassigned_open_count"] = metric_entry(None, "count", reason=why)
        metrics["reassign_count_hist_open"] = metric_entry(
            None, "value",
            reason="needs assignment history, or a reassign count field")
    return metrics


def check_continuity(open_total, previous_open, previous_date, snapshot_date,
                     new_total, closed_total):
    """Reconcile today's measured backlog with yesterday's.

    The recurrence is  open_today = open_yesterday + new_today - closed_today.
    Closures have to be subtracted; carrying yesterday forward and only adding
    today's new records rises every day and never falls.

    This is a check, not the source of truth. open_inc_total is measured
    directly by the open search. A non-zero drift usually means a record was
    closed retroactively, a status changed outside the window, or a search
    missed rows, all of which are worth seeing.
    """
    previous_open = to_number(previous_open)
    new_total = to_number(new_total)
    closed_total = to_number(closed_total)

    today = parse_datetime(snapshot_date)
    yesterday = parse_datetime(previous_date)
    gap = None
    if today is not None and yesterday is not None:
        gap = (today.date() - yesterday.date()).days

    if previous_open is None:
        return {"is_seed_day": True, "expected_open_backlog": None,
                "backlog_drift": None, "series_continuous": True,
                "days_since_previous": gap,
                "continuity_note": "first run: the measured backlog seeds the series"}

    if gap is not None and gap != 1:
        return {"is_seed_day": False, "expected_open_backlog": None,
                "backlog_drift": None, "series_continuous": False,
                "days_since_previous": gap,
                "continuity_note": ("the previous record is {} days back, so the "
                                    "carry-forward cannot span the gap. Backfill "
                                    "with period_mode 'date'.".format(gap))}

    if None in (new_total, closed_total):
        return {"is_seed_day": False, "expected_open_backlog": None,
                "backlog_drift": None, "series_continuous": True,
                "days_since_previous": gap,
                "continuity_note": ("wire new_inc_total from Script B and "
                                    "closed_inc_total from Script C to enable "
                                    "the drift check")}

    expected = previous_open + new_total - closed_total
    return {
        "is_seed_day": False,
        "expected_open_backlog": expected,
        "backlog_drift": (None if open_total is None
                          else round(open_total - expected, 2)),
        "series_continuous": True,
        "days_since_previous": gap,
        "continuity_note": "expected = previous {} + new {} - closed {}".format(
            previous_open, new_total, closed_total),
    }


def main(context=None):
    start, end, snapshot = resolve_day_window(
        get_input(context, "period_mode", "full_today"),
        get_input(context, "snapshot_date"),
        get_input(context, "now"),
    )

    records, skipped, suspect, filtered = normalize_records(
        get_input(context, "records", []), read_options(context), end)

    # Apply the open condition rather than trusting the search:
    #
    #   created_at <= end
    #   AND (closed_at IS NULL OR closed_at > end)
    #   AND NOT (closed_at IS NULL AND closed-state)
    #
    # A record raised after the day being recorded is not in that day's backlog,
    # and one already closed by the end of the day is not open however it was
    # found. Counting either would inflate the backlog whenever the search
    # filter and the closed-status list drift apart.
    future, closed_looking, open_records = [], [], []
    for record in records:
        created = parse_datetime(record.get("created_at"))
        if created is not None and created > end:
            future.append(record)
            continue
        closed_at = parse_datetime(record.get("closed_at"))
        if closed_at is not None and closed_at <= end:
            closed_looking.append(record)
            continue
        if closed_at is None and record.get("is_closed_state"):
            closed_looking.append(record)
            continue
        open_records.append(record)
    records = open_records

    metrics = compute_open_metrics(records, end)

    coverage = {
        "rows_fetched": len(records) + len(skipped) + filtered + len(future),
        "records_used": len(records),
        "records_skipped": len(skipped),
        "records_filtered_by_hierarchy": filtered,
        "records_created_after_period": len(future),
        "records_in_closed_status": len(closed_looking),
        "suspect_durations_dropped": suspect,
        "unavailable": {k: m["reason"] for k, m in metrics.items()
                        if m["status"] == "unavailable"},
        "proxied": {k: m["reason"] for k, m in metrics.items()
                    if m["status"] == "proxy"},
        "skipped_detail": skipped[:50],
        "records_excluded_as_closed": len(closed_looking),
        "warning": ("the open search returned {} record(s) that were already "
                    "closed by the end of the day: they are excluded from the "
                    "backlog. Check its filter against your closed status list."
                    .format(len(closed_looking)) if closed_looking else None),
    }

    extras = {"snapshot_date": snapshot}
    extras.update(check_continuity(
        metrics["open_inc_total"]["value"],
        get_input(context, "previous_open_backlog"),
        get_input(context, "previous_snapshot_date"),
        snapshot,
        get_input(context, "new_inc_total"),
        get_input(context, "closed_inc_total"),
    ))

    return shape_output(metrics, extras, coverage,
                        is_truthy(get_input(context, "include_coverage", False)))


# ======================================================================
# Entry point
# ======================================================================
# Turbine's Script action injects `action_inputs`, collects `action_outputs`,
# and fails the action through `action_error`. This runs on execution, reads
# `action_inputs`, and writes every metric into `action_outputs`. main() stays
# available so the file can also be driven directly by a test harness.

script = main
run = main
execute = main
handler = main

run_on_import(main)
