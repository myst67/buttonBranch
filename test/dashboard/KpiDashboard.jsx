/**
 * CIM KPI dashboard - a Turbine custom React widget.
 *
 * Give it the daily records from the metrics application; it does the rest.
 * No chart library: the plots are inline SVG, so there is nothing to install
 * and nothing to load from a CDN.
 *
 *   <KpiDashboard records={records} />
 *
 * `records` may be either shape the application stores:
 *   { snapshot_date, metrics: { open_inc_total: { value, ... } } }
 *   { 'Snapshot Date': '2026-09-07', open_inc_total: '{"value":42}' }
 *
 * Metric semantics live in metricRules.js, the windowing in timeline.js and the
 * arithmetic in aggregate.js. This file is presentation.
 */

import React, { useMemo, useState } from 'react';
import { PRESETS, applyWindow, shortLabel } from './timeline.js';
import { RULES, ruleOf, INTENT, respondsToMode } from './metricRules.js';
import { adaptRecords, bucketize, total, delta } from './aggregate.js';

/* Categorical slots 1-3, validated for both modes on the all-pairs list.
   Three series is the cap for this palette; a fourth would fail the floors. */
const CSS = `
.kpi-root {
  color-scheme: light;
  --surface-1: #fcfcfb; --plane: #f9f9f7;
  --ink-1: #0b0b0b; --ink-2: #52514e; --ink-muted: #898781;
  --grid: #e1e0d9; --border: #e1e0d9;
  --series-1: #2a78d6; --series-2: #eb6834; --series-3: #1baf7a;
  --good: #0ca30c; --critical: #d03b3b;
  font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  color: var(--ink-1); background: var(--plane); padding: 16px; border-radius: 10px;
}
@media (prefers-color-scheme: dark) {
  :root:where(:not([data-theme="light"])) .kpi-root {
    color-scheme: dark;
    --surface-1: #1a1a19; --plane: #0d0d0d;
    --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-muted: #898781;
    --grid: #2c2c2a; --border: #2c2c2a;
    --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
  }
}
:root[data-theme="dark"] .kpi-root {
  color-scheme: dark;
  --surface-1: #1a1a19; --plane: #0d0d0d;
  --ink-1: #ffffff; --ink-2: #c3c2b7; --ink-muted: #898781;
  --grid: #2c2c2a; --border: #2c2c2a;
  --series-1: #3987e5; --series-2: #d95926; --series-3: #199e70;
}
.kpi-controls { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; margin-bottom: 14px; }
.kpi-controls label { color: var(--ink-2); font-size: 12px; }
.kpi-controls select, .kpi-seg button {
  font: inherit; color: var(--ink-1); background: var(--surface-1);
  border: 1px solid var(--border); border-radius: 6px; padding: 5px 9px;
}
.kpi-seg { display: inline-flex; border: 1px solid var(--border); border-radius: 6px; overflow: hidden; }
.kpi-seg button { border: 0; border-radius: 0; cursor: pointer; }
.kpi-seg button[aria-pressed="true"] { background: var(--series-1); color: #fff; }
.kpi-seg button:disabled { opacity: .45; cursor: not-allowed; }
.kpi-tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(158px, 1fr)); gap: 10px; }
.kpi-tile { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 11px 13px; }
.kpi-tile h4 { margin: 0 0 6px; font-size: 11px; font-weight: 600; letter-spacing: .03em;
  text-transform: uppercase; color: var(--ink-muted); }
.kpi-value { font-size: 25px; font-weight: 600; line-height: 1.1; font-variant-numeric: tabular-nums; }
.kpi-value .unit { font-size: 14px; font-weight: 500; color: var(--ink-2); margin-left: 2px; }
.kpi-sub { margin-top: 5px; font-size: 11.5px; color: var(--ink-2); display: flex; gap: 6px; align-items: baseline; }
.kpi-delta.good { color: var(--good); } .kpi-delta.bad { color: var(--critical); }
.kpi-delta.flat { color: var(--ink-muted); }
.kpi-panel { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px;
  padding: 13px; margin-top: 14px; }
.kpi-panel h3 { margin: 0 0 2px; font-size: 14px; font-weight: 600; }
.kpi-panel p.note { margin: 0 0 10px; font-size: 12px; color: var(--ink-2); }
.kpi-legend { display: flex; flex-wrap: wrap; gap: 14px; margin-bottom: 6px; font-size: 12px; color: var(--ink-2); }
.kpi-legend span { display: inline-flex; align-items: center; gap: 6px; }
.kpi-swatch { width: 10px; height: 10px; border-radius: 2px; display: inline-block; }
.kpi-empty { color: var(--ink-2); padding: 24px; text-align: center; }
.kpi-table { width: 100%; border-collapse: collapse; font-size: 12px; font-variant-numeric: tabular-nums; }
.kpi-table th, .kpi-table td { padding: 5px 8px; border-bottom: 1px solid var(--border); text-align: right; }
.kpi-table th:first-child, .kpi-table td:first-child { text-align: left; }
.kpi-table th { color: var(--ink-muted); font-weight: 600; }
.kpi-scroll { overflow-x: auto; }
.kpi-toggle { background: none; border: 0; color: var(--series-1); cursor: pointer;
  font: inherit; padding: 0; margin-top: 10px; }
`;

