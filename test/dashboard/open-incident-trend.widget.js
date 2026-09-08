/**
 * Open incidents over time, with the latest day's breakdown.
 *
 * A Turbine report widget. Paste the whole file into a custom report widget.
 * No chart library and no CDN: the plot is inline SVG.
 *
 * Structure follows a widget known to work in this tenant:
 *   - versioned import specifier, '@swimlane/swimlane-element@2'
 *   - anonymous default-export class
 *   - no customElements.define; the platform registers the default export
 *   - static get styles() returns an array
 *   - firstUpdated/updated re-render once `report` arrives
 *
 * Data. The platform sets `this.report` to { data, rawData, query }:
 *   rawData - one object per record, which is what a timeline needs
 *   data    - aggregated series, grouped by the report's own dimensions
 * This reads rawData when it is there, and falls back to data[0].series.
 */

import { SwimlaneElement, css, html } from '@swimlane/swimlane-element@2';

/** The field key to chart, and the day field. Change these to chart another. */
const METRIC_KEY = 'open_inc_total';
const METRIC_LABEL = 'Open incidents';
const DATE_KEYS = ['Snapshot Date', 'snapshot_date', 'Snapshot Key', 'snapshotDate', 'date'];

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
    this.dimension = '';
    this.hover = null;
  }

  static get styles() {
    return [
      super.styles,
      css`
        :host { display: block; --series: #2a78d6; --ink-2: #52514e; --muted: #898781;
                --grid: #e1e0d9; --good: #0ca30c; --bad: #d03b3b; }
        @media (prefers-color-scheme: dark) {
          :host { --series: #3987e5; --ink-2: #c3c2b7; --grid: #2c2c2a; }
        }
        .head { display: flex; flex-wrap: wrap; gap: 10px; align-items: baseline;
                justify-content: space-between; margin-bottom: 8px; }
        h3 { margin: 0; font-size: 14px; font-weight: 600; }
        select { font: inherit; border: 1px solid var(--grid); border-radius: 6px;
                 padding: 4px 8px; background: transparent; color: inherit; }
        label { color: var(--ink-2); font-size: 12px; margin-right: 4px; }
        .hero { font-size: 32px; font-weight: 600; line-height: 1.05;
                font-variant-numeric: tabular-nums; }
        .sub { font-size: 12px; color: var(--ink-2); margin-top: 2px; }
        .up { color: var(--bad); } .down { color: var(--good); } .flat { color: var(--muted); }
        .row { display: flex; align-items: center; gap: 8px; margin: 5px 0; font-size: 12px; }
        .row .name { width: 36%; color: var(--ink-2); overflow: hidden;
                     text-overflow: ellipsis; white-space: nowrap; }
        .row .track { flex: 1; height: 10px; background: rgba(127,127,127,.15);
                      border-radius: 5px; }
        .row .fill { height: 10px; border-radius: 5px; background: var(--series); }
        .row .n { width: 46px; text-align: right; font-weight: 600;
                  font-variant-numeric: tabular-nums; }
        .note { font-size: 12px; color: var(--ink-2); }
        code { background: rgba(127,127,127,.15); padding: 1px 5px; border-radius: 4px; }
        table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 8px;
                font-variant-numeric: tabular-nums; }
        th, td { padding: 4px 6px; border-bottom: 1px solid var(--grid); text-align: right; }
        th:first-child, td:first-child { text-align: left; }
        summary { cursor: pointer; color: var(--series); font-size: 12px; margin-top: 10px; }
      `,
    ];
  }

  firstUpdated() {
    super.firstUpdated();
    if (this.report) this.requestUpdate();
  }

  updated(changedProperties) {
    super.updated(changedProperties);
    if (changedProperties.has('report') && this.report) this.requestUpdate();
  }

  /* ----------------------------------------------------------------- data --- */

  /**
   * Raw rows may be keyed by field id rather than field key, so build a lookup
   * from the application's field list and try both.
   */
  valueOf(row, wanted) {
    if (row[wanted] !== undefined) return row[wanted];
    const fields = (this.contextData && this.contextData.application
      && this.contextData.application.fields) || [];
    const field = fields.find((f) => f.key === wanted || f.name === wanted);
    if (field && row[field.id] !== undefined) return row[field.id];
    return undefined;
  }

  dateOf(row) {
    for (const key of DATE_KEYS) {
      const value = this.valueOf(row, key);
      if (value) return String(value).slice(0, 10);
    }
    return null;
  }

  /** A metric field may hold JSON, a plain number, or a nested metrics object. */
  parseMetric(raw) {
    if (raw == null || raw === '') return null;
    if (typeof raw === 'number') return { value: raw, breakdown: [] };
    if (typeof raw === 'object') return raw;
    try {
      return JSON.parse(raw);
    } catch (error) {
      const asNumber = Number(raw);
      return isFinite(asNumber) ? { value: asNumber, breakdown: [] } : null;
    }
  }

  /** {date, value, breakdown} per day, oldest first, limited to the window. */
  points() {
    const report = this.report || {};
    const rows = Array.isArray(report.rawData) ? report.rawData : [];

    let series = rows
      .map((row) => {
        const date = this.dateOf(row);
        const metric = this.parseMetric(this.valueOf(row, METRIC_KEY));
        if (!date || !metric) return null;
        const value = metric.value && typeof metric.value === 'object'
          ? metric.value.avg : metric.value;
        return value == null ? null
          : { date, value: Number(value), breakdown: metric.breakdown || [] };
      })
      .filter(Boolean);

    // Fall back to the aggregated series when the report exposes no raw rows.
    if (!series.length) series = this.fromAggregated();

    // One point per day; a re-run of a day would otherwise appear twice.
    const byDate = new Map();
    series.forEach((point) => byDate.set(point.date, point));
    return [...byDate.values()]
      .sort((a, b) => a.date.localeCompare(b.date))
      .slice(-this.days);
  }

  /**
   * report.data is grouped by the report's dimensions, so a point's `name` is
   * the group label. When the report groups by the metric field, that label is
   * the stored JSON; when it groups by date, the label is the date.
   */
  fromAggregated() {
    const groups = (this.report && this.report.data) || [];
    const series = (groups[0] && groups[0].series) || [];
    return series
      .map((item) => {
        const label = String(item.name || '');
        if (/^\d{4}-\d{2}-\d{2}/.test(label)) {
          return { date: label.slice(0, 10), value: Number(item.value) || 0, breakdown: [] };
        }
        const parsed = this.parseMetric(label);
        return parsed && parsed.snapshot_date
          ? { date: String(parsed.snapshot_date).slice(0, 10),
              value: Number(parsed.value) || 0, breakdown: parsed.breakdown || [] }
          : null;
      })
      .filter(Boolean);
  }

  /* --------------------------------------------------------------- render --- */

  render() {
    const points = this.points();
    if (!points.length) return this.renderEmpty();

    const latest = points[points.length - 1];
    const change = latest.value - points[0].value;
    const tone = change > 0 ? 'up' : change < 0 ? 'down' : 'flat';
    const arrow = change > 0 ? '▲' : change < 0 ? '▼' : '■';

    const dimensions = [...new Set((latest.breakdown || []).map((b) => b.dimension))];
    const dimension = dimensions.includes(this.dimension) ? this.dimension : dimensions[0];
    const bars = (latest.breakdown || []).filter((b) => b.dimension === dimension);
    const barMax = Math.max(1, ...bars.map((b) => b.count || 0));

    return html`
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
        across ${points.length} day${points.length === 1 ? '' : 's'}
      </div>

      ${this.renderChart(points)}

      ${bars.length ? html`
        <div class="head" style="margin-top:12px">
          <strong style="font-size:12.5px">Breakdown, ${latest.date}</strong>
          ${dimensions.length > 1 ? html`
            <select @change=${(e) => { this.dimension = e.target.value; }}>
              ${dimensions.map((d) => html`
                <option value=${d} ?selected=${d === dimension}>${d}</option>`)}
            </select>` : null}
        </div>
        ${bars.map((bar) => html`
          <div class="row">
            <span class="name" title=${bar.label}>${bar.label}</span>
            <span class="track">
              <span class="fill" style="width:${((bar.count || 0) / barMax) * 100}%"></span>
            </span>
            <span class="n">${(bar.count || 0).toLocaleString()}</span>
          </div>`)}` : null}

      <details>
        <summary>Show the numbers</summary>
        <table>
          <thead><tr><th>Date</th><th>${METRIC_LABEL}</th></tr></thead>
          <tbody>
            ${[...points].reverse().map((p) => html`
              <tr><td>${p.date}</td><td>${p.value.toLocaleString()}</td></tr>`)}
          </tbody>
        </table>
      </details>`;
  }

  /** One series, so the heading names it and no legend is needed. */
  renderChart(points) {
    const width = 640;
    const height = 165;
    const pad = { top: 12, right: 44, bottom: 22, left: 38 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;

    const max = Math.max(1, ...points.map((p) => p.value));
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
           role="img" aria-label="${METRIC_LABEL} over ${points.length} days"
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
                  fill="var(--series)" stroke="#fff" stroke-width="2"></circle>
          <text x=${x(this.hover)} y=${pad.top - 2} text-anchor="middle"
                font-size="11.5" fill="currentColor">${hovered.date} · ${hovered.value}</text>`
        : html`
          <text x=${x(points.length - 1) + 6} y=${y(points[points.length - 1].value) + 4}
                font-size="11.5" fill="var(--ink-2)">${points[points.length - 1].value}</text>`}
      </svg>`;
  }

  /** Says which of the two possible causes it is, rather than just "no data". */
  renderEmpty() {
    const report = this.report || {};
    const rows = Array.isArray(report.rawData) ? report.rawData : [];
    return html`
      <div class="head"><h3>${METRIC_LABEL}</h3></div>
      ${rows.length ? html`
        <p class="note">
          The report returned ${rows.length} row(s), but none carried a readable
          <code>${METRIC_KEY}</code> with a date. The keys on the first row are:
        </p>
        <p class="note"><code>${Object.keys(rows[0]).join(', ')}</code></p>
        <p class="note">
          Set <code>METRIC_KEY</code> and <code>DATE_KEYS</code> at the top of this
          file to match.
        </p>`
      : html`
        <p class="note">
          This report returned no rows. Add the daily metrics application's date
          field and <code>${METRIC_KEY}</code> as columns, and clear any filter
          that empties the range.
        </p>`}`;
  }
}
