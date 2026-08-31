# Roster backend (Python)

Learns from the rosters you upload and builds the next month under hard rules.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r backend/requirements.txt

cd backend
uvicorn app.main:app --reload --port 8000     # http://localhost:8000/docs
pytest -q                                     # 37 tests
python scripts/build_seed_team.py --clients 20   # size the team (default: 20 -> 60 people)
python scripts/generate_sample_history.py       # a sample sheet to upload
```

`data/seed/team.json` ships 60 employees over 20 clients - 10 people per client,
which is the headroom above the 8-per-client floor that keeps every month
solvable (see the root README for the arithmetic).

## The flow

1. **On the last day of the month** you upload last month's roster (`.xlsx`, `.csv`
   or `.json`) to `POST /api/history/upload`. It is parsed, stored, and both
   models are refit on the whole history.
2. `POST /api/roster/generate` scores every legal option with those models and
   hands the scores to a CP-SAT optimiser, which returns the best-scoring roster
   that satisfies every rule.
3. `GET /api/roster/{id}/export.xlsx` gives you the workbook.

## Where the machine learning is - and where it deliberately is not

Rostering is a constraint problem with hard rules. A model that emits the roster
directly can and will violate them, so the two jobs are split:

| Job | Owner | Why |
|---|---|---|
| *Which of the legal options is best?* | scikit-learn rankers (`app/ml.py`) | Preference is learnable from what the team actually did. |
| *Which combinations are legal at all?* | CP-SAT (`app/solver.py`) | Rules are guarantees, not tendencies. |
| *Did we really get it right?* | `app/validation.py` | Re-checks the finished sheet independently of the solver. |

**Two rankers** are trained, both as learning-to-rank problems - score every
candidate, label the one history actually used:

* **shift model** - which shift a person moves to, from features like the
  rotation step, how long since they last worked that shift, their share of
  Night duty so far, and the team's global transition frequencies;
* **week-off model** - which weekday their off block starts on, from the
  cyclical weekday encoding, weekend coverage, their own and the team's history
  of that block.

`LogisticRegression` on small histories (its coefficients also explain what was
learned, which the UI shows), `HistGradientBoostingClassifier` once there are
enough rows. Evaluation is a **time-ordered hold-out**: train on the older
months, predict the newest, report top-1 accuracy and AUC.

**Dynamic by design.** Every upload refits the models, and the score used by the
optimiser is a blend:

```
score = w * model + (1 - w) * heuristic prior,    w = months / (months + 2), capped at 0.85
```

so the very first month runs on transparent priors (rotate forward, spread the
Night load, rotate the week-off, share out weekend offs), and the learned model
takes over as history accumulates. `GET /api/model` reports `w` and the metrics
behind it; the UI shows both.

## The rules, as constraints

`x[e][s]` = employee `e` works shift `s` all month, `y[e][k]` = their weekly off
block starts on weekday `k`. The solver uses one variable per legal `(shift,
start)` pair, which keeps the formulation tight enough to prove optimality in
about 0.05s for 23 people.

| Rule | Constraint |
|---|---|
| 2. 2-4 clients each, >5 employees per client | checked before solving, with the exact client named (and the real floor is 8 per client, not 6) |
| 3. one shift for the month, never last month's | `AddExactlyOne` over the legal pairs; last month's shift is not among them |
| 4. Night 3 off + 4 on, others 2 off + 5 on, consecutive | the off block is stored as a start weekday and wraps the week (Sat-Sun-Mon), so both runs stay consecutive on the calendar |
| 5. every client staffed in every shift, every day | `>= 1` on-duty per client/shift/weekday, plus `>= 2` people per client/shift so the offs can be staggered |
| 6. Excel output | `app/exporting.py` (openpyxl), four sheets |

Solving is **lexicographic**: phase 1 maximises the learned preference to proven
optimality; phase 2 maximises how many client/shift/weekday slots have a *second*
person on duty, while holding preference within 2% of its optimum. Optimising
both at once costs 20s for under 1% of extra score.

If the team cannot be rostered at all, the API returns 422 with the reasons -
e.g. *`Client F` has 4 employees but cover in all 4 shifts on all 7 days needs at
least 8* - rather than searching forever.

## Reading real files

The parser (`app/parsing.py`) is built for sheets people actually keep:
title rows above the header, `W/O` / `OFF` / `-` for a day off, `N` / `s4` /
`Graveyard` for Night, clients separated by `,` `;` `/` or `|`, and date headers
as `Mon-01-Jul`, `2025-07-01`, `01/07` or real Excel dates. When the sheet omits
the year, the weekday names in the headers are used to identify it - only one
recent year has 1 July on a Monday - because the week-off pattern is read off
each column's real weekday. Irregular week-offs are fitted to the closest
repeating block and flagged as a warning rather than rejected.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/history/upload` | upload last month's roster; stores and retrains |
| GET | `/api/history` | stored months + model report |
| DELETE | `/api/history/{month}` | drop a month and retrain |
| POST | `/api/train` | force a refit |
| GET | `/api/model` | training report, metrics, blend weight |
| POST | `/api/roster/generate` | build a month (`month`, `seed`, `time_limit_seconds`, `min_per_client_shift`, `balance_slack`, optional `employees` override for joiners/leavers) |
| GET | `/api/roster/{id}` | the generated roster as JSON |
| GET | `/api/roster/{id}/export.xlsx` \| `.csv` | download |

If `dist/button-app` exists, the built Angular UI is served from `/` by the same
process.
