#!/usr/bin/env python
"""Work out how many employees a given number of clients needs, and write the team.

    python scripts/build_seed_team.py --clients 20

The arithmetic, for C clients:

* Rule 5 wants every client staffed in every shift on every day. One person is
  off 2-3 days a week, so a client/shift pair needs **2 people** minimum - hence
  ``MIN_PER_CLIENT_SHIFT * 4 shifts = 8`` employees per client as a hard floor.
* That floor is exactly tight: with 8 people a client has exactly 2 per shift,
  so their week-offs have to be perfectly disjoint *and* last month's shifts
  have to allow it. Measured over 10 random last-month shift mixes, a 20-client
  team of 48 (the floor) failed 3 times. ``TARGET_PER_CLIENT`` is the headroom
  that makes it hold every month.
* Rule 2 caps an employee at 4 clients, so:

      employees = ceil(C * TARGET_PER_CLIENT / average clients per employee)

For C = 20 that is ceil(20 * 10 / 3.33) = 60.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import MIN_PER_CLIENT_SHIFT, SHIFTS  # noqa: E402

#: Rule 2 allows 2, 3 or 4 clients each - use all three, averaging 3.33.
CLIENTS_PER_EMPLOYEE = (4, 3, 4, 2, 4, 3)
#: The hard floor is MIN_PER_CLIENT_SHIFT * len(SHIFTS); this is the working target.
TARGET_PER_CLIENT = 10


def required_employees(n_clients: int, target_per_client: int = TARGET_PER_CLIENT) -> int:
    average = sum(CLIENTS_PER_EMPLOYEE) / len(CLIENTS_PER_EMPLOYEE)
    return math.ceil(n_clients * target_per_client / average)


def build_team(n_clients: int, n_employees: int) -> list[dict]:
    """Deal clients out so every client ends up with the same headcount (+-1).

    Each client is given a share of the total assignments, and every employee
    takes the clients with the most demand still outstanding. That keeps the
    client sets varied - no two clients sharing nearly the same people, which is
    what makes cover fragile - without relying on a stride pattern that can
    silently fold back on itself.
    """
    clients = [f"Client {i + 1:02d}" for i in range(n_clients)]
    sizes = [CLIENTS_PER_EMPLOYEE[i % len(CLIENTS_PER_EMPLOYEE)] for i in range(n_employees)]
    total = sum(sizes)

    base, extra = divmod(total, n_clients)
    remaining = {client: base + (1 if index < extra else 0)
                 for index, client in enumerate(clients)}

    team: list[dict] = []
    for index, size in enumerate(sizes):
        if size > n_clients:
            raise SystemExit(f"Cannot give an employee {size} of only {n_clients} clients.")
        # Most-outstanding-demand first; the name is only a deterministic tie-break.
        picked = sorted(clients, key=lambda c: (-remaining[c], c))[:size]
        for client in picked:
            remaining[client] -= 1
        team.append({
            "employee": f"Person {index + 1}",
            "last_month_shift": SHIFTS[index % len(SHIFTS)],
            "client": sorted(picked),
        })
    return team


def summarise(team: list[dict]) -> dict:
    counts: dict[str, int] = {}
    for employee in team:
        for client in employee["client"]:
            counts[client] = counts.get(client, 0) + 1
    return {
        "employees": len(team),
        "clients": len(counts),
        "assignments": sum(len(e["client"]) for e in team),
        "per_client_min": min(counts.values()),
        "per_client_max": max(counts.values()),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clients", type=int, default=20)
    parser.add_argument("--employees", type=int, default=None,
                        help="override the calculated headcount")
    parser.add_argument("--out", default=str(ROOT / "data" / "seed" / "team.json"))
    args = parser.parse_args()

    floor = MIN_PER_CLIENT_SHIFT * len(SHIFTS)
    employees = args.employees or required_employees(args.clients)
    team = build_team(args.clients, employees)
    stats = summarise(team)

    if stats["clients"] != args.clients:
        raise SystemExit(f"Only {stats['clients']} of {args.clients} clients were used.")
    if stats["per_client_max"] - stats["per_client_min"] > 1:
        raise SystemExit(
            f"Uneven spread: {stats['per_client_min']}-{stats['per_client_max']} per client.")
    if stats["per_client_min"] < floor:
        raise SystemExit(
            f"Only {stats['per_client_min']} employees on the thinnest client; "
            f"{floor} are needed for 24x7 cover in all {len(SHIFTS)} shifts.")

    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(team, indent=2) + "\n")

    print(f"Wrote {path}")
    print(f"  {stats['employees']} employees over {stats['clients']} clients")
    print(f"  {stats['assignments']} client assignments, "
          f"{stats['per_client_min']}-{stats['per_client_max']} employees per client "
          f"(hard floor {floor})")


if __name__ == "__main__":
    main()
