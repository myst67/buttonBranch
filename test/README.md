# CIM Daily KPI Playbook

Three Turbine Python actions that turn CIM records into one KPI record per day.
Driven by a cron trigger, no external API calls, standard library only.

| File | Playbook action |
| --- | --- |
| `A_normalize_cim_records.py` | Normalize CIM records and classify the three bases |
| `B_compute_kpi_metrics.py` | Compute the metric catalog |
| `C_build_daily_record.py` | Build the daily record payload and dashboard |

See `PLAN.md` for the metric catalog, the field mapping and the sprint breakdown.

Each script carries the same helper block at the top, marked by a banner and
byte-identical across all three. If your tenant supports a reusable Python
component, lift that block out of all three and reference the component instead.

---

## Playbook flow

```
[ Cron trigger: daily at 11:55 ]
        |
[ Search Records ]  ->  CIM application
        |   records
[ Python: Script A ]          ->  records, period, coverage, summary
        |
[ If summary.has_records is false -> stop ]
        |
[ Python: Script B ]          ->  metrics, coverage
        |
[ Search Records ]  ->  KPI app, filter Snapshot Date == B.metrics.snapshot_date
        |   record id, or nothing
[ Python: Script C ]          ->  fields, action, record_id, dashboard
        |
[ If action == "update" -> Update Record ] [ Else -> Create Record ]
```

---

## The daily window

Set the cron schedule and `period_mode` together. They have to agree, or the
record will describe a different span than you expect.

| Cron | `period_mode` | The record covers |
| --- | --- | --- |
| `55 23 * * *` | `full_today` | the whole day, written five minutes before midnight |
| `55 11 * * *` | `yesterday` | the whole previous day |
| any | `today` | midnight up to the moment the job runs, a partial day |

**If 11:55 means 11:55 AM, do not use `today`.** It would store a half day of
new and closed counts under a full day's date, and the daily trend would read as
though volume had halved. Use `yesterday` at that hour, which always records a
complete day. If 11:55 means 23:55, use `full_today`.

Confirm which timezone your Turbine cron evaluates. The scripts work in UTC
throughout, so a tenant clock offset from UTC shifts which records land in which
day. Pass `now` if you need to pin the run time.

To backfill or correct a past day, run the playbook with `period_mode` set to
`date` and `snapshot_date` set to that day.

---

## Idempotency

The record is keyed on `snapshot_date`. Script C emits `period_key` (the date)
and `action`, which is `update` when the KPI-app search found that day's record
and `create` when it did not. A re-run on the same day therefore corrects the
day's record instead of adding a second one.

---

## Inputs

Script A carries all the configuration. B and C only need A's outputs.

| Input | Purpose |
| --- | --- |
| `records` | output of the CIM Search Records action |
| `period_mode` | `today`, `full_today`, `yesterday` or `date` |
| `snapshot_date` | the day to run, when re-running a past day |
| `now` | pin the run time, for reproducible re-runs |
| `field_map` | canonical name to your CIM key(s), when a column is renamed |
| `closed_statuses` | statuses meaning the record left the backlog |
| `resolved_statuses` | the subset counting as genuinely resolved |
| `false_positive_values` | values marking a false positive |
| `false_positive_fields` | which fields carry the verdict |
| `p1p2_values` | severity values treated as P1/P2 |
| `record_hierarchy_filter` | keep only parent rows, or only child rows |
| `suspect_minutes_over` | duration above which a value is treated as bad data |

Only `records` is required. Everything else has a default, and the defaults are
listed at the top of the helper block in each script.

---

## What gets stored

76 fields per day. Count and rate metrics store one field each; value metrics
store four (`Avg`, `Sum`, `P90`, `Count`), so the app can chart a mean without
unpacking JSON.

A metric whose source field does not exist on the CIM record is stored as
**null with a reason, never 0**. A missing field can therefore never read as a
good score. Those metrics still write their full set of columns, so the app
schema does not change shape on the day the field is added.

`Coverage JSON` travels with each record and names which fields resolved, how
many rows were skipped and why, how many suspect durations were dropped, and
every unavailable metric with its reason. Chart it to grey out a metric rather
than drawing it as zero.

`Dashboard JSON` holds the tiles, the breakdowns and the oldest-open table, so
the dashboard reads one record and needs no further lookups.

---

## Data handling

No CIM record data, exported rows, screenshots or live field values belong in
this repository. Column names appear because the field map needs them. Generate
any dry-run sample synthetically, outside the repo.
