'use strict';

const { WEEKDAYS, MONTHS } = require('./constants');

/**
 * Expands "YYYY-MM" into the days of that month, each carrying a Monday-based
 * weekday index and the "Mon-01-Jul" column label used in the output table.
 */
function buildMonth(monthSpec) {
  const match = /^(\d{4})-(\d{1,2})$/.exec(String(monthSpec).trim());
  if (!match) throw new Error(`Month must look like "2025-07", got "${monthSpec}".`);

  const year = Number(match[1]);
  const month = Number(match[2]); // 1-12
  if (month < 1 || month > 12) throw new Error(`Month ${month} is out of range.`);

  const dayCount = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const days = [];
  for (let day = 1; day <= dayCount; day++) {
    const date = new Date(Date.UTC(year, month - 1, day));
    const dow = (date.getUTCDay() + 6) % 7; // 0 = Monday
    days.push({
      day,
      dow,
      date,
      label: `${WEEKDAYS[dow]}-${String(day).padStart(2, '0')}-${MONTHS[month - 1]}`,
    });
  }
  return { year, month, monthName: MONTHS[month - 1], days };
}

module.exports = { buildMonth };
