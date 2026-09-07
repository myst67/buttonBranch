# Storing the daily metrics and building the dashboard

One record per day, rolled up in the widget. This document covers the
application design, the field list, and the aggregation rules that make weekly,
monthly, quarterly and yearly views correct.

---

## The rule that shapes everything

**Most metrics cannot be rolled up by averaging the daily values.** Averaging
daily rates or daily means is wrong whenever daily volume varies, which it
always does.

Two days of closures, 100 with 10 false positives and 2 with 1:

| | Averaging the daily values | Recomputed from totals |
| --- | --- | --- |
| FP rate | 30.0% | **10.8%** |
| MTTR | 51.0 h | **3.9 h** |

Averaging overstates the FP rate by 3x and MTTR by 13x. On a quiet Sunday with
two closures, one bad one moves the monthly number more than a hundred weekday
closures do.

So each metric has to declare how it combines, and the record has to store
enough to recompute rather than re-average. That is why every value metric
stores its **sum and count**, not just its average.

---

## Storage model

One Swimlane application, one record per day, keyed on `Snapshot Date`.

| | |
| --- | --- |
| Grain | one day |
| Key | `Snapshot Key` (text, e.g. `2026-09-07`), unique |
| Volume | 365 records a year, trivial for Swimlane and for a widget to fetch |
| Written by | the three metric scripts, through Create or Update Record |
| Re-run | same date updates that day's record, never adds a second |

Do **not** store one record per metric. A row per day per metric multiplies the
record count by 40 and makes every widget query a join.

Do **not** store weekly or monthly records as well, at least not at first. They
are derived, so they can go stale and disagree with the daily rows they came
from. Roll up in the widget. Revisit only if a yearly view feels slow, and see
*Precomputed roll-ups* below.

---

## Fields

Two representations of the same numbers, because they serve different consumers.

### Typed fields, for Swimlane itself

Swimlane's own search, filters, reports and column sorting work on typed fields,
not on JSON. Give every metric a numeric field:

| Group | Fields |
| --- | --- |
| Key | Snapshot Key (text, unique), Snapshot Date (date), Run Status (text) |
| Flow counts | New Inc Total, New Inc P1P2 Count, Closed Inc Total, Closed Inc Not Resolved, Closed Inc Same Day Open, False Positive Count, False Positive High Risk Count, True Positive Count |
| Stock counts | Open Inc Total, Open More Than Five Days, Open More Than Thirty Days, Stale Open No Update 5d, Unassigned Open Count, Distinct Agents |
| Distributions | for each: `<name> Avg`, `<name> Sum`, `<name> Count`, `<name> P90` |
| Rates | FP Rate, Same Day Close Rate, True Positive Rate |
| Continuity | Expected Open Backlog, Backlog Drift, Is Seed Day, Series Continuous |

**Store `Sum` and `Count` for every distribution.** Without them a monthly MTTR
cannot be computed correctly from daily rows, and `Avg` alone is a dead end.

### One JSON field, for the React widget

`Metrics JSON` holds the whole `metrics` object from the script, breakdowns
included. The widget parses this and needs nothing else, so adding a metric or a
breakdown dimension later does not mean adding fields.

Keep both. The typed fields make the data usable inside Swimlane; the JSON makes
the widget simple.

---

## Aggregation rules

`rollup.js` in this folder implements these. Every metric falls into one of five
kinds.

| Kind | Rolls up by | Metrics |
| --- | --- | --- |
| **Flow** | sum, or mean per day when the dropdown says "avg" | new, closed, false positives, true positives, same-day closes, SLA breaches |
| **Stock** | the **last** day in the period | open backlog, aged buckets, stale, unassigned, distinct agents |
| **Peak** | max | oldest open age |
| **Distribution** | weighted mean: total sum over total count | ages, dwell, MTTA, MTTR, durations, risk scores |
| **Rate** | recomputed from the period's own numerator and denominator | FP rate, same-day close rate, true positive rate, first close rate, SLA rates |

Three consequences worth internalising:

**Backlog never sums.** Thirty daily backlog readings added together is a
meaningless number roughly thirty times too large. A month's backlog is the
backlog on its last day. If you want the shape of the month, chart the daily
series instead of reducing it to one figure.

**`distinct_agents` cannot be rolled up from counts.** Five agents on Monday and
five on Tuesday might be five people or ten. Taking the last day is an
approximation. If a true monthly figure matters, store the day's owner list in
`Metrics JSON` (it is already in the `assigned_to` breakdown) and union the
labels in the widget.

**Averages need their weights.** A weighted mean is total sum over total count,
which is why `Sum` and `Count` are stored per distribution.

---

## The widget

```
[ Swimlane app: 365 daily records ]
        |  fetch once
[ React widget ]
        |
   rollup(records, grain, mode)      grain: day|week|month|quarter|year
        |                            mode:  sum|avg   (flow metrics only)
   +-- KPI tiles      <- bucket.metrics.<name>.value
   +-- Trend chart    <- series(records, 'open_inc_total', grain)
   +-- Composition    <- mergeBreakdown(records, 'open_inc_total', 'severity')
```

`rollup.js` exports:

| Function | Purpose |
| --- | --- |
| `rollup(records, grain, mode)` | one bucket per period, each with rolled-up metrics |
| `series(records, name, grain, mode)` | one metric as `{period, value}` for a chart |
| `mergeBreakdown(records, name, dimension)` | breakdown merged across the period |
| `periodKey(date, grain)` | the bucket a date belongs to |
| `ROLLUP_RULES` | the rule per metric, so the widget can label what it did |

Fetch the daily records once and roll up in the browser. 365 records is a small
payload, changing the dropdown is then instant with no refetch, and the daily
rows stay the single source of truth.

### Timeline dropdown

The dropdown sets two things, and they are independent:

* **Grain**: day, week, month, quarter, year.
* **Mode**: sum or avg, which only affects flow metrics. A stock metric ignores
  it, since "average backlog" and "backlog" are different questions, and a rate
  is always recomputed.

Label the tiles with what was done. "Closed 2,140 (sum, Sep)" and "Closed 71/day
(avg, Sep)" are both useful; an unlabelled number is not.

---

## Precomputed roll-ups, if you ever need them

Only if a yearly view gets slow. Add a `Period Type` field with values Day,
Week, Month, Quarter, Year, keep every row in the same application, and have a
second playbook write the non-daily rows using the same rules as `rollup.js`.

The widget then filters on `Period Type` instead of aggregating. The cost is
that derived rows can go stale and disagree with the daily rows behind them, so
only take it on when the payload actually hurts.

---

## Backfill and gaps

A missed day leaves a hole that a monthly sum silently absorbs, and a stock
metric taking "the last day" will reach further back than expected.

The scripts already detect this: `series_continuous` goes false and
`days_since_previous` is greater than 1. Store both. Backfill a missing day by
running the playbook with `period_mode: date` and `snapshot_date` set to it.

In the widget, `bucket.days` is how many daily records a period actually
contained. Compare it with the calendar length of that period and mark the tile
when they differ, rather than presenting a short month as though it were whole.
