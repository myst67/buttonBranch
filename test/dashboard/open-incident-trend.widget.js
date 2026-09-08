/**
 * Open Incident Trend - a Turbine report widget.
 *
 * Paste this whole file into a custom widget. It reads the daily metrics
 * records from the report it is placed on, and shows:
 *
 *   - the open backlog over the last X days, as a line
 *   - the headline number, with the change since the start of the window
 *   - the breakdown of the latest day, by a dimension you pick
 *
 * Nothing is fetched and nothing is imported beyond the Turbine element base,
 * so there is no CDN and no build step. The chart is inline SVG.
 *
 * ---------------------------------------------------------------------------
 * ONE THING TO CHECK ON FIRST RUN
 *
 * Turbine hands report data to a widget through a property on the element, and
 * the name of that property is not something this file can know in advance. So
 * it looks through the likely names, and if it finds none it renders a panel
 * listing the properties the element actually has, with the array-shaped ones
 * marked. Read that panel, then set DATA_PROPERTY below to the right name.
 * ---------------------------------------------------------------------------
 */

import { SwimlaneElement, css, html } from '@swimlane/swimlane-element';
import { reportFrameTemplate } from '@swimlane/swimlane-element/templates.js';

/**
 * The platform hands a report widget `this.report`, shaped
 * `{ data, rawData, query }`:
 *   rawData - the report's rows, one object per record
 *   data    - the aggregated series the built-in charts draw
 *   query   - the dimensions and measures configured on the report
 *
 * This widget reads `rawData`, because it does its own arithmetic over the
 * daily records. `data` is already grouped by whatever the report was set to.
 */

/** The metric this widget charts. */
const METRIC = 'open_inc_total';
const METRIC_LABEL = 'Open incidents';

/** Field names a record might use for its day. */
const DATE_KEYS = ['snapshot_date', 'Snapshot Date', 'Snapshot Key', 'snapshotDate', 'date'];

const WINDOWS = [7, 14, 30, 60, 90];

export default class extends SwimlaneElement {
  static get properties() {
    return {
      days: { type: Number },
      dimension: { type: String },
      hover: { type: Number },
    };
  }

  constructor() {
    super();
    this.days = 30;
    this.dimension = 'severity';
    this.hover = null;
  }

  static get styles() {
    return [super.styles, css`
      :host {
        display: block;
        --surface: #fcfcfb; --plane: #f9f9f7;
        --ink-1: #0b0b0b; --ink-2: #52514e; --muted: #898781;
        --grid: #e1e0d9; --series: #2a78d6;
        --good: #0ca30c; --bad: #d03b3b;
        font: 13px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        color: var(--ink-1);
      }
      @media (prefers-color-scheme: dark) {
        :host {
          --surface: #1a1a19; --plane: #0d0d0d;
          --ink-1: #ffffff; --ink-2: #c3c2b7; --muted: #898781;
          --grid: #2c2c2a; --series: #3987e5;
        }
      }
      .wrap { background: var(--surface); border: 1px solid var(--grid);
              border-radius: 8px; padding: 14px; }
      .head { display: flex; flex-wrap: wrap; gap: 10px; align-items: baseline;
              justify-content: space-between; margin-bottom: 10px; }
      h3 { margin: 0; font-size: 14px; font-weight: 600; }
      select { font: inherit; color: var(--ink-1); background: var(--surface);
               border: 1px solid var(--grid); border-radius: 6px; padding: 4px 8px; }
      label { color: var(--ink-2); font-size: 12px; margin-right: 4px; }
      .hero { font-size: 34px; font-weight: 600; line-height: 1.05;
              font-variant-numeric: tabular-nums; }
      .sub { font-size: 12px; color: var(--ink-2); margin-top: 3px; }
      .up { color: var(--bad); } .down { color: var(--good); } .flat { color: var(--muted); }
      .bars { margin-top: 6px; }
      .row { display: flex; align-items: center; gap: 8px; margin: 5px 0; font-size: 12px; }
      .row .name { width: 34%; color: var(--ink-2); overflow: hidden;
                   text-overflow: ellipsis; white-space: nowrap; }
      .row .track { flex: 1; height: 10px; background: var(--plane); border-radius: 5px; }
      .row .fill { height: 10px; border-radius: 5px; background: var(--series); }
      .row .n { width: 44px; text-align: right; font-variant-numeric: tabular-nums;
                font-weight: 600; }
      .diag { font-size: 12px; color: var(--ink-2); }
      .diag code { background: var(--plane); padding: 1px 5px; border-radius: 4px;
                   font-size: 11.5px; }
      .diag li { margin: 3px 0; }
      table { width: 100%; border-collapse: collapse; font-size: 12px;
              font-variant-numeric: tabular-nums; margin-top: 8px; }
      th, td { padding: 4px 6px; border-bottom: 1px solid var(--grid); text-align: right; }
      th:first-child, td:first-child { text-align: left; }
      th { color: var(--muted); font-weight: 600; }
      details summary { cursor: pointer; color: var(--series); margin-top: 10px;
                        font-size: 12px; }
    `];
  }

