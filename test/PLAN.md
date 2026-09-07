# CIM KPI Playbook - Build Plan

Target: a Turbine playbook that reads CIM records (fetch already exists), computes
the metric catalog below, and writes **one KPI record per day** into the existing
KPI application, driven by a cron trigger at 11:55.

Constraints this plan is built around:

- No external API calls. Every number is computed inside the playbook.
- Each script is standalone by default. A Turbine Python action is a single code
  block, so the helper block is repeated verbatim at the top of all three
  scripts. See *Shared helper* below if your tenant supports reusable components.
- The KPI application already exists, so the scripts produce a flat field payload
  that Swimlane's native Create/Update Record action writes.

---

## Data handling

This repository holds code and specification only. No CIM record data, no
exported rows, no screenshots and no field values from the live system are
committed here, and none should be added. Column names appear because the field
map needs them; record contents do not appear anywhere.

When a sample is needed for a dry run, generate a synthetic one outside the
repository rather than exporting real records.

---

## Playbook flow

```
[ Cron trigger: daily at 11:55 ]
        |
[ Search Records ]  ->  open: Status NOT IN closed, no date filter
[ Search Records ]  ->  new: created today
[ Search Records ]  ->  closed: closed today
        |   open_records + new_records + closed_records
[ Python: Script A - normalize and classify ]
        |   records, period, coverage, summary
[ If summary.has_records is false -> stop ]
        |
[ Python: Script B - compute the metric catalog ]
        |   metrics, coverage
[ Search Records ]  ->  KPI app, Snapshot Date == metrics.snapshot_date
        |
[ Python: Script C - build the storage payload ]
        |   fields, action, record_id
[ If action == "update" -> Update Record ] [ Else -> Create Record ]
```

Three Python actions. Script A owns the field mapping, Script B owns the
arithmetic, Script C owns the storage shape. That split means a CIM field rename
only ever touches Script A.

The backlog search is not optional. A one-day slice cannot measure the open
backlog, because backlog is a stock rather than a flow. Where the fetched data
cannot support a base, Script B stores those metrics as null with a reason
instead of computing them from a partial fetch.

---

## Shared helper

Worth doing if your Turbine tenant exposes reusable Python components or a global
script asset. It is one helper block (date and duration parsing, field mapping,
the stats functions) that all three scripts need, so sharing it means a parsing
fix is made once instead of three times.

The plan does not depend on the answer. Each script carries that helper block at
the top, byte-identical across the three, marked by a banner comment:

```
# ===== shared helper block - keep identical across scripts A, B, C =====
...
# ===== end shared helper block =====
```

If sharing turns out to be available, deleting the block from each script and
referencing the shared component is a delete, not a rewrite. If it is not, the
scripts already work as they stand. Confirming which way your tenant works is
part of Sprint 0.

---

## Field mapping from your CIM table

| Spec field | Your column | Notes |
| --- | --- | --- |
| `created_at` | First Created | long-form display timestamps are parsed |
| `updated_at` | Last Updated | |
| `closed_at` | Time Resolved | falls back to Time of Remediation |
| `current_state` | Status | full value vocabulary needed, see Sprint 0 |
| `assigned_to` | Current Owner | drives `distinct_agents` |
| `priority` (P1/P2) | Severity | `Critical` + `High` treated as P1/P2 |
| false positive | Classification, Manual Verdict | both fields are read |
| first acknowledge | Time to Acknowledge (+ Minutes) | replaces the history lookup |
| analyze duration | Time to Analyze (+ Minutes) | see data quality below |
| remediate duration | Time to Remediate | see data quality below |
| `reassign_count` | **absent** | blocks 3 metrics |
| `risk_score` | **absent** | blocks 4 metrics |
| `sla_breached` | **absent** | blocks 3 metrics |
| history events | **absent** | blocks 2 metrics |
| `state_changed_at` | **absent** | 1 metric falls back to Last Updated |

Dimensions also available for breakdowns: Type, Record-hierarchy, Threat Type,
Alert Categories, MITRE ATT&CK Technique, Escalated?.

---

## Metric coverage

23 of the 34 metrics compute from the columns you have today. 11 are blocked on
fields that do not exist yet. **Blocked metrics are stored as null with a stated
reason, never as 0**, so a missing field can never read as a good score.

