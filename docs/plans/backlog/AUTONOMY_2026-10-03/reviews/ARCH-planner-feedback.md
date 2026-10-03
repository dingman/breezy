# Area-planner contradictions with ARCH (feed into the next ARCH revision)

## From AUT-2 r1
- **P2-1**: Widen C2: `decision_id` becomes nullable, add a `p_source` column, and add the reasons `slippage_defect` and `unattributed`.
- **P2-2**: A 05:00Z label slot cannot label the prior day. Primary labelling is 14:15Z, with 05:00Z as the catch-up.
- **P2-3**: AUT-2 also produces a `HEALTH label_lag` verdict, which is missing from the §5 producer table.
- **P2-4**: The Z19 AMBIGUOUS-at-16:45Z measurement may need a supervisor log line, which lives in an AUT-5a file.
- **P2-5**: The FQ manifest's `trial_id_prefix` matches no stored latch key, so a scorer keyed on the prefix finds zero FQ trials.

## From AUT-4 r1
- **P4-1**: The rolling forward window sits inside the sealed holdout (2026-07-01 onward, with no end). A ruling (R-A) is needed.
- **P4-2**: FQ has no registered sequential boundary, and its fills predate any pre-registration. A ruling (R-B) is needed by about 11-10.
- **P4-3**: The statement "replay-sufficient days are scarce" is stale. 80 of 80 closed station-days pass, about 3.64 a day.
- **P4-4**: The statistics ARCH reuses from `scripts/` fall outside the producer code pins and must move into `src/breezy`.
- **P4-5**: K_max has no reset point. With PROMOTE disabled, a lineage gets only 4 candidates before the KILL.
- **P4-6**: Using the traded-rung calibration leg as a hard PASS conjunct gives good models a high false-fail rate.

## From AUT-3 r1
- **P3-1 (same as P4-1, CROSS-AREA)**: The sealed NBP holdout grows forward from 2026-07-01, which blocks rolling refits AND forward evaluation. ARCH must own ONE holdout ruling consumed by both AUT-3 and AUT-4. AUT-3 proposes freezing it at [07-01, 10-02); AUT-4 proposes R-A. Reconcile the two.
- **P3-2**: One mint per lineage per day across two model classes means the classes alternate days. Either confirm that or set a per-class ceiling.
- **P3-3**: The C2 decision probability already includes recalibration, so own-outcome refits stop once a recalibrated champion exists. C2 needs a raw (pre-recalibration) probability column.
- **P3-4**: The X22 sha check can pass vacuously; add a check that the probabilities actually change.
- **P3-5 (same as P4-4)**: The code pins skip `scripts/` modules.
- **P3-6**: Define a `refit_run/v1` evidence record contract.
- **P3-7**: No FQ model class consumes execution data. The AUT-3 criterion says "where the model class consumes them", so state this explicitly.
- **P3-8**: One loader-refusal test needs re-pointing under a reviewed L-12 widening.

## From AUT-6 r1
- **P6-1**: "The fee probe is unwired for FQ" is stale. It is wired at `app/trade.py:828-844` and was live on 10-02. Correct the README/ARCH evidence.
- **P6-2**: `RuntimeMaxSec` has no effect on `Type=oneshot` units (systemd 259). ARCH Y23 must use `TimeoutStartSec`.
- **P6-3**: "Studies end before 16:30Z" cannot hold for timers that start after launch. Restate it as no overlap with 16:30–17:10Z.
- **P6-4**: A live HALT cannot be injected without permanently freezing the lineage or venue. Add a drill-HALT path, or accept HALT as gate-proven only.
- **P6-5**: Ownership of the dead-man is ambiguous between AUT-5 and AUT-6. ARCH should state that AUT-5 owns the dead-man and AUT-6 supplies delivery and monitoring.
- **P6-6**: ARCH's single shared delivery journal conflicts with L-50. Use one file per attempt.
- **P6-7**: Name the executor of the SELF_HEAL and ALERT action classes (AUT-6).
- **P6-8**: The path unit cannot see nested verdict writes. Use staggered timers (this agrees with Z12).
- **P6-9**: Split portfolio-roi ownership: AUT-6 owns the unit's exit semantics, AUT-2 the scorer.
- **P6-10**: Uncommitted 14G drop-ins break the memory budget arithmetic.
- **Extra**: a sixth failed unit, `run-p814078`. The parity runs show a real live-vs-batch take divergence (38 vs 35), which belongs to AUT-1 and AUT-4.

