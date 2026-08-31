'use strict';

const fs = require('fs');
const { SHIFTS, WEEKDAYS, OFF_LABEL } = require('./constants');
const { writeXlsx } = require('./xlsxWriter');
const { isOffOn } = require('./offPattern');

/** The main sheet, exactly the requested layout: Name | Client | Mon-01-Jul ... */
function rosterSheet(roster) {
  const header = roster.header.map((h) => ({ v: h, style: 'header' }));
  const rows = [header];

  for (const row of roster.rows) {
    rows.push([
      { v: row.name, style: 'text' },
      { v: row.clientLabel, style: 'text' },
      ...row.cells.map((cell) => ({ v: cell, style: cell === OFF_LABEL ? 'Off' : cell })),
    ]);
  }

  return {
    name: `Roster ${roster.month.monthName}-${roster.month.year}`,
    rows,
    active: true,
    freeze: { row: 1, col: 2 },
    columns: [{ width: 22 }, { width: 24 }, ...roster.month.days.map(() => ({ width: 11 }))],
  };
}

/** Proof of rule 5: how many people each client has, per shift, per day. */
function coverageSheet(roster, coverage) {
  const rows = [[
    { v: 'Client', style: 'header' },
    { v: 'Shift', style: 'header' },
    { v: 'Team size', style: 'header' },
    { v: 'Min on any day', style: 'header' },
    ...roster.month.days.map((d) => ({ v: d.label, style: 'header' })),
  ]];

  for (const entry of coverage) {
    rows.push([
      { v: entry.client, style: 'text' },
      { v: entry.shift, style: entry.shift },
      { v: entry.headcount, style: 'number' },
      { v: entry.min, style: entry.min === 0 ? 'Off' : 'number' },
      ...entry.perDay.map((n) => ({ v: n, style: n === 0 ? 'Off' : 'number' })),
    ]);
  }

  return {
    name: 'Coverage check',
    rows,
    freeze: { row: 1, col: 4 },
    columns: [{ width: 14 }, { width: 12 }, { width: 11 }, { width: 15 },
      ...roster.month.days.map(() => ({ width: 11 }))],
  };
}

/** One line per employee: shift moved from/to, week-off block, day counts. */
function summarySheet(roster) {
  const rows = [[
    { v: 'Name', style: 'header' },
    { v: 'Client', style: 'header' },
    { v: 'Last month shift', style: 'header' },
    { v: 'This month shift', style: 'header' },
    { v: 'Week off', style: 'header' },
    { v: 'Off days / week', style: 'header' },
    { v: 'Working days', style: 'header' },
    { v: 'Off days', style: 'header' },
  ]];

  for (const row of roster.rows) {
    const offDays = [];
    for (let d = 0; d < 7; d++) if (isOffOn(row.pattern, d)) offDays.push(WEEKDAYS[d]);
    // Print the block in calendar order (a wrapped block reads Sat, Sun, Mon).
    const ordered = [];
    for (let i = 0; i < row.pattern.offLength; i++) {
      ordered.push(WEEKDAYS[(row.pattern.offStart + i) % 7]);
    }
    rows.push([
      { v: row.name, style: 'text' },
      { v: row.clientLabel, style: 'text' },
      { v: row.lastMonthShift, style: 'center' },
      { v: row.shift, style: row.shift },
      { v: ordered.join(', '), style: 'center' },
      { v: row.pattern.offLength, style: 'number' },
      { v: row.workingDays, style: 'number' },
      { v: row.offDays, style: 'number' },
    ]);
  }

  const perShift = SHIFTS.map((s) => `${s}: ${roster.rows.filter((r) => r.shift === s).length}`);
  rows.push([]);
  rows.push([{ v: 'Headcount per shift', style: 'bold' }, { v: perShift.join('   |   '), style: 'text' }]);

  return {
    name: 'Summary',
    rows,
    freeze: { row: 1, col: 1 },
    columns: [{ width: 22 }, { width: 24 }, { width: 17 }, { width: 17 },
      { width: 18 }, { width: 15 }, { width: 13 }, { width: 11 }],
  };
}

function exportRoster(roster, coverage, filePath) {
  return writeXlsx(filePath, [
    rosterSheet(roster),
    coverageSheet(roster, coverage),
    summarySheet(roster),
  ]);
}

/** Optional plain-text copy of the main sheet. */
function exportCsv(roster, filePath) {
  const quote = (v) => (/[",\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : String(v));
  const lines = [roster.header.map(quote).join(',')];
  for (const row of roster.rows) {
    lines.push([row.name, row.clientLabel, ...row.cells].map(quote).join(','));
  }
  fs.writeFileSync(filePath, lines.join('\n') + '\n', 'utf8');
  return filePath;
}

module.exports = { exportRoster, exportCsv };
