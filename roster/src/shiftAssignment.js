'use strict';

const { SHIFTS, MIN_EMPLOYEES_PER_CLIENT_SHIFT } = require('./constants');

const SHORTFALL_WEIGHT = 1000;

/**
 * Rule 3 + rule 5, first half: give every employee exactly one shift for the
 * whole month, never the shift they worked last month, such that every client
 * ends up with at least MIN_EMPLOYEES_PER_CLIENT_SHIFT people in each of the
 * four shifts (the headroom the week-off staggering needs).
 *
 * Solved with simulated annealing over "move one employee to another shift".
 * The search space is tiny (23 people x 3 legal shifts) so this converges in
 * milliseconds, and restarts make it robust to unlucky starts.
 */
function assignShifts(model, options = {}) {
  const { employees, clientNames } = model;
  const rng = options.rng;
  const minPerPair = options.minPerClientShift || MIN_EMPLOYEES_PER_CLIENT_SHIFT;
  const restarts = options.restarts || 40;
  const iterations = options.iterations || 20000;

  const clientIndex = new Map(clientNames.map((c, i) => [c, i]));
  const clientIdsOf = employees.map((e) => e.clients.map((c) => clientIndex.get(c)));
  const target = employees.length / SHIFTS.length;

  const shortfall = (n) => (n < minPerPair ? minPerPair - n : 0);

  let best = null;

  for (let attempt = 0; attempt < restarts; attempt++) {
    // counts[clientId][shiftId] and how many people sit in each shift.
    const counts = clientNames.map(() => new Array(SHIFTS.length).fill(0));
    const shiftSize = new Array(SHIFTS.length).fill(0);
    const assigned = employees.map((e) => SHIFTS.indexOf(rng.pick(e.allowedShifts)));

    employees.forEach((e, i) => {
      shiftSize[assigned[i]]++;
      clientIdsOf[i].forEach((c) => counts[c][assigned[i]]++);
    });

    const totalShortfall = () => counts.reduce(
      (sum, row) => sum + row.reduce((s, n) => s + shortfall(n), 0), 0);
    const balance = () => shiftSize.reduce((s, n) => s + (n - target) ** 2, 0);

    let hard = totalShortfall();
    let cost = hard * SHORTFALL_WEIGHT + balance();
    // Keep the best feasible state seen: annealing wanders, and we want the
    // most balanced legal assignment, not merely the last one it landed on.
    let bestLocal = hard === 0 ? { cost, assigned: assigned.slice() } : null;

    for (let step = 0; step < iterations; step++) {
      const temperature = 2.5 * (1 - step / iterations) + 0.01;
      const i = rng.int(employees.length);
      const from = assigned[i];
      const options_ = employees[i].allowedShifts
        .map((s) => SHIFTS.indexOf(s))
        .filter((s) => s !== from);
      const to = rng.pick(options_);

      let deltaHard = 0;
      for (const c of clientIdsOf[i]) {
        deltaHard += shortfall(counts[c][from] - 1) - shortfall(counts[c][from]);
        deltaHard += shortfall(counts[c][to] + 1) - shortfall(counts[c][to]);
      }
      const deltaBalance =
        ((shiftSize[from] - 1 - target) ** 2 - (shiftSize[from] - target) ** 2) +
        ((shiftSize[to] + 1 - target) ** 2 - (shiftSize[to] - target) ** 2);
      const delta = deltaHard * SHORTFALL_WEIGHT + deltaBalance;

      if (delta <= 0 || rng() < Math.exp(-delta / temperature)) {
        assigned[i] = to;
        shiftSize[from]--;
        shiftSize[to]++;
        for (const c of clientIdsOf[i]) {
          counts[c][from]--;
          counts[c][to]++;
        }
        hard += deltaHard;
        cost += delta;
        if (hard === 0 && (!bestLocal || cost < bestLocal.cost)) {
          bestLocal = { cost, assigned: assigned.slice() };
        }
      }
    }

    const candidate = bestLocal
      ? { cost: bestLocal.cost, hard: 0, assigned: bestLocal.assigned, attempts: attempt + 1 }
      : { cost, hard, assigned: assigned.slice(), attempts: attempt + 1 };
    if (!best || candidate.hard < best.hard || (candidate.hard === best.hard && candidate.cost < best.cost)) {
      best = candidate;
    }
    if (best.hard === 0 && best.cost < SHORTFALL_WEIGHT) break;
  }

  if (best.hard > 0) {
    throw new Error(
      'Could not give every client at least ' + minPerPair + ' people in every shift ' +
      '(' + best.hard + ' client/shift slot(s) short). The client<->employee mapping is too thin: ' +
      'spread employees over more clients, or add staff.');
  }

  const shiftByEmployee = new Map();
  employees.forEach((e, i) => shiftByEmployee.set(e.name, SHIFTS[best.assigned[i]]));
  return { shiftByEmployee, restartsUsed: best.attempts };
}

module.exports = { assignShifts };
