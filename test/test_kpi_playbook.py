"""Unit tests for the Swimlane KPI playbook scripts.

    python3 test_kpi_playbook.py          # stdlib only
    python3 -m pytest test_kpi_playbook.py -q

No third-party packages, so this runs anywhere the playbook scripts do.
"""

from __future__ import annotations

import json
import os
import unittest
from datetime import datetime, timedelta, timezone

import kpi_common
from run_pipeline_local import Context, load_action, run

UTC = timezone.utc
NOW = datetime(2026, 9, 7, 12, 0, 0, tzinfo=UTC)
NOW_ISO = "2026-09-07T12:00:00Z"
HERE = os.path.dirname(os.path.abspath(__file__))

normalize_action = load_action("01_normalize_cim_records.py")
metrics_action = load_action("02_compute_kpi_metrics.py")
trend_action = load_action("03_build_trend_series.py")
dashboard_action = load_action("04_build_dashboard_payload.py")
record_action = load_action("05_build_kpi_record_payload.py")


def iso(days_ago, hour=12):
    return (NOW - timedelta(days=days_ago)).replace(
        hour=hour, minute=0, second=0, microsecond=0).isoformat().replace("+00:00", "Z")


class DateParsingTests(unittest.TestCase):
    def test_parses_the_shapes_cim_records_carry(self):
        expected = datetime(2026, 8, 1, 9, 30, tzinfo=UTC)
        for value in [
            "2026-08-01T09:30:00Z",
            "2026-08-01T09:30:00.000Z",
            "2026-08-01 09:30:00",
            "2026-08-01T11:30:00+02:00",
            "08/01/2026 09:30",
        ]:
            self.assertEqual(kpi_common.parse_datetime(value), expected, value)

    def test_parses_epoch_seconds_and_milliseconds(self):
        self.assertEqual(kpi_common.parse_datetime(1754040600),
                         datetime(2025, 8, 1, 9, 30, tzinfo=UTC))
        self.assertEqual(kpi_common.parse_datetime(1754040600000),
                         datetime(2025, 8, 1, 9, 30, tzinfo=UTC))

    def test_returns_none_for_junk(self):
        for value in [None, "", "   ", "not a date", [], {}]:
            self.assertIsNone(kpi_common.parse_datetime(value), value)

    def test_naive_datetimes_are_treated_as_utc(self):
        parsed = kpi_common.parse_datetime("2026-08-01T09:30:00")
        self.assertEqual(parsed.tzinfo, UTC)


class PeriodTests(unittest.TestCase):
    def test_named_period_covers_the_expected_span(self):
        start, end = kpi_common.resolve_period("last_7_days", None, None, NOW_ISO)
        self.assertEqual(start.date().isoformat(), "2026-09-01")
        self.assertEqual(end, NOW)

    def test_explicit_dates_win_over_the_name(self):
        start, end = kpi_common.resolve_period(
            "last_7_days", "2026-01-01T00:00:00Z", "2026-01-31T23:59:59Z", NOW_ISO)
        self.assertEqual(start.date().isoformat(), "2026-01-01")
        self.assertEqual(end.date().isoformat(), "2026-01-31")

    def test_last_month_ends_before_the_first_of_this_month(self):
        start, end = kpi_common.resolve_period("last_month", None, None, NOW_ISO)
        self.assertEqual(start.date().isoformat(), "2026-08-01")
        self.assertEqual(end.date().isoformat(), "2026-08-31")

    def test_unknown_name_falls_back_to_30_days(self):
        start, _ = kpi_common.resolve_period("nonsense", None, None, NOW_ISO)
        self.assertEqual(start.date().isoformat(), "2026-08-09")


class FieldMapTests(unittest.TestCase):
    def test_override_is_tried_before_the_defaults(self):
        merged = kpi_common.merge_field_map({"status": "myStatus"})
        self.assertEqual(merged["status"][0], "myStatus")
        self.assertIn("status", merged["status"])

    def test_lookup_is_case_insensitive_and_supports_dotted_paths(self):
        record = {"Details": {"Assigned To": "j.silva"}, "STATUS": "New"}
        self.assertEqual(kpi_common.pick_field(record, ["details.assigned to"]), "j.silva")
        self.assertEqual(kpi_common.pick_field(record, ["status"]), "New")

    def test_empty_values_fall_through_to_the_next_candidate(self):
        record = {"closedDate": "", "resolvedDate": "2026-08-01T00:00:00Z"}
        self.assertEqual(
            kpi_common.pick_field(record, ["closedDate", "resolvedDate"]),
            "2026-08-01T00:00:00Z")


