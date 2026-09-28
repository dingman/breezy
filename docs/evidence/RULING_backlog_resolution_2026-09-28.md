# RULING — resolution of every blocked / parked backlog item (2026-09-28)

**Authority:** the operator directed on 2026-09-28: "you are responsible for making those decisions. Autonomously resolve all blocked/parked items." This is a coordinator ruling under that grant.

**Hard floors, unchanged by this ruling:** clearing the A1 halt or arming any family is the operator's act (RULING_A1 §7). The two operator caps are untouched. `allow_short=False`. Nautilus is immutable. No safety, settlement, contract or NO-SEND test is weakened. PREREG semantics are unchanged.

**Evidence base:** four read-only Codex triage passes on 2026-09-28 at 15:28–15:34Z, using file:line, commit and journal citations, plus coordinator host checks at 17:30Z. Each disposition below cites its primary source.

## 1. Revival path (EDGE-5 / RA-13)

**Decision: pursue R3 only, as an evidence-gated watch. Build nothing for R2 or R4 now.**

- R2 (a live sub-degree obs source) is physically absent (`RULING_HUNT-1…:22,36`; memory of the Stage 0b stop).
- R4 has no verified powered estimand.
- R3 is the only path backed by data that already accrues: EDGE-4 reaching ≥300 post-freeze CONFIRM station-days, with the `census_provenance:` line quoted (`EDGE-4_DISPOSITION_2026-09-27.md:20-22`).

**Obligation added (R3-PROJ):** RA-13 already infers that R3 cannot fire before about 2026-11-24 (300 days at 5 station-days/day from 09-26; `RULING_RA-13…:14`, INFERRED), which is before the backstop. R3-PROJ verifies that date against the real accrual rate (venue-skipped days, node-down days). If R3 cannot reach 300 before the backstop, the honest outcome is the programme KILL, with Kalshi K-2 as the successor (`KALSHI_K-1…:70-79`). R3-PROJ is analysis only. Per the EDGE backlog insight, it must not compute any statistic on post-09-25 tape.

**RA-11a:** stays parked. It is only needed if R2, R3 or R4 fires, and it dies with the KILL otherwise.

## 2. Dispositions

