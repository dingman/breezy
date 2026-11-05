# AUT-2 evidence: the -0.37 / +0.37 root cause, and why the 09-30 cash gate reads gross

Plan: `docs/plans/backlog/AUTONOMY_2026-10-03/AUT-2-outcome-labeling_plan_r7.md` §3.1 (WP1).
Verified read-only on 2026-10-06 against the live artefacts under `/home/jon/.local/share/breezy/`.
Classification only: this note carries no account balance, deposit or flow amount.

## Verdict

**There is no sign error.** The monitor report printed one settled row for every family because
the report was never scoped to a family. The `+0.37` figure is the v4 tally (three fills summed);
the `-0.37` figure is one of those three fills.

## Facts (each re-checked on 2026-10-06)

1. All four 2026-10-02 reports (`derived/position_monitor_report_2026-10-02_pm_us_crh_{v4,v2,cont,fq_v1}.md`)
   print the identical `positions: 1 (settled 1, unsettled 0)` and `SETTLED ... n=1
   realized_pnl_total=-0.3700`.
2. That one row is the trial
   `continuous_rung_hold/trial/SFO/2026-09-21/tc-temp-sfohigh-2026-09-21-gte66lt67f.POLYMARKET_US`
   (YES, `pnl=-0.3700`, `held=False`), joined from
   `derived/scored_trials/pm_us_crh_v4/scored_trials_20260922T141816645708220Z.parquet`.
3. The summaries directory (`catalog/quote_tape/monitor/summaries/`) holds exactly one file,
   `position_monitor_summaries_20260922T164011274098669Z.parquet` (the 09-22 16:40Z STOP flush),
   and exactly one row: that SFO YES trial.
4. The three v4 scored fills are MIA NO 09-21 (`-0.13`), SFO YES 09-21 (`-0.37`) and MDW NO 09-22
   (`+0.87`); their sum is the `+0.37` the v4 tally printed. The pooled scored-trial store holds
   seven rows in all (four older v2/cont rows from 09-15 plus these three).
5. **Mechanism.** The nightly report took every summary and every pooled scored trial. Its
   `--family-manifest` flag only stamped `RuleSeries.family`; nothing filtered by family, and the
   wrapper runs once per REGISTERED manifest. So every family's report counted the same single row.

## Why only one of the three v4 fills is a report row (the r7 INFERRED item, now verified)

A report row is a monitor summary joined to a scored trial; a scored trial with no summary is never
a row (`_join` iterates summaries). The two NO-leg fills have no summary because the monitor never
registered them. Both node logs show the same guarded error immediately after the NO fill:

| Fill | Node log | Evidence |
|---|---|---|
| MIA NO 09-21, filled 2026-09-21T19:18:36Z | `logs/breezy-trade-20260921T165055Z.log` line 1547 | `event=monitor_error site=ContinuousRungHoldStrategy-MIA ... {'site': 'on_position_opened', 'exc_type': 'KeyError'}` |
| MDW NO 09-22, filled 2026-09-22T18:00:01Z | `logs/breezy-trade-20260922T165020Z.log` line 1167 | `event=monitor_error site=ContinuousRungHoldStrategy-MDW ... {'site': 'on_position_opened', 'exc_type': 'KeyError'}` |
| SFO YES 09-21, filled 2026-09-21T20:21:35Z | same 09-21 log, line 1916 | no `monitor_error`; registered, flushed at STOP |

The 09-21 log carries exactly one `monitor_error` (the MIA NO one). The r7 inference that MDW NO
"filled in a later session that wrote no summary" is replaced by this: it also failed to register.
The earlier inference for MIA NO is likewise replaced. The KeyError site inside
`PositionMonitor._on_position_opened` was not isolated (not needed for the verdict). FU-1d
(`a2f8a85a`, 2026-09-26) later added routing of YES depth frames to NO-leg siblings; no NO fill
after it was inspected here.

## Fix (WP1)

- `scripts/analysis/position_monitor_nightly_report.py`: a family-bound report keeps only the
  summaries `resolve_trial_family` assigns to the bound family (REGISTERED manifests plus the bound
  one). An unbound report is byte-identical (golden test). A bound family whose composition kind
  composes no `PositionMonitor` (FQ) prints `NO_MONITOR_FOR_KIND <kind>`.
- Re-run read-only over the live stores with the four committed manifests: v4 shows `positions: 1`
  and `-0.3700`; v2, cont and fq_v1 show `positions: 0`; fq_v1 also prints
  `NO_MONITOR_FOR_KIND forecast_quantile_ladder`.
- FQ has zero scored fills and composes no `PositionMonitor`; its labelling is AUT-2 WP2 and WP3.

## H3: the 09-30 gross cash flag (`derived/PRIVATE_portfolio_roi_2026-09-30.json`)

Classification only.

- `settled_cumulative_passes` is `False` (the gross flag) while `settled_cumulative_passes_net` is
  `True`; `external_flow_evidence_status` is `OK`.
- The gross cumulative unexplained figure exceeds the net one by exactly the value of the single
  external flow recorded in the snapshot, to the cent (difference of the two minus that flow:
  `0.0000`). One day is `EXPLAINED_EXTERNAL_FLOW` in the net classification
  (`n_explained_external_flow_days = 1`), and that same day is the one `UNEXPLAINED_CAPITAL_FLOW`
  day inside the settled window in the gross classification.
- **H3 holds:** the gross gap is one explained external deposit that the gross path does not net.
  The gross flag is diagnostic only; the net flag is the reconciliation pass flag (plan §3.6.3).
- Outside the settled window the file also shows two `UNEXPLAINED_CAPITAL_FLOW` days (09-27, 09-28)
  and two `BALANCE_UNKNOWN` days (09-18, 09-25). They are provisional or unknown, not part of the
  settled verdict, and are WP5's INCONCLUSIVE rules, not this note's.

## Other observation recorded for WP6

On 2026-10-06 the ledger holds durable fills in the legacy `UNRECONCILED` bucket that no scorer has
labelled (`portfolio_roi_report.py --status-only` prints `GATED_UNLABELLED_FQ unlabelled=25`).
The count is every fill in that bucket, not only FQ: it also holds in-flight and unattributed CRH
fills. The full report's `roi_status` stays `OK` until WP6 gates it on the C2 marker, because the
existing tests (`test_portfolio_roi_report.py`, the Defect-2 and CFJ485874TMM cases) pin `OK` for
runs that carry in-flight `UNRECONCILED` fills.
