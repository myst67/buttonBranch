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
        +-- [ Search Records ] -> Status NOT IN closed, NO date filter
        |         |   open_records
        +-- [ Search Records ] -> created today
        |         |   new_records
        +-- [ Search Records ] -> closed today
                  |   closed_records
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

## Two searches, not one

A one-day search cannot measure the open backlog. Backlog is a stock, not a
flow: it is every record still open today regardless of when it was created, so
a slice of today's rows has no way to see a case opened three weeks ago. Fed a
day slice, the naive answer is not slightly off, it collapses. In a test where
the true backlog was 4 records with the oldest at 68 days, a today-only search
reported 1 record with the oldest at 0.67 days.

So run **one search per base** and pass each to its own input:

| Search | Filter | Feeds |
| --- | --- | --- |
| Open | Status NOT IN your closed statuses, **no date filter** | `open_records` |
| New | created within the day | `new_records` |
| Closed | closed within the day | `closed_records` |

Script A merges them and removes the overlap, keeping the copy with the later
Last Updated. A record found by two searches keeps both memberships, which is
normal: a case opened today and still open is both new and open.

**Open means the standing backlog, not "opened today".** The open search must
have no date filter. Filtered to the current day it returns only today's open
records, which is a different and much smaller number. If you want "opened today
and still open" as well, that is `new_inc_total` minus the same-day closes, not
`open_inc_total`.

### The search and the spec are cross-checked

Where a base has its own search, that search is the authority, since it is what
the CIM app itself considers open, new or closed. Script A still evaluates the
date conditions and reports any gap in `coverage.scope.base_disagreement`.

A gap is worth investigating. It usually means a search filter and the metric
definition have drifted apart, for example a closed search returning records
closed before today, or an open search that carries a date filter it should not.
Set `base_assignment` to `condition` to make the date conditions authoritative
instead.

### If you only wire one search

Script A works out what the fetched data can support and reports it in
`coverage.scope`. Script B then stores every metric that data cannot answer as
**null with a reason**, rather than computing a number from a slice that cannot
support it. With a single day search, that suppresses the 12 open-base metrics
and tells you to add the backlog search.

Auto-detection never concludes that a search was full. A day search filtered on
last-updated returns records created months ago, so a full search and a day
slice look identical from the data alone, and guessing wrong would silently
report a backlog computed from a partial fetch. If your search genuinely has no
date filter, declare it by setting `data_scope` to `full`.

| `data_scope` | Open base | Closed base |
| --- | --- | --- |
| `full` | measured | measured |
| `day_plus_backlog` | measured | measured |
| `day_updated` | null + reason | measured |
| `day_created` | null + reason | null + reason |

`day_created` suppresses the closed base too, because a search filtered on
created date cannot see a record opened last week and closed today.

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

## Day-on-day backlog

The backlog recurrence is:

```
open_today = open_yesterday + new_today - closed_today
```

**Closures have to be subtracted.** Carrying yesterday's backlog forward and
only adding today's new records makes the number rise every day and never fall.
On a normal ten-day stretch that reads 60 against a true backlog of 12, and the
gap keeps widening.

You do not actually need the recurrence to know the backlog. The open search
measures it directly every day, which is why `open_inc_total` comes from that
search. The recurrence is used as a **check**: pass yesterday's stored
`Open Inc Total` into Script B as `previous_open_backlog`, with yesterday's
`Snapshot Date` as `previous_snapshot_date`, and each run reconciles the two.

| Stored field | Meaning |
| --- | --- |
| `Open Inc Total` | measured directly by the open search |
| `Expected Open Backlog` | previous + new - closed |
| `Backlog Drift` | measured minus expected, normally 0 |
| `Is Seed Day` | true on the first run, which seeds the series |
| `Days Since Previous` | 1 on a healthy series |
| `Series Continuous` | false when a day was missed |

On the first run, 1 Sept in your case, omit `previous_open_backlog`. That day is
the seed: the measured backlog is stored as-is and `Is Seed Day` is true. Every
day after that is checked against it.

A non-zero drift is worth a look. It usually means a record was closed
retroactively, a status changed outside the window, or a search missed rows. It
is reported rather than smoothed away.

If the cron misses a day, the carry-forward is not valid across the gap, so
`Series Continuous` goes false and no expected value is produced. Backfill the
missing days with `period_mode: date` and `snapshot_date` set to each one.

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
| `open_records` | the open search, no date filter (alias `backlog_records`) |
| `new_records` | the created-today search |
| `closed_records` | the closed-today search |
| `records` | a single mixed search, if not using per-base searches |
| `base_assignment` | `auto` (trust each search), `search`, or `condition` |
| `previous_open_backlog` | yesterday's `Open Inc Total`, omit on the first run |
| `previous_snapshot_date` | yesterday's `Snapshot Date` |
| `data_scope` | `auto`, `full`, `day_plus_backlog`, `day_updated`, `day_created` |
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

Pass whichever searches you have. Without an open search, and without declaring
`data_scope: full`, the open-base metrics are suppressed rather than guessed.
Everything else has a default, listed at the top of the helper block.

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
