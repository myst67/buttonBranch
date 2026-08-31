# Monthly roster generator

Builds a full-month shift roster from a list of employees and the clients they
serve, checks it against every scheduling rule, and exports it to Excel.
Pure Node.js - **no dependencies**, including the `.xlsx` writer.

```bash
cd roster
node cli.js --month 2025-07 --print          # uses data/employees.json
node cli.js --month 2025-08 --input my-team.json --out august.xlsx --csv
node test/run-tests.js                       # 19 checks, 72 rosters validated
```

## Input

An array of employee objects, exactly the shape from the brief:

```json
[
  { "employee": "Person 1", "last_month_shift": "Morning", "client": ["a", "b", "c"] }
]
```

`data/employees.json` is a ready-made 23-employee / 6-client sample.
`data/employees-23-clients.json` is a larger 70-employee / 23-client sample.

## Output

`Roster <Mon>-<year>` sheet - the requested table, one row per employee:

| Name | Client | Tue-01-Jul | Wed-02-Jul | Thu-03-Jul | Fri-04-Jul |
|---|---|---|---|---|---|
| Person 11 | Client B, Client C, Client D, Client E | Morning | Off | Off | Morning |

Shift cells are colour-coded, `Off` is grey, and the header row plus the
Name/Client columns are frozen. Two extra sheets come along for review:

* **Coverage check** - people on duty per client, per shift, per day. Every
  number is >= 1, which is rule 5 made visible.
* **Summary** - each person's old shift, new shift, week-off block and day counts.

## How the rules are met

| Rule | Where | How |
|---|---|---|
| 2. 2-4 clients each, >5 employees per client | `src/input.js` | Validated up front; the run stops with a readable list of every problem. |
| 3. One shift per month, never last month's | `src/shiftAssignment.js` | Each employee's candidate set excludes `last_month_shift`; simulated annealing picks from what is left. |
| 4. Night = 3 off + 4 on, others = 2 off + 5 on, consecutive | `src/offPattern.js` | Each employee gets one repeating weekly off block, stored as its start weekday. The block wraps the week (e.g. Sat-Sun-Mon), so both the off days *and* the working days stay consecutive on the calendar. |
| 5. Everyone gets week offs, one after another | `src/offPattern.js` | The block is contiguous by construction and repeats every week, so every 7-day window holds exactly the shift's quota. |
| 5. Every client covered in every shift, every day | both solvers | The shift solver guarantees >= 2 people per client per shift; the off-pattern solver then staggers their blocks so no client/shift/day is left empty. |
| 6. Excel export | `src/excel.js`, `src/xlsxWriter.js` | Writes a real `.xlsx` (OOXML zip) with Node's built-in `zlib`. |

Everything is re-checked afterwards by `src/validate.js`, independently of the
solvers - so a bug in the search surfaces as a failed check, not a wrong sheet.

## Feasibility - how much staff a client needs

A person is off 2-3 days a week, so one person cannot cover a client/shift
7 days a week. Every client therefore needs **at least 2 people in each of the
4 shifts, i.e. 8 employees**, before a valid roster exists at all. With people
holding 2-4 clients each, that means roughly

```
clients <= (employees x clients-per-employee) / 8
```

`src/input.js` checks this before searching and explains exactly which client is
too thin, rather than looping forever. It also catches the subtler case where a
client has enough people but too many of them worked the same shift last month.

## Note on the brief

Point 1 says "23 clients" but the example row and points 2-3 describe employees,
and 23 clients would need ~46+ employees to be coverable at all. The shipped
sample reads it as **23 employees** (6 clients); nothing in the code is hard-coded
to those numbers - `data/employees-23-clients.json` runs the same code with 23
clients and 70 employees.

## Options

```
-m, --month  YYYY-MM   month to roster            (default: next month)
-i, --input  <file>    employee JSON array        (default: data/employees.json)
-o, --out    <file>    Excel file to write        (default: roster-<Mon>-<year>.xlsx)
-s, --seed   <number>  PRNG seed; same seed = same roster   (default: 42)
    --csv              also write a .csv
-p, --print            print the roster to the terminal
```

## Library use

```js
const { buildRoster, validateRoster, exportRoster } = require('./roster');

const roster = buildRoster(employees, { month: '2025-07', seed: 42 });
const { ok, errors, coverage } = validateRoster(roster);
if (ok) exportRoster(roster, coverage, 'july.xlsx');
```
