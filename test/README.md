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

## If the action shows no output

The scripts **run as soon as the file is executed**, whether or not the sandbox
supplies a `context`. That matters for diagnosis: with no inputs bound the counts
come back as zero, so a result full of zeros proves the script ran and points at
the input binding, while a result of `{}` means the file never executed.

Inputs are found three ways: a `context` object or dict, a bare `inputs` dict, or
each input injected as its own global variable.

The result is then published four ways, one of which your tenant will read:

* returned from `main(context)`
* exposed as a module-level `outputs`
* written to `context.outputs`
* aliased as `script`, `run`, `execute` and `handler` for tenants that expect a
  differently named entry function

The scripts also avoid syntax newer than Python 3.6, so an older sandbox still
compiles them.

**To find out which convention your tenant uses**, paste
`probe_turbine_contract.py` into a Python action, add one input named `records`
bound to any search result, and run it once. Whatever the run shows tells you
the answer: the `probe_via` value names the channel that reached the output
panel, `inputs_read_from` names how inputs arrived, and `first_record_keys`
lists the exact column names your CIM search returns, which is what the field
map has to match. It is a one-off check, not part of the playbook.

`OUTPUT_FIELDS.md` lists every output key each script returns, with the field
type that fits.

If an action still produces nothing, work through these in order:

1. **Does the action's Inputs panel show `{}`?** Then nothing was passed in.
   Define an input named `records` on the action and map it to the search
   result. This is separate from the output problem and has to be fixed too.
2. **Are the outputs declared?** Some tenants only surface output keys that are
   declared in the action's output schema. Add the keys you want to map, for
   example `open_inc_total`, spelled exactly as the script returns them.
3. **Is the input named `records`?** The script reads its inputs by name. An
   input bound correctly but named `record` or `results` reads as empty, and the
   script returns zeros rather than failing.
4. **Check `coverage` in the result.** `rows_fetched` tells you whether the
   records arrived at all. Zero means the binding, not the script.
5. **Was the whole file pasted?** Each script is one file, helper block included.
   Pasting only the part below the helper banner leaves the helpers undefined.

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
