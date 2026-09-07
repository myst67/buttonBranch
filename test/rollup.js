/**
 * Roll daily KPI records up to week, month, quarter or year.
 *
 * Written for a Swimlane custom React widget: no dependencies, pure functions.
 *
 * The reason this module exists: most metrics cannot be rolled up by averaging
 * the daily values. Averaging daily rates or daily means gives badly wrong
 * answers whenever daily volume varies, which it always does. Two days of
 * closures, 100 with 10 false positives and 2 with 1:
 *
 *   averaging the daily rates -> 30.0% FP      recomputed from totals -> 10.8%
 *   averaging the daily means -> 51.0 h MTTR   weighted by volume     ->  3.9 h
 *
 * So every metric declares how it rolls up, and rates and means are always
 * recomputed from their stored numerator and denominator.
 */

/** How each metric combines across days. */
export const ROLLUP_RULES = {
  // Flow metrics: things that happened during the day, so they add up.
  new_inc_total: { rule: 'sum' },
  new_inc_p1p2_count: { rule: 'sum' },
  new_inc_escalated_count: { rule: 'sum' },
  new_inc_acknowledged_count: { rule: 'sum' },
  closed_inc_total: { rule: 'sum' },
  closed_inc_not_resolved: { rule: 'sum' },
  closed_inc_same_day_open: { rule: 'sum' },
  closed_inc_on_first_attempt: { rule: 'sum' },
  false_positive_count: { rule: 'sum' },
  false_positive_high_risk_count: { rule: 'sum' },
  true_positive_count: { rule: 'sum' },
  sla_breached_count: { rule: 'sum' },

  // Stock metrics: a level measured at a moment. Summing 30 days of backlog is
  // meaningless, so the period takes the value from its last day.
  open_inc_total: { rule: 'last' },
  open_more_than_five_days: { rule: 'last' },
  open_more_than_thirty_days: { rule: 'last' },
  stale_open_no_update_5d: { rule: 'last' },
  unassigned_open_count: { rule: 'last' },
  distinct_agents: { rule: 'last' },
  oldest_open_age: { rule: 'max' },

  // Distributions: recombine from the stored sum and count, never by averaging
  // the daily averages.
  age_open_inc: { rule: 'weighted' },
  age_last_update_open_inc: { rule: 'weighted' },
  state_dwell_hours: { rule: 'weighted' },
  mtta_hours: { rule: 'weighted' },
  mtta_minutes: { rule: 'weighted' },
  duration_closed_inc: { rule: 'weighted' },
  duration_false_positive_closed_inc: { rule: 'weighted' },
  mttr_hours: { rule: 'weighted' },
  reassign_count_open_inc: { rule: 'weighted' },
  reassign_count_hist_open: { rule: 'weighted' },
  risk_score_closed_inc: { rule: 'weighted' },
  risk_score_false_positive_inc: { rule: 'weighted' },
  risk_score_high_risk_fp_inc: { rule: 'weighted' },

  // Rates: recomputed from the period's own numerator and denominator.
  fp_rate: { rule: 'ratio', of: 'false_positive_count', per: 'closed_inc_total' },
  same_day_close_rate: { rule: 'ratio', of: 'closed_inc_same_day_open', per: 'closed_inc_total' },
  true_positive_rate: { rule: 'ratio', of: 'true_positive_count', per: 'closed_inc_total' },
  first_close_rate: { rule: 'ratio', of: 'closed_inc_on_first_attempt', per: 'closed_inc_total' },
  sla_breach_rate: { rule: 'ratio', of: 'sla_breached_count', per: 'new_inc_total' },
  sla_compliance_rate: { rule: 'complement', of: 'sla_breach_rate' },
};

const GRAINS = ['day', 'week', 'month', 'quarter', 'year'];

/** The bucket a date belongs to, as a sortable key. */
export function periodKey(isoDate, grain) {
  const date = new Date(isoDate + (isoDate.length === 10 ? 'T00:00:00Z' : ''));
  const year = date.getUTCFullYear();
  const month = date.getUTCMonth();
  switch (grain) {
    case 'day':
      return isoDate.slice(0, 10);
    case 'week': {
      // ISO week: bucket by the Monday that starts it.
      const monday = new Date(date);
      const weekday = (date.getUTCDay() + 6) % 7;
      monday.setUTCDate(date.getUTCDate() - weekday);
      return monday.toISOString().slice(0, 10);
    }
    case 'month':
      return `${year}-${String(month + 1).padStart(2, '0')}`;
    case 'quarter':
      return `${year}-Q${Math.floor(month / 3) + 1}`;
    case 'year':
      return String(year);
    default:
      throw new Error(`unknown grain "${grain}", expected one of ${GRAINS.join(', ')}`);
  }
}

const numeric = (value) => (typeof value === 'number' && isFinite(value) ? value : null);

/** Read one metric's value out of a stored daily record. */
function readMetric(record, name) {
  const entry = (record.metrics || {})[name];
  if (!entry) return null;
  return entry.value;
}

function scalarOf(value) {
  if (value == null) return null;
  if (typeof value === 'object') return numeric(value.avg);
  return numeric(value);
}

