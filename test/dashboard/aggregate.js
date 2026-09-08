/**
 * Turn daily records into the buckets a chart or tile renders.
 *
 * Accepts either shape the application might hand over:
 *   { snapshot_date, metrics: { open_inc_total: { value, ... } } }
 *   { snapshot_date, open_inc_total: '{"value":42,...}' }   // one text field per metric
 */

import { RULES, ruleOf, respondsToMode } from './metricRules.js';
import { periodKey } from './timeline.js';

const round = (value, digits = 2) => {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
};

const isNumber = (value) => typeof value === 'number' && isFinite(value);

/** Normalise a stored record, parsing per-metric text fields when that is the shape. */
export function adaptRecord(record) {
  if (!record) return null;
  const date = record.snapshot_date || record['Snapshot Date'] || record['Snapshot Key'];
  if (!date) return null;

  if (record.metrics && typeof record.metrics === 'object') {
    return { snapshot_date: String(date).slice(0, 10), metrics: record.metrics };
  }

  // One text field per metric: parse the ones we recognise, ignore the rest.
  const metrics = {};
  Object.keys(record).forEach((key) => {
    if (!(key in RULES)) return;
    const raw = record[key];
    if (raw == null || raw === '') return;
    if (typeof raw === 'object') {
      metrics[key] = raw;
      return;
    }
    try {
      metrics[key] = JSON.parse(raw);
    } catch (error) {
      // A bare number in the field is still usable.
      const asNumber = Number(raw);
      if (isFinite(asNumber)) metrics[key] = { value: asNumber };
    }
  });
  return { snapshot_date: String(date).slice(0, 10), metrics };
}

export const adaptRecords = (records) =>
  (records || []).map(adaptRecord).filter(Boolean)
    .sort((a, b) => a.snapshot_date.localeCompare(b.snapshot_date));

const entryOf = (record, name) => (record.metrics || {})[name];

/** A metric's headline number for one day, whatever shape it was stored in. */
function scalar(entry) {
  if (!entry) return null;
  const value = entry.value;
  if (value == null) return null;
  if (typeof value === 'object') return isNumber(value.avg) ? value.avg : null;
  return isNumber(value) ? value : null;
}

function distribution(entry) {
  const value = entry && entry.value;
  if (!value || typeof value !== 'object') return null;
  return { sum: isNumber(value.sum) ? value.sum : null, count: isNumber(value.count) ? value.count : 0 };
}

/** Combine one metric across the days in a bucket, by its own rule. */
export function combine(name, days, mode = 'sum') {
  const rule = ruleOf(name);
  const entries = days.map((d) => entryOf(d, name)).filter(Boolean);
  if (!entries.length) return { value: null, days: 0, rule: rule.rule };

  if (rule.rule === 'ratio') {
    const of = combine(rule.of, days, 'sum').value;
    const per = combine(rule.per, days, 'sum').value;
    return { value: per ? round((of / per) * 100) : 0, days: entries.length, rule: 'ratio' };
  }

  const values = entries.map(scalar).filter((v) => v !== null);
  if (rule.rule === 'last') {
    return { value: values.length ? values[values.length - 1] : null, days: entries.length, rule: 'last' };
  }
  if (rule.rule === 'max') {
    return { value: values.length ? Math.max(...values) : null, days: entries.length, rule: 'max' };
  }
  if (rule.rule === 'weighted') {
    let sum = 0;
    let count = 0;
    entries.forEach((entry) => {
      const dist = distribution(entry);
      if (dist && dist.sum !== null) {
        sum += dist.sum;
        count += dist.count;
      }
    });
    // Fall back to a plain mean only when sum/count were never stored.
    if (!count) {
      return values.length
        ? { value: round(values.reduce((a, b) => a + b, 0) / values.length), days: entries.length, rule: 'weighted', approximate: true }
        : { value: null, days: entries.length, rule: 'weighted' };
    }
    return { value: round(sum / count), days: entries.length, rule: 'weighted', count };
  }

  const total = values.reduce((a, b) => a + b, 0);
  return {
    value: mode === 'avg' && values.length ? round(total / values.length) : total,
    days: entries.length,
    rule: 'sum',
  };
}

/** Group records into buckets and roll every metric up inside each one. */
export function bucketize(records, grain = 'day', mode = 'sum') {
  const buckets = new Map();
  records.forEach((record) => {
    const key = periodKey(record.snapshot_date, grain);
    if (!buckets.has(key)) buckets.set(key, []);
    buckets.get(key).push(record);
  });

  const names = new Set();
  records.forEach((r) => Object.keys(r.metrics || {}).forEach((n) => names.add(n)));

  return [...buckets.entries()].map(([key, days]) => {
    const metrics = {};
    names.forEach((name) => {
      metrics[name] = combine(name, days, mode);
    });
    return {
      period: key,
      days: days.length,
      from: days[0].snapshot_date,
      to: days[days.length - 1].snapshot_date,
      metrics,
    };
  });
}

/** One metric across the whole selected window, for a tile. */
export function total(records, name, mode = 'sum') {
  return combine(name, records, mode);
}

/** Period-over-period change, comparing the last bucket with the one before. */
export function delta(buckets, name) {
  if (buckets.length < 2) return null;
  const current = buckets[buckets.length - 1].metrics[name];
  const previous = buckets[buckets.length - 2].metrics[name];
  if (!current || !previous || current.value == null || previous.value == null) return null;
  const change = round(current.value - previous.value);
  return {
    change,
    pct: previous.value ? round((change / Math.abs(previous.value)) * 100, 1) : null,
    direction: change > 0 ? 'up' : change < 0 ? 'down' : 'flat',
  };
}

export { respondsToMode };
