# CIM Daily KPI Playbook

Three independent Turbine Python actions, one per incident base. Each takes the
`records` array from its own Search Records action, computes that base's metrics,
and returns plain values you map straight into application fields.

| Script | Fed by | Returns |
| --- | --- | --- |
| `A_open_incident_metrics.py` | Status NOT IN closed, **no date filter** | 37 fields |
| `B_new_incident_metrics.py` | created within the day | 18 fields |
| `C_closed_incident_metrics.py` | closed within the day | 38 fields |

No external API calls, standard library only. Each script carries the same
helper block, marked by a banner and byte-identical across all three, so if your
tenant supports a reusable Python component you can lift it out of all three.

See `PLAN.md` for the metric catalog and the sprint breakdown.

---

## Playbook flow

```
[ Cron trigger: daily at 11:55 ]
        |
        +-- [ Search Records ] -> Status NOT IN closed, NO date filter
        |         |   records
        |   [ Python: Script A ] -> open metrics
        |
        +-- [ Search Records ] -> created today
        |         |   records
        |   [ Python: Script B ] -> new metrics
        |
        +-- [ Search Records ] -> closed today
                  |   records
            [ Python: Script C ] -> closed metrics
        |
[ Create / Update Record ]  ->  KPI application, one record per day
```

The three are independent and can run in parallel. Only the backlog drift check
links them, and it is optional: pass Script B's `new_inc_total` and Script C's
`closed_inc_total` into Script A if you want it.

---

## How the scripts talk to Turbine

Turbine's Script native action injects three globals, and the scripts use them:

| Global | Role |
| --- | --- |
| `action_inputs` | dict of the inputs configured on the action |
| `action_outputs` | dict the action collects as its result |
| `action_error` | populate it to fail the action with that message |

Each script runs as soon as the action executes, reads `action_inputs`, and
writes its result into `action_outputs`. If it raises, the message goes to
`action_error` rather than disappearing.

## What the output contains

One key: `metrics`. Every entry has the same shape.

```json
"open_inc_total": {
  "value": 2,
  "kind": "count",
  "status": "ok",
  "reason": null,
  "description": "Records still open at the end of the day.",
  "breakdown": [
    {"dimension": "severity",    "label": "Critical",    "count": 1},
    {"dimension": "severity",    "label": "High",        "count": 1},
    {"dimension": "status",      "label": "Blocked",     "count": 1},
    {"dimension": "status",      "label": "New",         "count": 1},
    {"dimension": "assigned_to", "label": "analyst.one", "count": 1}
  ]
}
```

`description` is a one-line explanation of the metric, so a tile or tooltip
does not need its own copy of the wording. It is present even when the metric is
unavailable, so the UI can still say what the number would have meant.

`breakdown` is a flat array. Every row carries the dimension it came from, so a
widget filters to one dimension with `rows.filter(r => r.dimension === 'severity')`
or charts them all. A **count** metric's rows within any one dimension always sum
back to the metric itself. A **value** metric's own value is the distribution
(count, sum, avg, min, max, p50, p90) and it breaks down into the count, mean
and sum per dimension:

```json
"age_open_inc": {
  "value": {"count": 3, "sum": 19.62, "avg": 6.54, "min": 0.67, "max": 12.32,
            "p50": 6.62, "p90": 12.32},
  "kind": "value_days",
  "breakdown": [
    {"dimension": "severity", "label": "Critical", "count": 1, "avg": 0.67, "sum": 0.67}
  ]
}
```

A metric that cannot be computed has a null value, an empty breakdown array, and
a `reason` naming the field it needs, so it is never mistaken for a real zero.

Dimensions are severity, status, owner, classification, threat type and record
type. Any the records do not carry is left out rather than filling the output
with "Unassigned" rows.

Map an application field from `metrics.<name>.value`, or for a value metric
`metrics.<name>.value.avg`.

Set `include_coverage` to true to add a `coverage` object while diagnosing a
run; it is off by default because it is diagnostics, not a metric.

--- | --- |
| `action_inputs` | dict of the inputs configured on the action |
| `action_outputs` | dict the action collects as its result |
| `action_error` | populate it to fail the action with that message |

Each script runs as soon as the action executes, reads `action_inputs`, and
writes every metric into `action_outputs`. If it raises, the message goes to
`action_error` rather than disappearing.

`main(context)` is still defined so the file can be driven by a test harness,
but Turbine does not need it.

### If the result is still empty

* **`{}` with no error** means the file did not execute. Confirm the whole file
  was pasted, helper block included.
* **Zeros everywhere** means it ran but got no records. Check the input is named
  exactly `records`, and read `coverage.rows_fetched`.
* **`coverage.records_skipped` above zero** means records arrived but had no
  usable created date. `coverage.skipped_detail` says why, and `field_map` fixes
  it without editing the script.

---

## Mapping outputs to fields

Every metric is a top-level output, so the mapping is direct. No JSON to unpack.

```
A.open_inc_total              ->  Open Inc Total
A.open_more_than_five_days    ->  Open More Than Five Days
A.age_open_inc_avg            ->  Avg Backlog Age Days
B.new_inc_total               ->  New Inc Total
B.mtta_hours_avg              ->  MTTA Hours
C.closed_inc_total            ->  Closed Inc Total
C.fp_rate                     ->  FP Rate %
C.mttr_hours_avg              ->  MTTR Hours
```

A metric defined as a value rather than a count expands to four outputs, so one
stored metric answers both "sum" and "mean" without a re-run:

