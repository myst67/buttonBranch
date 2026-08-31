"""The parser has to cope with whatever the scheduling team actually sends."""
from app.config import OFF_DAYS_PER_WEEK
from app.parsing import (RosterParseError, fit_off_block, is_off_value,
                         normalise_shift, parse_day_header, parse_roster_file)
import pytest


def test_reads_the_wide_layout_with_a_title_row(wide_workbook_bytes, team):
    roster = parse_roster_file(wide_workbook_bytes, "june.xlsx")

    assert roster.month == "2025-06"
    assert len(roster.employees) == len(team)

    first = roster.by_name()["Person 1"]
    assert first.shift == "Morning"
    assert first.clients == team[0]["client"]
    assert first.off_start == 0
    assert first.off_length == OFF_DAYS_PER_WEEK["Morning"]
    assert roster.next_month() == "2025-07"


def test_reads_csv_with_shorthand_shifts_and_week_off_spellings():
    csv = ("Employee,Client,Mon-01-Jul,Tue-02-Jul,Wed-03-Jul,Thu-04-Jul,Fri-05-Jul,"
           "Sat-06-Jul,Sun-07-Jul\n"
           "Asha,Client A; Client B,N,N,N,N,W/O,W/O,W/O\n"
           "Bala,Client A/Client C,OFF,OFF,M,M,M,M,M\n")
    roster = parse_roster_file(csv.encode(), "june.csv")

    asha = roster.by_name()["Asha"]
    assert asha.shift == "Night"
    assert asha.clients == ["Client A", "Client B"]
    assert asha.off_days == ["Fri", "Sat", "Sun"]

    bala = roster.by_name()["Bala"]
    assert bala.shift == "Morning"
    assert bala.clients == ["Client A", "Client C"]
    assert bala.off_days == ["Mon", "Tue"]


def test_reads_the_simple_one_row_per_employee_list():
    csv = ("name,last month shift,client\n"
           "Asha,Morning,\"a, b\"\n"
           "Bala,night,\"b, c\"\n")
    roster = parse_roster_file(csv.encode(), "team.csv", month_hint="2025-06")

    assert [e.shift for e in roster.employees] == ["Morning", "Night"]
    assert roster.employees[0].off_start is None
    assert any("week-off history is unknown" in w for w in roster.warnings)


def test_reads_the_json_input_format(team, tmp_path):
    import json

    roster = parse_roster_file(json.dumps(team).encode(), "team.json", month_hint="2025-06")
    assert len(roster.employees) == len(team)
    assert roster.employees[0].shift == "Morning"


def test_irregular_week_offs_are_fitted_and_flagged():
    csv = ("Name,Client,Mon-01-Jul,Tue-02-Jul,Wed-03-Jul,Thu-04-Jul,Fri-05-Jul,"
           "Sat-06-Jul,Sun-07-Jul,Mon-08-Jul,Tue-09-Jul,Wed-10-Jul,Thu-11-Jul,"
           "Fri-12-Jul,Sat-13-Jul,Sun-14-Jul\n"
           "Asha,\"a, b\",Off,Off,M,M,M,M,M,Off,M,M,M,M,Off,M\n")
    roster = parse_roster_file(csv.encode(), "june.csv")

    asha = roster.by_name()["Asha"]
    assert asha.off_start == 0          # the dominant Mon-Tue block wins
    assert any("irregular" in w for w in roster.warnings)


def test_rejects_a_file_with_nothing_to_learn_from():
    with pytest.raises(RosterParseError, match="employee-name column"):
        parse_roster_file(b"a,b\n1,2\n", "junk.csv")


def test_header_and_cell_normalisation():
    assert parse_day_header("Mon-01-Jul") == (1, 7, None)
    assert parse_day_header("2025-07-01") == (1, 7, 2025)
    assert parse_day_header("Name") == (None, None, None)
    assert normalise_shift("NIGHT") == "Night"
    assert normalise_shift("s2") == "Afternoon"
    assert normalise_shift("holiday") is None
    assert is_off_value("W/O") and is_off_value("off") and not is_off_value("Morning")


def test_off_block_fitting_picks_the_best_repeating_block():
    weekly = [[False] * 4, [True] * 4, [True] * 4, [False] * 4,
              [False] * 5, [False] * 5, [False] * 4]
    assert fit_off_block(weekly, 2) == (1, 2, 0)
    assert fit_off_block([[False] * 4 for _ in range(7)], 2) == (None, 2, 0)