### Computable now (22 exact, 1 proxy)

| Metric | Base | Computed from | Sprint |
| --- | --- | --- | --- |
| `open_inc_total` | open | COUNT | 2 |
| `open_more_than_five_days` | open | age at period end > 5d | 2 |
| `open_more_than_thirty_days` | open | age at period end > 30d | 2 |
| `stale_open_no_update_5d` | open | Last Updated older than 5d | 2 |
| `distinct_agents` | open | COUNT(DISTINCT Current Owner) | 2 |
| `new_inc_total` | new | COUNT | 2 |
| `new_inc_p1p2_count` | new | Severity in Critical/High | 2 |
| `closed_inc_total` | closed | COUNT | 2 |
| `closed_inc_not_resolved` | closed | Status not in closed/resolved | 2 |
| `closed_inc_same_day_open` | closed | DATE(closed) = DATE(created) | 2 |
| `false_positive_count` | closed | verdict fields | 2 |
| `false_positive_high_risk_count` | closed | verdict + Severity | 2 |
| `true_positive_count` | closed | resolved and not FP | 2 |
| `fp_rate` | closed | % | 2 |
| `same_day_close_rate` | closed | % | 2 |
| `age_open_inc` | open | days since First Created | 3 |
| `age_last_update_open_inc` | open | days since Last Updated | 3 |
| `oldest_open_age` | open | MAX(age days) | 3 |
| `duration_closed_inc` | closed | (closed - created) hours | 3 |
| `duration_false_positive_closed_inc` | closed | same, FP only | 3 |
| `mttr_hours` | closed | duration where truly resolved | 3 |
| `mtta_hours` | new | **Time to Acknowledge** | 3 |
| `state_dwell_hours` | open | *proxy:* hours since Last Updated | 3 |

`mtta_hours` is better than the spec asks for. The spec derives it from the first
`assigned`/`state_changed` history event; your table already stores the measured
value, so no history feed is needed for this one.

`state_dwell_hours` is the one proxy. Without a state-change timestamp, "hours in
the current state" becomes "hours since last update", which is the same number
only when the last update was the state change. Flagged as a proxy in the output.

### Blocked, pending new fields

| Metric | Needs | Sprint |
| --- | --- | --- |
| `reassign_count_open_inc` | reassign count field | 5 |
| `closed_inc_on_first_attempt` | reassign count field | 5 |
| `first_close_rate` | reassign count field | 5 |
| `reassigned_open_count` | assignment history | 5 |
| `reassign_count_hist_open` | assignment history | 5 |
| `risk_score_closed_inc` | risk score field | 5 |
| `risk_score_false_positive_inc` | risk score field | 5 |
| `risk_score_high_risk_fp_inc` | risk score field | 5 |
| `sla_breached_count` | SLA breach flag | 5 |
| `sla_breach_rate` | SLA breach flag | 5 |
| `sla_compliance_rate` | SLA breach flag | 5 |

Three fields on the CIM record (reassign count, risk score, SLA breached) unblock
9 of the 11. The remaining 2 need an assignment history feed.

---

## Base definitions

Implemented exactly as specified:

```
open    created_at <= end
        AND (closed_at IS NULL OR closed_at > end)
        AND NOT (closed_at IS NULL AND closed_state)

new     created_at BETWEEN start AND end

closed  closed_state AND COALESCE(closed_at, updated_at) BETWEEN start AND end
```

Note the asymmetry, which is deliberate and worth keeping: `open` tests the raw
`closed_at`, so a record in a closed state with no timestamp is excluded from
open entirely, while `closed` catches that same record through `updated_at`.

---

## Data quality findings

Two things to resolve before trusting the duration columns:

1. **The `... Minutes` columns do not all use the same unit.** At least one of
   them carries a magnitude consistent with milliseconds rather than minutes,
   while another agrees with its text column. Confirm the unit of each before
   trusting it. The scripts defend against this in two ways: they read the text
   column first, which also keeps the sub-minute precision the integer column
   truncates, and they treat any duration above one year as a bad value, excluded
   from the averages and counted in the coverage report rather than silently
   wrecking the mean.

2. **A zero duration alongside an empty timestamp is a default, not a
   measurement.** Where a duration column reads 0 but its paired timestamp is
   blank, the value is treated as null rather than as an instant remediation.

---

## Sprints

