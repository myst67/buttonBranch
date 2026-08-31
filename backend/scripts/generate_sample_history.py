#!/usr/bin/env python
"""Write a realistic "last month" roster you can upload straight into the UI.

    python scripts/generate_sample_history.py

Produces data/sample/last-month-<month>.xlsx in the wide layout the parser
expects, built from the seed team in data/seed (run build_seed_team.py first
to change its size).
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.calendar_utils import next_month  # noqa: E402
from app.exporting import export_to_file  # noqa: E402
from app.service import RosterService  # noqa: E402

TEAM = ROOT / "data" / "seed" / "team.json"
SEED_MONTH = "2025-05"


def main() -> None:
    team = json.loads(TEAM.read_text())
    target = next_month(SEED_MONTH)

    with tempfile.TemporaryDirectory() as scratch:
        scratch = Path(scratch)
        service = RosterService(history_dir=scratch / "history",
                                model_dir=scratch / "models",
                                export_dir=scratch / "exports")
        service.upload(json.dumps(team).encode(), "team.json", month_hint=SEED_MONTH)
        roster = service.generate(month=target, time_limit_seconds=8)

        out_dir = ROOT / "data" / "sample"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = export_to_file(roster, out_dir / f"last-month-{target}.xlsx")

    print(f"Wrote {path.relative_to(ROOT)}")
    print(f"  {len(roster.rows)} employees, {len(roster.month.days)} days, "
          f"rules valid: {roster.validation['ok']}")
    print("  Upload it on the Last month tab to build the next month.")


if __name__ == "__main__":
    main()
