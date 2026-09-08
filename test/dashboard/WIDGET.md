# Open Incident Trend widget

A Turbine report widget: the open backlog over the last X days, with the
breakdown of the latest day. One file, paste it into a custom widget.

Nothing is fetched and nothing is loaded from a CDN. The chart is inline SVG,
so there is no library to install and no build step.

---

## Setup

1. Create a report on the daily metrics application. Include the
   `Snapshot Date` field and the `open_inc_total` field.
2. Add a custom widget to that report and paste in
   `open-incident-trend.widget.js`.
3. Save and open it.

## Why a widget renders blank

Four things the platform requires. Break any one and the preview is empty with
no error:

1. **Use the versioned import specifier.** `'@swimlane/swimlane-element@2'`, not
   the bare package name.
2. **The class must be anonymous.** `export default class extends SwimlaneElement`.
3. **Never call `customElements.define`.** The platform registers the default
   export; defining it in the file stops it rendering.
4. **`static get styles()` returns an array** beginning with `super.styles`.

Re-render when the data lands, which is after the first render:

```js
firstUpdated() { super.firstUpdated(); if (this.report) this.requestUpdate(); }
updated(changed) {
  super.updated(changed);
  if (changed.has('report') && this.report) this.requestUpdate();
}
```

## Configuring the report

**Use a plain column report, not an aggregated one.**

| Do | Don't |
| --- | --- |
| Add the date field and `open_inc_total` as columns | Add a measure with "Count of" |
| Leave Group By empty | Group By the date or the metric |

A "Count of" measure counts *records*, not the values inside them, so a day
where the backlog was 148 contributes 1. It is also the only aggregation
Swimlane offers on a text field, since text cannot be summed. That is why the
trend needs raw rows.

The widget still reads an aggregated report where it can: if the groups carry
the stored JSON it recovers the real values, and if they only carry counts it
plots the counts and says so. But a plain column report is the shape that works
without caveats.

## The data contract

A report widget receives `this.report`:

| Property | What it holds |
| --- | --- |
| `rawData` | the report's rows, one object per record |
| `data` | the aggregated series the built-in charts draw |
| `query` | the dimensions and measures configured on the report |

This widget reads `rawData`, because a timeline needs one point per day and its
own arithmetic. It falls back to `data[0].series` when the report exposes no raw
rows, handling both the case where the group label is a date and the case where
the report groups by the metric field and the label is the stored JSON.

Raw rows may be keyed by **field id** rather than field key. The widget resolves
either, using `contextData.application.fields` to map key to id.

`this.contextData` carries `application`, `currentUser`, `origin` and `token`.

## What it reads

`open_inc_total` on each row, in whichever form it is stored:

| Stored as | Handled |
| --- | --- |
| JSON text, `{"value": 148, "breakdown": [...]}` | yes |
| an object, from a `metrics` field | yes |
| a bare number | yes, though then there is no breakdown |

The day comes from `snapshot_date`, `Snapshot Date`, `Snapshot Key`,
`snapshotDate` or `date`, whichever the row carries.

## What it shows

- The latest value as the headline, with the change across the window. Rising
  backlog is red, falling is green.
- A line of the backlog over the window, with a crosshair on hover and the last
  value labelled at the line end.
- The breakdown of the latest day as bars, with a dimension picker when the
  metric carries more than one.
- A "Show the numbers" table, so the values are readable without the chart.

The window control offers 7, 14, 30, 60 and 90 days.

## Charting a different metric

Change two constants at the top:

```js
const METRIC = 'closed_inc_total';
const METRIC_LABEL = 'Closed incidents';
```

That works for any count metric. For a distribution such as `mttr_hours` the
value is an object rather than a number; the widget reads its `avg`, which is
the right headline, but a sum over the window would need the weighted-mean rule
from `metricRules.js`.