### Sprint 0 - confirm the vocabulary  [OPEN, needs your answers]

No code. Five answers that change the arithmetic:

1. The full list of **Status** values, and which of them mean closed.
2. The values **Classification** and **Manual Verdict** take, and which mean false
   positive.
3. Whether **Severity** is the right stand-in for P1/P2, and whether P1/P2 is
   Critical+High or Critical only.
4. Whether metrics should count **parent records only**, child signals only, or
   both. Where the table mixes a parent record with its child signals, counting
   every row inflates the incident totals.
5. Whether **Time Resolved** or **Time of Remediation** is authoritative for
   closure.
6. Whether your tenant supports a **reusable Python component or global script**,
   which decides whether the helper block is shared or repeated per script.

Sprints 1 to 4 are built and run on documented defaults, so these answers are
corrections rather than blockers. Items 1, 2 and 4 will change the numbers.
Item 7 below is new and decides the daily window.

7. Whether the 11:55 cron is **11:55 AM or 11:55 PM**, and which timezone the
   trigger evaluates in. At 11:55 AM the run must use `period_mode: yesterday`
   to record a complete day; at 23:55 it uses `full_today`.

### Sprint 1 - Script A, normalize and classify  [DELIVERED]

Deliverable: `A_normalize_cim_records.py`.

- Maps your columns onto canonical names, configurable via a `field_map` input.
- Parses dates, compound durations (`Xh Ym Zs` text and numeric), yes/no fields.
- Computes `is_closed_state`, `is_resolved_state`, `is_false_positive`, `is_p1p2`.
- Applies the three base conditions and tags each record `in_open`, `in_new`,
  `in_closed`.
- Emits a `coverage` block: which canonical fields were found, which are missing,
  how many rows were skipped and why, how many suspect durations were dropped.

Done when: every record is classified, records without a parsable First Created
are reported rather than dropped, and the coverage block names the missing fields.

### Sprint 2 - Script B part 1, counts and rates  [DELIVERED]

Deliverable: the count and rate half of `B_compute_kpi_metrics.py` (15 metrics).

Done when: the three base counts satisfy `opening + new - closed = closing` on a
real extract, and `fp_rate`, `same_day_close_rate` agree with their numerators
and denominators.

### Sprint 3 - Script B part 2, durations and value metrics  [DELIVERED]

Deliverable: the value half of the same script (8 metrics).

Each value metric stores `count`, `sum`, `avg`, `min`, `max`, `p50`, `p90`, so
one stored metric answers both "sum" and "mean" without a re-run. `count` is how
many records carried the value, which is not the size of the base when a column
is sparsely filled.

Done when: durations round-trip against a hand-checked record, the suspect-value
guard is exercised, and `mtta_hours` matches the Time to Acknowledge column.

### Sprint 4 - Script C, storage and dashboard  [DELIVERED]

Deliverable: `C_build_storage_payload.py`.

- Flattens the catalog to one field per stored number (value metrics expand to
  `<metric>_avg`, `<metric>_sum`, `<metric>_p90`).
- Emits `period_key` (`2026-08-01_2026-08-31`) so a re-run of a period updates
  its record instead of duplicating it, plus `action` = create or update.
- Emits the dashboard payload (tiles, trend, breakdowns by Severity, Threat Type,
  MITRE technique, Current Owner).

Done when: a re-run of the same period updates one record, and every blocked
metric is stored as null with its reason rather than 0.

### Sprint 5 - unblock the remaining 11

Not a code sprint until the fields exist. Add reassign count, risk score and SLA
breached to the CIM record; the scripts already reserve their names and will start
reporting them as soon as the field map resolves. Assignment history is the larger
piece and only affects 2 metrics, so it is last.

---

## Storage shape

One KPI record per day, keyed on Snapshot Date. 76 fields, all produced by
Script C:

| Group | Fields |
| --- | --- |
| Key | Snapshot Date, Period Start, Period End, Run Status |
| Counts | one numeric field per count metric (15) |
| Rates | one numeric field per rate metric, stored as a percentage |
| Values | `Avg`, `Sum`, `P90`, `Count` per value metric |
| Payload | Dashboard JSON, Coverage JSON |

Coverage JSON is stored alongside the numbers so a chart can grey out a metric
that was never computable in that period, instead of drawing it as zero.
