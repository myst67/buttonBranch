"""Whatever the model prefers, the roster must obey every rule."""
import pytest

from app.config import OFF_DAYS_PER_WEEK, OFF_LABEL, SHIFTS
from app.ml import RosterLearner
from app.roster import build_roster
from app.solver import (EmployeeInput, InfeasibleRoster, SolverOptions,
                        check_feasibility, solve_roster)
from app.validation import validate
from conftest import month_roster


#: Keep the suite quick - the second (cover) phase is best-effort anyway.
FAST = SolverOptions(time_limit_seconds=2.0)


def _team_inputs(team):
    return [EmployeeInput(row["employee"], list(row["client"]), row["last_month_shift"])
            for row in team]


@pytest.fixture
def learner(team):
    trained = RosterLearner()
    trained.train([month_roster(team, f"2025-{month:02d}", shift_offset=offset)
                   for offset, month in enumerate(range(3, 7))])
    return trained


@pytest.fixture
def solved(team, learner):
    return solve_roster(_team_inputs(team), learner, FAST)


@pytest.mark.parametrize("month", ["2025-07", "2025-02", "2024-02", "2025-11", "2026-01"])
def test_every_rule_holds_for_any_month(team, learner, month):
    result = solve_roster(_team_inputs(team), learner, SolverOptions(seed=7, time_limit_seconds=2.0))
    roster = build_roster(result.assignments, month)
    report = validate(roster)
    assert report["ok"], report["errors"][:5]


def test_rule_3_one_shift_all_month_and_never_last_months(team, solved):
    previous = {row["employee"]: row["last_month_shift"] for row in team}
    roster = build_roster(solved.assignments, "2025-07")
    for row in roster.rows:
        assert set(row.cells) - {OFF_LABEL} == {row.shift}
        assert row.shift != previous[row.name]


def test_rule_4_night_gets_three_offs_and_four_working_days(solved):
    roster = build_roster(solved.assignments, "2025-07")
    for row in roster.rows:
        assert row.off_length == OFF_DAYS_PER_WEEK[row.shift]
        for start in range(len(row.cells) - 6):
            week = row.cells[start:start + 7]
            assert week.count(OFF_LABEL) == OFF_DAYS_PER_WEEK[row.shift]


def test_rule_5_every_client_is_staffed_in_every_shift_every_day(solved, team):
    roster = build_roster(solved.assignments, "2025-07")
    clients = {c for row in team for c in row["client"]}
    assert len(roster.coverage) == len(clients) * len(SHIFTS)
    for entry in roster.coverage:
        assert entry.minimum >= 1, f"{entry.client}/{entry.shift} drops to 0"
        assert entry.headcount >= 2


def test_shift_headcounts_stay_balanced(solved, team):
    sizes = [sum(1 for a in solved.assignments if a.shift == shift) for shift in SHIFTS]
    assert max(sizes) - min(sizes) <= 2
    assert sum(sizes) == len(team)


def test_the_solver_explains_each_move(solved):
    for assignment in solved.assignments:
        assert assignment.previous_shift in assignment.reason
        assert "week-off" in assignment.reason
        assert 0.0 <= assignment.shift_score <= 1.0


def test_a_client_with_too_few_people_is_rejected_with_a_reason(team, learner):
    thin = [dict(row) for row in team]
    for row in thin:
        row["client"] = [c for c in row["client"] if c != "Client F"] or ["Client A"]
    thin[0]["client"] = list(dict.fromkeys(thin[0]["client"] + ["Client F"]))
    thin[1]["client"] = list(dict.fromkeys(thin[1]["client"] + ["Client F"]))

    with pytest.raises(InfeasibleRoster) as error:
        solve_roster(_team_inputs(thin), learner, FAST)
    assert any("Client F" in reason for reason in error.value.reasons)


def test_a_shift_nobody_may_take_is_reported_before_solving(team):
    blocked = [dict(row) for row in team]
    for row in blocked:
        if "Client A" in row["client"]:
            row["last_month_shift"] = "Night"
    reasons = check_feasibility(_team_inputs(blocked), SolverOptions())
    assert any("Night" in reason and "Client A" in reason for reason in reasons)


def test_validation_catches_a_roster_that_breaks_a_rule(solved):
    roster = build_roster(solved.assignments, "2025-07")
    row = roster.rows[0]
    index = next(i for i in range(10, 20) if row.cells[i] != OFF_LABEL)
    row.cells[index] = OFF_LABEL                 # an extra day off, out of pattern

    report = validate(roster)
    assert not report["ok"]
    assert any(row.name in error for error in report["errors"])


# -- accepting a team whose shape breaks rule 2 -------------------------------

def _single_client(team):
    """The same team with one person cut back to a single client.

    The client they keep is chosen so that no client drops below the coverage
    floor: the point of the fixture is a rule 2 problem on its own, with the
    arithmetic still satisfiable.
    """
    reduced = [dict(row, client=list(row["client"])) for row in team]
    counts = {}
    for row in reduced:
        for client in row["client"]:
            counts[client] = counts.get(client, 0) + 1
    for row in reduced:
        if all(counts[c] > 8 for c in row["client"][1:]):
            row["client"] = row["client"][:1]
            return reduced, row["employee"]
    raise AssertionError("no employee could be reduced without breaking coverage")