class NormalizeTests(unittest.TestCase):
    def normalize(self, records, **kwargs):
        inputs = {"records": records, "now": NOW_ISO, "period": "last_30_days"}
        inputs.update(kwargs)
        return normalize_action.main(Context(inputs))

    def test_maps_mixed_case_cim_keys_onto_canonical_fields(self):
        result = self.normalize([{
            "id": "1", "trackingFull": "CIM-1", "Alert Name": "Phish",
            "status": "In Progress", "priority": "High", "assignedTo": "l.chen",
            "assignmentGroup": "SOC Tier 1", "createdDate": iso(3),
        }])
        record = result["records"][0]
        self.assertEqual(record["tracking_id"], "CIM-1")
        self.assertEqual(record["title"], "Phish")
        self.assertEqual(record["assignee"], "l.chen")
        self.assertEqual(record["team"], "SOC Tier 1")
        self.assertTrue(record["is_open"])

    def test_closed_status_without_a_timestamp_still_leaves_the_backlog(self):
        result = self.normalize([{
            "id": "1", "status": "Resolved", "createdDate": iso(5),
            "closedDate": "", "modified": iso(2),
        }])
        record = result["records"][0]
        self.assertTrue(record["is_closed"])
        self.assertEqual(record["closed_day"], iso(2)[:10])

    def test_open_status_with_a_closed_timestamp_counts_as_closed(self):
        result = self.normalize([{
            "id": "1", "status": "In Progress",
            "createdDate": iso(5), "closedDate": iso(1),
        }])
        self.assertTrue(result["records"][0]["is_closed"])

    def test_custom_closed_statuses_are_honoured(self):
        result = self.normalize(
            [{"id": "1", "status": "Mitigated", "createdDate": iso(5)}],
            closed_statuses=["mitigated"])
        self.assertTrue(result["records"][0]["is_closed"])

    def test_records_without_a_created_date_are_skipped_not_dropped_silently(self):
        result = self.normalize([
            {"id": "good", "status": "New", "createdDate": iso(1)},
            {"id": "bad", "status": "New", "createdDate": "nope"},
        ])
        self.assertEqual(result["summary"]["total"], 1)
        self.assertEqual(result["summary"]["skipped"], 1)
        self.assertEqual(result["skipped"][0]["id"], "bad")

    def test_accepts_a_json_string_instead_of_a_list(self):
        payload = json.dumps([{"id": "1", "status": "New", "createdDate": iso(1)}])
        self.assertEqual(self.normalize(payload)["summary"]["total"], 1)

    def test_accepts_a_wrapped_results_object(self):
        payload = {"records": [{"id": "1", "status": "New", "createdDate": iso(1)}]}
        self.assertEqual(self.normalize(payload)["summary"]["total"], 1)

    def test_age_and_resolution_are_computed(self):
        result = self.normalize([{
            "id": "1", "status": "Closed",
            "createdDate": iso(4), "closedDate": iso(2),
        }])
        self.assertAlmostEqual(result["records"][0]["resolution_hours"], 48.0, places=1)

    def test_sla_breach_is_flagged_for_open_and_closed_records(self):
        result = self.normalize([
            {"id": "late-open", "status": "New", "createdDate": iso(5), "slaDue": iso(3)},
            {"id": "ok-closed", "status": "Closed", "createdDate": iso(5),
             "closedDate": iso(4), "slaDue": iso(3)},
        ])
        by_id = {r["id"]: r for r in result["records"]}
        self.assertTrue(by_id["late-open"]["sla_breached"])
        self.assertFalse(by_id["ok-closed"]["sla_breached"])

    def test_empty_input_produces_an_empty_but_valid_output(self):
        result = self.normalize([])
        self.assertEqual(result["records"], [])
        self.assertFalse(result["summary"]["has_records"])


