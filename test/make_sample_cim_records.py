"""Generate a deterministic sample CIM dataset for local testing.

    python3 make_sample_cim_records.py > sample_cim_records.json

The keys deliberately do NOT match the canonical names - they mimic the mixed
casing a real CIM app ends up with - so the field map in action 1 is exercised.
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone

UTC = timezone.utc
AS_OF = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)

PRIORITIES = ["Critical", "High", "Medium", "Low"]
SEVERITIES = ["Critical", "High", "Medium", "Low"]
TEAMS = ["SOC Tier 1", "SOC Tier 2", "Threat Hunting", "Fraud Ops"]
ANALYSTS = ["a.rahman", "j.silva", "m.okafor", "l.chen", "p.novak"]
SOURCES = ["EDR", "SIEM", "Email Gateway", "User Report", "Threat Intel"]
CATEGORIES = ["Phishing", "Malware", "Unauthorized Access", "Data Loss", "Policy Violation"]
OPEN_STATUSES = ["New", "In Progress", "Pending Review"]
CLOSED_STATUSES = ["Closed", "Resolved", "False Positive"]

SLA_HOURS = {"Critical": 4, "High": 12, "Medium": 48, "Low": 120}


def build(count=140, seed=20260907):
    rng = random.Random(seed)
    records = []
    for index in range(count):
        # Spread creations over 75 days so a 30-day window has real history
        # on both sides of it.
        created = AS_OF - timedelta(
            days=rng.uniform(0, 75), hours=rng.uniform(0, 24)
        )
        priority = rng.choices(PRIORITIES, weights=[1, 3, 5, 3])[0]
        # Older records are more likely to be closed already.
        age_days = (AS_OF - created).days
        closed_chance = min(0.92, 0.35 + age_days * 0.012)
        is_closed = rng.random() < closed_chance

        record = {
            "id": "cim-{:04d}".format(index + 1),
            "trackingFull": "CIM-{:05d}".format(1000 + index),
            "Alert Name": "{} detected on host-{:03d}".format(
                rng.choice(CATEGORIES), rng.randint(1, 250)),
            "priority": priority,
            "Severity": rng.choice(SEVERITIES),
            "assignedTo": rng.choice(ANALYSTS) if rng.random() > 0.12 else "",
            "assignmentGroup": rng.choice(TEAMS),
            "incidentType": rng.choice(CATEGORIES),
            "detectionSource": rng.choice(SOURCES),
            "createdDate": created.isoformat().replace("+00:00", "Z"),
            "slaDue": (created + timedelta(hours=SLA_HOURS[priority])).isoformat().replace("+00:00", "Z"),
        }

        if is_closed:
            # Resolution time scales with priority; a few stragglers run long.
            base_hours = SLA_HOURS[priority] * rng.uniform(0.2, 1.8)
            if rng.random() < 0.1:
                base_hours *= rng.uniform(3, 8)
            closed = min(created + timedelta(hours=base_hours), AS_OF)
            record["status"] = rng.choice(CLOSED_STATUSES)
            record["closedDate"] = closed.isoformat().replace("+00:00", "Z")
            record["modified"] = record["closedDate"]
        else:
            record["status"] = rng.choice(OPEN_STATUSES)
            record["closedDate"] = ""
            record["modified"] = AS_OF.isoformat().replace("+00:00", "Z")

        records.append(record)

    # A couple of deliberately broken rows: action 1 must skip them, not crash.
    records.append({"id": "cim-bad-1", "status": "New", "createdDate": ""})
    records.append({"id": "cim-bad-2", "status": "New", "createdDate": "not a date"})
    return records


if __name__ == "__main__":
    json.dump(build(), sys.stdout, indent=2)
    sys.stdout.write("\n")
