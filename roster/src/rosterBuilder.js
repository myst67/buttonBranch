'use strict';

const { OFF_LABEL } = require('./constants');
const { createRng } = require('./random');
const { normaliseEmployees } = require('./input');
const { assignShifts } = require('./shiftAssignment');
const { assignOffPatterns, isOffOn } = require('./offPattern');
const { buildMonth } = require('./calendar');

/**
 * Builds the whole month's roster from the raw input array.
 *
 * @param {Array} rawInput  [{ employee, last_month_shift, client: [...] }, ...]
 * @param {Object} options  { month: "2025-07", seed: 42 }
 */
function buildRoster(rawInput, options = {}) {
  const month = buildMonth(options.month);
  const rng = createRng(options.seed === undefined ? 42 : options.seed);

  const model = normaliseEmployees(rawInput);
  const { shiftByEmployee } = assignShifts(model, { rng });
  const { patternByEmployee, groups } = assignOffPatterns(model, shiftByEmployee, { rng });

  const rows = model.employees.map((employee) => {
    const shift = shiftByEmployee.get(employee.name);
    const pattern = patternByEmployee.get(employee.name);
    const cells = month.days.map((d) => (isOffOn(pattern, d.dow) ? OFF_LABEL : shift));
    return {
      name: employee.name,
      clients: employee.clients.slice(),
      clientLabel: employee.clients.join(', '),
      lastMonthShift: employee.lastShift,
      shift,
      pattern,
      cells,
      workingDays: cells.filter((c) => c !== OFF_LABEL).length,
      offDays: cells.filter((c) => c === OFF_LABEL).length,
    };
  });

  // Sort the sheet by shift, then client, then name - easier to eyeball cover.
  const shiftOrder = new Map(require('./constants').SHIFTS.map((s, i) => [s, i]));
  rows.sort((a, b) =>
    shiftOrder.get(a.shift) - shiftOrder.get(b.shift) ||
    a.clientLabel.localeCompare(b.clientLabel) ||
    a.name.localeCompare(b.name));

  const header = ['Name', 'Client', ...month.days.map((d) => d.label)];

  return { month, header, rows, model, shiftByEmployee, patternByEmployee, groups };
}

module.exports = { buildRoster };
