/**
 * The timeline dropdown: each preset is a window of days plus a grouping grain.
 *
 * Both parts matter. "Last 7 days" is seven daily points; "Monthly" is every
 * day you have, grouped into months. Presets that name a period-to-date window
 * are anchored on today, so a month-to-date view never reaches into last month.
 */

export const PRESETS = [
  { id: 'last_7_days', label: 'Last 7 days', days: 7, grain: 'day' },
  { id: 'last_14_days', label: 'Last 14 days', days: 14, grain: 'day' },
  { id: 'last_30_days', label: 'Last 30 days', days: 30, grain: 'day' },
  { id: 'last_90_days', label: 'Last 90 days', days: 90, grain: 'day' },
  { id: 'wtd', label: 'Week to date', anchor: 'week', grain: 'day' },
  { id: 'mtd', label: 'Month to date', anchor: 'month', grain: 'day' },
  { id: 'qtd', label: 'Quarter to date', anchor: 'quarter', grain: 'day' },
  { id: 'ytd', label: 'Year to date', anchor: 'year', grain: 'day' },
  { id: 'weekly_13', label: 'Weekly, last 13 weeks', days: 91, grain: 'week' },
  { id: 'monthly_12', label: 'Monthly, last 12 months', days: 366, grain: 'month' },
  { id: 'quarterly_8', label: 'Quarterly, last 8 quarters', days: 731, grain: 'quarter' },
  { id: 'yearly_all', label: 'Yearly, all time', grain: 'year' },
  { id: 'all_daily', label: 'All time, daily', grain: 'day' },
];

const dayMs = 86400000;
const iso = (date) => date.toISOString().slice(0, 10);

/** Start of the calendar period containing `date`. */
function anchorStart(date, anchor) {
  const start = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  if (anchor === 'week') {
    // ISO week, Monday start.
    start.setUTCDate(start.getUTCDate() - ((start.getUTCDay() + 6) % 7));
  } else if (anchor === 'month') {
    start.setUTCDate(1);
  } else if (anchor === 'quarter') {
    start.setUTCMonth(Math.floor(start.getUTCMonth() / 3) * 3, 1);
  } else if (anchor === 'year') {
    start.setUTCMonth(0, 1);
  }
  return start;
}

/**
 * Narrow daily records to a preset's window.
 * `today` is passed in rather than read from the clock, so the view is testable
 * and a demo can be pinned to a date.
 */
export function applyWindow(records, preset, today = new Date()) {
  if (!preset) return records;
  if (preset.anchor) {
    const from = iso(anchorStart(today, preset.anchor));
    return records.filter((r) => r.snapshot_date >= from);
  }
  if (preset.days) {
    const from = iso(new Date(today.getTime() - (preset.days - 1) * dayMs));
    return records.filter((r) => r.snapshot_date >= from);
  }
  return records;
}

/** The bucket a date belongs to, as a sortable key. */
export function periodKey(isoDate, grain) {
  const date = new Date(`${isoDate.slice(0, 10)}T00:00:00Z`);
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth();
  if (grain === 'day') return isoDate.slice(0, 10);
  if (grain === 'week') {
    const monday = new Date(date);
    monday.setUTCDate(date.getUTCDate() - ((date.getUTCDay() + 6) % 7));
    return monday.toISOString().slice(0, 10);
  }
  if (grain === 'month') return `${year}-${String(month + 1).padStart(2, '0')}`;
  if (grain === 'quarter') return `${year}-Q${Math.floor(month / 3) + 1}`;
  if (grain === 'year') return String(year);
  throw new Error(`unknown grain "${grain}"`);
}

/** A short label for an axis tick. */
export function shortLabel(key, grain) {
  if (grain === 'day' || grain === 'week') return key.slice(5).replace('-', '/');
  return key;
}
