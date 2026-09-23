"""CP-SAT optimiser: the part that guarantees the rules.

The learner in :mod:`app.ml` says how *desirable* each option is; this module
decides which combination is actually *allowed*, and picks the best-scoring
feasible one. Every scheduling rule is a hard constraint here, so no amount of
model drift can produce a roster that breaks them.

Decision variables
    ``x[e][s]``     employee ``e`` works shift ``s`` all month (rule 3)
    ``y[e][k]``     employee ``e``'s weekly off block starts on weekday ``k``
    ``z[e][s][k]``  the two together, which is what coverage is counted on

Hard constraints
    one shift per employee, never last month's (rule 3);
    one week-off block per employee, 3 days for Night and 2 otherwise,
    consecutive because the block is stored as a start weekday (rule 4);
    at least two people per client per shift, and at least one of them on duty
    on every weekday (rule 5);
    shift headcounts balanced to within a slack.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

from .config import (MAX_CLIENTS_PER_EMPLOYEE, MIN_CLIENTS_PER_EMPLOYEE,
                     MIN_EMPLOYEES_PER_CLIENT, MIN_PER_CLIENT_SHIFT,
                     OFF_DAYS_PER_WEEK, SHIFTS, WEEKDAYS, works_on)
from .models import Assignment

SCALE = 1000
#: Phase 2 may give up this fraction of the preference score to buy spare cover.
PREFERENCE_TOLERANCE = 0.02
REDUNDANCY_TIME_LIMIT = 5.0
#: How many times the shift-balance may be loosened before giving up.
MAX_RELAXATIONS = 3


class InfeasibleRoster(Exception):
    """The rules cannot all hold for this team - with the reasons why."""

    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("\n".join(reasons))


@dataclass
class EmployeeInput:
    name: str
    clients: list[str]
    previous_shift: Optional[str] = None


@dataclass
class SolverOptions:
    min_per_client_shift: int = MIN_PER_CLIENT_SHIFT
    balance_slack: int = 1
    time_limit_seconds: float = 20.0
    seed: int = 42
    prefer_redundancy: bool = True
    #: Accept a team whose *shape* breaks rule 2 - people outside the 2-4 client
    #: range, or a client below the headcount floor - and build anyway. The
    #: scheduling rules stay hard either way: only the checks that describe the
    #: input rather than the schedule are waived. Coverage arithmetic is never
    #: waived, because no schedule satisfying rule 5 exists when it fails.
    accept_team_shape: bool = False
    #: Build even when a client cannot be covered in every shift on every day.
    #: The solver then minimises the number of uncovered client/shift/day slots
    #: instead of requiring zero of them, and the ones it could not fill are
    #: reported as gaps. Rules 3 and 4 stay hard: nobody works two shifts or
    #: loses their week-off to plug a hole.
    allow_coverage_gaps: bool = False

    def __post_init__(self):
        # Accepting gaps is the broader waiver: a caller willing to ship a sheet
        # with uncovered days is not asking to be stopped by the team's shape.
        # Enforced here so every entry point inherits it, not just the service.
        if self.allow_coverage_gaps:
            self.accept_team_shape = True


@dataclass
class SolveResult:
    assignments: list[Assignment]
    status: str
    objective: float
    solve_seconds: float
    balance_slack_used: int
    notes: list[str] = field(default_factory=list)


# ------------------------------------------------------------- checks -------
def classify_feasibility(employees: list[EmployeeInput], options: SolverOptions
                         ) -> tuple[list[str], list[str]]:
    """Split the structural checks into the two kinds they really are.

    Returns ``(blocking, advisory)``.

    *Blocking* problems are arithmetic: the numbers prove that no roster
    obeying rule 5 exists, so building one anyway can only produce a sheet with
    holes in it. A client needs ``min_per_client_shift`` people in each of the
    four shifts before staggered week-offs can cover all seven days; below that
    the client is uncovered on somebody's day off no matter how the solver
    arranges things.

    *Advisory* problems describe the shape of the team rather than the schedule
    - an employee outside the 2-4 client range, a client under the headcount
    floor. A roster over such a team can still satisfy every scheduling rule,
    so these are reported but need not stop the build.

    With ``allow_coverage_gaps`` the arithmetic problems move to advisory too.
    They are still true - those clients will have uncovered days - but the
    caller has asked for the best roster available rather than none at all, so
    they become something to report rather than something to refuse on.
    """
    blocking: list[str] = []
    advisory: list[str] = []
    if not employees:
        return ["No employees were supplied."], []

    by_client: dict[str, list[EmployeeInput]] = {}
    for employee in employees:
        if not MIN_CLIENTS_PER_EMPLOYEE <= len(employee.clients) <= MAX_CLIENTS_PER_EMPLOYEE:
            advisory.append(
                f"{employee.name}: has {len(employee.clients)} client(s); rule 2 requires "
                f"{MIN_CLIENTS_PER_EMPLOYEE}-{MAX_CLIENTS_PER_EMPLOYEE}.")
        for client in employee.clients:
            by_client.setdefault(client, []).append(employee)

    needed = options.min_per_client_shift * len(SHIFTS)
    for client, staff in sorted(by_client.items()):
        if len(staff) < MIN_EMPLOYEES_PER_CLIENT:
            advisory.append(
                f'Client "{client}": has {len(staff)} employees; rule 2 requires more than '
                f"{MIN_EMPLOYEES_PER_CLIENT - 1}.")
        if len(staff) < needed:
            (advisory if options.allow_coverage_gaps else blocking).append(
                f'Client "{client}": has {len(staff)} employees but cover in all '
                f"{len(SHIFTS)} shifts on all 7 days needs at least {needed} "
                f"({options.min_per_client_shift} per shift, so week-offs can be staggered). "
                f"Give {needed - len(staff)} more of the team this client, or add people.")
            continue
        for shift in SHIFTS:
            eligible = sum(1 for e in staff if e.previous_shift != shift)
            if eligible < options.min_per_client_shift:
                (advisory if options.allow_coverage_gaps else blocking).append(
                    f'Client "{client}", shift {shift}: only {eligible} of {len(staff)} people '
                    f"may take it (the others worked {shift} last month), but "
                    f"{options.min_per_client_shift} are needed.")
    return blocking, advisory


def check_feasibility(employees: list[EmployeeInput], options: SolverOptions) -> list[str]:
    """Every structural problem, blocking or not, in one list."""
    blocking, advisory = classify_feasibility(employees, options)
    return blocking + advisory


# -------------------------------------------------------------- solve -------
def solve_roster(employees: list[EmployeeInput], learner, options: Optional[SolverOptions] = None
                 ) -> SolveResult:
    """Score every legal option with the learner, then optimise under the rules."""
    from ortools.sat.python import cp_model

    options = options or SolverOptions()
    blocking, advisory = classify_feasibility(employees, options)
    # An advisory problem stops the build unless the caller has said it accepts
    # the team as it stands. A blocking one always stops it: there is no roster
    # to find, so proceeding would only mean returning a sheet with holes.
    fatal = blocking if options.accept_team_shape else blocking + advisory
    if fatal:
        raise InfeasibleRoster(fatal)

    n = len(employees)
    clients = sorted({c for e in employees for c in e.clients})
    members: dict[str, list[int]] = {c: [i for i, e in enumerate(employees) if c in e.clients]
                                     for c in clients}

    # ---- scores from the learner ----------------------------------------
    shift_scores: list[dict[str, float]] = []
    shift_detail: list[dict[str, tuple[float, float, Optional[float]]]] = []
    off_scores: list[dict[tuple[str, int], float]] = []
    for employee in employees:
        previous = employee.previous_shift
        per_shift: dict[str, float] = {}
        per_detail: dict[str, tuple] = {}
        per_off: dict[tuple[str, int], float] = {}
        for shift in SHIFTS:
            if shift == previous:
                continue
            blended, prior, model = learner.score_shift(
                employee.name, previous or shift, shift, len(employee.clients))
            per_shift[shift] = blended
            per_detail[shift] = (blended, prior, model)
            for start in range(7):
                per_off[(shift, start)] = learner.score_off(
                    employee.name, shift, start, len(employee.clients))[0]
        shift_scores.append(per_shift)
        shift_detail.append(per_detail)
        off_scores.append(per_off)

    notes: list[str] = []
    if advisory:
        # Carried into the roster's metadata so a sheet built over a team that
        # breaks rule 2 says so, rather than looking unconditionally clean.
        notes.append(f"Built over a team with {len(advisory)} rule 2 exception(s), "
                     f"accepted by the caller.")
        notes.extend(advisory)
    slack = options.balance_slack

    # Balance is the only soft rule here, so it is the only thing worth relaxing.
    # A few steps, then one attempt with it dropped entirely - never an unbounded
    # loop that spends the full time limit on each of n slack values.
    for attempt in range(MAX_RELAXATIONS + 2):
        result = _solve_once(employees, clients, members, shift_scores, off_scores,
                             options, slack, cp_model)
        if result is not None:
            break
        if attempt == MAX_RELAXATIONS:
            slack = n                      # last try: no balance constraint at all
            notes.append("Dropped the shift-balance constraint entirely to find a "
                         "feasible roster.")
        elif attempt < MAX_RELAXATIONS:
            slack += 1
            notes.append(f"Relaxed the shift-balance slack to {slack} to find a "
                         f"feasible roster.")
    else:
        raise InfeasibleRoster([
            "No roster satisfies every rule for this team, even with the shift "
            "headcounts left completely free. The client/employee mapping is too thin: "
            "give the thin clients more people, or spread people over more clients.",
            "Most often this means some client cannot have two people in every shift "
            "once last month's shifts are excluded."])

    picks, status, objective, redundancy, seconds = result

    assignments: list[Assignment] = []
    for index, employee in enumerate(employees):
        shift, start = picks[index]
        blended, prior, model = shift_detail[index][shift]
        assignments.append(Assignment(
            name=employee.name,
            clients=list(employee.clients),
            previous_shift=employee.previous_shift,
            shift=shift,
            off_start=start,
            shift_score=round(blended, 3),
            off_score=round(off_scores[index][(shift, start)], 3),
            reason=_explain(employee, shift, start, blended, prior, model),
        ))

    assignments.sort(key=lambda a: (SHIFTS.index(a.shift), ", ".join(a.clients), a.name))
    if options.prefer_redundancy:
        total = len(clients) * len(SHIFTS) * 7
        notes.append(f"{redundancy} of {total} client/shift/weekday slots have a second "
                     f"person on duty as cover.")
    return SolveResult(assignments=assignments, status=status, objective=objective,
                       solve_seconds=round(seconds, 3), balance_slack_used=slack,
                       notes=notes)


def _solve_once(employees, clients, members, shift_scores, off_scores, options, slack, cp_model):
    """Lexicographic solve: preference first, spare cover second.

    Maximising preference and cover redundancy together turns a 0.05s problem
    into one that cannot prove optimality in 20s, for a fraction of a percent of
    extra score. So phase 1 optimises the learned preference alone, and phase 2
    maximises how many client/shift/day slots have a second person on duty while
    holding the preference score at (almost) its optimum.
    """
    n = len(employees)
    model = cp_model.CpModel()

    # One variable per legal (shift, off-block start) pair. Modelling the pair
    # directly - rather than a shift variable ANDed with an off variable - keeps
    # the formulation tight enough for CP-SAT to prove optimality in about 0.05s.
    z: dict[tuple[int, str, int], object] = {}
    x: dict[tuple[int, str], object] = {}

    for i, employee in enumerate(employees):
        legal = [s for s in SHIFTS if s != employee.previous_shift]
        for shift in legal:
            for k in range(7):
                z[(i, shift, k)] = model.NewBoolVar(f"z_{i}_{shift}_{k}")
        # Rule 3 + rule 4 in one line: exactly one shift for the month and
        # exactly one weekly off block; last month's shift is not in ``legal``.
        model.AddExactlyOne(z[(i, s, k)] for s in legal for k in range(7))
        for shift in legal:
            indicator = model.NewBoolVar(f"x_{i}_{shift}")
            model.Add(indicator == sum(z[(i, shift, k)] for k in range(7)))
            x[(i, shift)] = indicator

    # Rule 5: every client staffed in every shift, on every weekday.
    #
    # With allow_coverage_gaps the two coverage constraints gain a slack term
    # rather than being dropped. The solver must then still cover everything it
    # can - phase 0 minimises the slack - and what it could not cover is read
    # back as the gap report instead of being silently absent.
    redundancy_terms = []
    gap_terms = []
    for client, staff in members.items():
        for shift in SHIFTS:
            eligible = [i for i in staff if (i, shift) in x]
            staffed = sum(x[(i, shift)] for i in eligible)
            if options.allow_coverage_gaps:
                short = model.NewIntVar(0, options.min_per_client_shift,
                                        f"short_{client}_{shift}")
                model.Add(staffed + short >= options.min_per_client_shift)
                # Weighted below a whole uncovered day: being one body light on
                # a shift is a thinner failure than leaving a day unstaffed.
                gap_terms.append((short, 1))
            else:
                model.Add(staffed >= options.min_per_client_shift)
            off_length = OFF_DAYS_PER_WEEK[shift]
            for weekday in range(7):
                on_duty = [z[(i, shift, k)] for i in eligible for k in range(7)
                           if works_on(k, off_length, weekday)]
                if options.allow_coverage_gaps:
                    uncovered = model.NewBoolVar(f"gap_{client}_{shift}_{weekday}")
                    model.Add(sum(on_duty) + uncovered >= 1)
                    gap_terms.append((uncovered, 10))
                else:
                    model.Add(sum(on_duty) >= 1)
                if options.prefer_redundancy:
                    spare = model.NewBoolVar(f"spare_{client}_{shift}_{weekday}")
                    model.Add(sum(on_duty) >= 2).OnlyEnforceIf(spare)
                    model.Add(sum(on_duty) <= 1).OnlyEnforceIf(spare.Not())
                    redundancy_terms.append(spare)

    # Keep the four shifts roughly the same size.
    lower = max(0, math.floor(n / len(SHIFTS)) - slack)
    upper = math.ceil(n / len(SHIFTS)) + slack
    for shift in SHIFTS:
        headcount = sum(x[(i, shift)] for i in range(n) if (i, shift) in x)
        model.Add(headcount >= lower)
        model.Add(headcount <= upper)

    preference = []
    for i in range(n):
        for shift, score in shift_scores[i].items():
            preference.append(int(round(score * SCALE)) * x[(i, shift)])
            for k in range(7):
                preference.append(
                    int(round(off_scores[i][(shift, k)] * SCALE)) * z[(i, shift, k)])

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 8
    solver.parameters.random_seed = options.seed

    # -- phase 0: leave as few slots uncovered as this team allows ---------
    # Coverage outranks preference, so it is settled first and then held: the
    # learner may choose between equally-covered rosters, never buy a nicer
    # score with somebody's client going unstaffed.
    if gap_terms:
        penalty = sum(weight * term for term, weight in gap_terms)
        model.Minimize(penalty)
        solver.parameters.max_time_in_seconds = options.time_limit_seconds
        if solver.Solve(model) not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            return None
        model.Add(penalty <= int(round(solver.ObjectiveValue())))

    # -- phase 1: the best roster the learner can ask for ------------------
    model.Maximize(sum(preference))
    solver.parameters.max_time_in_seconds = options.time_limit_seconds
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None

    seconds = solver.WallTime()
    status_name = f"{solver.StatusName(status)} (preference)"
    best_preference = int(round(solver.ObjectiveValue()))
    picks = _read_picks(solver, z, n)
    redundancy = sum(1 for term in redundancy_terms if solver.Value(term))

    # -- phase 2: spend the remaining freedom on spare cover ---------------
    if redundancy_terms:
        # Hand phase 1's roster over as a hint so phase 2 always starts from a
        # valid incumbent and can only improve on it within its time budget.
        for i, (shift, start) in enumerate(picks):
            model.AddHint(z[(i, shift, start)], 1)
        floor_value = int(best_preference * (1 - PREFERENCE_TOLERANCE))
        model.Add(sum(preference) >= floor_value)
        model.Maximize(sum(redundancy_terms))
        solver.parameters.max_time_in_seconds = min(options.time_limit_seconds,
                                                    REDUNDANCY_TIME_LIMIT)
        second = solver.Solve(model)
        seconds += solver.WallTime()
        if second in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            picks = _read_picks(solver, z, n)
            redundancy = int(round(solver.ObjectiveValue()))
            status_name += f" + {solver.StatusName(second)} (cover)"

    return picks, status_name, best_preference / SCALE, redundancy, seconds


def _read_picks(solver, z, n: int) -> list[tuple[str, int]]:
    picks = []
    for i in range(n):
        picks.append(next((s, k) for (e, s, k) in z if e == i and solver.Value(z[(e, s, k)])))
    return picks


def _explain(employee: EmployeeInput, shift: str, start: int, blended: float,
             prior: float, model: Optional[float]) -> str:
    off_length = OFF_DAYS_PER_WEEK[shift]
    block = ", ".join(WEEKDAYS[(start + i) % 7] for i in range(off_length))
    move = (f"{employee.previous_shift} -> {shift}" if employee.previous_shift
            else f"assigned {shift}")
    source = (f"model {model:.2f} / heuristic {prior:.2f}" if model is not None
              else f"heuristic {prior:.2f}")
    return f"{move} (score {blended:.2f}; {source}); week-off {block}"