| ID | Disposition | Ruling |
|---|---|---|
| RA-9f | BUILD (Path A only) | Build the zero-look `UNDERPOWERED_NOT_REGISTERED` registrar for `H-OFFWINDOW-T4-2026-09` per `RULING_RA-9…:108,121-138`. Do **not** flip `HORIZON_TOLLING_LANDED`: a flip is needed only for a future look-taking v3 record. |
| PATH-B-SOURCE-GATE | RULE: dormant | The flag stays False, which fails closed. It reopens only on its four named triggers (`PATH-B-SOURCE-GATE…:62-66`). |
| AUD-12 / RA-3 | RULE: dormant | It is flipped only by its own validity ruling, attached to the revival path, and never as backlog cleanup. |
| AUD-06b | KEEP-GATED (evidence floor) | Needs a CONFIRMED unit-qty edge and a newly registered family. |
| HUNT-1 | WATCH | The requirement stands. Its triggers are unchanged (`RULING_HUNT-1…:34-38`). |
| THIN-BOOK-REFUSAL | RULE | This is fill-rate and opportunity-cost evidence, not slippage (`RULING_AUD-12a…:42-43`). It must not feed sizing before the AUD-06b gates. |
| Kalshi sibling | RULE | A post-KILL successor, not a revival path. |
| LADDER_EV stage 2 | PARKED (outside the revival path) | Nothing on the R3 path consumes it. Reopen only if an R3 re-plan names a ladder estimand. The stage-1 modules stay. |
| G-16 / G-17 | CLOSE | Superseded by the AUD-17 / AUD-03 plans (`AUDIT_2026-09-21/README.md:41,56`). |
| PREREG v2 residue | CLOSE | No new revival work uses v2 (V2-LOOK-GATE 0287442 refuses v2 look-taking). |
| EDGE-2-LIVE / EDGE-2-LAG / R-7-IMPL / EXEC SPINE R-7 residue | KEEP-GATED (A1 floor) | Watch for the first post-re-arm AMBIGUOUS order and the first create-path `R7_POSITION_REPORTING_LAG` line. Deterministic tests already cover AC7. |
| EDGE-2-MULTIPAGE step 2 | WATCH | Trigger: `resolver: activities join … traversed N pages` or ≥80 activities. Building before the trigger would contradict its own plan. |
| EDGE-2-REFACTOR | CLOSE | Refactor steps 1–8 are YAGNI. G1–G14 (77ef02c) stay as a guard. Reopen only inside a behaviour change that touches `_resolve_ambiguous_intents`. |
| FAILURE-KIND durable | BUILD | Persist the last failure kind with the durable ambiguous intent, so the kind survives a restart. |
| SP-5b | BUILD | Its trigger is prospective (before the next registration), so building early is strictly safer. Carry the two architect fixes. |
| T-9 | RULE | No blind-flatten patch. Each family's PREREG states its exit policy. CRH stays hold-to-settlement unless the 09-16 exit seam is armed. |
| T-6 | BUILD (doc) | Correct the stale `node_config.py:11-14` summary. |
| `max_simultaneous_positions` | CLOSE | Fixed in dbd91d9 (`risk.py:327-335`). |
| `InvalidStateTrigger STOPPED->START_COMPLETED` ×4 per boot | BUILD | A halted strategy must reach `stop` without the FSM error, still never arming. |
| FU-8b-DEPLOY / NOTIFIER-IMPORT-ISOLATION | CLOSE | Live: the `refusal re-poll timer armed` line appears in node log 20260928T165022Z. The node imported and booted post-merge. |
| ING-2-AMEND | BUILD | The removal check FAILED on 09-28 09:45Z: chunks=324, peak 6G, 610 s, deferred_instances=45. The TEMPORARY drop-in stays. Diagnose and bound the path that still defers. |
| ING-2 residual (deferred-unit alert) | CLOSE | Exit 4 means `DEFERRAL_STALLED`, and `OnFailure=` routes it to `study_failure_notifier` (`quote_tape_exit_codes.py:33-38`). |
| AUD-07 | RUN | seg-0928a exited 0 with 32 cells still in `20k/DEFERRED`. Drain 20k before 80k, in a gate-free night window. The chain never advances while `20k/DEFERRED` is non-empty. |
| AUD04-FRESH | CLOSE (proven) | The 15:20Z run was killed by the 15:21Z host reboot. The 17:33Z re-run logged `AUD-04 per-trial reconciliation: matched=False cutoff=2026-09-20 n_exit_only=1 exit_only_trial_ids=['continuous_rung_hold/trial/MIA/2026-09-13']` (`~/.local/share/breezy/derived/exit_window_study.log`). The reconciliation now runs; it is NOT SKIPPED. |
| RECON-MIA-0913 (new) | INVESTIGATE | That MIA 09-13 trial appears in the exit study and is absent from AUD-04. Find which side is wrong before any P&L figure is cited. |
| AUD-10b | RUN | C12 is satisfied: the 09-28 15:50Z replay finished at 15:58Z, but at a **10G peak**, which equals the TEMPORARY cap. Stage 0 and the R3-5 byte-diff are still owed before the drop-in comes off. The 10G peak must be explained first (the REPLAY-BIGINST claim was that the peak no longer scales with instance size). |
| AUD-02 | WATCH | A0 earliest close is 09-30. The 09-27 WP-D1 run was complete=true. |
| Whole-tape replay regen | CLOSE | Superseded by AUD-09 / AUD-10b scheduled per-station replay. |
| CF-1 | CLOSE | The unverified count inference is not relied on. |
| CF-2, CF-7 | RULE: attach to consumer | These are prerequisites of METAR station selection, which has no plan. They are built inside that plan, not standalone. |
| CF-4 | RULE: accept | Record qualifiers are non-settlement metadata with no consumer. |
| CF-5b | BUILD | One deduped chronic-UNREADABLE condition, using the existing `AlertState`. |
| CF-6 | BUILD | The live test reads its contact from the environment and skips when unset. No personal address literal in tests. |
| CF-8 | CLOSE | 304 reuse is proven (`test_ingest_nws_actor.py:1017-1045`). |
| CF-11 | BUILD | Measured 09-28: 105 files under `src/` (519 tree-wide). One mechanical `src/`-only format commit, gate-green, with no behaviour diff. |
| CF-12 | BUILD | Measured 09-28: ruff reports 84; mypy stops on 2 collection blockers. Fix the blockers first, then re-measure. |
| CF-13, CF-14b | KEEP-GATED (evidence floor) | No live CCA/CCB correction event, and no observed 1-of-N stage-3 failure. |
| PF-1 | CLOSE | Micro-perf with no measured problem. Reopen on a profile. |
| BL-10 | BUILD (security review required) | The send-boundary fingerprint still hashes caller-chosen bytes (`submit_chain.py:248-263`). It must fingerprint method, path and serialized body. |
| AUD-18 | OPEN as the evidence producer | Only sub-item (b), RA-2 d10272b, is closed. AUD-18a / `hypothesis_triage.py` owns the R3 revival count. |
| EDGE-6 | CLOSE | 6b/6d/6f live; 6c K1 retired in 833bada. The only residue was ING-2-AMEND, now ING-2-AMEND2. |
| TRADE-ROW-DRIFT / SUP-ADOPT-LOG-GLOB | CLOSE | Merged in be206e0 and d5b688f; the latter verified live at 01:40Z on 09-28. |
| PROBE-CLASSIFIER-DRIFT | Folded into EDGE-2-MULTIPAGE step 2 | Same trigger (M-4 1b). |
| GL-4P | CLOSE | Satisfied by the 09-23 MIA evidence pack (`README.md:109-121`). |

**Peer review:** Codex adversarial review r1 (`docs/plans/backlog/RESOLUTION_2026-09-28/RULING_review_codex_r1_2026-09-28.md`) returned ENDORSE-WITH-AMENDMENTS. All amendments are applied above. It found no hard-invariant violation.

## 3. What remains after this ruling

- **Build:** RA-9f Path A, FAILURE-KIND durable, SP-5b, halted-FSM noise, ING-2-AMEND2, BL-10, CF-5b, CF-6, CF-11, CF-12, T-6.
- **Analysis:** R3-PROJ, RECON-MIA-0913.
- **Run:** AUD-07 20k drain, AUD-10b Stage 0 / R3-5 and the 10G explanation.
- **Watch or gated:** everything else.