/** Sum and count of a distribution metric, for a correct weighted mean. */
function distributionOf(value) {
  if (value == null || typeof value !== 'object') return { sum: null, count: 0 };
  return { sum: numeric(value.sum), count: numeric(value.count) || 0 };
}

/**
 * Merge one metric across the days in a bucket.
 * Returns { value, count } where count is how many days contributed.
 */
function combine(name, days, mode) {
  const spec = ROLLUP_RULES[name] || { rule: 'sum' };
  const values = days.map((d) => readMetric(d, name));
  const present = values.filter((v) => v !== null && v !== undefined);
  if (!present.length) return { value: null, days: 0 };

  switch (spec.rule) {
    case 'sum': {
      const total = present.reduce((acc, v) => acc + (numeric(v) || 0), 0);
      // The dropdown's "avg" view means per-day average of a flow metric.
      return { value: mode === 'avg' ? round(total / present.length) : total, days: present.length };
    }
    case 'last':
      return { value: scalarOf(present[present.length - 1]), days: present.length };
    case 'max':
      return { value: Math.max(...present.map((v) => scalarOf(v) || 0)), days: present.length };
    case 'weighted': {
      // Weighted by how many records each day contributed, so a quiet day
      // cannot swing the period's mean.
      let sum = 0;
      let count = 0;
      present.forEach((v) => {
        const dist = distributionOf(v);
        if (dist.sum !== null) {
          sum += dist.sum;
          count += dist.count;
        }
      });
      return { value: count ? round(sum / count) : null, days: present.length, sum, count };
    }
    default:
      return { value: null, days: present.length };
  }
}

const round = (value, digits = 2) => {
  const factor = 10 ** digits;
  return Math.round(value * factor) / factor;
};

/**
 * Roll daily records up to the chosen grain.
 *
 * @param {Array} records daily records, each { snapshot_date, metrics }
 * @param {string} grain  day | week | month | quarter | year
 * @param {string} mode   'sum' (default) or 'avg', for flow metrics only
 * @returns {Array} one bucket per period, oldest first
 */
export function rollup(records, grain = 'day', mode = 'sum') {
  const buckets = new Map();
  [...records]
    .filter((r) => r && r.snapshot_date)
    .sort((a, b) => a.snapshot_date.localeCompare(b.snapshot_date))
    .forEach((record) => {
      const key = periodKey(record.snapshot_date, grain);
      if (!buckets.has(key)) buckets.set(key, []);
      buckets.get(key).push(record);
    });

  const names = new Set();
  records.forEach((r) => Object.keys(r.metrics || {}).forEach((n) => names.add(n)));

  return [...buckets.entries()].map(([key, days]) => {
    const metrics = {};
    names.forEach((name) => {
      const spec = ROLLUP_RULES[name] || { rule: 'sum' };
      if (spec.rule === 'ratio' || spec.rule === 'complement') return;
      metrics[name] = combine(name, days, mode);
    });

    // Rates last, so their numerator and denominator are already rolled up.
    names.forEach((name) => {
      const spec = ROLLUP_RULES[name];
      if (!spec) return;
      if (spec.rule === 'ratio') {
        const of = metrics[spec.of] && metrics[spec.of].value;
        const per = metrics[spec.per] && metrics[spec.per].value;
        metrics[name] = {
          value: per ? round((of / per) * 100) : 0,
          days: days.length,
          of: of ?? null,
          per: per ?? null,
        };
      } else if (spec.rule === 'complement') {
        const base = metrics[spec.of] && metrics[spec.of].value;
        metrics[name] = { value: base == null ? null : round(100 - base), days: days.length };
      }
    });

    return {
      period: key,
      grain,
      days: days.length,
      from: days[0].snapshot_date,
      to: days[days.length - 1].snapshot_date,
      metrics,
    };
  });
}

/**
 * Merge one metric's breakdown across days, for a chart of the whole period.
 * Counts add up; means are re-weighted by their own counts.
 */
export function mergeBreakdown(records, metricName, dimension) {
  const totals = new Map();
  records.forEach((record) => {
    const entry = (record.metrics || {})[metricName];
    const rows = entry && entry.breakdown && entry.breakdown[dimension];
    (rows || []).forEach((row) => {
      const current = totals.get(row.label) || { label: row.label, count: 0, sum: 0 };
      current.count += row.count || 0;
      current.sum += row.sum != null ? row.sum : 0;
      totals.set(row.label, current);
    });
  });
  return [...totals.values()]
    .map((row) => ({
      label: row.label,
      count: row.count,
      avg: row.count ? round(row.sum / row.count) : null,
      sum: round(row.sum),
    }))
    .sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
}

/** A single metric as a time series, ready for a chart. */
export function series(records, metricName, grain = 'day', mode = 'sum') {
  return rollup(records, grain, mode).map((bucket) => ({
    period: bucket.period,
    value: bucket.metrics[metricName] ? bucket.metrics[metricName].value : null,
  }));
}

export const GRAIN_OPTIONS = GRAINS;
