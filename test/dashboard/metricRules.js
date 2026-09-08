/**
 * How each metric behaves over time, and how it combines across days.
 *
 * This is the only place the dashboard encodes metric semantics. Everything
 * else - tiles, charts, the timeline dropdown - reads from here.
 *
 * The rules exist because most metrics cannot be rolled up by averaging daily
 * values. Two days of closures, 100 with 10 false positives and 2 with 1:
 * averaging the daily rates gives 30% against a true 10.8%, and averaging the
 * daily means gives 51h MTTR against a true 3.9h. So flows add, stocks take the
 * last day, and distributions recombine from their stored sum and count.
 */

export const RULES = {
  // Flow: counted during the day, so days add together.
  new_inc_total: { rule: 'sum', label: 'New', unit: '' },
  new_inc_p1p2_count: { rule: 'sum', label: 'New P1/P2', unit: '' },
  new_inc_escalated_count: { rule: 'sum', label: 'New escalated', unit: '' },
  closed_inc_total: { rule: 'sum', label: 'Closed', unit: '' },
  closed_inc_not_resolved: { rule: 'sum', label: 'Closed not resolved', unit: '' },
  closed_inc_same_day_open: { rule: 'sum', label: 'Same-day closes', unit: '' },

  // Stock: a level measured at a moment. Summing 30 days of backlog is
  // meaningless, so a period takes the value from its last day.
  open_inc_total: { rule: 'last', label: 'Open backlog', unit: '' },
  open_more_than_five_days: { rule: 'last', label: 'Open > 5d', unit: '' },
  open_more_than_thirty_days: { rule: 'last', label: 'Open > 30d', unit: '' },
  stale_open_no_update_5d: { rule: 'last', label: 'Stale > 5d', unit: '' },
  unassigned_open_count: { rule: 'last', label: 'Unassigned', unit: '' },
  distinct_agents: { rule: 'last', label: 'Active owners', unit: '' },

  // Peak.
  oldest_open_age: { rule: 'max', label: 'Oldest open', unit: 'd' },

  // Distribution: recombined from sum and count, never by averaging averages.
  age_open_inc: { rule: 'weighted', label: 'Backlog age', unit: 'd' },
  age_last_update_open_inc: { rule: 'weighted', label: 'Days since update', unit: 'd' },
  state_dwell_hours: { rule: 'weighted', label: 'State dwell', unit: 'h' },
  mttr_hours: { rule: 'weighted', label: 'MTTR', unit: 'h' },
  mtta_hours: { rule: 'weighted', label: 'MTTA', unit: 'h' },
  mtta_minutes: { rule: 'weighted', label: 'MTTA', unit: 'm' },
  duration_closed_inc: { rule: 'weighted', label: 'Time to close', unit: 'h' },

  // Rate: recomputed from the period's own numerator and denominator.
  fp_rate: { rule: 'ratio', of: 'false_positive_count', per: 'closed_inc_total', label: 'FP rate', unit: '%' },
  same_day_close_rate: { rule: 'ratio', of: 'closed_inc_same_day_open', per: 'closed_inc_total', label: 'Same-day close rate', unit: '%' },
  true_positive_rate: { rule: 'ratio', of: 'true_positive_count', per: 'closed_inc_total', label: 'True positive rate', unit: '%' },
};

/** Only flow metrics answer to the sum/avg switch. */
export const respondsToMode = (name) => (RULES[name] || {}).rule === 'sum';

export const ruleOf = (name) => (RULES[name] || { rule: 'sum', label: name, unit: '' });

/** How a tile should read a change: for some metrics up is bad. */
export const INTENT = {
  open_inc_total: 'lower', open_more_than_five_days: 'lower',
  open_more_than_thirty_days: 'lower', stale_open_no_update_5d: 'lower',
  oldest_open_age: 'lower', age_open_inc: 'lower', mttr_hours: 'lower',
  mtta_hours: 'lower', state_dwell_hours: 'lower', fp_rate: 'lower',
  age_last_update_open_inc: 'lower', unassigned_open_count: 'lower',
  closed_inc_total: 'higher', same_day_close_rate: 'higher',
  closed_inc_same_day_open: 'higher', distinct_agents: 'neutral',
  new_inc_total: 'neutral', new_inc_p1p2_count: 'neutral',
};
