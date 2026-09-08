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

## On the first run, check the data property

Turbine passes report data to a widget through a property on the element, and
the name of that property is not something the file can know in advance. So it
tries the likely names, and if none of them hold report rows it renders a panel
listing the properties the element actually has, with the shape of each.

Read the name off that panel and set it at the top of the file:

```js
const DATA_PROPERTY = 'reportData';   // whatever the panel showed
```

Leave it `null` to keep auto-discovering. Discovery is tested against eight
shapes, including `reportData` as a plain array, `report.results`,
`data.records`, `report.raw.results`, and a property under a name it has never
heard of.

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