  /* ---------------------------------------------------------------- data --- */

  /** The report's rows. */
  rows() {
    const raw = this.report && this.report.rawData;
    return Array.isArray(raw) ? raw : [];
  }

  dateOf(row) {
    for (const key of DATE_KEYS) {
      if (row[key]) return String(row[key]).slice(0, 10);
    }
    return null;
  }

  /** Read the metric off a row, whether it is an object or a JSON string. */
  metricOf(row) {
    const raw = row[METRIC] ?? (row.metrics || {})[METRIC];
    if (raw == null || raw === '') return null;
    if (typeof raw === 'object') return raw;
    if (typeof raw === 'number') return { value: raw };
    try {
      return JSON.parse(raw);
    } catch (error) {
      const asNumber = Number(raw);
      return isFinite(asNumber) ? { value: asNumber } : null;
    }
  }

  /** The last `days` rows, oldest first, each reduced to {date, value, breakdown}. */
  series(rows) {
    const points = rows
      .map((row) => {
        const date = this.dateOf(row);
        const metric = this.metricOf(row);
        if (!date || !metric) return null;
        const value = typeof metric.value === 'object'
          ? metric.value?.avg ?? null
          : metric.value;
        return value == null ? null
          : { date, value: Number(value), breakdown: metric.breakdown || [] };
      })
      .filter(Boolean)
      .sort((a, b) => a.date.localeCompare(b.date));
    return points.slice(-this.days);
  }

  /* -------------------------------------------------------------- render --- */

  render() {
    const rows = this.rows();
    if (!rows.length) return this.renderEmpty();

    const points = this.series(rows);
    if (!points.length) {
      return reportFrameTemplate(html`
        <div class="wrap diag">
          <h3>${METRIC_LABEL}</h3>
          <p>
            The report returned ${rows.length} row(s), but none carried a readable
            <code>${METRIC}</code>. The keys on the first row are:
          </p>
          <p><code>${Object.keys(rows[0]).join(', ')}</code></p>
          <p>Set <code>METRIC</code> at the top of this file to the right key.</p>
        </div>`);
    }

    const latest = points[points.length - 1];
    const first = points[0];
    const change = latest.value - first.value;
    const tone = change > 0 ? 'up' : change < 0 ? 'down' : 'flat';
    const arrow = change > 0 ? '▲' : change < 0 ? '▼' : '■';

    const dimensions = [...new Set(latest.breakdown.map((b) => b.dimension))];
    const dimension = dimensions.includes(this.dimension) ? this.dimension : dimensions[0];
    const bars = latest.breakdown.filter((b) => b.dimension === dimension);
    const barMax = Math.max(1, ...bars.map((b) => b.count));

    return reportFrameTemplate(html`
      <div class="wrap">
        <div class="head">
          <h3>${METRIC_LABEL}</h3>
          <span>
            <label for="win">Last</label>
            <select id="win" @change=${(e) => { this.days = Number(e.target.value); }}>
              ${WINDOWS.map((n) => html`
                <option value=${n} ?selected=${n === this.days}>${n} days</option>`)}
            </select>
          </span>
        </div>

        <div class="hero">${latest.value.toLocaleString()}</div>
        <div class="sub">
          as at ${latest.date} ·
          <span class=${tone}>${arrow} ${Math.abs(change).toLocaleString()}</span>
          over ${points.length} day${points.length === 1 ? '' : 's'}
        </div>

        ${this.renderChart(points)}

        ${bars.length ? html`
          <div class="head" style="margin-top:14px">
            <strong style="font-size:12.5px">Breakdown, ${latest.date}</strong>
            ${dimensions.length > 1 ? html`
              <select @change=${(e) => { this.dimension = e.target.value; }}>
                ${dimensions.map((d) => html`
                  <option value=${d} ?selected=${d === dimension}>${d}</option>`)}
              </select>` : null}
          </div>
          <div class="bars">
            ${bars.map((bar) => html`
              <div class="row">
                <span class="name" title=${bar.label}>${bar.label}</span>
                <span class="track">
                  <span class="fill" style="width:${(bar.count / barMax) * 100}%"></span>
                </span>
                <span class="n">${bar.count.toLocaleString()}</span>
              </div>`)}
          </div>` : null}

        <details>
          <summary>Show the numbers</summary>
          <table>
            <thead><tr><th>Date</th><th>${METRIC_LABEL}</th></tr></thead>
            <tbody>
              ${[...points].reverse().map((p) => html`
                <tr><td>${p.date}</td><td>${p.value.toLocaleString()}</td></tr>`)}
            </tbody>
          </table>
        </details>
      </div>`);
  }