def test_a_one_client_employee_blocks_by_default(team, learner):
    reduced, name = _single_client(team)
    with pytest.raises(InfeasibleRoster) as error:
        solve_roster(_team_inputs(reduced), learner, FAST)
    assert any(name in reason for reason in error.value.reasons)


def test_accepting_the_team_shape_builds_a_roster_that_still_obeys_every_rule(team, learner):
    reduced, name = _single_client(team)
    options = SolverOptions(time_limit_seconds=2.0, accept_team_shape=True)

    result = solve_roster(_team_inputs(reduced), learner, options)
    roster = build_roster(result.assignments, "2025-07")
    report = validate(roster, accept_team_shape=True)

    # The waiver covers the input's shape, never the schedule.
    assert report["schedule_ok"], report["errors"][:5]
    assert report["ok"], report["errors"][:5]
    assert any(name in entry for entry in report["team_shape"])
    # The exception is recorded rather than silently dropped.
    assert any(name in note for note in result.notes)


def test_accepting_the_team_shape_does_not_waive_the_coverage_arithmetic(team, learner):
    """A client too small to cover four shifts blocks either way: no roster obeying
    rule 5 exists, so building one could only produce a sheet with holes."""
    thin = [row for row in team if "Client F" not in row["client"]]
    thin += [dict(row, client=list(row["client"])) for row in team
             if "Client F" in row["client"]][:3]

    for accept in (False, True):
        options = SolverOptions(time_limit_seconds=2.0, accept_team_shape=accept)
        with pytest.raises(InfeasibleRoster) as error:
            solve_roster(_team_inputs(thin), learner, options)
        assert any("Client F" in reason for reason in error.value.reasons)


def test_classify_splits_the_two_kinds_of_problem(team):
    from app.solver import classify_feasibility

    reduced, name = _single_client(team)
    blocking, advisory = classify_feasibility(_team_inputs(reduced), SolverOptions())
    assert blocking == []
    assert any(name in entry for entry in advisory)


# -- building through a coverage gap ------------------------------------------

def _thin_client(team, keep=3):
    """The team with Client F cut to ``keep`` people - below the 8 that covering
    four shifts on seven days needs, so some day must go uncovered."""
    thin = [dict(row, client=[c for c in row["client"] if c != "Client F"])
            for row in team]
    given = 0
    for row in thin:
        if given == keep:
            break
        if len(row["client"]) < 4:
            row["client"] = row["client"] + ["Client F"]
            given += 1
    return [row for row in thin if row["client"]]


def test_a_thin_client_still_refuses_unless_gaps_are_allowed(team, learner):
    thin = _thin_client(team)
    with pytest.raises(InfeasibleRoster):
        solve_roster(_team_inputs(thin), learner, FAST)


def test_allowing_gaps_builds_the_best_roster_the_team_allows(team, learner):
    thin = _thin_client(team)
    options = SolverOptions(time_limit_seconds=5.0, allow_coverage_gaps=True)

    result = solve_roster(_team_inputs(thin), learner, options)
    roster = build_roster(result.assignments, "2025-07")
    report = validate(roster, accept_team_shape=True, accept_coverage_gaps=True)

    # Rules 3 and 4 are never traded away to plug a hole.
    assert report["schedule_ok"], report["errors"][:5]
    # The thin client is the one that goes short, and it is named.
    assert not report["fully_covered"]
    assert all("Client F" in gap for gap in report["coverage_gaps"])
    # Everything the team could cover, it did.
    for entry in roster.coverage:
        if entry.client != "Client F":
            assert min(entry.per_day) >= 1, f"{entry.client}/{entry.shift} went short"


def test_gaps_are_minimised_not_merely_permitted(team, learner):
    """Allowing gaps must not licence the solver to leave more uncovered than
    it has to: a team that can be fully covered still is."""
    options = SolverOptions(time_limit_seconds=5.0, allow_coverage_gaps=True)

    result = solve_roster(_team_inputs(team), learner, options)
    roster = build_roster(result.assignments, "2025-07")
    report = validate(roster, accept_team_shape=True, accept_coverage_gaps=True)

    assert report["fully_covered"], report["coverage_gaps"][:5]
    assert report["ok"], report["errors"][:5]


def test_the_gap_report_names_the_fix(team):
    from app.gaps import analyse

    thin = _thin_client(team)
    report = analyse(_team_inputs(thin), 2)

    entry = next(c for c in report["clients_short"] if c["client"] == "Client F")
    assert entry["short"] == entry["needed"] - entry["employees"]
    moves = [m for m in report["moves"] if m["client"] == "Client F"]
    assert len(moves) == entry["short"]
    assert all(m["clients_after"] <= 4 for m in moves)
