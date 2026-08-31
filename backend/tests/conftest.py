import json
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.models import EmployeeMonth, MonthRoster  # noqa: E402
from app.service import RosterService  # noqa: E402

TEAM_FILE = Path(__file__).resolve().parent / "data" / "team-small.json"
SEED_TEAM_FILE = Path(__file__).resolve().parents[1] / "data" / "seed" / "team.json"


@pytest.fixture
def team() -> list[dict]:
    """A small 23-employee / 6-client team, so the rule tests stay quick."""
    return json.loads(TEAM_FILE.read_text())


@pytest.fixture
def seed_team() -> list[dict]:
    """The team actually shipped in data/seed - 60 employees over 20 clients."""
    return json.loads(SEED_TEAM_FILE.read_text())


@pytest.fixture
def service(tmp_path) -> RosterService:
    return RosterService(history_dir=tmp_path / "history",
                         model_dir=tmp_path / "models",
                         export_dir=tmp_path / "exports")


def month_roster(team: list[dict], month: str, shift_offset: int = 0,
                 with_offs: bool = True) -> MonthRoster:
    """Synthesise a past month by rotating everyone forward ``shift_offset`` slots."""
    from app.config import OFF_DAYS_PER_WEEK, SHIFTS

    employees = []
    for index, row in enumerate(team):
        shift = SHIFTS[(SHIFTS.index(row["last_month_shift"]) + shift_offset) % 4]
        employees.append(EmployeeMonth(
            name=row["employee"], clients=list(row["client"]), shift=shift,
            off_start=(index * 3) % 7 if with_offs else None,
            off_length=OFF_DAYS_PER_WEEK[shift] if with_offs else None))
    return MonthRoster(month=month, employees=employees)


@pytest.fixture
def wide_workbook_bytes(team):
    """A last-month roster in the wide "Name | Client | Mon-01-Jul" layout."""
    from io import BytesIO

    from app.calendar_utils import build_month
    from app.config import OFF_DAYS_PER_WEEK, works_on

    month = build_month("2025-06")
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["Monthly roster - June 2025"])  # a title row, as real sheets have
    sheet.append(["Name", "Client"] + [d.label for d in month.days])
    for index, row in enumerate(team):
        shift = row["last_month_shift"]
        start = (index * 3) % 7
        length = OFF_DAYS_PER_WEEK[shift]
        cells = [shift if works_on(start, length, d.weekday) else "Off" for d in month.days]
        sheet.append([row["employee"], ", ".join(row["client"])] + cells)
    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()