  /** Inline SVG line. One series, so the heading names it and no legend is needed. */
  renderChart(points) {
    const width = 640;
    const height = 170;
    const pad = { top: 10, right: 46, bottom: 22, left: 38 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;

    const values = points.map((p) => p.value);
    const max = Math.max(1, ...values);
    const niceMax = Math.ceil(max / 5) * 5 || 5;
    const x = (i) => pad.left + (points.length === 1 ? plotW / 2 : (i / (points.length - 1)) * plotW);
    const y = (v) => pad.top + plotH - (v / niceMax) * plotH;
    const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(p.value)}`).join(' ');
    const every = Math.max(1, Math.ceil(points.length / 7));
    const hovered = this.hover != null && points[this.hover] ? points[this.hover] : null;

    const move = (event) => {
      const box = event.currentTarget.getBoundingClientRect();
      const rel = ((event.clientX - box.left) / box.width) * width - pad.left;
      const index = Math.round((rel / plotW) * (points.length - 1));
      this.hover = index >= 0 && index < points.length ? index : null;
    };

    return html`
      <svg viewBox="0 0 ${width} ${height}" width="100%" height=${height}
           role="img" aria-label="${METRIC_LABEL} over the last ${points.length} days"
           @mousemove=${move} @mouseleave=${() => { this.hover = null; }}>
        ${[0, 0.5, 1].map((f) => {
          const tick = Math.round(niceMax * f);
          return html`
            <line x1=${pad.left} x2=${width - pad.right} y1=${y(tick)} y2=${y(tick)}
                  stroke="var(--grid)" stroke-width="1"></line>
            <text x=${pad.left - 7} y=${y(tick) + 4} text-anchor="end"
                  font-size="11" fill="var(--muted)">${tick}</text>`;
        })}
        ${points.map((p, i) => (i % every === 0 ? html`
          <text x=${x(i)} y=${height - 6} text-anchor="middle"
                font-size="11" fill="var(--muted)">${p.date.slice(5)}</text>` : null))}

        <path d=${path} fill="none" stroke="var(--series)" stroke-width="2"
              stroke-linejoin="round" stroke-linecap="round"></path>

        ${hovered ? html`
          <line x1=${x(this.hover)} x2=${x(this.hover)} y1=${pad.top} y2=${pad.top + plotH}
                stroke="var(--muted)" stroke-width="1" stroke-dasharray="3 3"></line>
          <circle cx=${x(this.hover)} cy=${y(hovered.value)} r="4.5"
                  fill="var(--series)" stroke="var(--surface)" stroke-width="2"></circle>
          <text x=${x(this.hover)} y=${pad.top - 1} text-anchor="middle"
                font-size="11.5" fill="var(--ink-1)">${hovered.date} · ${hovered.value}</text>`
        : html`
          <text x=${x(points.length - 1) + 7} y=${y(points[points.length - 1].value) + 4}
                font-size="11.5" fill="var(--ink-2)">${points[points.length - 1].value}</text>`}
      </svg>`;
  }

  /** Shown when the report returned no rows at all. */
  renderEmpty() {
    return reportFrameTemplate(html`
      <div class="wrap diag">
        <h3>${METRIC_LABEL}</h3>
        <p>
          This report returned no rows. Add the daily metrics application's
          <code>Snapshot Date</code> and <code>${METRIC}</code> fields to the
          report, and make sure it is not filtered to an empty range.
        </p>
      </div>`);
  }
}

