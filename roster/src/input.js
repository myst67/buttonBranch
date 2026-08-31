'use strict';

const { SHIFTS, MIN_EMPLOYEES_PER_CLIENT_SHIFT } = require('./constants');

const MIN_CLIENTS_PER_EMPLOYEE = 2;
const MAX_CLIENTS_PER_EMPLOYEE = 4;
const MIN_EMPLOYEES_PER_CLIENT = 6; // "more than 5 employees"

/**
 * Normalises the raw input array:
 *   [{ employee: "Person 1", last_month_shift: "Morning", client: ["a","b"] }]
 * into an indexed model, and reports every structural problem at once instead
 * of failing on the first one.
 */
function normaliseEmployees(rawInput) {
  if (!Array.isArray(rawInput) || rawInput.length === 0) {
    throw new Error('Input data must be a non-empty array of employee objects.');
  }

  const problems = [];
  const seenNames = new Set();

  const employees = rawInput.map((row, index) => {
    const name = String(row.employee || '').trim();
    if (!name) problems.push(`Row ${index + 1}: "employee" is missing.`);
    if (seenNames.has(name)) problems.push(`Duplicate employee name "${name}".`);
    seenNames.add(name);

    const lastShift = String(row.last_month_shift || '').trim();
    if (!SHIFTS.includes(lastShift)) {
      problems.push(
        `${name || `Row ${index + 1}`}: last_month_shift "${lastShift}" is not one of ${SHIFTS.join(', ')}.`);
    }

    const clients = Array.from(new Set((row.client || []).map((c) => String(c).trim()).filter(Boolean)));
    if (clients.length < MIN_CLIENTS_PER_EMPLOYEE || clients.length > MAX_CLIENTS_PER_EMPLOYEE) {
      problems.push(
        `${name}: has ${clients.length} client(s); rule 2 requires ${MIN_CLIENTS_PER_EMPLOYEE}-${MAX_CLIENTS_PER_EMPLOYEE}.`);
    }

    return { index, name, lastShift, clients, allowedShifts: SHIFTS.filter((s) => s !== lastShift) };
  });

  const clientNames = [...new Set(employees.flatMap((e) => e.clients))].sort();
  const employeesByClient = new Map(clientNames.map((c) => [c, []]));
  employees.forEach((e) => e.clients.forEach((c) => employeesByClient.get(c).push(e)));

  for (const client of clientNames) {
    const staff = employeesByClient.get(client);
    if (staff.length < MIN_EMPLOYEES_PER_CLIENT) {
      problems.push(`Client "${client}": has ${staff.length} employees; rule 2 requires more than ${MIN_EMPLOYEES_PER_CLIENT - 1}.`);
    }
    // Rule 5 needs MIN_EMPLOYEES_PER_CLIENT_SHIFT people per shift, in all four
    // shifts, so a client is only coverable with 4 x that many people.
    const needed = MIN_EMPLOYEES_PER_CLIENT_SHIFT * SHIFTS.length;
    if (staff.length < needed) {
      problems.push(
        `Client "${client}": has ${staff.length} employees but full 24x7 cover in all ${SHIFTS.length} shifts ` +
        `needs at least ${needed} (${MIN_EMPLOYEES_PER_CLIENT_SHIFT} per shift, so week-offs can be staggered).`);
    }
    // A shift nobody is allowed to move into cannot be staffed at all.
    for (const shift of SHIFTS) {
      const eligible = staff.filter((e) => e.lastShift !== shift).length;
      if (staff.length >= needed && eligible < MIN_EMPLOYEES_PER_CLIENT_SHIFT) {
        problems.push(
          `Client "${client}", shift ${shift}: only ${eligible} of ${staff.length} employees are eligible ` +
          `(the rest worked ${shift} last month), but ${MIN_EMPLOYEES_PER_CLIENT_SHIFT} are needed.`);
      }
    }
  }

  if (problems.length) {
    throw new Error(`Input data cannot produce a valid roster:\n  - ${problems.join('\n  - ')}`);
  }

  return { employees, clientNames, employeesByClient };
}

module.exports = {
  normaliseEmployees,
  MIN_CLIENTS_PER_EMPLOYEE,
  MAX_CLIENTS_PER_EMPLOYEE,
  MIN_EMPLOYEES_PER_CLIENT,
};