## From AUT-1 r1
- **P1-1**: The NBP feed HAS positive log lines (`NBM_NBP_PUBLISHED`, `FQ_VECTOR_COMPLETE`, live). The gap is the missing absence detector. Correct the README evidence.
- **P1-2**: The Breezy idle timeout is configured at 600 s, not 60 s.
- **P1-3**: C1 `OrderLink.intent_id` cannot be filled without editing the byte-pinned exec client. Redefine the join.
- **P1-4**: C1 has no store for depth and forecast payloads (`depth_ref`, `forecast_input_sha256`). AUT-1 adds one; ARCH should define it.
- **P1-5**: The C1 capture path sits outside the common storage-root rule.
- **P1-6**: One shared daily file with two writers breaks L-50. Offline settlement records go to a separate file (consistent with P6-6).
- **P1-7**: AUT-1's `app/trade.py` and `try_submit` work must be sequenced after AUT-5a, not in parallel in Wave 1.

## From AUT-7 r1
- **P7-1**: Read literally, the resolver would refuse fq_v1 itself, because its manifest cites the 10-01 live-orders ruling, not the policy ruling. Define the bootstrap exemption.
- **P7-2**: The DRILL_INJECT budget conflict is already W2 (resolved in Rev 5).
- **P7-3**: No allowed HALT row covers a halt caused by a failed rollback. Add one.
- **P7-4**: "Within one supervisor cycle" needs the 16:45 pass to write ROLLBACK plus ACTIVATE together.
- **P7-5**: No content-addressed copy of the fq_v1 artefact exists. `family_manifest.py:276-279` checks paths against a directory that does not exist.
- **P7-6**: The open-intent probe cannot run while the node is up, so the 15:30 check is advisory only; the LAUNCH re-check is authoritative.

## From AUT-5 r1 (arrived after the Rev 6 dispatch; carry into the next revision)
- **P5-1 (same as P7-1)**: The bootstrap root fq_v1 carries the operator ruling, not the policy ruling.
- **P5-2**: Add bootstrap rows ∅→CHAMPION and ∅→RETIRED to the transition table.
- **P5-3**: The supervisor's four spawn sites forward its own env, not the child's. G22 is wrong, and one cited line is wrong.
- **P5-4 (same as W6)**: The `entry_guard` package cannot import the adapter fill decoder; use injection.
- **P5-5**: "The supervisor triggers the intraday pass" is replaced by a timer guarantee.
- **P5-6**: No drawdown producer is named. AUT-5 assigns it to AUT-4.
- **P5-7**: The shadow stage needs a `registry_shadow` value for `BREEZY_FAMILY_SOURCE`.
- **P5-8**: The drill takes 5–6 trading days, not 4.

## From AUT-2 r2
- **P2-6**: The C6 RefusingPlugin YAGNI rule conflicts with labelling a retired kind's remaining fills. A kind keeps its real Scorer until its last fill is labelled.
- **P2-7**: The §4.4 "produced after STOP" horizon applies only to the 16:45Z pre-launch pass.
- **P2-8**: C2 must list the `voided_pair` exclusion reason (W14), alongside `slippage_defect` and `unattributed` (a hard prerequisite).

## From AUT-4 r2 (carry into the next ARCH revision)
- **P4-7**: ATTEST names required verdict KINDS, not detectors, so daily AUT-4 verdicts valid for 26 h would reopen the W1 gap. Restrict the ATTEST-required kinds to intraday HEALTH and RECONCILIATION.
- **P4-8**: With α never reset, k exceeds K_max after the first window, which breaks C4. Separate k (the lifetime α index) from the K_max mint count per window.
- **P4-9**: Add an engine input journal (the verdicts read per pass) so "consumed" can be checked.
- **P4-10**: C4's single `prereg_ruling_sha256` cannot carry both the FQ prereg and the policy ruling. Split it into two fields.
- **P4-11**: `verdict_id` must exclude `produced_at_ns`.
- **P4-12**: The `assumptions` enum needs four more tags.

## From AUT-3 r2
- **P3-9**: C2 must pin `p_at_decision` = the bought-leg probability. AUT-2 r2 adopted this.
- **P3-10**: W7: ARCH chooses the mint limit (K_max per window), so `ERROR(k_exceeded)` is never produced. State this.

## From AUT-6 r2
- **P6-11**: W12 (detectors include drill fills) contradicts §5.3, which excludes drill fills from every statistic. State that §5.3 exclusion applies to live n and the KILL clock only.
- **P6-12**: The INTEGRITY safety floor needs a second writer of restrictive-demand files (an AUT-6 producer), but ARCH lets only the engine write them. Permit restrictive-only demand writes from pinned producers.
- **P6-13**: The health unit needs a producer pin, and the dead-man reads its heartbeat.
- **D-HALT (blocking by 2026-10-10)**: Decide the drill-HALT path; this matches P6-4.

## Coordinator decision to absorb
- `reviews/ALPHA-decision.md`: k_life lifetime α, the K_max mint limit per window, `K_LIFETIME_EFFECTIVE`, and the window-cap INCONCLUSIVE rule.

