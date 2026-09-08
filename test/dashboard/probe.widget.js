/**
 * Minimal Turbine report widget - a probe, not a dashboard.
 *
 * Paste this in first. It renders one heading and a dump of everything the
 * element can see, so two questions get answered at once:
 *
 *   1. Does a widget render here at all? If this shows nothing either, the
 *      problem is the widget contract, not the data.
 *   2. What property holds the report rows, and what shape are they?
 *
 * Nothing here can fail on data: it never assumes a property exists.
 */

import { SwimlaneElement, html, css } from '@swimlane/swimlane-element';

export default class ProbeWidget extends SwimlaneElement {
  static get styles() {
    return css`
      :host { display: block; font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; }
      .box { background: #1a1a19; color: #e8e8e4; padding: 12px; border-radius: 8px; }
      h3 { margin: 0 0 8px; font-size: 13px; color: #7fd1a8; font-family: sans-serif; }
      .k { color: #7fb2f0; }
      .t { color: #d99a5b; }
      pre { white-space: pre-wrap; word-break: break-word; margin: 6px 0 0;
            max-height: 340px; overflow: auto; background: #0d0d0d; padding: 8px;
            border-radius: 6px; }
      li { margin: 2px 0; }
    `;
  }

  describe(value) {
    if (value === null) return 'null';
    if (Array.isArray(value)) return `array[${value.length}]`;
    if (value instanceof Date) return 'Date';
    if (typeof value === 'object') return `object{${Object.keys(value).slice(0, 8).join(',')}}`;
    if (typeof value === 'string') return `string "${value.slice(0, 40)}"`;
    return typeof value;
  }

  /** First array of objects found anywhere shallow on the element. */
  firstArray() {
    for (const key of Object.keys(this)) {
      const value = this[key];
      if (Array.isArray(value) && value.length && typeof value[0] === 'object') {
        return { key, sample: value[0], count: value.length };
      }
      if (value && typeof value === 'object') {
        for (const inner of Object.keys(value)) {
          const nested = value[inner];
          if (Array.isArray(nested) && nested.length && typeof nested[0] === 'object') {
            return { key: `${key}.${inner}`, sample: nested[0], count: nested.length };
          }
        }
      }
    }
    return null;
  }

  render() {
    const keys = Object.keys(this);
    const found = this.firstArray();
    return html`
      <div class="box">
        <h3>Probe widget is rendering.</h3>
        <div>Properties on this element (${keys.length}):</div>
        <ul>
          ${keys.length
            ? keys.map((k) => html`<li><span class="k">${k}</span> <span class="t">${this.describe(this[k])}</span></li>`)
            : html`<li>none</li>`}
        </ul>
        ${found ? html`
          <div>First row array: <span class="k">${found.key}</span> (${found.count} rows). One row:</div>
          <pre>${JSON.stringify(found.sample, null, 2)}</pre>`
          : html`<div>No array of objects found on the element.</div>`}
      </div>`;
  }
}

if (typeof customElements !== 'undefined' && !customElements.get('probe-widget')) {
  customElements.define('probe-widget', ProbeWidget);
}
