"""Playbook action 4 of 5 - assemble the dashboard payload.

Takes the metrics and the trend series and produces the exact structure the
custom KPI application renders: tiles across the top, charts under them, then
tables.  Nothing here calls out to anything - it is pure shaping, which is what
makes it safe to run inside Turbine.

Pass ``previous_metrics`` (the same block from the prior run) to get
period-over-period deltas and arrows on the tiles.

Turbine inputs
--------------
metrics           output of action 2
trend             output of action 3
previous_metrics  optional metrics block from the previous run
dashboard_title   optional heading (default "CIM Incident KPI Dashboard")

Turbine outputs
---------------
dashboard   tiles + charts + tables, JSON-safe
checks      integrity checks; ``checks.ok`` is false when a number is impossible

Self-contained: the shared helpers this action needs are inlined below,
so the whole file pastes into one Turbine Python action.
"""

from __future__ import annotations



# ======================================================================
# Helpers
# ======================================================================

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

def pct(part, whole, digits=1):
    """Percentage of ``part`` in ``whole``; 0.0 when ``whole`` is 0."""
    if not whole:
        return 0.0
    return round((float(part) / float(whole)) * 100.0, digits)

# ======================================================================
# Action
# ======================================================================

def _delta(current, previous):
    """Tile delta with a direction the UI can turn into an arrow."""
    if previous is None or current is None:
        return {"value": None, "pct": None, "direction": "flat"}
    change = current - previous
    return {
        "value": change,
        "pct": pct(change, previous) if previous else None,
        "direction": "up" if change > 0 else ("down" if change < 0 else "flat"),
    }

def _tile(key, label, value, delta=None, unit=None, intent="neutral", hint=None):
    """``intent`` says whether *up* is good, so the UI colours the arrow right."""
    return {
        "key": key,
        "label": label,
        "value": value,
        "unit": unit,
        "delta": delta or {"value": None, "pct": None, "direction": "flat"},
        "intent": intent,
        "hint": hint,
    }

def build_dashboard(metrics, trend=None, previous=None, title=None):
    metrics = metrics or {}
    trend = trend or {}
    previous = previous or {}

    totals = metrics.get("totals", {})
    rates = metrics.get("rates", {})
    age = metrics.get("backlog_age", {})
    resolution = metrics.get("resolution", {})
    sla = metrics.get("sla", {})
    breakdowns = metrics.get("breakdowns", {})

    prev_totals = previous.get("totals", {})
    prev_res = previous.get("resolution", {})

    tiles = [
        _tile("open_backlog", "Open Backlog", totals.get("open_backlog"),
              _delta(totals.get("open_backlog"), prev_totals.get("open_backlog")),
              intent="lower_is_better",
              hint="Records still open at the end of the period"),
        _tile("new", "New Incidents", totals.get("new"),
              _delta(totals.get("new"), prev_totals.get("new")),
              intent="neutral",
              hint="Created inside the period"),
        _tile("closed", "Closed", totals.get("closed"),
              _delta(totals.get("closed"), prev_totals.get("closed")),
              intent="higher_is_better",
              hint="Moved to a closed status inside the period"),
        _tile("net_change", "Net Change", totals.get("net_change"),
              _delta(totals.get("net_change"), prev_totals.get("net_change")),
              intent="lower_is_better",
              hint="New minus closed; negative means the backlog shrank"),
        _tile("closure_rate", "Closure Rate", rates.get("closure_rate_pct"),
              unit="%", intent="higher_is_better",
              hint="Closed as a share of new; above 100% is burning down"),
        _tile("mttr", "MTTR", resolution.get("mttr_hours"),
              _delta(resolution.get("mttr_hours"), prev_res.get("mttr_hours")),
              unit="hours", intent="lower_is_better",
              hint="Mean time from created to closed"),
        _tile("aged", "Aged over 30d", age.get("over_30d"),
              unit=None, intent="lower_is_better",
              hint="Open records older than 30 days"),
        _tile("sla", "SLA Compliance", sla.get("compliance_pct"),
              unit="%", intent="higher_is_better",
              hint="Share of SLA-tracked records not breached"),
    ]

    charts = [
        {
            "key": "backlog_trend",
            "type": "line",
            "title": "New vs Closed vs Backlog",
            "x": trend.get("labels", []),
            "series": [
                {"name": "New", "data": trend.get("new", [])},
                {"name": "Closed", "data": trend.get("closed", [])},
                {"name": "Open Backlog", "data": trend.get("backlog", [])},
            ],
        },
        {
            "key": "backlog_age",
            "type": "bar",
            "title": "Backlog Age",
            "x": [b["label"] for b in age.get("buckets", [])],
            "series": [{"name": "Open", "data": [b["count"] for b in age.get("buckets", [])]}],
        },
        {
            "key": "open_by_priority",
            "type": "donut",
            "title": "Open by Priority",
            "x": [b["label"] for b in breakdowns.get("open_by_priority", [])],
            "series": [{"name": "Open",
                        "data": [b["count"] for b in breakdowns.get("open_by_priority", [])]}],
        },
        {
            "key": "new_by_source",
            "type": "bar",
            "title": "New by Source",
            "x": [b["label"] for b in breakdowns.get("new_by_source", [])],
            "series": [{"name": "New",
                        "data": [b["count"] for b in breakdowns.get("new_by_source", [])]}],
        },
    ]

    tables = [
        {"key": "open_by_team", "title": "Open by Team",
         "columns": ["Team", "Open"],
         "rows": [[b["label"], b["count"]] for b in breakdowns.get("open_by_team", [])]},
        {"key": "open_by_assignee", "title": "Open by Assignee",
         "columns": ["Assignee", "Open"],
         "rows": [[b["label"], b["count"]] for b in breakdowns.get("open_by_assignee", [])]},
        {"key": "oldest_open", "title": "Oldest Open Records",
         "columns": ["Tracking Id", "Title", "Priority", "Assignee", "Age (days)"],
         "rows": [[r.get("tracking_id") or r.get("id"), r.get("title"), r.get("priority"),
                   r.get("assignee"), r.get("age_days")]
                  for r in metrics.get("oldest_open", [])]},
    ]

    return {
        "title": title or "CIM Incident KPI Dashboard",
        "generated_at": metrics.get("generated_at"),
        "period": metrics.get("period", {}),
        "tiles": tiles,
        "charts": charts,
        "tables": tables,
    }

def run_checks(metrics):
    """Catch a bad field mapping before it reaches a dashboard tile."""
    totals = (metrics or {}).get("totals", {})
    opening = totals.get("opening_backlog")
    new = totals.get("new")
    closed = totals.get("closed")
    closing = totals.get("open_backlog")

    failures = []
    if None not in (opening, new, closed, closing):
        expected = opening + new - closed
        if expected != closing:
            failures.append(
                "Backlog does not balance: opening {} + new {} - closed {} = {}, "
                "but closing backlog is {}. Check the created/closed field mapping."
                .format(opening, new, closed, expected, closing)
            )
    for name in ("new", "closed", "open_backlog"):
        value = totals.get(name)
        if value is not None and value < 0:
            failures.append("Negative count for {}: {}".format(name, value))

    return {"ok": not failures, "failures": failures}

def main(context=None):
    metrics = get_input(context, "metrics", {}) or {}
    dashboard = build_dashboard(
        metrics,
        get_input(context, "trend", {}),
        get_input(context, "previous_metrics", {}),
        get_input(context, "dashboard_title"),
    )
    return {"dashboard": dashboard, "checks": run_checks(metrics)}
