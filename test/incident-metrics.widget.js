/**
 * Simple report widget for a grouped report.
 *
 * Built for a report configured as:
 *   EDIT MEASURES    open_inc_total
 *   EDIT DIMENSIONS  Date  (Group By)
 *
 * That gives `this.report.data` as:
 *   [{ name: '<group>', series: [{ name: '<date>', value: <number> }] }]
 *
 * The widget plots that series as bars, newest last, with a table underneath.
 * It also prints what the report is actually measuring, because on a text field
 * the only aggregation available is "Count of", which counts records rather
 * than the values inside them.
 */

import { SwimlaneElement, css, html } from '@swimlane/swimlane-element@2';

export default class extends SwimlaneElement {
  static get properties() {
    return { groupIndex: { type: Number } };
  }

  constructor() {
    super();
    this.groupIndex = 0;
  }

  static get styles() {
    return [
      super.styles,
      css`
        :host { display: block; --bar: #2a78d6; --ink-2: #52514e; --muted: #898781;
                --grid: #e1e0d9; }
        @media (prefers-color-scheme: dark) {
          :host { --bar: #3987e5; --ink-2: #c3c2b7; --grid: #2c2c2a; }
        }
        h3 { margin: 0 0 2px; font-size: 14px; font-weight: 600; }
        .note { margin: 0 0 12px; font-size: 12px; color: var(--ink-2); }
        .warn { color: #b06a00; }
        select { font: inherit; color: inherit; background: transparent;
                 border: 1px solid var(--grid); border-radius: 6px; padding: 4px 8px;
                 margin-bottom: 10px; }
        .row { display: flex; align-items: center; gap: 8px; margin: 4px 0; font-size: 12px; }
        .row .lbl { width: 96px; color: var(--ink-2); text-align: right;
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .row .track { flex: 1; height: 12px; background: rgba(127,127,127,.14);
                      border-radius: 6px; }
        .row .fill { display: block; height: 12px; border-radius: 6px; background: var(--bar); }
        .row .n { width: 48px; text-align: right; font-weight: 600;
                  font-variant-numeric: tabular-nums; }
        .stats { display: flex; gap: 22px; margin: 12px 0 4px; }
        .stat b { display: block; font-size: 20px; font-variant-numeric: tabular-nums; }
        .stat span { font-size: 11px; color: var(--muted); text-transform: uppercase;
                     letter-spacing: .04em; }
        table { width: 100%; border-collapse: collapse; font-size: 12px; margin-top: 6px;
                font-variant-numeric: tabular-nums; }
        th, td { padding: 4px 6px; border-bottom: 1px solid var(--grid); text-align: right; }
        th:first-child, td:first-child { text-align: left; }
        th { color: var(--muted); font-weight: 600; }
        summary { cursor: pointer; color: var(--bar); font-size: 12px; margin-top: 10px; }
        code { background: rgba(127,127,127,.15); padding: 1px 5px; border-radius: 4px; }
      `,
    ];
  }

  // The report arrives after the first render, so ask for another one.
  firstUpdated() {
    super.firstUpdated();
    if (this.report) this.requestUpdate();
  }

  updated(changed) {
    super.updated(changed);
    if (changed.has('report') && this.report) this.requestUpdate();
  }

  /** What the report is measuring, straight from its own query. */
  measureNote() {
    const query = (this.report && this.report.query) || {};
    const measures = query.measures || [];
    const aggregate = measures.length ? measures[0].aggregateType : null;
    if (!aggregate) return null;
    if (String(aggregate).toLowerCase().includes('count')) {
      return html`<span class="warn">Measure is <code>${aggregate}</code>, which counts
        records rather than the values inside them.</span>`;
    }
    return html`Measure: <code>${aggregate}</code>.`;
  }

  render() {
    const groups = (this.report && this.report.data) || [];
    if (!groups.length) {
      return html`
        <h3>Incident metrics</h3>
        <p class="note">
          This report returned no groups. Set a measure and a Group By on the
          report's Query tab, then reopen the widget.
        </p>`;
    }

    const index = Math.min(this.groupIndex, groups.length - 1);
    const group = groups[index] || {};
    const series = (group.series || []).map((item) => ({
      label: String(item.name == null ? '' : item.name),
      value: Number(item.value) || 0,
    }));

    const max = Math.max(1, ...series.map((s) => s.value));
    const total = series.reduce((sum, s) => sum + s.value, 0);
    const average = series.length ? Math.round((total / series.length) * 100) / 100 : 0;
    const latest = series.length ? series[series.length - 1] : null;

    return html`
      <h3>${group.name || 'Incident metrics'}</h3>
      <p class="note">
        ${series.length} point${series.length === 1 ? '' : 's'}. ${this.measureNote()}
      </p>

      ${groups.length > 1 ? html`
        <select @change=${(e) => { this.groupIndex = Number(e.target.value); }}>
          ${groups.map((g, i) => html`
            <option value=${i} ?selected=${i === index}>${g.name}</option>`)}
        </select>` : null}

      <div class="stats">
        <span class="stat"><b>${total.toLocaleString()}</b><span>Total</span></span>
        <span class="stat"><b>${average.toLocaleString()}</b><span>Average</span></span>
        <span class="stat"><b>${latest ? latest.value.toLocaleString() : '--'}</b>
          <span>Latest</span></span>
      </div>

      ${series.map((point) => html`
        <div class="row">
          <span class="lbl" title=${point.label}>${point.label}</span>
          <span class="track">
            <span class="fill" style="width:${(point.value / max) * 100}%"></span>
          </span>
          <span class="n">${point.value.toLocaleString()}</span>
        </div>`)}

      <details>
        <summary>Show the numbers</summary>
        <table>
          <thead><tr><th>Group</th><th>Value</th></tr></thead>
          <tbody>
            ${series.map((point) => html`
              <tr><td>${point.label}</td><td>${point.value.toLocaleString()}</td></tr>`)}
          </tbody>
        </table>
      </details>`;
  }
}
