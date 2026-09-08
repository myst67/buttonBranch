/**
 * Timeline chart: one point per day, for the last N days.
 *
 * x axis - the date
 * y axis - the metric's value on that day
 *
 * REPORT SETUP. The report has to hand over a date and a value together, which
 * means the date must be a dimension. Set EDIT DIMENSIONS to:
 *
 *     1. Date                 Group By     <- first
 *     2. open_inc_total       Group By
 *
 * Each group is then a day, and its series label is the stored object holding
 * that day's value.
 *
 * Grouping by the metric alone cannot work: without a date in the data there is
 * nothing to put on the x axis.
 */

import { SwimlaneElement, css, html } from '@swimlane/swimlane-element@2';

const TITLE = 'Open incidents';
const DEFAULT_DAYS = 7;

export default class extends SwimlaneElement {
  static get properties() {
    return { days: { type: Number } };
  }

  constructor() {
    super();
    this.days = DEFAULT_DAYS;
  }

  static get styles() {
    return [
      super.styles,
      css`
        :host { display: block; --line: #2a78d6; --ink-2: #52514e; --muted: #898781;
                --grid: #e1e0d9; }
        @media (prefers-color-scheme: dark) {
          :host { --line: #3987e5; --ink-2: #c3c2b7; --grid: #2c2c2a; }
        }
        .top { display: flex; align-items: baseline; justify-content: space-between;
               gap: 12px; margin-bottom: 6px; }
        h3 { margin: 0; font-size: 14px; font-weight: 600; }
        select { font: inherit; color: inherit; background: transparent;
                 border: 1px solid var(--grid); border-radius: 6px; padding: 3px 7px; }
        .note { margin: 0; font-size: 12px; color: var(--ink-2); }
        code { background: rgba(127,127,127,.15); padding: 1px 5px; border-radius: 4px; }
      `,
    ];
  }

  firstUpdated() {
    super.firstUpdated();
    if (this.report) this.requestUpdate();
  }

  updated(changed) {
    super.updated(changed);
    if (changed.has('report') && this.report) this.requestUpdate();
  }

  /* ------------------------------------------------------------------ data */

  toDate(value) {
    if (value == null || value === '') return null;
    const text = String(value).trim();
    const iso = text.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (iso) return `${iso[1]}-${iso[2]}-${iso[3]}`;
    const parsed = new Date(text);
    return isNaN(parsed.getTime()) ? null : parsed.toISOString().slice(0, 10);
  }

  /** A label is either plain text or the stored metric object. */
  valueOf(label, fallback) {
    const text = String(label == null ? '' : label);
    if (text.startsWith('{')) {
      try {
        const parsed = JSON.parse(text);
        const inner = parsed.value;
        const value = inner && typeof inner === 'object' ? inner.avg : inner;
        if (value != null) return Number(value);
      } catch (error) {
        // fall through to the count
      }
    }
    return Number(fallback) || 0;
  }

  /**
   * One point per day. Two report shapes provide a date:
   *   grouped by date, then metric - the group is the day, the label the value
   *   grouped by date alone        - the series label is the day
   */
  points() {
    const groups = (this.report && this.report.data) || [];
    const byDate = new Map();

    groups.forEach((group) => {
      const groupDate = this.toDate(group.name);
      (group.series || []).forEach((item) => {
        const date = groupDate || this.toDate(item.name);
        if (!date) return;
        const value = groupDate
          ? this.valueOf(item.name, item.value)
          : Number(item.value) || 0;
        // Keep the largest reading for a day, so a day cannot appear twice.
        if (!byDate.has(date) || byDate.get(date) < value) byDate.set(date, value);
      });
    });

    return [...byDate.entries()]
      .map(([date, value]) => ({ date, value }))
      .sort((a, b) => a.date.localeCompare(b.date))
      .slice(-this.days);
  }

  /* ---------------------------------------------------------------- render */

  render() {
    const points = this.points();

    if (!points.length) {
      return html`
        <div class="top"><h3>${TITLE}</h3></div>
        <p class="note">
          No dates in this report, so there is nothing to put on the x axis. On
          the Query tab set <code>EDIT DIMENSIONS</code> to the date field first
          and the metric second, both as Group By.
        </p>`;
    }

    return html`
      <div class="top">
        <h3>${TITLE}</h3>
        <select @change=${(e) => { this.days = Number(e.target.value); }}>
          ${[7, 14, 30, 90].map((n) => html`
            <option value=${n} ?selected=${n === this.days}>Last ${n} days</option>`)}
        </select>
      </div>
      ${this.chart(points)}`;
  }

  chart(points) {
    const width = 640;
    const height = 240;
    const pad = { top: 14, right: 16, bottom: 30, left: 42 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;

    const max = Math.max(1, ...points.map((p) => p.value));
    const step = Math.max(1, Math.ceil(max / 4));
    const top = step * 4;
    const x = (i) => pad.left + (points.length === 1 ? plotW / 2 : (i / (points.length - 1)) * plotW);
    const y = (v) => pad.top + plotH - (v / top) * plotH;
    const path = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(p.value)}`).join(' ');
    const every = Math.max(1, Math.ceil(points.length / 7));

    return html`
      <svg viewBox="0 0 ${width} ${height}" width="100%" height=${height}
           role="img" aria-label="${TITLE} per day over the last ${points.length} days">
        ${[0, 1, 2, 3, 4].map((n) => {
          const tick = step * n;
          return html`
            <line x1=${pad.left} x2=${width - pad.right} y1=${y(tick)} y2=${y(tick)}
                  stroke="var(--grid)" stroke-width="1"></line>
            <text x=${pad.left - 8} y=${y(tick) + 4} text-anchor="end" font-size="11"
                  fill="var(--muted)">${tick}</text>`;
        })}

        ${points.map((p, i) => (i % every === 0 || i === points.length - 1 ? html`
          <text x=${x(i)} y=${height - 10} text-anchor="middle" font-size="11"
                fill="var(--muted)">${p.date.slice(5)}</text>` : null))}

        <path d=${path} fill="none" stroke="var(--line)" stroke-width="2"
              stroke-linejoin="round" stroke-linecap="round"></path>

        ${points.map((p, i) => html`
          <g>
            <circle cx=${x(i)} cy=${y(p.value)} r="4" fill="var(--line)"></circle>
            <title>${p.date}: ${p.value}</title>
          </g>`)}

        ${/* A number on every point collides once the window widens, so label
              them only while they fit, and otherwise just the latest. */
          points.length <= 10
            ? points.map((p, i) => html`
                <text x=${x(i)} y=${y(p.value) - 9} text-anchor="middle" font-size="11"
                      fill="var(--ink-2)">${p.value}</text>`)
            : html`
                <text x=${x(points.length - 1)} y=${y(points[points.length - 1].value) - 9}
                      text-anchor="end" font-size="11" fill="var(--ink-2)"
                      >${points[points.length - 1].value}</text>`}
      </svg>`;
  }
}
