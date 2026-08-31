#!/usr/bin/env node
'use strict';

const fs = require('fs');
const path = require('path');
const { buildRoster } = require('./src/rosterBuilder');
const { validateRoster } = require('./src/validate');
const { exportRoster, exportCsv } = require('./src/excel');
const { SHIFTS, OFF_LABEL } = require('./src/constants');

function parseArgs(argv) {
  const args = { seed: 42, csv: false, print: false };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    const next = () => argv[++i];
    switch (arg) {
      case '--month': case '-m': args.month = next(); break;
      case '--input': case '-i': args.input = next(); break;
      case '--out': case '-o': args.out = next(); break;
      case '--seed': case '-s': args.seed = Number(next()); break;
      case '--csv': args.csv = true; break;
      case '--print': case '-p': args.print = true; break;
      case '--help': case '-h': args.help = true; break;
      default:
        throw new Error(`Unknown option "${arg}". Run with --help.`);
    }
  }
  return args;
}

const HELP = `
Monthly roster generator

  node cli.js [options]

  -m, --month  YYYY-MM   Month to roster            (default: next month)
  -i, --input  <file>    Employee JSON array        (default: data/employees.json)
  -o, --out    <file>    Excel file to write        (default: roster-<Mon>-<year>.xlsx)
  -s, --seed   <number>  PRNG seed; same seed = same roster   (default: 42)
      --csv              Also write a .csv next to the .xlsx
  -p, --print            Print the roster to the terminal
  -h, --help             Show this help

Input format:
  [{ "employee": "Person 1", "last_month_shift": "Morning", "client": ["a","b","c"] }]
`;

function defaultMonth() {
  const now = new Date();
  const next = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() + 1, 1));
  return `${next.getUTCFullYear()}-${String(next.getUTCMonth() + 1).padStart(2, '0')}`;
}

function printTable(roster) {
  const widths = roster.header.map((h, i) => Math.max(
    h.length,
    ...roster.rows.map((r) => String([r.name, r.clientLabel, ...r.cells][i]).length)));
  const line = (cells) => cells.map((c, i) => String(c).padEnd(widths[i])).join('  ');

  console.log('');
  console.log(line(roster.header));
  console.log(widths.map((w) => '-'.repeat(w)).join('  '));
  for (const row of roster.rows) console.log(line([row.name, row.clientLabel, ...row.cells]));
  console.log('');
}

function main() {
  let args;
  try {
    args = parseArgs(process.argv.slice(2));
  } catch (error) {
    console.error(error.message);
    process.exit(2);
  }
  if (args.help) { console.log(HELP); return; }

  const month = args.month || defaultMonth();
  const inputPath = path.resolve(args.input || path.join(__dirname, 'data', 'employees.json'));

  let rawInput;
  try {
    rawInput = JSON.parse(fs.readFileSync(inputPath, 'utf8'));
  } catch (error) {
    console.error(`Could not read input data from ${inputPath}: ${error.message}`);
    process.exit(1);
  }

  let roster;
  try {
    roster = buildRoster(rawInput, { month, seed: args.seed });
  } catch (error) {
    console.error(`\nRoster could not be built:\n${error.message}\n`);
    process.exit(1);
  }

  const result = validateRoster(roster);

  const outPath = path.resolve(
    args.out || `roster-${roster.month.monthName}-${roster.month.year}.xlsx`);
  exportRoster(roster, result.coverage, outPath);
  if (args.csv) exportCsv(roster, outPath.replace(/\.xlsx$/i, '') + '.csv');

  console.log(`\nRoster for ${roster.month.monthName} ${roster.month.year}`);
  console.log(`  employees ......... ${roster.rows.length}`);
  console.log(`  clients ........... ${roster.model.clientNames.length}`);
  console.log(`  days .............. ${roster.month.days.length}`);
  for (const shift of SHIFTS) {
    const team = roster.rows.filter((r) => r.shift === shift);
    const offs = team.length ? team[0].pattern.offLength : 0;
    console.log(`  ${shift.padEnd(10)} ...... ${String(team.length).padStart(2)} people, ` +
      `${offs} week-off days each`);
  }
  const worst = result.coverage.reduce((min, c) => Math.min(min, c.min), Infinity);
  console.log(`  thinnest client/shift/day cover: ${worst} person on duty`);

  if (args.print) printTable(roster);

  if (result.ok) {
    console.log(`\nAll rules check out. Written to ${outPath}\n`);
  } else {
    console.error(`\n${result.errors.length} rule violation(s):`);
    result.errors.slice(0, 25).forEach((e) => console.error(`  - ${e}`));
    if (result.errors.length > 25) console.error(`  ... and ${result.errors.length - 25} more`);
    console.error(`\nThe sheet was still written to ${outPath} so you can inspect it.\n`);
    process.exit(1);
  }
}

if (require.main === module) main();

module.exports = { parseArgs, defaultMonth, OFF_LABEL };
