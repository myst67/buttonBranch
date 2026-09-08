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

import { SwimlaneElement, css, html, svg } from '@swimlane/swimlane-element@2';

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
        /* Turbine renders dark without setting prefers-color-scheme, so the
           chrome is drawn from the host's own text colour at low opacity and
           reads correctly on any background. Only the series keeps a fixed
           hue. */
        :host { display: block; --line: #3987e5; --fill: rgba(57, 135, 229, .18); }
        .top { display: flex; align-items: baseline; justify-content: space-between;
               gap: 12px; margin-bottom: 6px; }
        h3 { margin: 0; font-size: 14px; font-weight: 600; }
        select { font: inherit; color: inherit; background: transparent;
                 border: 1px solid currentColor; border-radius: 6px; padding: 3px 7px;
                 opacity: .8; }
        .note { margin: 4px 0 0; font-size: 12px; opacity: .75; }
        details { margin-top: 10px; font-size: 12px; }
        summary { cursor: pointer; opacity: .8; }
        code { background: rgba(127,127,127,.2); padding: 1px 5px; border-radius: 4px; }
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
    // How many readings landed on each day. More than one means the playbook
    // created several records for that date instead of updating one.
    this.perDay = new Map();

    groups.forEach((group) => {
      const groupDate = this.toDate(group.name);
      (group.series || []).forEach((item) => {
        const date = groupDate || this.toDate(item.name);
        if (!date) return;
        const value = groupDate
          ? this.valueOf(item.name, item.value)
          : Number(item.value) || 0;
        this.perDay.set(date, (this.perDay.get(date) || 0) + 1);
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

    if (!points.length) return this.renderNoDates();

    return html`
      <div class="top">
        <h3>${TITLE}</h3>
        <select @change=${(e) => { this.days = Number(e.target.value); }}>
          ${[7, 14, 30, 90].map((n) => html`
            <option value=${n} ?selected=${n === this.days}>Last ${n} days</option>`)}
        </select>
      </div>
      ${this.chart(points)}
      ${this.dataNote(points)}
      ${this.sourceDetail()}`;
  }

  /**
   * What the report actually handed over. Always available, because when a
   * chart is thinner than expected the answer is in here and guessing at it
   * from the outside is slow.
   */
  sourceDetail() {
    const groups = (this.report && this.report.data) || [];
    const perDay = this.perDay || new Map();
    const names = groups.map((g) => String(g.name == null ? 'null' : g.name));
    const dated = names.filter((n) => this.toDate(n));

    return html`
      <details>
        <summary>What this report sent</summary>
        <p class="note">
          ${groups.length} group(s), of which ${dated.length} parse as a date.
          ${perDay.size} day(s) charted.
        </p>
        <p class="note">
          Group names:
          ${names.slice(0, 12).map((n) => html`<code>${n.slice(0, 40)}</code> `)}
          ${names.length > 12 ? html`and ${names.length - 12} more` : null}
        </p>
        ${groups.length <= 1 ? html`
          <p class="note">
            Only one group came back. If the application holds more days than
            that, the report is paginated and the widget is seeing one page:
            raise the report's page size, or remove the second dimension so each
            day is its own group.
          </p>` : null}
      </details>`;
  }

  /**
   * Says why a chart looks thinner than expected, which is nearly always the
   * data rather than the chart.
   */
  dataNote(points) {
    const perDay = this.perDay || new Map();
    const readings = [...perDay.values()].reduce((sum, n) => sum + n, 0);
    const busiest = Math.max(0, ...perDay.values());

    if (points.length === 1 && busiest > 1) {
      return html`
        <p class="note">
          ${readings} records all carry the date ${points[0].date}, so there is
          one day to plot. Each playbook run is creating a record rather than
          updating that day's, which is what the upsert key is for. The highest
          reading is charted.
        </p>`;
    }
    if (points.length === 1) {
      return html`
        <p class="note">
          One day recorded so far. The line builds as the playbook runs each day.
        </p>`;
    }
    if (busiest > 1) {
      return html`
        <p class="note">
          ${readings} records across ${points.length} days, so some days hold
          more than one. The highest reading for each day is charted.
        </p>`;
    }
    return null;
  }

  /**
   * No date could be read, so show what the report actually sent. Guessing at
   * the shape from the outside is what makes this slow; the labels themselves
   * settle it.
   */
  renderNoDates() {
    const groups = (this.report && this.report.data) || [];
    const trim = (value, n) => {
      const text = String(value == null ? 'null' : value);
      return text.length > n ? `${text.slice(0, n)}...` : text;
    };

    return html`
      <div class="top"><h3>${TITLE}</h3></div>
      <p class="note">
        No date could be read from this report, so there is nothing for the x
        axis. On the Query tab set <code>EDIT DIMENSIONS</code> to the date
        field first and the metric second, both as Group By.
      </p>
      ${groups.length ? html`
        <p class="note">What this report sent, ${groups.length} group(s):</p>
        <ul class="note">
          ${groups.slice(0, 6).map((g) => html`
            <li>
              group <code>${trim(g.name, 60)}</code>
              — ${(g.series || []).length} series, first label
              <code>${trim((g.series || [])[0] && (g.series || [])[0].name, 90)}</code>
            </li>`)}
        </ul>
        <p class="note">
          If a group name above is your date, it is not parsing; send it to me
          and I will match it.
        </p>`
      : html`<p class="note">The report sent no groups at all.</p>`}`;
  }

  chart(points) {
    const width = 640;
    const height = 240;
    const pad = { top: 14, right: 16, bottom: 30, left: 46 };
    const plotW = width - pad.left - pad.right;
    const plotH = height - pad.top - pad.bottom;

    const max = Math.max(1, ...points.map((p) => p.value));
    const step = Math.max(1, Math.ceil(max / 4));
    const top = step * 4;
    const x = (i) => pad.left + (points.length === 1 ? plotW / 2 : (i / (points.length - 1)) * plotW);
    const y = (v) => pad.top + plotH - (v / top) * plotH;

    const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(p.value)}`).join(' ');
    // The same path closed to the baseline, so the line reads as an area.
    const area = `${line} L${x(points.length - 1)},${pad.top + plotH} `
      + `L${x(0)},${pad.top + plotH} Z`;
    const every = Math.max(1, Math.ceil(points.length / 7));
    const last = points[points.length - 1];
    // A label above a high point would be clipped by the top edge, so it flips
    // underneath once there is no room for it.
    const labelY = (v) => (y(v) - 10 < pad.top + 4 ? y(v) + 16 : y(v) - 10);

    // Everything nested inside <svg> is built with the `svg` tag, not `html`.
    // A fragment built with `html` is parsed in the HTML namespace, so it is
    // appended but never drawn - the chart comes out blank.
    return html`
      <svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}"
           role="img" aria-label="${TITLE} per day over the last ${points.length} days">
        ${[0, 1, 2, 3, 4].map((n) => {
          const tick = step * n;
          return svg`
            <line x1="${pad.left}" x2="${width - pad.right}" y1="${y(tick)}" y2="${y(tick)}"
                  stroke="currentColor" stroke-opacity="0.14" stroke-width="1"></line>
            <text x="${pad.left - 8}" y="${y(tick) + 4}" text-anchor="end" font-size="11"
                  fill="currentColor" fill-opacity="0.55">${tick}</text>`;
        })}

        ${points.map((p, i) => (i % every === 0 || i === points.length - 1
          ? svg`<text x="${x(i)}" y="${height - 10}" text-anchor="middle" font-size="11"
                      fill="currentColor" fill-opacity="0.55">${p.date.slice(5)}</text>`
          : null))}

        <path d="${area}" fill="var(--fill)" stroke="none"></path>
        <path d="${line}" fill="none" stroke="var(--line)" stroke-width="2"
              stroke-linejoin="round" stroke-linecap="round"></path>

        ${points.map((p, i) => svg`
          <circle cx="${x(i)}" cy="${y(p.value)}" r="4" fill="var(--line)">
            <title>${p.date}: ${p.value}</title>
          </circle>`)}

        ${points.length <= 10
          ? points.map((p, i) => svg`
              <text x="${x(i)}" y="${labelY(p.value)}" text-anchor="middle" font-size="11"
                    fill="currentColor" fill-opacity="0.85">${p.value}</text>`)
          : svg`<text x="${x(points.length - 1)}" y="${labelY(last.value)}" text-anchor="end"
                      font-size="11" fill="currentColor" fill-opacity="0.85">${last.value}</text>`}
      </svg>`;
  }
}