## From AUT-7 r2 (arrived after the Rev 7 dispatch)
- **P7-7**: Three new `pins.py` ceilings are needed: ROLLBACK_MIN_DWELL_H, the rollback target age cap, and the drill headroom.
- **P7-8**: An exhausted RECOVERABLE_INFRA budget ends in an INTEGRITY freeze. Rollback-failure HALTs must NOT be classed under it; the coordinator rules that rollback failure never freezes the venue.
- **P7-9**: The §4.4 horizon for an "intraday RESUME" is unreachable, because intraday is restrictive-only. Clarify (consistent with AUT-7 K6: RESUME is written only at 16:45).
- **P7-10**: The node re-reads the artefact by path (`app/trade.py:788`), which is a resolve-to-load gap. C5 must require a single-read handoff, or a re-verify-by-sha at load.
- **P7-11**: `is_fee_verified` is held in node memory only (`fee_drift_probe.py:292-299`). The engine uses an AUT-6 verdict.

## From AUT-1 r2
- **P1-8**: The C1 decision `kind` list needs an exit kind, so exit fills can join.
- **P1-9**: Add `capture_untagged` to the C5 VetoReason list.
- **P1-10**: Restart through `try-restart`, matching the repo's rotate unit, not `restart`.
- **P1-11**: `RuntimeMaxSec` on oneshot units: Rev 6 should already use `TimeoutStartSec`. Verify.
- **P1-12**: The self-heal restart-cap "day" resets at 16:45Z, before LAUNCH.

## From AUT-5 r2
- **P5-9**: Use `TimeoutStartSec`, not `RuntimeMaxSec`, on oneshots (repeat; verify Rev 7).
- **P5-10**: "RECONCILIATION produced after that day's STOP" conflicts with the 15:30Z pass writing the pending swap before the 16:40Z STOP. Rule: the post-STOP verdict is required at the 16:45Z ACTIVATE, not at the 15:30Z pending write. The 15:30Z write uses the latest intraday RECONCILIATION.
- **P5-11**: The relaunch request is valid for 120 s, because the supervisor polls every 60 s (`trade_supervisor_core.py:1866`).

## From AUT-4 r3 (arrived after the Rev 8 dispatch; for the freeze review)
- **P4-13/P4-14**: Settled by Rev 6/7: α is charged per nomination and `k_life` is the lifetime nomination counter. Verify that C5 stores `k_life`.
- **P4-15**: C4 FORWARD_SHADOW (c) still requires the ABSOLUTE traded-rung calibration leg, which the family fails today, so no PASS is possible. Replace it with the RELATIVE conjunct (AUT-4 E11/F5: a one-sided paired test with a margin against the champion, failing closed below N buckets).

## From AUT-3 r3
- **P3-11**: Settled by Rev 6: the scheduling rule is no overlap with [16:30Z, 17:10Z), not "end before 16:30Z". Confirm the freeze candidate states it once.
- **P3-12**: C4 carries `k_life` and `alpha_k` (verify in Rev 8).

## From AUT-6 r3 (for the freeze review)
- **P6-14 (C-12)**: Permit restrictive-only demand-file writes from pinned AUT-6 producers (the INTEGRITY floor), and reserve one demand slot for INTEGRITY.
- **P6-15**: Delivery records carry `severity`, `attempt_kind` and `drill`.
- **P6-16**: AUT-6's own WARN alerts are sent with delivery proof.
- **P6-17**: The node CRITICAL outbox is file-backed (it survives SIGKILL).
- **P6-18**: The restart call uses `systemctl --user try-restart --no-block` (consistent with P1-10).

## From AUT-7 r3 (for the freeze review)
- **P7-12**: The drill DEMOTE and HALT rows need explicit drill counters (`drill_demotes`, `drill_halts`) with ceilings; they are budgeted but uncapped today.
- **P7-13**: Add a chain row kind for target ineligibility (`TARGET_INELIGIBLE`, cause `target_integrity`). Verify that Rev 8 carries the `ROLLBACK_FAILED` class and drops the intraday RESUME clause.
- **P7-14**: AUT-5's drill timeline must align with the AUT-7 r3 sequence (DEMOTE→RESUME→HALT→ROLLBACK, the 27-day start rule).

## From AUT-1 r3 (for the Rev 9 freeze check; patch into Rev 9.1 if absent)
- **P1-13**: C1 has no store for quote-tick inputs. Widen the payload store with `quote/<sha>.json` (ask, bid, ts_event) so a quote-triggered Take can cite its preimage.
- **P1-14**: C1 `eval_ns` is defined as wall clock, but FQ decides on venue `ts_event`. Define `eval_ns` = the decision's event time (`ts_event`) and add `wall_ns` as a separate field.
- **P1-15**: The closed C4 outcome enum has no NO_INPUT. Confirm that `INCONCLUSIVE` plus `metrics.day_status=NO_INPUT` is the sanctioned form.
- **P1-16**: Self-heal is alert-only until the AUT-5b policy ruling, and AUT-6 restarts only FAILED units. A hung-but-active recorder therefore needs `try-restart` of an ACTIVE unit, allowlisted for the recorder under the HUNG classification. State this.
