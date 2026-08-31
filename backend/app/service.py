"""Wires the pieces together: upload -> learn -> solve -> validate -> export."""
from __future__ import annotations

import datetime as dt
import uuid
from pathlib import Path
from typing import Optional

from .calendar_utils import next_month
from .config import EXPORT_DIR, HISTORY_DIR, MODEL_DIR, MIN_PER_CLIENT_SHIFT
from .exporting import export_to_bytes, export_to_csv, export_to_file
from .history import HistoryStore
from .ml import RosterLearner
from .models import MonthRoster
from .parsing import parse_roster_file
from .roster import GeneratedRoster, build_roster
from .solver import (EmployeeInput, InfeasibleRoster, SolverOptions,
                     check_feasibility, solve_roster)
from .validation import validate


class RosterService:
    def __init__(self, history_dir: Path | str = HISTORY_DIR,
                 model_dir: Path | str = MODEL_DIR,
                 export_dir: Path | str = EXPORT_DIR):
        self.store = HistoryStore(history_dir)
        self.model_dir = Path(model_dir)
        self.export_dir = Path(export_dir)
        self.export_dir.mkdir(parents=True, exist_ok=True)
        self._learner: Optional[RosterLearner] = None
        self._generated: dict[str, GeneratedRoster] = {}

    # -- model ------------------------------------------------------------
    @property
    def learner(self) -> RosterLearner:
        """Loads the trained model, training one on the spot if there is none."""
        if self._learner is None:
            self._learner = RosterLearner.load(self.model_dir) or self.train()
        return self._learner

    def train(self) -> RosterLearner:
        """Refit both rankers on everything uploaded so far."""
        learner = RosterLearner()
        learner.train(self.store.load_all())
        learner.save(self.model_dir)
        self._learner = learner
        return learner

    def model_report(self) -> dict:
        report = self.learner.report
        return report.to_dict() if report else {"n_history_months": 0, "months": []}

    # -- history ----------------------------------------------------------
    def upload(self, content: bytes, filename: str, month_hint: Optional[str] = None,
               persist: bool = True) -> dict:
        """Take last month's roster, store it, and learn from it."""
        parsed = parse_roster_file(content, filename, month_hint)
        if persist:
            self.store.save(parsed)
            self.train()

        target = parsed.next_month()
        employees = self._employees_from(parsed)
        blockers = check_feasibility(employees, SolverOptions())

        return {
            "month": parsed.month,
            "month_label": parsed.label,
            "target_month": target,
            "employees": [e.to_dict() for e in parsed.employees],
            "clients": parsed.clients,
            "warnings": parsed.warnings,
            "blockers": blockers,
            "ready": not blockers,
            "training": self.model_report(),
        }

    def history(self) -> list[dict]:
        summaries = []
        for roster in self.store.load_all():
            summaries.append({
                "month": roster.month,
                "month_label": roster.label,
                "employees": len(roster.employees),
                "clients": len(roster.clients),
                "with_off_pattern": sum(1 for e in roster.employees if e.off_start is not None),
                "warnings": len(roster.warnings),
            })
        return summaries

    def delete_month(self, month: str) -> bool:
        removed = self.store.delete(month)
        if removed:
            self.train()
        return removed

    # -- generation -------------------------------------------------------
    def generate(self, month: Optional[str] = None, source_month: Optional[str] = None,
                 employees: Optional[list[dict]] = None, seed: int = 42,
                 time_limit_seconds: float = 20.0,
                 min_per_client_shift: int = MIN_PER_CLIENT_SHIFT,
                 balance_slack: int = 1) -> GeneratedRoster:
        """Build the target month from the stored history (rule 1-6 guaranteed)."""
        base = self.store.load(source_month) if source_month else self.store.latest()
        if base is None and not employees:
            raise ValueError(
                "No last-month roster has been uploaded yet, so there is nothing to "
                "build this month from.")

        team = ([EmployeeInput(name=e["employee"] if "employee" in e else e["name"],
                               clients=list(e.get("client") or e.get("clients") or []),
                               previous_shift=e.get("last_month_shift") or e.get("shift"))
                 for e in employees]
                if employees else self._employees_from(base))

        target = month or (next_month(base.month) if base else None)
        if not target:
            raise ValueError("No target month given and none could be inferred.")

        options = SolverOptions(min_per_client_shift=min_per_client_shift,
                                balance_slack=balance_slack, seed=seed,
                                time_limit_seconds=time_limit_seconds)
        result = solve_roster(team, self.learner, options)

        meta = {
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "source_month": base.month if base else None,
            "solver_status": result.status,
            "solve_seconds": result.solve_seconds,
            "objective": round(result.objective, 3),
            "balance_slack_used": result.balance_slack_used,
            "notes": result.notes,
            "training": self.model_report(),
        }
        roster = build_roster(result.assignments, target, meta)
        roster.validation = validate(roster)

        roster_id = uuid.uuid4().hex[:12]
        roster.meta["id"] = roster_id
        self._generated[roster_id] = roster
        export_to_file(roster, self.export_dir / f"roster-{target}-{roster_id}.xlsx")
        return roster

    # -- export -----------------------------------------------------------
    def get(self, roster_id: str) -> Optional[GeneratedRoster]:
        return self._generated.get(roster_id)

    def export_xlsx(self, roster_id: str) -> Optional[bytes]:
        roster = self.get(roster_id)
        return export_to_bytes(roster) if roster else None

    def export_csv(self, roster_id: str) -> Optional[str]:
        roster = self.get(roster_id)
        return export_to_csv(roster) if roster else None

    # -- helpers ----------------------------------------------------------
    @staticmethod
    def _employees_from(roster: MonthRoster) -> list[EmployeeInput]:
        return [EmployeeInput(name=e.name, clients=list(e.clients), previous_shift=e.shift)
                for e in roster.employees]


__all__ = ["RosterService", "InfeasibleRoster"]
