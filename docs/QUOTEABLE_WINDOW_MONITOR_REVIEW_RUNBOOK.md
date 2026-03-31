# Quoteable Window Monitor Review Runbook

Purpose:

- keep the `quoteable_window_monitor_v1` front disciplined for 14 days
- review evidence on a fixed cadence without changing code, scope, or timers mid-observation
- force a decision at day 14 instead of drifting into endless monitoring

Freeze rule:

- do not change fair value, filters, scope, timers, or alerting during the observation window unless there is a real operational defect
- operational defects are limited to timer failure, artifact corruption, broken JSONL append, or repeated upstream API failures that stop sampling

Canonical server paths:

- repo: `/root/polymarket-bot`
- env file: `/etc/default/polymarket-bot`
- samples: `/root/polymarket-bot/data/reports/quoteable_window_monitor_samples.jsonl`
- latest json: `/root/polymarket-bot/data/reports/quoteable_window_monitor_latest.json`
- latest md: `/root/polymarket-bot/data/reports/quoteable_window_monitor_latest.md`

Core review questions:

1. Is the monitor still collecting samples cleanly on cadence?
2. Does the current V1 universe ever become quoteable in recurring UTC windows?
3. If it does, is quoteability persistent enough to matter, or just single-sample noise?
4. Is quoteability concentrated in one or two markets, or broad enough to support a real lane?

## Day 3 Review

Goal:

- confirm the monitor is healthy and the early signal is not an artifact of broken plumbing

Checks:

1. Service health

```bash
systemctl status pm-quoteable-window-monitor.timer --no-pager
systemctl status pm-quoteable-window-monitor.service --no-pager
journalctl -u pm-quoteable-window-monitor.service -n 120 --no-pager
```

Pass criteria:

- timer is `active (waiting)`
- latest service run exited with `status=0/SUCCESS`
- no repeating crash loop

2. Artifact integrity

```bash
wc -l /root/polymarket-bot/data/reports/quoteable_window_monitor_samples.jsonl
tail -n 3 /root/polymarket-bot/data/reports/quoteable_window_monitor_samples.jsonl
cat /root/polymarket-bot/data/reports/quoteable_window_monitor_latest.json
```

Pass criteria:

- `sample_count` in `latest.json` matches JSONL line count
- samples are append-only JSON objects
- aggregate rebuild is working

3. Early signal sanity

Review in `latest.json`:

- `quoteable_count`
- `quoteable_ratio`
- `reason_counts`
- `best_hours_utc`
- `best_dayparts_utc`

Interpretation:

- if `quoteable_count` remains `0`, that is acceptable at day 3
- if dominant reasons are still `spread_too_wide` and `spread_not_normalizable`, the monitor is likely measuring a real venue condition, not a discovery bug
- if artifacts are healthy but signal is flat, keep observing unchanged

Day 3 decision:

- `keep_observing_unchanged`
- only branch off this path if there is a real operational defect

## Day 7 Review

Goal:

- decide whether there is any temporal structure worth exploiting before day 14

Checks:

1. Re-run health and artifact integrity from day 3.

2. Inspect temporal structure

Review in `latest.json`:

- `best_hours_utc`
- `best_dayparts_utc`
- `best_markets_by_quoteable_time`
- `quoteable_windows`
- `quoteable_minutes_by_market`
- `median_normalized_spread_bps_when_quoteable`
- `median_depth_when_quoteable`

3. Inspect persistence, not just hits

Questions:

- are there any markets with repeated quoteable windows across multiple samples?
- are quoteable windows clustered in a small set of UTC hours?
- do windows persist beyond one isolated sample?
- is quoteability broad across several markets, or concentrated in one tiny corner?

Interim decision matrix:

- `keep_observing_unchanged`
  - use when signal is still flat or too weak to justify interpretation changes
- `narrow_to_recurring_near_quoteable_subset`
  - use when a small set of markets repeatedly comes close, even if not fully quoteable yet
- `prepare_scope_relaxation_hypothesis`
  - use only if the current universe remains structurally dead and the evidence now points to a scope problem rather than a timing problem

Guardrail:

- do not change the lane yet at day 7
- day 7 is for hypothesis refinement, not implementation churn

## Day 14 Review

Goal:

- force a strategic verdict from evidence

Required inputs:

- 14 days of samples, or at minimum a complete uninterrupted 7-day block plus justification if 14 days is impossible
- clean `latest.json`
- intact JSONL history

Questions to answer:

1. Does the current V1 universe become quoteable recurrently in specific UTC windows?
2. Is quoteability persistent enough to support session scheduling?
3. Is quoteability broad enough across markets to support the lane, or is it too concentrated?

Allowed day 14 verdicts:

1. `session_windows_exist`

Meaning:

- the current V1 universe does become quoteable in recurring windows

Next front:

- `shadow_a_session_scheduler_v1`

2. `structurally_unquoteable`

Meaning:

- even after temporal monitoring, the current V1 universe remains dead for passive quoting

Next front:

- controlled V1 scope-relaxation design

3. `tiny_recurrent_subset_only`

Meaning:

- only a narrow subset of markets becomes quoteable with any persistence

Next front:

- schedule-based shadow for that subset only

Day 14 output standard:

- one verdict
- one next front
- one short evidence paragraph

Do not write an essay. Make the decision.

## Review Template

Use this template for day 3, day 7, and day 14 notes:

```md
# Quoteable Window Review - Day X

- Review date:
- Sample count:
- Timer health:
- Latest service status:
- Quoteable count:
- Quoteable ratio:
- Dominant reject reasons:
- Best UTC hours:
- Best dayparts:
- Best markets by quoteable time:
- Persistence summary:
- Concentration summary:
- Decision:
- Next front:
```

## Hard Do-Not-Do List

- do not add another timer during the observation window
- do not change fair value during the observation window
- do not relax V1 scope during the observation window
- do not arm micro-live during the observation window
- do not reinterpret `no_participation` as neutral just because the monitor is healthy

The point of this runbook is to keep the lane honest while the data accumulates.
