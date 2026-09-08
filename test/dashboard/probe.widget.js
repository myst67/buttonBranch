/**
 * Probe widget - paste this in first.
 *
 * It renders what the platform actually hands the widget: the shape of
 * `this.report`, one raw row, and the report's query. That tells us the field
 * keys and the aggregation, which is what the real widget needs.
 *
 * Structure matters here, and it is what the platform expects:
 *   - an ANONYMOUS default-export class
 *   - no customElements.define; the platform registers the default export
 *   - styles as `[super.styles, css\`...\`]`, so the frame keeps its own
 */

import { SwimlaneElement, css, html } from '@swimlane/swimlane-element';
import { reportFrameTemplate } from '@swimlane/swimlane-element/templates.js';

export default class extends SwimlaneElement {
  static get styles() {
    return [
      super.styles,
      css`
        .p { font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace; padding: 8px; }
        h4 { margin: 10px 0 4px; font: 600 12px/1.3 sans-serif; }
        pre { white-space: pre-wrap; word-break: break-word; margin: 0;
              max-height: 260px; overflow: auto; padding: 8px; border-radius: 6px;
              background: rgba(127, 127, 127, 0.12); }
      `,
    ];
  }

  render() {
    const report = this.report || {};
    const rawData = Array.isArray(report.rawData) ? report.rawData : [];
    const data = Array.isArray(report.data) ? report.data : [];

    return reportFrameTemplate(html`
      <div class="p">
        <h4>report keys</h4>
        <pre>${Object.keys(report).join(', ') || 'this.report is undefined'}</pre>

        <h4>query</h4>
        <pre>${JSON.stringify(report.query, null, 2) || 'none'}</pre>

        <h4>rawData: ${rawData.length} row(s), first one</h4>
        <pre>${rawData.length ? JSON.stringify(rawData[0], null, 2) : 'empty'}</pre>

        <h4>data (aggregated series): ${data.length} group(s), first one</h4>
        <pre>${data.length ? JSON.stringify(data[0], null, 2) : 'empty'}</pre>

        <h4>application fields (key -> type)</h4>
        <pre>${(this.contextData?.application?.fields || [])
          .map((f) => `${f.key} -> ${f.fieldType}`).join('\n') || 'none'}</pre>
      </div>
    `);
  }
}