const TILES = [
  'open_inc_total', 'new_inc_total', 'closed_inc_total', 'mttr_hours',
  'oldest_open_age', 'distinct_agents', 'open_more_than_five_days',
  'open_more_than_thirty_days', 'stale_open_no_update_5d', 'age_open_inc',
  'new_inc_p1p2_count', 'closed_inc_same_day_open',
];

/* Two charts, not one. Backlog is a level in the hundreds; new and closed are
   daily counts in single digits. On a shared axis the flows flatten into a line
   along the baseline, and a second y-axis is never the answer, so they get their
   own plot at their own scale. */
const BACKLOG_SERIES = [{ name: 'open_inc_total', color: 'var(--series-1)' }];
const FLOW_SERIES = [
  { name: 'new_inc_total', color: 'var(--series-2)' },
  { name: 'closed_inc_total', color: 'var(--series-3)' },
];

const fmt = (value, unit) => {
  if (value == null) return '--';
  const rounded = Math.abs(value) >= 100 ? Math.round(value) : Math.round(value * 100) / 100;
  return `${rounded.toLocaleString()}${unit ? '' : ''}`;
};

/** How a change should read: for backlog and MTTR, up is bad. */
function deltaTone(name, direction) {
  const intent = INTENT[name] || 'neutral';
  if (direction === 'flat' || intent === 'neutral') return 'flat';
  const goodWhenDown = intent === 'lower';
  return (direction === 'down') === goodWhenDown ? 'good' : 'bad';
}

function Tile({ name, bucketed, windowed, mode }) {
  const rule = ruleOf(name);
  const summary = total(windowed, name, mode);
  const change = delta(bucketed, name);
  if (summary.value == null) return null;

  const how = rule.rule === 'sum'
    ? (mode === 'avg' ? 'mean per day' : 'total')
    : rule.rule === 'last' ? 'at period end'
    : rule.rule === 'max' ? 'peak'
    : rule.rule === 'ratio' ? 'recomputed' : 'weighted mean';

  return (
    <div className="kpi-tile">
      <h4>{rule.label}</h4>
      <div className="kpi-value">
        {fmt(summary.value)}
        {rule.unit ? <span className="unit">{rule.unit}</span> : null}
      </div>
      <div className="kpi-sub">
        <span>{how}</span>
        {change ? (
          <span className={`kpi-delta ${deltaTone(name, change.direction)}`}>
            {change.direction === 'up' ? '▲' : change.direction === 'down' ? '▼' : '■'}
            {' '}{Math.abs(change.change).toLocaleString()}
          </span>
        ) : null}
      </div>
    </div>
  );
}

