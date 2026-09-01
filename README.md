# Monthly roster builder

Upload last month's roster on the last day of the month; get the new month's
roster, rule-checked and in Excel.

* **Backend** - Python (FastAPI + scikit-learn + OR-Tools CP-SAT) in `backend/`
* **UI** - Angular in `src/`
* `roster/` - the original dependency-free Node.js prototype of the scheduling
  rules, kept as a reference implementation

## Run it

**Setting this up on your own machine? See [DEPLOYMENT.md](DEPLOYMENT.md)** for
the full from-scratch guide - prerequisites, both run modes, running it as a
service, configuration, backups and troubleshooting. On Windows 11, follow its
step-by-step appendix. The short version:

```bash
# 1. backend
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt
cd backend && uvicorn app.main:app --reload --port 8000

# 2. UI (second terminal) - /api is proxied to :8000
#    Needs Node 20 or 22; Angular 6 does not build on Node 24+.
npm install
npm start                       # http://localhost:4200
```

Need something to upload? `python backend/scripts/generate_sample_history.py`
writes a realistic sheet to `backend/data/sample/` from the seed team in
`backend/data/seed/team.json` - **20 clients and 60 employees** (see below).

For a single-process deployment, `npm run build` then start the backend: it
serves `dist/button-app` at `/` when that folder exists.

## What it does

1. **Upload** last month's sheet - `.xlsx`, `.csv` or `.json`. It is parsed
   (shift worked, clients, week-off block per person), stored, and both models
   are refit on the full history.
2. **Learn.** Two scikit-learn rankers score the options: which shift each
   person should move to, and which week-off block they should get. On the first
   upload they run on transparent heuristics; the learned model takes over as
   months accumulate. The UI shows the current blend, the accuracy and the
   strongest signals.
3. **Solve.** CP-SAT picks the highest-scoring roster that satisfies every rule.
4. **Check and export.** The finished sheet is re-validated independently, then
   exported with Roster, Coverage check, Summary and Model sheets.

## The rules

| # | Rule | How it is guaranteed |
|---|---|---|
| 1 | input is a list of `{employee, last_month_shift, client[]}` | read from the uploaded sheet, or posted directly |
| 2 | 2-4 clients per employee, >5 employees per client | validated before solving, naming the client at fault |
| 3 | one shift for the whole month, never last month's | hard constraint; last month's shift is not a candidate |
| 4 | Night: 3 week-offs + 4 consecutive working days. Others: 2 + 5 | the off block is a start weekday that wraps the week, so both runs stay consecutive |
| 5 | every client staffed in every shift on every day | `>= 1` on duty per client/shift/day, and `>= 2` people per client/shift so the offs can be staggered |
| 6 | Excel output: `Name`, `Client`, then `Mon-01-Jul ...` | openpyxl, colour-coded, frozen panes |

## How big does the team have to be?

A client needs **at least 8 people** (2 per shift x 4 shifts) before 24x7 cover
is possible at all - one person cannot cover a shift 7 days a week with 2-3 days
off. For 20 clients that is a floor of `20 x 8 / 4 clients each = 40` employees.

The floor is not enough in practice. At exactly 8 people a client has exactly 2
per shift, so their week-offs must be perfectly disjoint *and* last month's
shifts must happen to allow it. Solving 20 clients / 48 employees against 10
different last-month shift mixes failed 3 times out of 10. So the seed team
targets **10 employees per client**:

```
employees = clients x 10 / average clients per employee
          = 20 x 10 / 3.33  = 60
```

`backend/data/seed/team.json` is that team: **60 employees, 20 clients**, every
client with exactly 10 people, and a 2/3/4 client mix per employee (10 / 20 / 30
people) as rule 2 allows. Verified at 10/10 valid rosters across random
last-month shift mixes and five different months, ~7s each, with a second person
on duty in ~62% of client/shift/weekday slots as cover.

Change the size with `python backend/scripts/build_seed_team.py --clients 30`;
it recalculates the headcount and refuses to write a team that cannot be
rostered. Impossible teams are rejected at upload with the specific reason
instead of a timeout.

## Tests

```bash
cd backend && pytest -q                                   # 37 tests
npm test -- --watch=false --browsers=ChromeHeadlessCI     # Angular
```

Backend coverage: parsing real-world sheet quirks, cold-start and multi-month
learning, model persistence, every rule across five different months, the
infeasibility diagnostics, the shipped 20-client seed team, and the full monthly
cycle - upload, generate, export, then re-upload that export as next month's
input, asserting the shift model starts training and its weight grows.

See `backend/README.md` for the model, the constraint formulation and the API.
