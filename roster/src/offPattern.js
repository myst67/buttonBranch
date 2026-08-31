'use strict';

const { OFF_DAYS_PER_WEEK } = require('./constants');

const UNCOVERED_WEIGHT = 1000; // a client/shift/day with nobody on duty
const SINGLE_COVER_WEIGHT = 1; // covered by exactly one person: legal, but fragile

/**
 * Rules 4/5/6: give every employee a repeating weekly week-off block - 3 days
 * for Night, 2 days for the other shifts - and stagger those blocks so every
 * client keeps at least one person on duty in every shift on every day.
 *
 * A pattern is just the weekday the off block starts on (0 = Mon ... 6 = Sun);
 * the block wraps around the week, e.g. start 5 + 3 days = Sat, Sun, Mon. That
 * wrap keeps both the off days AND the working days consecutive on the
 * calendar, which is what "4 days working consecutively" asks for.
 */
function assignOffPatterns(model, shiftByEmployee, options = {}) {
  const { employees, clientNames } = model;
  const rng = options.rng;
  const restarts = options.restarts || 40;
  const iterations = options.iterations || 60000;

  const offLength = employees.map((e) => OFF_DAYS_PER_WEEK[shiftByEmployee.get(e.name)]);

  // One group per (client, shift) pair that actually has people in it.
  const groups = [];
  const groupIdByKey = new Map();
  const groupsOf = employees.map(() => []);
  employees.forEach((e, i) => {
    const shift = shiftByEmployee.get(e.name);
    for (const client of e.clients) {
      const key = `${client}||${shift}`;
      let id = groupIdByKey.get(key);
      if (id === undefined) {
        id = groups.length;
        groupIdByKey.set(key, id);
        groups.push({ client, shift, members: [] });
      }
      groups[id].members.push(i);
      groupsOf[i].push(id);
    }
  });

  const worksOn = (start, len, dow) => ((dow - start + 7) % 7) >= len;
  const cellPenalty = (n) => (n === 0 ? UNCOVERED_WEIGHT : n === 1 ? SINGLE_COVER_WEIGHT : 0);

  let best = null;

  for (let attempt = 0; attempt < restarts; attempt++) {
    const starts = employees.map(() => rng.int(7));
    // onDuty[groupId][dow] = how many of the group's members work that weekday.
    const onDuty = groups.map(() => new Array(7).fill(0));
    employees.forEach((_, i) => {
      for (const g of groupsOf[i]) {
        for (let d = 0; d < 7; d++) if (worksOn(starts[i], offLength[i], d)) onDuty[g][d]++;
      }
    });

    let cost = 0;
    let uncovered = 0;
    onDuty.forEach((row) => row.forEach((n) => {
      cost += cellPenalty(n);
      if (n === 0) uncovered++;
    }));

    let bestLocal = uncovered === 0 ? { cost, starts: starts.slice() } : null;

    for (let step = 0; step < iterations && cost > 0; step++) {
      const temperature = 3 * (1 - step / iterations) + 0.01;
      const i = rng.int(employees.length);
      const from = starts[i];
      let to = rng.int(7);
      if (to === from) to = (to + 1 + rng.int(6)) % 7;

      const touched = groupsOf[i];
      let delta = 0;
      let deltaUncovered = 0;
      for (const g of touched) {
        for (let d = 0; d < 7; d++) {
          const before = onDuty[g][d];
          const after = before
            - (worksOn(from, offLength[i], d) ? 1 : 0)
            + (worksOn(to, offLength[i], d) ? 1 : 0);
          if (after === before) continue;
          delta += cellPenalty(after) - cellPenalty(before);
          deltaUncovered += (after === 0 ? 1 : 0) - (before === 0 ? 1 : 0);
        }
      }

      if (delta <= 0 || rng() < Math.exp(-delta / temperature)) {
        starts[i] = to;
        for (const g of touched) {
          for (let d = 0; d < 7; d++) {
            onDuty[g][d] += (worksOn(to, offLength[i], d) ? 1 : 0)
              - (worksOn(from, offLength[i], d) ? 1 : 0);
          }
        }
        cost += delta;
        uncovered += deltaUncovered;
        if (uncovered === 0 && (!bestLocal || cost < bestLocal.cost)) {
          bestLocal = { cost, starts: starts.slice() };
        }
      }
    }

    if (bestLocal) { cost = bestLocal.cost; uncovered = 0; starts.splice(0, starts.length, ...bestLocal.starts); }

    if (!best || uncovered < best.uncovered || (uncovered === best.uncovered && cost < best.cost)) {
      best = { cost, uncovered, starts: starts.slice(), attempts: attempt + 1 };
    }
    if (uncovered === 0) break;
  }

  if (best.uncovered > 0) {
    const detail = groups.length ? ` (${best.uncovered} client/shift/day slot(s) left empty)` : '';
    throw new Error(
      `Could not stagger the week-offs so every client is covered in every shift on every day${detail}. ` +
      'Give the thin client/shift pairs another employee.');
  }

  const patternByEmployee = new Map();
  employees.forEach((e, i) => {
    patternByEmployee.set(e.name, { offStart: best.starts[i], offLength: offLength[i] });
  });
  return { patternByEmployee, groups, restartsUsed: best.attempts };
}

/** True when the given Monday-based weekday falls inside the employee's off block. */
function isOffOn(pattern, dow) {
  return ((dow - pattern.offStart + 7) % 7) < pattern.offLength;
}

module.exports = { assignOffPatterns, isOffOn };
