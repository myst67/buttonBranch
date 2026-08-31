'use strict';

const { SHIFTS, OFF_DAYS_PER_WEEK, OFF_LABEL } = require('./constants');
const { MIN_EMPLOYEES_PER_CLIENT } = require('./input');

/**
 * Re-checks the finished roster against every rule, independently of the
 * solvers that produced it - so a bug in the search shows up as a failed
 * check rather than a silently wrong sheet.
 */
function validateRoster(roster) {
  const errors = [];
  const { rows, month } = roster;
  const dayCount = month.days.length;

  // --- Rule 3: one shift for the whole month, different from last month -----
  for (const row of rows) {
    const distinct = [...new Set(row.cells.filter((c) => c !== OFF_LABEL))];
    if (distinct.length !== 1) {
      errors.push(`${row.name}: works ${distinct.length} different shifts this month (${distinct.join(', ')}).`);
    } else if (distinct[0] !== row.shift) {
      errors.push(`${row.name}: shift column says ${row.shift} but the sheet shows ${distinct[0]}.`);
    }
    if (row.shift === row.lastMonthShift) {
      errors.push(`${row.name}: assigned ${row.shift}, the same shift as last month.`);
    }
  }

  // --- Rule 4/5: week-off blocks -------------------------------------------
  for (const row of rows) {
    const expectedOffs = OFF_DAYS_PER_WEEK[row.shift];

    if (row.offDays === 0) errors.push(`${row.name}: never gets a week off.`);

    // Every complete 7-day window must hold exactly the shift's off quota.
    for (let start = 0; start + 7 <= dayCount; start++) {
      const offs = row.cells.slice(start, start + 7).filter((c) => c === OFF_LABEL).length;
      if (offs !== expectedOffs) {
        errors.push(
          `${row.name} (${row.shift}): ${offs} off day(s) in the 7 days from ` +
          `${month.days[start].label}; expected ${expectedOffs}.`);
        break;
      }
    }

    // Off days must sit next to each other, and so must the working days.
    // Runs touching the first/last day of the month are legitimately clipped.
    let runStart = null;
    for (let d = 0; d <= dayCount; d++) {
      const off = d < dayCount && row.cells[d] === OFF_LABEL;
      if (off && runStart === null) runStart = d;
      if (!off && runStart !== null) {
        const length = d - runStart;
        const clipped = runStart === 0 || d === dayCount;
        if (length !== expectedOffs && !(clipped && length < expectedOffs)) {
          errors.push(
            `${row.name} (${row.shift}): a run of ${length} off day(s) from ` +
            `${month.days[runStart].label}; the block must be ${expectedOffs} consecutive days.`);
          break;
        }
        runStart = null;
      }
    }

    // Working days must be consecutive too: a full block between two
    // week-offs is exactly 7 - expectedOffs days long.
    const expectedWork = 7 - expectedOffs;
    let workStart = null;
    for (let d = 0; d <= dayCount; d++) {
      const working = d < dayCount && row.cells[d] !== OFF_LABEL;
      if (working && workStart === null) workStart = d;
      if (!working && workStart !== null) {
        const length = d - workStart;
        const clipped = workStart === 0 || d === dayCount;
        if (length > expectedWork || (length < expectedWork && !clipped)) {
          errors.push(
            `${row.name} (${row.shift}): ${length} consecutive working day(s) from ` +
            `${month.days[workStart].label}; the pattern allows ${expectedWork}.`);
          break;
        }
        workStart = null;
      }
    }
  }

  // --- Rule 5: every client covered in every shift, every day ---------------
  const coverage = buildCoverage(roster);
  for (const entry of coverage) {
    for (let d = 0; d < dayCount; d++) {
      if (entry.perDay[d] === 0) {
        errors.push(
          `Client "${entry.client}" has nobody on ${entry.shift} on ${month.days[d].label}.`);
      }
    }
  }

  // --- Rule 2: shape of the input, restated against the produced sheet ------
  const clientCounts = new Map();
  rows.forEach((r) => r.clients.forEach((c) => clientCounts.set(c, (clientCounts.get(c) || 0) + 1)));
  for (const [client, count] of clientCounts) {
    if (count < MIN_EMPLOYEES_PER_CLIENT) {
      errors.push(`Client "${client}" is served by only ${count} employee(s).`);
    }
  }
  for (const row of rows) {
    if (row.clients.length < 2 || row.clients.length > 4) {
      errors.push(`${row.name}: has ${row.clients.length} client(s); expected 2-4.`);
    }
  }

  return { ok: errors.length === 0, errors, coverage };
}

/** Per client + shift, how many people are on duty on each day of the month. */
function buildCoverage(roster) {
  const { rows, month } = roster;
  const dayCount = month.days.length;
  const clients = [...new Set(rows.flatMap((r) => r.clients))].sort();
  const out = [];

  for (const client of clients) {
    for (const shift of SHIFTS) {
      const staff = rows.filter((r) => r.shift === shift && r.clients.includes(client));
      const perDay = new Array(dayCount).fill(0);
      for (let d = 0; d < dayCount; d++) {
        perDay[d] = staff.filter((r) => r.cells[d] === shift).length;
      }
      out.push({ client, shift, headcount: staff.length, perDay, min: Math.min(...perDay) });
    }
  }
  return out;
}

module.exports = { validateRoster, buildCoverage };
