"""Run all five playbook actions end to end, off the playbook.

    python3 run_pipeline_local.py
    python3 run_pipeline_local.py --records sample_cim_records.json \
        --period last_30_days --now 2026-09-07T12:00:00Z --out out.json

Each action is loaded from its numbered file and called exactly the way Turbine
calls it, so what you see here is what the playbook produces.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ACTIONS = [
    ("01_normalize_cim_records.py", "normalize"),
    ("02_compute_kpi_metrics.py", "metrics"),
    ("03_build_trend_series.py", "trend"),
    ("04_build_dashboard_payload.py", "dashboard"),
    ("05_build_kpi_record_payload.py", "record"),
]


def load_action(filename):
    """Import a module whose name starts with a digit."""
    path = os.path.join(HERE, filename)
    module_name = "action_" + os.path.splitext(filename)[0].replace("-", "_")
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class Context:
    """Stand-in for the Turbine context object."""

    def __init__(self, inputs):
        self.inputs = dict(inputs)


def run(records, period="last_30_days", now=None, granularity="day",
        field_map=None, closed_statuses=None, top_n=10, previous_metrics=None):
    modules = {name: load_action(filename) for filename, name in ACTIONS}

    step1 = modules["normalize"].main(Context({
        "records": records,
        "period": period,
        "now": now,
        "field_map": field_map,
        "closed_statuses": closed_statuses,
    }))

    step2 = modules["metrics"].main(Context({
        "records": step1["records"],
        "period": step1["period"],
        "now": now,
        "top_n": top_n,
    }))

    step3 = modules["trend"].main(Context({
        "records": step1["records"],
        "period": step1["period"],
        "granularity": granularity,
    }))

    step4 = modules["dashboard"].main(Context({
        "metrics": step2["metrics"],
        "trend": step3["trend"],
        "previous_metrics": previous_metrics,
    }))

    step5 = modules["record"].main(Context({
        "metrics": step2["metrics"],
        "dashboard": step4["dashboard"],
        "trend": step3["trend"],
    }))

    return {
        "normalize": step1,
        "metrics": step2["metrics"],
        "trend": step3["trend"],
        "dashboard": step4["dashboard"],
        "checks": step4["checks"],
        "record": step5,
    }


def _print_summary(result):
    totals = result["metrics"]["totals"]
    checks = result["checks"]
    print("Period      : {} -> {}".format(
        result["metrics"]["period"]["start"], result["metrics"]["period"]["end"]))
    print("Parsed      : {} records ({} skipped)".format(
        result["normalize"]["summary"]["total"], result["normalize"]["summary"]["skipped"]))
    print("")
    for tile in result["dashboard"]["tiles"]:
        unit = tile["unit"] or ""
        print("  {:<18} {}{}".format(tile["label"], tile["value"], unit))
    print("")
    print("Opening {} + New {} - Closed {} = Closing {}".format(
        totals["opening_backlog"], totals["new"], totals["closed"], totals["open_backlog"]))
    print("Checks      : {}".format("OK" if checks["ok"] else "FAILED"))
    for failure in checks["failures"]:
        print("  ! " + failure)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--records", default=os.path.join(HERE, "sample_cim_records.json"))
    parser.add_argument("--period", default="last_30_days")
    parser.add_argument("--now", default="2026-09-07T12:00:00Z")
    parser.add_argument("--granularity", default="day", choices=["day", "week"])
    parser.add_argument("--field-map", help="path to a JSON field-map override")
    parser.add_argument("--out", help="write the full JSON result here")
    args = parser.parse_args(argv)

    with open(args.records) as handle:
        records = json.load(handle)
    field_map = None
    if args.field_map:
        with open(args.field_map) as handle:
            field_map = json.load(handle)

    result = run(records, period=args.period, now=args.now,
                 granularity=args.granularity, field_map=field_map)
    _print_summary(result)

    if args.out:
        with open(args.out, "w") as handle:
            json.dump(result, handle, indent=2, default=str)
        print("\nFull result written to {}".format(args.out))
    return 0 if result["checks"]["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
