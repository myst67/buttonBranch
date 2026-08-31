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