class MetricsTests(unittest.TestCase):
    def build(self, raw):
        step1 = normalize_action.main(Context(
            {"records": raw, "now": NOW_ISO, "period": "last_30_days"}))
        step2 = metrics_action.main(Context(
            {"records": step1["records"], "period": step1["period"], "now": NOW_ISO}))
        return step2["metrics"]

    def test_counts_new_closed_and_backlog_over_the_window(self):
        metrics = self.build([
            {"id": "1", "status": "New", "createdDate": iso(5)},           # new + open
            {"id": "2", "status": "Closed", "createdDate": iso(10),
             "closedDate": iso(2)},                                        # new + closed
            {"id": "3", "status": "New", "createdDate": iso(200)},         # opening backlog
            {"id": "4", "status": "Closed", "createdDate": iso(200),
             "closedDate": iso(150)},                                      # outside entirely
        ])
        totals = metrics["totals"]
        self.assertEqual(totals["new"], 2)
        self.assertEqual(totals["closed"], 1)
        self.assertEqual(totals["opening_backlog"], 1)
        self.assertEqual(totals["open_backlog"], 2)
        self.assertEqual(totals["net_change"], 1)

    def test_backlog_identity_holds_on_the_sample_dataset(self):
        with open(os.path.join(HERE, "sample_cim_records.json")) as handle:
            metrics = self.build(json.load(handle))
        totals = metrics["totals"]
        self.assertEqual(
            totals["opening_backlog"] + totals["new"] - totals["closed"],
            totals["open_backlog"])

    def test_a_record_closed_after_the_window_is_still_open_backlog(self):
        metrics = self.build([{"id": "1", "status": "New", "createdDate": iso(3)}])
        self.assertEqual(metrics["totals"]["open_backlog"], 1)

    def test_aging_buckets_cover_every_open_record_exactly_once(self):
        metrics = self.build([
            {"id": str(n), "status": "New", "createdDate": iso(days)}
            for n, days in enumerate([0, 1, 3, 6, 12, 20, 45])
        ])
        bucketed = sum(b["count"] for b in metrics["backlog_age"]["buckets"])
        self.assertEqual(bucketed, metrics["totals"]["open_backlog"])

    def test_mttr_averages_only_records_closed_in_the_window(self):
        metrics = self.build([
            {"id": "1", "status": "Closed", "createdDate": iso(4), "closedDate": iso(3)},
            {"id": "2", "status": "Closed", "createdDate": iso(4), "closedDate": iso(2)},
        ])
        self.assertEqual(metrics["resolution"]["sample_size"], 2)
        self.assertAlmostEqual(metrics["resolution"]["mttr_hours"], 36.0, places=1)

    def test_closure_rate_is_zero_when_nothing_arrived(self):
        metrics = self.build([{"id": "1", "status": "New", "createdDate": iso(200)}])
        self.assertEqual(metrics["rates"]["closure_rate_pct"], 0.0)

    def test_priority_breakdown_is_ordered_critical_first(self):
        metrics = self.build([
            {"id": "1", "status": "New", "priority": "Low", "createdDate": iso(1)},
            {"id": "2", "status": "New", "priority": "Low", "createdDate": iso(1)},
            {"id": "3", "status": "New", "priority": "Critical", "createdDate": iso(1)},
        ])
        labels = [b["label"] for b in metrics["breakdowns"]["open_by_priority"]]
        self.assertEqual(labels[0], "Critical")

    def test_backlog_age_is_measured_at_the_period_end_not_today(self):
        # Created 200 days ago, still open. Over a last_7_days window its age
        # at the period end is ~200 days, so it lands in the 30d+ bucket.
        metrics = self.build_for_period(
            [{"id": "1", "status": "New", "createdDate": iso(200)}], "last_7_days")
        self.assertEqual(metrics["totals"]["open_backlog"], 1)
        oldest = metrics["backlog_age"]["oldest_days"]
        self.assertGreater(oldest, 199)
        self.assertLess(oldest, 201)
        over_30 = next(b for b in metrics["backlog_age"]["buckets"] if b["label"] == "30d+")
        self.assertEqual(over_30["count"], 1)

    def build_for_period(self, raw, period):
        step1 = normalize_action.main(Context(
            {"records": raw, "now": NOW_ISO, "period": period}))
        step2 = metrics_action.main(Context(
            {"records": step1["records"], "period": step1["period"], "now": NOW_ISO}))
        return step2["metrics"]

    def test_empty_records_do_not_raise(self):
        metrics = self.build([])
        self.assertEqual(metrics["totals"]["open_backlog"], 0)
        self.assertIsNone(metrics["resolution"]["mttr_hours"])