/** Line chart. One axis only: every series here is a count of records. */
function TrendChart({ buckets, grain, series }) {
  const [hover, setHover] = useState(null);
  const width = 720;
  const height = 240;
  const pad = { top: 12, right: 58, bottom: 26, left: 40 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const points = buckets.map((b) => b.period);
  const active = series.filter((s) => buckets.some((b) => b.metrics[s.name]?.value != null));
  if (!points.length || !active.length) return <div className="kpi-empty">No data in this window.</div>;

  const values = active.flatMap((s) => buckets.map((b) => b.metrics[s.name]?.value).filter((v) => v != null));
  const max = Math.max(1, ...values);
  const niceMax = Math.ceil(max / 5) * 5 || 5;
  const x = (i) => pad.left + (points.length === 1 ? plotW / 2 : (i / (points.length - 1)) * plotW);
  const y = (v) => pad.top + plotH - (v / niceMax) * plotH;

  const ticks = [0, 0.5, 1].map((f) => Math.round(niceMax * f));
  const labelEvery = Math.max(1, Math.ceil(points.length / 8));

  // Direct labels at the line ends, nudged apart when two series finish close
  // together. Without this the last values overprint each other.
  const endLabels = active
    .map((s) => {
      const index = buckets.map((b) => b.metrics[s.name]?.value)
        .reduce((acc, v, i) => (v == null ? acc : i), -1);
      return index < 0 ? null
        : { name: s.name, index, value: buckets[index].metrics[s.name].value,
            y: y(buckets[index].metrics[s.name].value) };
    })
    .filter(Boolean)
    .sort((a, b) => a.y - b.y);
  for (let i = 1; i < endLabels.length; i++) {
    const gap = endLabels[i].y - endLabels[i - 1].y;
    if (gap < 13) endLabels[i].y = endLabels[i - 1].y + 13;
  }

  const move = (event) => {
    const box = event.currentTarget.getBoundingClientRect();
    const rel = ((event.clientX - box.left) / box.width) * width - pad.left;
    const index = Math.round((rel / plotW) * (points.length - 1));
    setHover(index >= 0 && index < points.length ? index : null);
  };

  return (
    <div>
      <div className="kpi-legend" hidden={active.length < 2}>
        {active.map((s) => (
          <span key={s.name}>
            <i className="kpi-swatch" style={{ background: s.color }} />
            {ruleOf(s.name).label}
          </span>
        ))}
      </div>
      <div className="kpi-scroll">
        <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height}
             role="img" aria-label="New, closed and open backlog over time"
             onMouseMove={move} onMouseLeave={() => setHover(null)}>
          {ticks.map((t) => (
            <g key={t}>
              <line x1={pad.left} x2={width - pad.right} y1={y(t)} y2={y(t)}
                    stroke="var(--grid)" strokeWidth="1" />
              <text x={pad.left - 8} y={y(t) + 4} textAnchor="end"
                    fontSize="11" fill="var(--ink-muted)">{t}</text>
            </g>
          ))}
          {points.map((p, i) => (i % labelEvery === 0 ? (
            <text key={p} x={x(i)} y={height - 8} textAnchor="middle"
                  fontSize="11" fill="var(--ink-muted)">{shortLabel(p, grain)}</text>
          ) : null))}

          {hover != null ? (
            <line x1={x(hover)} x2={x(hover)} y1={pad.top} y2={pad.top + plotH}
                  stroke="var(--ink-muted)" strokeWidth="1" strokeDasharray="3 3" />
          ) : null}

          {endLabels.map((label) => (
            <text key={`lbl-${label.name}`} x={x(label.index) + 8} y={label.y + 4}
                  fontSize="11.5" fill="var(--ink-2)">{fmt(label.value)}</text>
          ))}

          {active.map((s) => {
            const path = buckets
              .map((b, i) => {
                const v = b.metrics[s.name]?.value;
                return v == null ? null : `${i === 0 ? 'M' : 'L'}${x(i)},${y(v)}`;
              })
              .filter(Boolean).join(' ');
            return (
              <g key={s.name}>
                <path d={path} fill="none" stroke={s.color} strokeWidth="2"
                      strokeLinejoin="round" strokeLinecap="round" />
                {hover != null && buckets[hover]?.metrics[s.name]?.value != null ? (
                  <circle cx={x(hover)} cy={y(buckets[hover].metrics[s.name].value)} r="4.5"
                          fill={s.color} stroke="var(--surface-1)" strokeWidth="2" />
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>
      {hover != null ? (
        <div style={{ fontSize: 12, color: 'var(--ink-2)', marginTop: 4 }}>
          <strong style={{ color: 'var(--ink-1)' }}>{buckets[hover].period}</strong>
          {active.map((s) => (
            <span key={s.name} style={{ marginLeft: 12 }}>
              <i className="kpi-swatch" style={{ background: s.color, marginRight: 5 }} />
              {ruleOf(s.name).label} {fmt(buckets[hover].metrics[s.name]?.value)}
            </span>
          ))}
        </div>
      ) : null}
    </div>
  );
}

/** Backlog health: how much of the open backlog is ageing or untouched. */
function BacklogBars({ windowed, mode }) {
  const rows = ['open_inc_total', 'open_more_than_five_days',
    'open_more_than_thirty_days', 'stale_open_no_update_5d']
    .map((name) => ({ name, label: ruleOf(name).label, value: total(windowed, name, mode).value }))
    .filter((row) => row.value != null);
  if (!rows.length) return null;
  const max = Math.max(1, ...rows.map((r) => r.value));

  return (
    <div>
      {rows.map((row) => (
        <div key={row.name} style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '7px 0' }}>
          <span style={{ width: 130, fontSize: 12, color: 'var(--ink-2)' }}>{row.label}</span>
          <svg width="100%" height="16" style={{ flex: 1 }} role="img"
               aria-label={`${row.label}: ${row.value}`}>
            <rect x="0" y="3" rx="4" ry="4" height="10"
                  width={`${(row.value / max) * 100}%`} fill="var(--series-1)" />
          </svg>
          <strong style={{ width: 52, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
            {fmt(row.value)}
          </strong>
        </div>
      ))}
    </div>
  );
}

function DataTable({ buckets, series }) {
  return (
    <div className="kpi-scroll">
      <table className="kpi-table">
        <thead>
          <tr>
            <th>Period</th>
            <th>Days</th>
            {series.map((s) => <th key={s.name}>{ruleOf(s.name).label}</th>)}
          </tr>
        </thead>
        <tbody>
          {buckets.map((b) => (
            <tr key={b.period}>
              <td>{b.period}</td>
              <td>{b.days}</td>
              {series.map((s) => <td key={s.name}>{fmt(b.metrics[s.name]?.value)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function KpiDashboard({ records, today }) {
  const [presetId, setPresetId] = useState('last_30_days');
  const [mode, setMode] = useState('sum');
  const [showTable, setShowTable] = useState(false);

  const all = useMemo(() => adaptRecords(records), [records]);
  const preset = PRESETS.find((p) => p.id === presetId) || PRESETS[0];
  const now = today ? new Date(today) : new Date();

  const windowed = useMemo(() => applyWindow(all, preset, now),
    [all, presetId, today]);
  const buckets = useMemo(() => bucketize(windowed, preset.grain, mode),
    [windowed, preset.grain, mode]);

  const tiles = TILES.filter((name) => windowed.some((r) => r.metrics && r.metrics[name]));
  const modeApplies = tiles.some(respondsToMode);

  return (
    <div className="kpi-root">
      <style>{CSS}</style>

      <div className="kpi-controls">
        <label htmlFor="kpi-timeline">Timeline</label>
        <select id="kpi-timeline" value={presetId} onChange={(e) => setPresetId(e.target.value)}>
          {PRESETS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>

        <span className="kpi-seg" role="group" aria-label="How flow metrics are combined">
          <button type="button" aria-pressed={mode === 'sum'} disabled={!modeApplies}
                  onClick={() => setMode('sum')}>Sum</button>
          <button type="button" aria-pressed={mode === 'avg'} disabled={!modeApplies}
                  onClick={() => setMode('avg')}>Avg / day</button>
        </span>

        <span style={{ color: 'var(--ink-muted)', fontSize: 12 }}>
          {windowed.length} day{windowed.length === 1 ? '' : 's'}
          {buckets.length !== windowed.length ? ` in ${buckets.length} ${preset.grain}s` : ''}
        </span>
      </div>

      {!windowed.length ? (
        <div className="kpi-panel kpi-empty">
          No records in this window. Widen the timeline, or check the playbook has run.
        </div>
      ) : (
        <>
          <div className="kpi-tiles">
            {tiles.map((name) => (
              <Tile key={name} name={name} bucketed={buckets} windowed={windowed} mode={mode} />
            ))}
          </div>

          <div className="kpi-panel">
            <h3>Open backlog</h3>
            <p className="note">
              A level, not a flow: the backlog as it stood at the end of each {preset.grain}.
            </p>
            <TrendChart buckets={buckets} grain={preset.grain} series={BACKLOG_SERIES} />
          </div>

          <div className="kpi-panel">
            <h3>New vs closed</h3>
            <p className="note">
              Counts within each {preset.grain}. Plotted separately from the backlog,
              which runs an order of magnitude higher and would flatten these to the axis.
            </p>
            <TrendChart buckets={buckets} grain={preset.grain} series={FLOW_SERIES} />
            <button type="button" className="kpi-toggle" onClick={() => setShowTable(!showTable)}>
              {showTable ? 'Hide the numbers' : 'Show the numbers'}
            </button>
            {showTable ? (
              <DataTable buckets={buckets} series={[...BACKLOG_SERIES, ...FLOW_SERIES]} />
            ) : null}
          </div>

          <div className="kpi-panel">
            <h3>Backlog health</h3>
            <p className="note">How much of the open backlog is ageing or untouched.</p>
            <BacklogBars windowed={windowed} mode={mode} />
          </div>
        </>
      )}
    </div>
  );
}