```
age_open_inc_avg    age_open_inc_sum    age_open_inc_p90    age_open_inc_count
```

`_count` is how many records carried the value, which is not the size of the
base when a column is sparsely filled.

Each script also returns `metrics` (the same values with status and reason),
`coverage`, `breakdowns` and, from Script A, `oldest_open`. Those are objects,
useful for a JSON field or a dashboard, not for a numeric field.

---

## The open search must have no date filter

Open backlog is a stock, not a flow: every record still open, whenever it was
raised. Filtered to the current day, that search returns only today's open
records, which is a different and much smaller number.

If you want "opened today and still open", that is `B.new_inc_total` minus the
same-day closes, not `A.open_inc_total`.

Filter the **closed** search on the closed or last-updated date, never on created
date. A created-date filter misses every record raised earlier and closed today,
which is most of them.

Each script checks the records it was given against the day window and reports a
mismatch in `coverage.warning` rather than counting them: records outside the
window, records in the wrong status, records raised after the day being recorded.

---

## Day-on-day backlog

The recurrence is:

```
open_today = open_yesterday + new_today - closed_today
```

**Closures have to be subtracted.** Carrying yesterday forward and only adding
today's new records rises every day and never falls. Over a normal ten-day
stretch that reads 60 against a true backlog of 12, and the gap keeps widening.

You do not need the recurrence to know the backlog: the open search measures it
directly, which is where `open_inc_total` comes from. The recurrence is a
**check**. Pass yesterday's stored value as `previous_open_backlog`, with
`previous_snapshot_date`, plus `new_inc_total` and `closed_inc_total`, and
Script A reconciles them:

| Output | Meaning |
| --- | --- |
| `expected_open_backlog` | previous + new - closed |
| `backlog_drift` | measured minus expected, normally 0 |
| `is_seed_day` | true on the first run, which seeds the series |
| `days_since_previous` | 1 on a healthy series |
| `series_continuous` | false when a day was missed |

On the first run, omit `previous_open_backlog`. That day seeds the series. A
non-zero drift later usually means a record was closed retroactively, a status
changed outside the window, or a search missed rows. A missed day sets
`series_continuous` false and produces no expected value, since a carry-forward
cannot span a gap; backfill with `period_mode: date`.

---

## The daily window

Set the cron and `period_mode` together, or the record will cover a different
span than its date implies.

| Cron | `period_mode` | Covers |
| --- | --- | --- |
| `55 23 * * *` | `full_today` | the whole day |
| `55 11 * * *` | `yesterday` | the whole previous day |
| any | `today` | midnight to the run time, a partial day |

**If 11:55 means 11:55 AM, do not use `today`.** It stores half a day of counts
under a full day's date. Use `yesterday` at that hour. Confirm which timezone
your cron evaluates; the scripts work in UTC throughout.

To backfill or correct a day, set `period_mode: date` and `snapshot_date`.

---

## Field names

Names are matched on letters and digits only, case-insensitively, so
`First Created`, `firstCreated` and `first-created` all resolve to the same
canonical field. A change in naming convention cannot silently empty the
metrics.

The keys the CIM search returns are mapped out of the box, including
`tracking-id`, `first-created`, `last-updated`, `manual-verdict`,
`current-owner`, and the measured durations `signal-mtta-minutes`,
`signal-mtti-minutes` and `signal-mttr-minutes`.

If a field is still not found, `coverage.records_skipped` counts the records
that had no usable created date and `skipped_detail` says why. Add the real key
through the `field_map` input rather than editing the script.

---

## Inputs

`records` is the only required input. The rest have defaults, listed at the top
of the helper block.

| Input | Purpose |
| --- | --- |
| `records` | the array from this script's Search Records action |
| `period_mode`, `snapshot_date`, `now` | which day is being recorded |
| `field_map` | canonical name to your CIM key(s), when a column is renamed |
| `closed_statuses` | statuses meaning the record left the backlog |
| `resolved_statuses` | the subset counting as genuinely resolved |
| `false_positive_values` | values marking a false positive |
| `false_positive_fields` | which fields carry the verdict |
| `p1p2_values` | severity values treated as P1/P2 |
| `record_hierarchy_filter` | keep only parent rows, or only child rows |
| `suspect_minutes_over` | duration above which a value is treated as bad data |

Script A additionally takes `previous_open_backlog`, `previous_snapshot_date`,
`new_inc_total` and `closed_inc_total` for the drift check.

---

## Metrics that cannot be computed yet

11 of the 34 need fields the CIM record does not carry. They are returned as
**null with a reason, never 0**, so a missing field cannot read as a good score,
and they still return their full set of outputs so the application field set does
not change shape on the day you add the source.

| Script | Blocked | Needs |
| --- | --- | --- |
| A | `reassign_count_open_inc`, `reassigned_open_count`, `reassign_count_hist_open` | a reassign count field |
| B | `sla_breached_count`, `sla_breach_rate`, `sla_compliance_rate` | an SLA breached field |
| C | `closed_inc_on_first_attempt`, `first_close_rate` | a reassign count field |
| C | `risk_score_closed_inc`, `risk_score_false_positive_inc`, `risk_score_high_risk_fp_inc` | a risk score field |

Three fields unblock all eleven. `coverage.unavailable` names each one and why.

`state_dwell_hours` is a proxy: without a state-changed timestamp it measures
hours since the last update. It is reported in `coverage.proxied`.

---

## Data handling

No CIM record data, exported rows, screenshots or live field values belong in
this repository. Column names appear because the field map needs them. Generate
any dry-run sample synthetically, outside the repo.
