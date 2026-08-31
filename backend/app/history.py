"""Every uploaded month is kept, because the model gets better with each one."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .config import HISTORY_DIR
from .models import MonthRoster


class HistoryStore:
    """A directory of ``<YYYY-MM>.json`` files - the model's training set."""

    def __init__(self, directory: Path | str = HISTORY_DIR):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, month: str) -> Path:
        return self.directory / f"{month}.json"

    def save(self, roster: MonthRoster) -> Path:
        path = self._path(roster.month)
        path.write_text(json.dumps(roster.to_dict(), indent=2), encoding="utf-8")
        return path

    def load(self, month: str) -> Optional[MonthRoster]:
        path = self._path(month)
        if not path.exists():
            return None
        return MonthRoster.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def months(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.json"))

    def load_all(self) -> list[MonthRoster]:
        """All stored months, oldest first - the order the model learns in."""
        return [r for r in (self.load(m) for m in self.months()) if r is not None]

    def latest(self) -> Optional[MonthRoster]:
        months = self.months()
        return self.load(months[-1]) if months else None

    def delete(self, month: str) -> bool:
        path = self._path(month)
        if path.exists():
            path.unlink()
            return True
        return False
