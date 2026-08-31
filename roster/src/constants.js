'use strict';

/** The four shifts an employee can be placed in for the whole month. */
const SHIFTS = ['Morning', 'Afternoon', 'Evening', 'Night'];

/**
 * Week-off length per shift (rule 4):
 *   Night  -> 3 offs + 4 consecutive working days
 *   others -> 2 offs + 5 consecutive working days
 */
const OFF_DAYS_PER_WEEK = { Morning: 2, Afternoon: 2, Evening: 2, Night: 3 };

/**
 * Rule 5 (coverage): every client needs somebody on duty in every shift on
 * every day. A person is off 2-3 days a week, so a client/shift pair needs at
 * least this many people before the off blocks can be staggered to cover 7/7.
 */
const MIN_EMPLOYEES_PER_CLIENT_SHIFT = 2;

/** Monday-first week, matching the "Mon-01-Jul" column labels. */
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

const OFF_LABEL = 'Off';

module.exports = {
  SHIFTS,
  OFF_DAYS_PER_WEEK,
  MIN_EMPLOYEES_PER_CLIENT_SHIFT,
  WEEKDAYS,
  MONTHS,
  OFF_LABEL,
};
