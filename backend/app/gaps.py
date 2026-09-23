"""Where the team cannot cover every client, and the smallest fix for it.

The solver can build a roster through a coverage gap, but a gap is a client
with nobody on duty on some day - it is worth knowing exactly how big the hole
is and what would close it. This module answers both without solving anything:
it is arithmetic over the client/employee mapping.

The recommendation is a concrete list of moves - give this person that client -
chosen to close every gap with as few changes as possible, preferring the
people who are under the rule 2 minimum anyway so one edit fixes two problems.
"""
from __future__ import annotations

from .config import (MAX_CLIENTS_PER_EMPLOYEE, MIN_CLIENTS_PER_EMPLOYEE, SHIFTS)


def analyse(employees, min_per_client_shift: int = 2) -> dict:
    """The coverage shortfall per client, and the moves that would close it.

    ``employees`` is a list of objects with ``name``, ``clients`` and
    ``previous_shift`` - the solver's ``EmployeeInput``.
    """
    needed = min_per_client_shift * len(SHIFTS)

    by_client: dict[str, list] = {}
    for employee in employees:
        for client in employee.clients:
            by_client.setdefault(client, []).append(employee)

    short: list[dict] = []
    for client, staff in sorted(by_client.items()):
        shortfall = needed - len(staff)
        blocked_shifts = []
        for shift in SHIFTS:
            eligible = sum(1 for e in staff if e.previous_shift != shift)
            if eligible < min_per_client_shift:
                blocked_shifts.append({
                    "shift": shift, "eligible": eligible,
                    "needed": min_per_client_shift,
                    "note": f"{len(staff) - eligible} of the {len(staff)} worked "
                            f"{shift} last month and may not repeat it.",
                })
        if shortfall > 0 or blocked_shifts:
            short.append({
                "client": client,
                "employees": len(staff),
                "needed": needed,
                "short": max(0, shortfall),
                "shifts_blocked": blocked_shifts,
            })

    moves, unresolved = _plan(employees, by_client, short, min_per_client_shift)

    return {
        "ok": not short,
        "needed_per_client": needed,
        "min_per_client_shift": min_per_client_shift,
        "clients_short": short,
        "moves": moves,
        "unresolved": unresolved,
        "summary": _summary(short, moves, unresolved),
    }


def _plan(employees, by_client, short, min_per_client_shift):
    """Pick who to give which client, fewest moves first.

    Preference order for a candidate: the fewest clients today (so the move
    also pulls them up to the rule 2 minimum), then a last-month shift that is
    not the one the client is blocked on, so the addition is actually eligible
    for the shift that needs a body.
    """
    # Copied, because planning a move has to be visible to the next one: two
    # clients must not both be offered the same person's last free slot.
    load = {e.name: list(e.clients) for e in employees}
    by_name = {e.name: e for e in employees}

    moves: list[dict] = []
    unresolved: list[str] = []

    for entry in sorted(short, key=lambda c: -c["short"]):
        client = entry["client"]
        blocked = {b["shift"] for b in entry["shifts_blocked"]}
        wanted = entry["short"]
        # A blocked shift needs a body eligible for it even when the headcount
        # is otherwise fine, so ask for at least one.
        if not wanted and blocked:
            wanted = len(blocked)

        for placed in range(wanted):
            candidates = [
                name for name, clients in load.items()
                if client not in clients and len(clients) < MAX_CLIENTS_PER_EMPLOYEE
            ]
            if not candidates:
                unresolved.append(
                    f'Client "{client}" is still {wanted - placed} person(s) short and '
                    f"nobody has room for another client without passing the "
                    f"{MAX_CLIENTS_PER_EMPLOYEE}-client ceiling. This one needs a hire.")
                break

            def rank(name):
                employee = by_name[name]
                helps_blocked = any(employee.previous_shift != s for s in blocked) if blocked else False
                return (len(load[name]),                    # fewest clients first
                        0 if helps_blocked else 1,          # eligible where it is needed
                        name)

            chosen = min(candidates, key=rank)
            employee = by_name[chosen]
            load[chosen].append(client)
            moves.append({
                "employee": chosen,
                "client": client,
                "clients_before": len(load[chosen]) - 1,
                "clients_after": len(load[chosen]),
                "previous_shift": employee.previous_shift,
                "why": _why(len(load[chosen]) - 1, client),
            })
    return moves, unresolved


def _why(clients_before: int, client: str) -> str:
    if clients_before < MIN_CLIENTS_PER_EMPLOYEE:
        return (f'Adding "{client}" brings them to {clients_before + 1} clients, which '
                f"also clears their rule 2 exception.")
    return f'They have room for "{client}" without passing the {MAX_CLIENTS_PER_EMPLOYEE}-client ceiling.'


def _summary(short, moves, unresolved) -> str:
    if not short:
        return "Every client has enough people to be covered in all four shifts."
    people = len({m["employee"] for m in moves})
    head = (f"{len(short)} client(s) cannot be covered in every shift on every day. "
            f"{len(moves)} client assignment(s) across {people} person(s) would close "
            f"the gap without hiring.")
    if unresolved:
        head += f" {len(unresolved)} of them cannot be closed by reassignment alone."
    return head