class TrendTests(unittest.TestCase):
    def build(self, raw, granularity="day", period="last_30_days"):
        step1 = normalize_action.main(Context(
            {"records": raw, "now": NOW_ISO, "period": period}))
        step2 = metrics_action.main(Context(
            {"records": step1["records"], "period": step1["period"], "now": NOW_ISO}))
        step3 = trend_action.main(Context(
            {"records": step1["records"], "period": step1["period"],
             "granularity": granularity}))
        return step2["metrics"], step3["trend"]

    def test_last_backlog_point_matches_the_open_backlog_tile(self):
        with open(os.path.join(HERE, "sample_cim_records.json")) as handle:
            metrics, trend = self.build(json.load(handle))
        self.assertEqual(trend["backlog"][-1], metrics["totals"]["open_backlog"])

    def test_series_has_one_point_per_day_in_the_window(self):
        _, trend = self.build([{"id": "1", "status": "New", "createdDate": iso(1)}],
                              period="last_7_days")
        self.assertEqual(len(trend["points"]), 7)
        self.assertEqual(trend["granularity"], "day")

    def test_daily_new_counts_land_on_the_right_day(self):
        _, trend = self.build([
            {"id": "1", "status": "New", "createdDate": iso(2)},
            {"id": "2", "status": "New", "createdDate": iso(2)},
        ], period="last_7_days")
        by_date = {p["date"]: p for p in trend["points"]}
        self.assertEqual(by_date[iso(2)[:10]]["new"], 2)

    def test_weekly_rollup_preserves_the_totals(self):
        with open(os.path.join(HERE, "sample_cim_records.json")) as handle:
            raw = json.load(handle)
        _, daily = self.build(raw, granularity="day")
        _, weekly = self.build(raw, granularity="week")
        self.assertEqual(sum(weekly["new"]), sum(daily["new"]))
        self.assertEqual(sum(weekly["closed"]), sum(daily["closed"]))
        self.assertEqual(weekly["backlog"][-1], daily["backlog"][-1])

    def test_no_records_gives_a_flat_zero_series(self):
        _, trend = self.build([], period="last_7_days")
        self.assertEqual(set(trend["backlog"]), {0})


class DashboardTests(unittest.TestCase):
    def test_tiles_charts_and_tables_are_all_present(self):
        result = run(self._sample(), now=NOW_ISO)
        dashboard = result["dashboard"]
        keys = {tile["key"] for tile in dashboard["tiles"]}
        self.assertTrue({"open_backlog", "new", "closed", "mttr"} <= keys)
        self.assertEqual(len(dashboard["charts"]), 4)
        self.assertEqual(len(dashboard["tables"]), 3)

    def test_deltas_compare_against_the_previous_run(self):
        previous = {"totals": {"open_backlog": 10, "new": 5, "closed": 5, "net_change": 0}}
        metrics = {"totals": {"open_backlog": 14, "new": 8, "closed": 4, "net_change": 4}}
        dashboard = dashboard_action.build_dashboard(metrics, {}, previous)
        tile = next(t for t in dashboard["tiles"] if t["key"] == "open_backlog")
        self.assertEqual(tile["delta"]["value"], 4)
        self.assertEqual(tile["delta"]["direction"], "up")

    def test_checks_flag_a_backlog_that_does_not_balance(self):
        broken = {"totals": {"opening_backlog": 10, "new": 5, "closed": 2, "open_backlog": 99}}
        checks = dashboard_action.run_checks(broken)
        self.assertFalse(checks["ok"])
        self.assertIn("does not balance", checks["failures"][0])

    def test_checks_pass_on_the_real_pipeline(self):
        self.assertTrue(run(self._sample(), now=NOW_ISO)["checks"]["ok"])

    def test_dashboard_payload_is_json_serialisable(self):
        result = run(self._sample(), now=NOW_ISO)
        json.dumps(result["dashboard"])

    def _sample(self):
        with open(os.path.join(HERE, "sample_cim_records.json")) as handle:
            return json.load(handle)


