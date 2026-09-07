# Swimlane Turbine - CIM KPI Dashboard Playbook

Python for a Turbine playbook that reads your CIM records and produces the KPI
numbers a Glass-style dashboard shows: **open backlog, new incidents, closed
incidents**, plus backlog aging, MTTR, SLA compliance and the daily trend line.

Turbine cannot call an external API here, so every number is computed inside
the playbook by these scripts. Nothing in this folder makes a network call, and
nothing outside the Python standard library is imported.

---

## Files

| File | What it is |
| --- | --- |
| `kpi_common.py` | Shared helpers: context plumbing, date parsing, field mapping, stats |
| `01_normalize_cim_records.py` | Action 1 - map raw CIM records onto a canonical shape |
| `02_compute_kpi_metrics.py` | Action 2 - the KPI arithmetic |
| `03_build_trend_series.py` | Action 3 - daily / weekly series for the charts |
| `04_build_dashboard_payload.py` | Action 4 - tiles, charts, tables, integrity checks |
| `05_build_kpi_record_payload.py` | Action 5 - the KPI application record payload |
| `bundle_for_turbine.py` | Inlines `kpi_common` so each action pastes as one block |
| `dist/*.turbine.py` | The generated paste-ready versions |
| `run_pipeline_local.py` | Runs all five actions on your laptop |
| `make_sample_cim_records.py` | Deterministic sample dataset generator |
| `sample_cim_records.json` | 142 sample records, including two deliberately broken ones |
| `test_kpi_playbook.py` | 50 unit tests, standard library only |

---

## Try it before touching Swimlane

```bash
cd test
python3 run_pipeline_local.py
python3 test_kpi_playbook.py
```

Output on the sample data:

```
Period      : 2026-08-09T00:00:00Z -> 2026-09-07T12:00:00Z
Parsed      : 140 records (2 skipped)

  Open Backlog       37
  New Incidents      55
  Closed             33
  Net Change         22
  Closure Rate       60.0%
  MTTR               137.6hours
  Aged over 30d      11
  SLA Compliance     36.4%

Opening 15 + New 55 - Closed 33 = Closing 37
Checks      : OK
```

To run it against a real export, save your CIM records as a JSON array and pass
them in:

```bash
python3 run_pipeline_local.py --records my_cim_export.json \
    --period last_month --field-map my_field_map.json --out result.json
```

---

## Playbook layout

```
[ Trigger: schedule, e.g. hourly or nightly ]
        |
[ Swimlane: Search Records ]  ->  your CIM application
        |   records
[ Python: 01 normalize ]      ->  records, period, summary, skipped
        |
[ If summary.has_records is false -> stop ]
        |
[ Python: 02 metrics ]        ->  metrics
[ Python: 03 trend ]          ->  trend
        |
[ Swimlane: Search Records ]  ->  KPI app, filter Period Key == 05.period_key
        |
[ Python: 04 dashboard ]      ->  dashboard, checks
        |
[ If checks.ok is false -> notify, stop ]
        |
[ Python: 05 record payload ] ->  fields, action, record_id
        |
[ If action == "update" -> Swimlane: Update Record ]
[ Else                  -> Swimlane: Create Record ]
```

Actions 2 and 3 are independent and can run in parallel.

Every script exposes `def main(context)` and returns a plain dict, which is what
a Turbine Python action expects. `get_inputs` accepts `context.inputs`,
`context["inputs"]` and a bare dict, so the same file runs in the playbook and
in the local runner.

### Pasting into Turbine

A Turbine Python action is a single code block and cannot import a sibling
file, so paste the generated bundles rather than the numbered sources:

```bash
python3 bundle_for_turbine.py --check
# then paste dist/01_normalize_cim_records.turbine.py into the first action
```

Edit the numbered sources and re-run the bundler. Never edit `dist/` by hand.

---

## Wiring the inputs

| Action | Input | Bind to |
| --- | --- | --- |
| 01 | `records` | output of the CIM Search Records action |
| 01 | `field_map` | your field overrides (see below), or leave empty |
| 01 | `closed_statuses` | your closed status values, or leave empty |
| 01 | `period` | `last_30_days`, `month_to_date`, `last_month`, ... |
| 02, 03 | `records`, `period` | outputs of action 1 |
| 03 | `granularity` | `day` or `week` |
| 04 | `metrics`, `trend` | outputs of actions 2 and 3 |
| 04 | `previous_metrics` | the metrics stored on last period's KPI record |
| 05 | `existing_record_id` | id from the KPI-app search, empty when none found |

### Field map

