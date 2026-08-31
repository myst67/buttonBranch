"""The team shipped in data/seed has to be usable out of the box."""
from app.config import MIN_PER_CLIENT_SHIFT, SHIFTS
from app.ml import RosterLearner
from app.roster import build_roster
from app.solver import EmployeeInput, SolverOptions, check_feasibility, solve_roster
from app.validation import validate
from conftest import month_roster


def test_the_seed_team_has_20_clients_and_enough_people(seed_team):
    counts: dict[str, int] = {}
    for employee in seed_team:
        assert 2 <= len(employee["client"]) <= 4                    # rule 2
        assert len(set(employee["client"])) == len(employee["client"])
        for client in employee["client"]:
            counts[client] = counts.get(client, 0) + 1

    assert len(seed_team) == 60
    assert len(counts) == 20
    # A client needs two people per shift before 24x7 cover is possible at all.
    floor = MIN_PER_CLIENT_SHIFT * len(SHIFTS)
    assert min(counts.values()) >= floor
    assert max(counts.values()) - min(counts.values()) <= 1         # evenly spread
    assert sorted({len(e["client"]) for e in seed_team}) == [2, 3, 4]


def test_the_seed_team_produces_a_valid_month(seed_team):
    inputs = [EmployeeInput(e["employee"], e["client"], e["last_month_shift"])
              for e in seed_team]
    assert check_feasibility(inputs, SolverOptions()) == []

    learner = RosterLearner()
    learner.train([month_roster(seed_team, "2025-06")])
    result = solve_roster(inputs, learner, SolverOptions(time_limit_seconds=3))

    roster = build_roster(result.assignments, "2025-07")
    report = validate(roster)
    assert report["ok"], report["errors"][:5]
    assert report["checked"] == {"employees": 60, "clients": 20, "days": 31,
                                 "client_shift_day_slots": 20 * len(SHIFTS) * 31}
    # Rule 5, stated the other way round: nobody's client is ever left unstaffed.
    assert min(entry.minimum for entry in roster.coverage) >= 1