class RecordPayloadTests(unittest.TestCase):
    def test_period_key_is_stable_for_the_same_window(self):
        period = {"start": "2026-08-01T00:00:00Z", "end": "2026-08-31T23:59:59Z"}
        self.assertEqual(record_action.build_period_key(period), "2026-08-01_2026-08-31")

    def test_action_is_update_when_an_existing_record_is_supplied(self):
        metrics = {"period": {"start": "2026-08-01T00:00:00Z", "end": "2026-08-31T00:00:00Z"},
                   "totals": {"new": 1}}
        created = record_action.main(Context({"metrics": metrics}))
        updated = record_action.main(Context({"metrics": metrics,
                                              "existing_record_id": "abc123"}))
        self.assertEqual(created["action"], "create")
        self.assertEqual(updated["action"], "update")
        self.assertEqual(updated["record_id"], "abc123")

    def test_field_names_can_be_renamed_for_a_different_app(self):
        metrics = {"period": {}, "totals": {"new": 7}}
        fields = record_action.build_fields(metrics, field_names={"new_count": "Nuevos"})
        self.assertEqual(fields["Nuevos"], 7)
        self.assertNotIn("New Incidents", fields)

    def test_payload_carries_the_headline_numbers(self):
        result = run(self._sample(), now=NOW_ISO)
        fields = result["record"]["fields"]
        self.assertEqual(fields["Open Backlog"], result["metrics"]["totals"]["open_backlog"])
        self.assertEqual(fields["New Incidents"], result["metrics"]["totals"]["new"])
        json.loads(fields["Dashboard JSON"])

    def _sample(self):
        with open(os.path.join(HERE, "sample_cim_records.json")) as handle:
            return json.load(handle)


class ContextShapeTests(unittest.TestCase):
    def test_inputs_read_from_an_object_a_dict_or_a_bare_dict(self):
        for context in [Context({"period": "last_7_days"}),
                        {"inputs": {"period": "last_7_days"}},
                        {"period": "last_7_days"}]:
            self.assertEqual(kpi_common.get_input(context, "period"), "last_7_days")

    def test_blank_values_fall_back_to_the_default(self):
        self.assertEqual(kpi_common.get_input(Context({"top_n": ""}), "top_n", 10), 10)
        self.assertEqual(kpi_common.get_input(Context({"records": []}), "records", ["x"]), ["x"])


class StatsTests(unittest.TestCase):
    def test_median_handles_even_and_odd_lengths(self):
        self.assertEqual(kpi_common.median([1, 2, 3]), 2)
        self.assertEqual(kpi_common.median([1, 2, 3, 4]), 2.5)

    def test_percentile_and_pct_are_safe_on_empty_or_zero_input(self):
        self.assertIsNone(kpi_common.percentile([], 90))
        self.assertEqual(kpi_common.pct(5, 0), 0.0)
        self.assertEqual(kpi_common.pct(1, 4), 25.0)

    def test_count_by_labels_missing_values_as_unassigned(self):
        counts = kpi_common.count_by([{"team": None}, {"team": "SOC"}], "team")
        self.assertIn({"label": "Unassigned", "count": 1}, counts)


class BundleTests(unittest.TestCase):
    """The pasted-into-Turbine bundles must behave like the source modules."""

    def test_every_action_bundles_into_valid_standalone_python(self):
        import bundle_for_turbine

        with open(os.path.join(HERE, bundle_for_turbine.COMMON)) as handle:
            common = handle.read()
        for action_file in bundle_for_turbine.ACTIONS:
            source = bundle_for_turbine.bundle(action_file, common)
            self.assertNotIn("from kpi_common import", source)
            namespace = {"__name__": "bundled"}
            exec(compile(source, action_file, "exec"), namespace)
            self.assertTrue(callable(namespace.get("main")), action_file)

    def test_bundled_metrics_match_the_source_pipeline(self):
        import bundle_for_turbine

        with open(os.path.join(HERE, bundle_for_turbine.COMMON)) as handle:
            common = handle.read()
        with open(os.path.join(HERE, "sample_cim_records.json")) as handle:
            raw = json.load(handle)

        bundled = {}
        for action_file in bundle_for_turbine.ACTIONS[:2]:
            namespace = {"__name__": "bundled"}
            exec(compile(bundle_for_turbine.bundle(action_file, common),
                         action_file, "exec"), namespace)
            bundled[action_file] = namespace["main"]

        step1 = bundled[bundle_for_turbine.ACTIONS[0]](
            Context({"records": raw, "period": "last_30_days", "now": NOW_ISO}))
        step2 = bundled[bundle_for_turbine.ACTIONS[1]](
            Context({"records": step1["records"], "period": step1["period"], "now": NOW_ISO}))

        expected = run(raw, now=NOW_ISO)["metrics"]["totals"]
        self.assertEqual(step2["metrics"]["totals"], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
