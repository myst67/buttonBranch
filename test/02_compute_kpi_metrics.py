"""Playbook action 2 of 5 - turn canonical records into KPI numbers.

This is the arithmetic behind the dashboard tiles: the open backlog, what came
in, what went out, how old the backlog is, how fast we close, and how the work
splits by priority, severity, team and source.

The backlog identity always holds:  opening + new - closed == closing.
Action 4 asserts it, so a mapping mistake shows up as a failed check rather
than a quietly wrong tile.

Turbine inputs
--------------
records        output of action 1
period         output of action 1
now            optional ISO "as of" time
age_buckets    optional [[label, min_days, max_days_or_null], ...]
top_n          how many rows to keep in each breakdown table (default 10)

Turbine outputs
---------------
metrics        the full KPI block
"""

from __future__ import annotations

from datetime import datetime

from kpi_common import (
    DEFAULT_AGE_BUCKETS,
    PRIORITY_ORDER,
    UTC,
    bucket_ages,
    count_by,
    get_input,
    mean,
    median,
    parse_datetime,
    pct,
    percentile,
    to_iso,
)


def _within(value, start, end):
    moment = parse_datetime(value)
    return moment is not None and start <= moment <= end


def _open_at(record, moment):
    """Was this record in the backlog at ``moment``?"""
    created = parse_datetime(record.get("created"))
    if created is None or created > moment:
        return False
    closed = parse_datetime(record.get("closed"))
    return closed is None or closed > moment


def _coerce_buckets(raw):
    if not raw:
        return DEFAULT_AGE_BUCKETS
    buckets = []
    for entry in raw:
        if isinstance(entry, dict):
            buckets.append((entry.get("label"), entry.get("min_days", 0), entry.get("max_days")))
        elif isinstance(entry, (list, tuple)) and len(entry) >= 3:
            buckets.append((entry[0], entry[1], entry[2]))
    return buckets or DEFAULT_AGE_BUCKETS


def compute_metrics(records, period_start, period_end, now=None, age_buckets=None, top_n=10):
    start = parse_datetime(period_start)
    end = parse_datetime(period_end)
    as_of = parse_datetime(now) or datetime.now(UTC)
    records = records or []

    new_records = [r for r in records if _within(r.get("created"), start, end)]
    closed_records = [r for r in records if _within(r.get("closed"), start, end)]
    open_now = [r for r in records if r.get("is_open")]

    # Backlog at both ends of the window, so the tile can show the delta.
    opening_backlog = [r for r in records if _open_at(r, start)]
    closing_backlog = [r for r in records if _open_at(r, end)]

    # Ages are measured on the *closing* backlog at the period end, so that a
    # re-run of a past period describes that period and not today.
    backlog_ages = {}
    for record in closing_backlog:
        created = parse_datetime(record.get("created"))
        if created is not None:
            backlog_ages[id(record)] = round(
                (end - created).total_seconds() / 86400.0, 2)
    ages = list(backlog_ages.values())

    resolution_hours = [r.get("resolution_hours") for r in closed_records
                        if r.get("resolution_hours") is not None]

    sla_tracked = [r for r in records if r.get("sla_due_set")]
    sla_breached_open = [r for r in open_now if r.get("sla_breached")]
    sla_breached_closed = [r for r in closed_records if r.get("sla_breached")]
    sla_met = len(sla_tracked) - len(
        [r for r in sla_tracked if r.get("sla_breached")]
    )

    aged_over_30 = [age for age in ages if age >= 30]
    untouched = [r for r in closing_backlog
                 if r.get("assignee") in (None, "", "Unassigned")]

    return {
        "generated_at": to_iso(as_of),
        "period": {"start": to_iso(start), "end": to_iso(end)},

        # --- headline tiles -------------------------------------------------
        "totals": {
            "new": len(new_records),
            "closed": len(closed_records),
            "open_backlog": len(closing_backlog),
            "opening_backlog": len(opening_backlog),
            "net_change": len(new_records) - len(closed_records),
            "open_now": len(open_now),
            "total_records": len(records),
        },
        "rates": {
            # >100% means we closed more than arrived, i.e. the backlog shrank.
            "closure_rate_pct": pct(len(closed_records), len(new_records)),
            "backlog_change_pct": pct(
                len(closing_backlog) - len(opening_backlog), len(opening_backlog) or 1
            ),
            "unassigned_pct": pct(len(untouched), len(closing_backlog)),
            "aged_over_30d_pct": pct(len(aged_over_30), len(closing_backlog)),
        },

        # --- how old is the backlog ----------------------------------------
        "backlog_age": {
            "buckets": bucket_ages(ages, _coerce_buckets(age_buckets)),
            "avg_days": mean(ages),
            "median_days": median(ages),
            "p90_days": percentile(ages, 90),
            "oldest_days": round(max(ages), 2) if ages else None,
            "over_30d": len(aged_over_30),
            "unassigned": len(untouched),
        },

        # --- how fast do we close ------------------------------------------
        "resolution": {
            "sample_size": len(resolution_hours),
            "mttr_hours": mean(resolution_hours),
            "median_hours": median(resolution_hours),
            "p90_hours": percentile(resolution_hours, 90),
            "fastest_hours": round(min(resolution_hours), 2) if resolution_hours else None,
            "slowest_hours": round(max(resolution_hours), 2) if resolution_hours else None,
        },

        # --- SLA -------------------------------------------------------------
        "sla": {
            "tracked": len(sla_tracked),
            "met": max(sla_met, 0),
            "breached_open": len(sla_breached_open),
            "breached_closed": len(sla_breached_closed),
            "compliance_pct": pct(max(sla_met, 0), len(sla_tracked)),
        },

        # --- breakdowns for the dashboard tables/charts ----------------------
        "breakdowns": {
            "open_by_priority": count_by(closing_backlog, "priority", order=PRIORITY_ORDER),
            "open_by_severity": count_by(closing_backlog, "severity", order=PRIORITY_ORDER),
            "open_by_status": count_by(closing_backlog, "status"),
            "open_by_team": count_by(closing_backlog, "team", top=top_n),
            "open_by_assignee": count_by(closing_backlog, "assignee", top=top_n),
            "new_by_source": count_by(new_records, "source", top=top_n),
            "new_by_category": count_by(new_records, "category", top=top_n),
            "closed_by_team": count_by(closed_records, "team", top=top_n),
        },

        # --- worklist for the "oldest open" table ---------------------------
        "oldest_open": [
            {
                "id": r.get("id"),
                "tracking_id": r.get("tracking_id"),
                "title": r.get("title"),
                "priority": r.get("priority"),
                "assignee": r.get("assignee"),
                "age_days": backlog_ages.get(id(r)),
                "created": r.get("created"),
            }
            for r in sorted(closing_backlog,
                            key=lambda r: backlog_ages.get(id(r)) or 0,
                            reverse=True)[:top_n]
        ],
    }


def main(context=None):
    period = get_input(context, "period", {}) or {}
    metrics = compute_metrics(
        get_input(context, "records", []),
        period.get("start"),
        period.get("end"),
        get_input(context, "now"),
        get_input(context, "age_buckets"),
        int(get_input(context, "top_n", 10)),
    )
    return {"metrics": metrics}
