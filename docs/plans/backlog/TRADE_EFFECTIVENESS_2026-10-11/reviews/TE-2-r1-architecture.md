**VERDICT: NOT-READY** · **SCORE: 60/100**

The core design is sound: an outcome-blind Phase A, a freeze, exact tests at the station-day level, and a re-fetch that really is needed. It fails on two blockers: one stated premise is wrong (the holdout), and one STOP fires no matter what the data shows (the coverage gap). There are also four HIGH routing and reproduction defects.

| ID | Sev | Finding | Evidence | Required change |
|---|---|---|---|---|
| A1 | BLOCKER | P7 and S0-E are wrong. A ruling already freezes the holdout at [07-01, 10-02); days on or after 10-02 are forward data. Every FQ climate day is 10-02..10-06, so none is a holdout day. Filing a new ruling would contradict C4.1 item 4 ("changing this text is an ARCH change"). The code has not caught up: `DEFAULT_SPLITS` still has no end date. | `RULING_holdout_freeze_and_forward_window_2026-10-03.md:5-14`; `nbp_calibration.py:277` | Cite C4.1 §2 and drop the ruling step. Keep the `open_holdout` AST pin. In WP4, replace "sit in the holdout split" with "forward data; validate only on days after 10-06, never in [07-01, 10-02)". |
| A2 | BLOCKER | S0-F STOPs every time. It requires `coverage_gap_days==0`, but the top-level value is 1 and SFO has a gap (2026-03-11). P10's "283 final days" is wrong for SFO (282). | `derived/fq-truth/coverage.json:4,62-66` | Scope the gap check to the settlement days only. |
| A3 | HIGH | The poll ledger starts at the 10-06 01Z cycle, so it covers none of the take cycles. K2's "newest visible cycle" and the S0-D sha comparison cannot be run as written. The node logs do record which cycle was in use. | `poll_ledger.jsonl:1` (no "0[1-5] Oct" lines); `NBM_NBP_PUBLISHED cycle_ns=` lines in each `breezy-trade-202610*.log` | Take the cycle and visibility from the logs. Mark the ledger sha check N/A for 10-01..10-05. |
| A4 | HIGH | K3 is routed to CF-2 and CF-7. CF-2 is the unconsumed `never_substitute` setting and CF-7 is a `BREEZY_USER_AGENT` hygiene item. Both belong to a METAR station-selection plan that does not exist. The verdict rules also count K3 as FIXABLE, but PM.us settles on CLI, so a METAR flip does not change P&L. | `RULING_backlog_resolution_2026-09-28.md:59`; archived PROGRESS `:80,:84` | Make K3 descriptive. If an input route is wanted, use the F13 source list. Remove K3 from FIXABLE_DEFECT. |
| A5 | HIGH | The 23/25 at 1e-9 threshold is achievable, because p̂ depends only on percentiles, draws and the ladder (`decision.py:313-331`). But "production code" means HEAD, and the boot line records no code sha. Any change to bounds or calibration after 10-05 means a guaranteed STOP or false K1 labels. | `breezy-trade-20261004T165012Z.log:3` | Pin the reproduction to the commit that was deployed at each boot. Class a miss caused by an unavailable or reissued bulletin as UNTESTABLE, not K1. |
| A6 | HIGH | No consumer for INCONCLUSIVE, which is the likeliest result with about 12 station-days. Meanwhile VARIANCE is close to unreachable: with P_d around 0.5, Π(1−P_d) is about 1e-4. | §4 verdict rules, §5 WP4 | Add an INCONCLUSIVE consumer. Say up front that T-WIN is expected to reject. |
| A7 | MED | Existing code is duplicated. The join should call `bridge_decision`, `read_log_events` and `bridge_report` directly. Holm already exists. K4 should use the `reconcile.py` settlement leg. Truth should come through `settlement_source.NwsCliFinal` plus `score_trial`, the same path TE-1 uses, not a separate CSV loader. The ASOS loaders in `settlement_alignment_study` should be reused. The H0-K station-day collapse duplicates `combine_station_day`. | `decision_link.py:161-255`; `nbp_calibration.py:1670`; `release_timing.py:270`; `reconcile.py:8-10`; `settlement_source.py:41-51`; `cli_basis_boundary_study.py:13-23`; `current_rung_hold_v2.py:296` | Reuse these and drop test 8 plus the hand-written join and truth loader. |
| A8 | MED | P6 is incomplete. The validate run already tested October bias: `month_10` mean residual −0.20 °F, n=369, p=0.31, not significant. G2.1 (n=4335) has far more power than T-SPREAD on about 12 days. | `NBP_S2_VALIDATE_RESULT…md:264-269,24` | Use G2.0 and G2.1 as the baseline. Reframe LOC_ARTEFACT as v5.0 May–June parameter extrapolation, not the day-length fit. |
| A9 | MED | F13 freezes at or after 10-21, and the plan sets no deadline to feed it. | `PROGRESS.md:104` | Add a delivery date, or state the slip explicitly. |
| A10 | LOW | "Commit precedes the first Phase B run in git history" cannot be enforced, because git records commits, not runs. | §2 S0-H | Use the predeclaration sha pin plus commit order of predeclaration versus result artifact. |
| A11 | LOW | The manifest says `terminal_climate_day 2026-10-05`, but there is an SFO 10-06 fill. The plan relabels the field as "take day" without checking. | `pm_us_crh_fq_v1.json:6`; audit `:20` | Check what the field means. If it is a climate day, the 10-06 fill is a K1 candidate. |

**Premises checked**
- P1: CONFIRMED (`decision.py:216-218, 277-281, 331, 349, 353-355`)
- P2: CONFIRMED (`:200-212`)
- P3: CONFIRMED (32 Takes, 32 OrderInitialized, 25 OrderFilled)
- P4: not verified
- P5: CONFIRMED (`fill_source.py:58,66`)
- P6: manifest CONFIRMED; the "extrapolation" consequence is INCOMPLETE (A8)
- P7: WRONG on governance. The ruling makes days on or after 10-02 forward data, even though the code is unchanged.
- P8: CONFIRMED (`:99-100, :104-127`)
- P9: CONFIRMED (`:210-220, :237`)
- P10: PARTLY WRONG (SFO 282 days; gap = 1)
- P11: derived store CONFIRMED (`derived/nbp` ends 09-29; no payload archive, so the re-fetch is needed). Ledger coverage is WRONG (it starts 10-06).
- P12: CONFIRMED (`RULING_FQ-v2…:44-50`)
- P13: L-1, L-2, L-18, L-40, L-42, L-52 and L-55 headers CONFIRMED