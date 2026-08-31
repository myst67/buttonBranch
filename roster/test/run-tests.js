'use strict';

const assert = require('assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { buildRoster, validateRoster, exportRoster, exportCsv } = require('..');
const { buildMonth } = require('../src/calendar');
const { OFF_LABEL, SHIFTS, OFF_DAYS_PER_WEEK } = require('../src/constants');

const employees = JSON.parse(
  fs.readFileSync(path.join(__dirname, '..', 'data', 'employees.json'), 'utf8'));

let passed = 0;
let failed = 0;

function test(name, fn) {
  try {
    fn();
    passed++;
    console.log(`  ok   ${name}`);
  } catch (error) {
    failed++;
    console.log(`  FAIL ${name}\n       ${error.message.split('\n').join('\n       ')}`);
  }
}

console.log('\ncalendar');
test('labels the days like Mon-01-Jul', () => {
  const july = buildMonth('2025-07');
  assert.strictEqual(july.days.length, 31);
  assert.strictEqual(july.days[0].label, 'Tue-01-Jul');
  assert.strictEqual(july.days[30].label, 'Thu-31-Jul');
});
test('handles a leap February', () => {
  assert.strictEqual(buildMonth('2024-02').days.length, 29);
  assert.strictEqual(buildMonth('2025-02').days.length, 28);
});
test('rejects a malformed month', () => {
  assert.throws(() => buildMonth('July 2025'), /Month must look like/);
});

console.log('\nroster rules (23 employees x 24 months x 3 seeds)');
const months = [];
for (let year = 2025; year <= 2026; year++) {
  for (let month = 1; month <= 12; month++) months.push(`${year}-${String(month).padStart(2, '0')}`);
}

for (const seed of [1, 42, 2024]) {
  test(`every rule holds for seed ${seed}, all 24 months`, () => {
    for (const month of months) {
      const roster = buildRoster(employees, { month, seed });
      const result = validateRoster(roster);
      assert.ok(result.ok, `${month}: ${result.errors.slice(0, 3).join(' | ')}`);
    }
  });
}

const roster = buildRoster(employees, { month: '2025-07', seed: 42 });

test('rule 3: one shift all month, never last month\'s shift', () => {
  for (const row of roster.rows) {
    const worked = new Set(row.cells.filter((c) => c !== OFF_LABEL));
    assert.strictEqual(worked.size, 1, `${row.name} works ${[...worked].join('/')}`);
    assert.notStrictEqual(row.shift, row.lastMonthShift, `${row.name} kept ${row.shift}`);
  }
});

test('rule 4: 3 offs / 4 on for Night, 2 offs / 5 on for the rest, every week', () => {
  for (const row of roster.rows) {
    const expected = OFF_DAYS_PER_WEEK[row.shift];
    assert.strictEqual(row.pattern.offLength, expected);
    for (let start = 0; start + 7 <= row.cells.length; start++) {
      const offs = row.cells.slice(start, start + 7).filter((c) => c === OFF_LABEL).length;
      assert.strictEqual(offs, expected, `${row.name} week at day ${start + 1}`);
    }
  }
});

test('rule 4: the week-off days sit next to each other', () => {
  for (const row of roster.rows) {
    const runs = row.cells.join(',').split(/,?(?:Morning|Afternoon|Evening|Night),?/)
      .filter(Boolean)
      .map((run) => run.split(',').filter((c) => c === OFF_LABEL).length);
    for (const length of runs) {
      assert.ok(length <= row.pattern.offLength, `${row.name} has a ${length}-day off run`);
    }
  }
});

test('rule 5: everybody gets week offs', () => {
  for (const row of roster.rows) assert.ok(row.offDays > 0, `${row.name} never gets a day off`);
});

test('rule 5: every client is staffed in every shift on every day', () => {
  const result = validateRoster(roster);
  const clients = [...new Set(roster.rows.flatMap((r) => r.clients))];
  assert.strictEqual(result.coverage.length, clients.length * SHIFTS.length);
  for (const entry of result.coverage) {
    assert.ok(entry.min >= 1,
      `${entry.client}/${entry.shift} drops to ${entry.min} on some day`);
  }
});

test('rule 2: 2-4 clients each, and every client has more than 5 people', () => {
  const counts = new Map();
  for (const row of roster.rows) {
    assert.ok(row.clients.length >= 2 && row.clients.length <= 4, row.name);
    row.clients.forEach((c) => counts.set(c, (counts.get(c) || 0) + 1));
  }
  for (const [client, count] of counts) assert.ok(count > 5, `${client} has ${count}`);
});

test('the same seed rebuilds the identical roster', () => {
  const again = buildRoster(employees, { month: '2025-07', seed: 42 });
  assert.deepStrictEqual(
    again.rows.map((r) => [r.name, r.shift, r.pattern.offStart]),
    roster.rows.map((r) => [r.name, r.shift, r.pattern.offStart]));
});

console.log('\ninput validation');
test('rejects an employee with only one client', () => {
  const bad = employees.map((e, i) => (i === 0 ? { ...e, client: [e.client[0]] } : e));
  assert.throws(() => buildRoster(bad, { month: '2025-07' }), /requires 2-4/);
});

test('rejects a client that is too thin to cover 24x7', () => {
  const bad = JSON.parse(JSON.stringify(employees));
  bad.forEach((e) => { e.client = e.client.filter((c) => c !== 'Client F'); });
  bad[0].client.push('Client F');
  bad[1].client.push('Client F');
  assert.throws(() => buildRoster(bad, { month: '2025-07' }), /Client F/);
});

test('rejects an unknown last_month_shift', () => {
  const bad = employees.map((e, i) => (i === 0 ? { ...e, last_month_shift: 'Graveyard' } : e));
  assert.throws(() => buildRoster(bad, { month: '2025-07' }), /not one of/);
});

test('rejects a client where nobody is eligible for a shift', () => {
  const bad = JSON.parse(JSON.stringify(employees));
  // Everyone on Client A worked Night last month -> nobody may take Night now.
  bad.forEach((e) => { if (e.client.includes('Client A')) e.last_month_shift = 'Night'; });
  assert.throws(() => buildRoster(bad, { month: '2025-07' }), /eligible/);
});

console.log('\nexport');
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'roster-test-'));

test('writes an xlsx that is a well-formed zip package', () => {
  const file = exportRoster(roster, validateRoster(roster).coverage, path.join(tmpDir, 'r.xlsx'));
  const buffer = fs.readFileSync(file);
  assert.strictEqual(buffer.slice(0, 2).toString(), 'PK');
  assert.ok(buffer.includes('[Content_Types].xml'));
  assert.ok(buffer.includes('xl/worksheets/sheet3.xml'));
  assert.ok(buffer.length > 5000, 'file looks empty');
});

test('the csv has the requested Name, Client, dates header', () => {
  const file = exportCsv(roster, path.join(tmpDir, 'r.csv'));
  const lines = fs.readFileSync(file, 'utf8').trim().split('\n');
  assert.strictEqual(lines.length, roster.rows.length + 1);
  const header = lines[0].split(',');
  assert.strictEqual(header[0], 'Name');
  assert.strictEqual(header[1], 'Client');
  assert.strictEqual(header[2], 'Tue-01-Jul');
});

fs.rmSync(tmpDir, { recursive: true, force: true });

console.log(`\n${passed} passed, ${failed} failed\n`);
process.exit(failed ? 1 : 0);
