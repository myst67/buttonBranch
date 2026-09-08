/**
 * Incident metrics report widget.
 *
 * Reads `this.report.data`, whose series labels are the values stored on the
 * record. Where a metric is stored as JSON, the label is that JSON and the
 * number wanted is inside it, so the label is parsed rather than printed.
 *
 * Two shapes are handled, and the widget picks whichever the data supports:
 *
 *   TIMELINE      the parsed labels carry a snapshot_date, so each point is a
 *                 day and the metric's own value is plotted against it
 *   DISTRIBUTION  they do not, so the chart shows how many records held each
 *                 value: "29 days at 0, one day at 2"
 *
 * The distribution is what an aggregated report over a text field can support:
 * its measure counts records, not the values inside them. The timeline appears
 * on its own once the stored objects carry their date.
 */

import { SwimlaneElement, css, html } from '@swimlane/swimlane-element@2';

export default class extends SwimlaneElement {
  static get properties() {
    return { groupIndex: { type: Number }, selected: { type: Number } };
  }

  constructor() {
    super();
    this.groupIndex = 0;
    this.selected = null;
  }

  static get styles() {
    return [
      super.styles,
      css`
        :host { display: block; --bar: #2a78d6; --bar-2: #eb6834; --ink-2: #52514e;
                --muted: #898781; --grid: #e1e0d9; }
        @media (prefers-color-scheme: dark) {
          :host { --bar: #3987e5; --bar-2: #d95926; --ink-2: #c3c2b7; --grid: #2c2c2a; }
        }
        h3 { margin: 0 0 2px; font-size: 14px; font-weight: 600; }
        .note { margin: 0 0 10px; font-size: 12px; color: var(--ink-2); }
        .mode { font-size: 11px; text-transform: uppercase; letter-spacing: .05em;
                color: var(--muted); }
        select { font: inherit; color: inherit; background: transparent;
                 border: 1px solid var(--grid); border-radius: 6px; padding: 4px 8px;
                 margin-bottom: 10px; }
        .stats { display: flex; gap: 24px; margin: 10px 0 12px; }
        .stat b { display: block; font-size: 21px; font-variant-numeric: tabular-nums; }
        .stat span { font-size: 11px; color: var(--muted); text-transform: uppercase;
                     letter-spacing: .04em; }
        .row { display: flex; align-items: center; gap: 8px; margin: 4px 0; font-size: 12px;
               cursor: pointer; }
        .row.on .fill { background: var(--bar-2); }
        .row .lbl { width: 108px; color: var(--ink-2); text-align: right;
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .row .track { flex: 1; height: 12px; background: rgba(127,127,127,.14);
                      border-radius: 6px; }
        .row .fill { display: block; height: 12px; border-radius: 6px; background: var(--bar); }
        .row .n { width: 54px; text-align: right; font-weight: 600;
                  font-variant-numeric: tabular-nums; }
        .bd { margin: 10px 0 0; padding: 10px; border: 1px solid var(--grid);
              border-radius: 8px; }
        .bd h4 { margin: 0 0 6px; font-size: 12px; font-weight: 600; }
        .bd .row { cursor: default; }
        .bd .lbl { width: 128px; }
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

  firstUpdated() {
    super.firstUpdated();
    if (this.report) this.requestUpdate();
  }

  updated(changed) {
    super.updated(changed);
    if (changed.has('report') && this.report) this.requestUpdate();
  }

  /* ------------------------------------------------------------------ data */

  /** A series label is either plain text or the stored metric object. */
  parseLabel(label) {
    const text = String(label == null ? '' : label);
    if (!text.startsWith('{')) return null;
    try {
      return JSON.parse(text);
    } catch (error) {
      return null;
    }
  }

  /** Points for the selected group, plus what they can support. */
  read() {
    const groups = (this.report && this.report.data) || [];
    const index = Math.min(this.groupIndex, Math.max(0, groups.length - 1));
    const group = groups[index] || {};

    const points = (group.series || []).map((item) => {
      const parsed = this.parseLabel(item.name);
      const inner = parsed && parsed.value;
      return {
        // How many records held this value.
        records: Number(item.value) || 0,
        // The metric's own number, when the label carried it.
        value: inner && typeof inner === 'object' ? inner.avg : inner,
        date: parsed && parsed.snapshot_date ? String(parsed.snapshot_date).slice(0, 10) : null,
        breakdown: (parsed && parsed.breakdown) || [],
        description: (parsed && parsed.description) || '',
        raw: String(item.name == null ? '' : item.name),
      };
    });

    const timeline = points.length > 0 && points.every((p) => p.date);
    if (timeline) points.sort((a, b) => a.date.localeCompare(b.date));
    else points.sort((a, b) => (Number(a.value) || 0) - (Number(b.value) || 0));

    return { groups, index, group, points, timeline };
  }

  /* ---------------------------------------------------------------- render */

  render() {
    const { groups, index, group, points, timeline } = this.read();

    if (!groups.length) {
      return html`
        <h3>Incident metrics</h3>
        <p class="note">
          This report returned no groups. Set a measure and a Group By on the
          report's Query tab, then reopen the widget.
        </p>`;
    }

    const described = points.find((p) => p.description);
    const totalRecords = points.reduce((sum, p) => sum + p.records, 0);
    const bars = timeline
      ? points.map((p) => ({ label: p.date, amount: Number(p.value) || 0, point: p }))
      : points.map((p) => ({
          label: p.value == null ? p.raw.slice(0, 24) : `value ${p.value}`,
          amount: p.records,
          point: p,
        }));
    const max = Math.max(1, ...bars.map((b) => b.amount));

    const selected = this.selected != null && bars[this.selected]
      ? bars[this.selected].point
      : (points.find((p) => p.breakdown && p.breakdown.length) || null);
    const dimensions = selected
      ? [...new Set(selected.breakdown.map((b) => b.dimension))] : [];

    return html`
      <h3>${described ? described.description : (group.name || 'Incident metrics')}</h3>
      <p class="note">
        <span class="mode">${timeline ? 'Timeline' : 'Distribution'}</span> ·
        ${timeline
          ? html`${points.length} day${points.length === 1 ? '' : 's'}, plotting each day's value.`
          : html`${totalRecords} record${totalRecords === 1 ? '' : 's'} across
                 ${points.length} distinct value${points.length === 1 ? '' : 's'}.
                 The report counts records, so it cannot place them in time;
                 each bar is how many records held that value.`}
      </p>

      ${groups.length > 1 ? html`
        <select @change=${(e) => { this.groupIndex = Number(e.target.value); this.selected = null; }}>
          ${groups.map((g, i) => html`
            <option value=${i} ?selected=${i === index}>${g.name}</option>`)}
        </select>` : null}

      <div class="stats">
        ${timeline ? html`
          <span class="stat">
            <b>${bars.length ? bars[bars.length - 1].amount.toLocaleString() : '--'}</b>
            <span>Latest</span></span>
          <span class="stat">
            <b>${Math.max(...bars.map((b) => b.amount)).toLocaleString()}</b>
            <span>Peak</span></span>
          <span class="stat">
            <b>${Math.round((bars.reduce((s, b) => s + b.amount, 0) / bars.length) * 100) / 100}</b>
            <span>Mean</span></span>`
        : html`
          <span class="stat"><b>${totalRecords.toLocaleString()}</b><span>Records</span></span>
          <span class="stat">
            <b>${points.length ? (points[points.length - 1].value ?? '--') : '--'}</b>
            <span>Highest value</span></span>
          <span class="stat">
            <b>${(() => {
              const weighted = points.reduce((s, p) => s + (Number(p.value) || 0) * p.records, 0);
              return totalRecords ? Math.round((weighted / totalRecords) * 100) / 100 : 0;
            })()}</b>
            <span>Mean value</span></span>`}
      </div>

      ${bars.map((bar, i) => html`
        <div class="row ${selected === bar.point ? 'on' : ''}"
             @click=${() => { this.selected = i; }} title=${bar.point.raw}>
          <span class="lbl">${bar.label}</span>
          <span class="track">
            <span class="fill" style="width:${(bar.amount / max) * 100}%"></span>
          </span>
          <span class="n">${bar.amount.toLocaleString()}</span>
        </div>`)}

      ${selected && selected.breakdown.length ? html`
        <div class="bd">
          <h4>Breakdown${selected.date ? html` · ${selected.date}`
                        : html` · value ${selected.value}`}</h4>
          ${dimensions.map((dim) => html`
            ${selected.breakdown.filter((b) => b.dimension === dim).map((b) => html`
              <div class="row">
                <span class="lbl">${dim} · ${b.label}</span>
                <span class="track">
                  <span class="fill" style="width:${(b.count
                    / Math.max(1, ...selected.breakdown.map((x) => x.count))) * 100}%"></span>
                </span>
                <span class="n">${b.count}</span>
              </div>`)}`)}
        </div>` : null}

      <details>
        <summary>Show the numbers</summary>
        <table>
          <thead><tr>
            <th>${timeline ? 'Date' : 'Value'}</th>
            <th>${timeline ? 'Value' : 'Records'}</th>
          </tr></thead>
          <tbody>
            ${bars.map((bar) => html`
              <tr><td>${bar.label}</td><td>${bar.amount.toLocaleString()}</td></tr>`)}
          </tbody>
        </table>
      </details>`;
  }
}