Action 1 is the only script that knows your CIM field names. It already tries
common variants, so start with no override and only add what it misses:

```json
{
  "created": ["Incident Opened", "createdDate"],
  "closed": ["Incident Closed"],
  "status": "Case Status",
  "priority": "Case Priority",
  "team": "Assignment Group",
  "sla_due": "SLA Target"
}
```

Values may be a single key or a list. Lookups are case-insensitive and dotted
paths reach into nested objects, so `"assignee": "details.assigned to"` works.

Only `created` is mandatory. A record without a parsable created date is put in
`skipped` with a reason instead of being dropped silently, so a mapping mistake
is visible rather than quietly shrinking your counts.

### Which records count as closed

A record leaves the backlog when its status is in `closed_statuses` **or** it
has a closed timestamp. Defaults cover closed, resolved, completed, done,
cancelled, false positive, duplicate and rejected. If a record has a closed
status but no timestamp, action 1 falls back to its modified date so the trend
line still draws it down on a real day.

---

## What each number means

| KPI | Definition |
| --- | --- |
| **New** | Created inside the period |
| **Closed** | Moved to a closed status inside the period |
| **Open backlog** | Created on or before the period end and not closed by then |
| **Opening backlog** | The same, measured at the period start |
| **Net change** | New minus closed; negative means the backlog shrank |
| **Closure rate** | Closed as a percentage of new; above 100% is burning down |
| **MTTR** | Mean hours from created to closed, over records closed in the period |
| **Backlog age** | Age of each backlog record at the period end, bucketed 0-1d, 2-3d, 4-7d, 8-14d, 15-30d, 30d+ |
| **SLA compliance** | Share of SLA-tracked records not breached; an open record breaches once its due date passes |

Open backlog is measured **at the period end**, not "right now". The aging
buckets, the priority and team breakdowns and the oldest-open table all describe
that same period-end backlog. Those differ from today's view when you re-run a
past period, and measuring at the end is what makes the trend line, the tiles
and the tables agree with each other.

### The check that catches a bad mapping

Action 4 asserts the backlog identity:

```
opening backlog + new - closed == closing backlog
```

If it does not hold, `checks.ok` is false and `checks.failures` says so in
words. Branch the playbook on it. A mismatch almost always means `created` or
`closed` is mapped to the wrong field, and it is much better to see that as a
failed check than as a wrong tile.

---

## The KPI application

Keep **one record per period**, keyed by `period_key` (`2026-08-01_2026-08-31`).
Action 5 emits that key plus `action`, which is `update` when the preceding
search found an existing record and `create` otherwise. Re-running a period
therefore corrects the record instead of duplicating it.

Suggested fields, all produced by action 5:

| Field | Type |
| --- | --- |
| Period Key, Run Status | text |
| Period Start, Period End, Generated At | date/time |
| New Incidents, Closed Incidents, Open Backlog, Opening Backlog, Net Change | numeric |
| Closure Rate %, SLA Compliance % | numeric |
| MTTR Hours, Median Resolution Hours, Avg Backlog Age Days, Oldest Open Days | numeric |
| Aged Over 30d, Unassigned Open, SLA Breached Open | numeric |
| Dashboard JSON, Trend JSON | long text |

Rename any of them with the `field_names` input rather than editing the script.

`Dashboard JSON` holds the whole rendered payload, so the dashboard reads one
record and needs no further lookups. Because history lives in these records,
period-over-period deltas come from feeding last period's metrics into action 4
as `previous_metrics`.

### The dashboard payload

`dashboard.tiles` carries one entry per tile with `value`, a `delta`
(`value`, `pct`, `direction`) and an `intent` of `higher_is_better`,
`lower_is_better` or `neutral`, so the UI colours a rising MTTR red and a rising
closure rate green without hard-coding rules.

`dashboard.charts` is ready to bind: a line chart of new vs closed vs backlog, a
bar chart of backlog age, a donut of open by priority, a bar of new by source.
Each has `x` and `series`, and action 3 also emits flat `labels` / `new` /
`closed` / `backlog` arrays for widgets that want them raw.

`dashboard.tables` gives open by team, open by assignee, and the oldest open
records as `columns` plus `rows`.

---

## Notes

- All timestamps are handled in UTC and emitted as ISO-8601 with a `Z`.
- Pass `now` to pin the "as of" moment. The tests and the sample data rely on
  it, and it makes a re-run of a past period reproducible.
- The trend series is capped at `max_points` (default 180) so a mis-set period
  cannot build a huge payload.
- Large result sets: page the CIM search and concatenate before action 1, or
  narrow the period. The scripts are O(n) over records and hold everything in
  memory.
