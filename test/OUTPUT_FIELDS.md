# Output keys to declare

Every key each script returns, with the application field type that fits.

Declare these in the action's output schema if your tenant only surfaces
declared keys. Names are case sensitive and must match exactly.


## `A_open_incident_metrics.py`

37 mappable outputs, plus 4 objects.

| Output key | Type |
| --- | --- |
| `age_last_update_open_inc_avg` | number |
| `age_last_update_open_inc_count` | number |
| `age_last_update_open_inc_p90` | number |
| `age_last_update_open_inc_sum` | number |
| `age_open_inc_avg` | number |
| `age_open_inc_count` | number |
| `age_open_inc_p90` | number |
| `age_open_inc_sum` | number |
| `backlog_drift` | number |
| `continuity_note` | text |
| `days_since_previous` | number |
| `distinct_agents` | number |
| `expected_open_backlog` | number |
| `is_seed_day` | boolean |
| `oldest_open_age` | number |
| `open_inc_total` | number |
| `open_more_than_five_days` | number |
| `open_more_than_thirty_days` | number |
| `period_end` | text |
| `period_start` | text |
| `reassign_count_hist_open_avg` | number |
| `reassign_count_hist_open_count` | number |
| `reassign_count_hist_open_p90` | number |
| `reassign_count_hist_open_sum` | number |
| `reassign_count_open_inc_avg` | number |
| `reassign_count_open_inc_count` | number |
| `reassign_count_open_inc_p90` | number |
| `reassign_count_open_inc_sum` | number |
| `reassigned_open_count` | number |
| `series_continuous` | boolean |
| `snapshot_date` | text |
| `stale_open_no_update_5d` | number |
| `state_dwell_hours_avg` | number |
| `state_dwell_hours_count` | number |
| `state_dwell_hours_p90` | number |
| `state_dwell_hours_sum` | number |
| `unassigned_open_count` | number |

Objects, for a JSON field or the dashboard rather than a numeric field:
`metrics`, `coverage`, `breakdowns`, `oldest_open`


## `B_new_incident_metrics.py`

18 mappable outputs, plus 4 objects.

| Output key | Type |
| --- | --- |
| `mtta_hours_avg` | number |
| `mtta_hours_count` | number |
| `mtta_hours_p90` | number |
| `mtta_hours_sum` | number |
| `mtta_minutes_avg` | number |
| `mtta_minutes_count` | number |
| `mtta_minutes_p90` | number |
| `mtta_minutes_sum` | number |
| `new_inc_acknowledged_count` | number |
| `new_inc_escalated_count` | number |
| `new_inc_p1p2_count` | number |
| `new_inc_total` | number |
| `period_end` | text |
| `period_start` | text |
| `sla_breach_rate` | number |
| `sla_breached_count` | number |
| `sla_compliance_rate` | number |
| `snapshot_date` | text |

Objects, for a JSON field or the dashboard rather than a numeric field:
`metrics`, `coverage`, `breakdowns`


## `C_closed_incident_metrics.py`

38 mappable outputs, plus 4 objects.

| Output key | Type |
| --- | --- |
| `closed_inc_not_resolved` | number |
| `closed_inc_on_first_attempt` | number |
| `closed_inc_same_day_open` | number |
| `closed_inc_total` | number |
| `duration_closed_inc_avg` | number |
| `duration_closed_inc_count` | number |
| `duration_closed_inc_p90` | number |
| `duration_closed_inc_sum` | number |
| `duration_false_positive_closed_inc_avg` | number |
| `duration_false_positive_closed_inc_count` | number |
| `duration_false_positive_closed_inc_p90` | number |
| `duration_false_positive_closed_inc_sum` | number |
| `false_positive_count` | number |
| `false_positive_high_risk_count` | number |
| `first_close_rate` | number |
| `fp_rate` | number |
| `mttr_hours_avg` | number |
| `mttr_hours_count` | number |
| `mttr_hours_p90` | number |
| `mttr_hours_sum` | number |
| `period_end` | text |
| `period_start` | text |
| `risk_score_closed_inc_avg` | number |
| `risk_score_closed_inc_count` | number |
| `risk_score_closed_inc_p90` | number |
| `risk_score_closed_inc_sum` | number |
| `risk_score_false_positive_inc_avg` | number |
| `risk_score_false_positive_inc_count` | number |
| `risk_score_false_positive_inc_p90` | number |
| `risk_score_false_positive_inc_sum` | number |
| `risk_score_high_risk_fp_inc_avg` | number |
| `risk_score_high_risk_fp_inc_count` | number |
| `risk_score_high_risk_fp_inc_p90` | number |
| `risk_score_high_risk_fp_inc_sum` | number |
| `same_day_close_rate` | number |
| `snapshot_date` | text |
| `true_positive_count` | number |
| `true_positive_rate` | number |

Objects, for a JSON field or the dashboard rather than a numeric field:
`metrics`, `coverage`, `breakdowns`


## A blocked metric returns null, not 0

The metrics waiting on a reassign count, risk score or SLA breached field come
back as null. Declare them as numeric and allow empty. They keep their keys so
the application field set does not change shape the day the source is added.

## Value metrics expand to four keys

A metric defined as a value rather than a count returns `_avg`, `_sum`, `_p90`
and `_count`. `_count` is how many records carried the value, which is not the
size of the base when a column is sparsely filled.

## Field type to declare in the application

Take `open_inc_total` as the worked example. The script returns it as an
object, and the two useful pieces of it go into two different field types.

| Application field | Type | Bind to | Stores |
| --- | --- | --- | --- |
| `Open Inc Total` | Numeric | `metrics.open_inc_total.value` | `373` |
| `Open Inc Total Detail` | Text, multi-line | `metrics.open_inc_total` | the whole JSON object |
| `Snapshot Date` | Date | `metrics.snapshot_date.value` | `2026-09-08` |
| `Snapshot Key` | Text | `metrics.snapshot_date.value` | `2026-09-08`, the upsert key |

The **numeric** field is the one a report can chart. A numeric field offers
Sum, Average, Min, Max and Last as the measure, so a report grouped by
`Snapshot Date` returns one point per day carrying the metric itself.

A **text** field offers only `Count of`. That counts records sharing the same
string, so a chart built on it plots how many times a value repeated, not the
value. That is why a JSON-only application charts the record count.

Storing both is not duplication with a cost: the numeric field is the measure,
the text field is what a tooltip or a drill-down reads for the breakdown. Only
the numeric one is ever selected under Edit Measure.

This is a field-mapping change in the playbook's Save/Update Record action.
The scripts already return both shapes and do not change.
