# AUD-02 parent completion plan, Rev 2 (replaces Rev 1 in full)

## Overview
This plan finishes AUD-02, which was left NOT STARTED even though its sub-item AUD-02b (the set-family-halt CLI, `e837511`) has merged. Work runs in this order:
1. **Stage 0:** write and verify the AUD-02b deployment note first.
2. **Stage 1:** commit Amendment C to `POST_FORECAST_PHASE_2026-09-20.md`, citing that note's real path.
3. **Stage 2:** run B3 (ruling), B2 (verification) and step 5 (ruling) in parallel with A0 (unattended study) and WP-D1 (study).

Git evidence found in Rev 1 still holds. `a49c7b4 feat(wp-b2)` landed on 2026-09-20, before the audit, which contradicts AUD-02 §3 ("no matching commit").

**Routing: this session is Claude-only** (coordinator fact iii), so Grok and Codex are not used.
- **tdd-guide** does every write: the A0 pull script, its unit, the evidence-record test, the WP-D1 measurement script and any fix, the A-6 test, and the step-5 qualifying-rate flag.
- **trading-bot-architect + security-reviewer** rule on B3.
- **prediction-market-reviewer + trading-bot-architect** rule on step 5.
- **python-reviewer** does B2 verification, read-only.

Every brief restates the invariants: Nautilus is immutable; `allow_short` stays False; no safety, settlement or contract test is weakened; operator caps are never assigned; NO-SEND and enablement are not touched. Every brief sets `projectPath=/home/jon/breezy`, gives the agent its own scratchpad, allows one heavy job at a time, and says it runs blind.

## Rev 2 dispositions
| Item | Disposition (where in Rev 2) |
|---|---|
| ARCH 1 | Probe HIGH risk removed and replaced by a citation of `docs/evidence/RULING_fee_drift_probe_target_2026-09-25.md`. The probe never ran live, and the node was hand-launched at 09-24 20:15Z, before `30dd034`. DoD 2 adds the decoded-payload check and the re-set path (§Stage 0). |
| ARCH 2 | The deployment note is written and verified first (Stage 0). Amendment C is committed afterwards, and C-2 cites the note's real path. |
| ARCH 3 + TBA 1 | Re-mint removed from B3's scope; it goes to security-reviewer's separate item "permit cumulative coverage". B3 still prints the worst-case multi-mint bound with the given citations. The runbook states the gap is accepted and NOT alerted until B1 (§2 B3). |
| ARCH 4 | DoD 1 uses whitespace-normalised matching plus `git merge-base --is-ancestor` for each SHA (§5). |
| ARCH 5 + TBA 3 | WP-D1 closing rule rewritten: set equality; venue list paged to eof; same discovery cycle; pre-registered ERROR regex and whitelist; days counted from the first boot carrying `aa737f1`; ≥5 days (§2 WP-D1). |
| ARCH 6 | A0 uses mutation evidence (L-33). B-6 is pre-registered exactly. A per-day completeness threshold is added, and missing slugs are recorded. AUD-12b samples are excluded. C-4 shows A0 in parallel with WP-D1 (§1, §2 A0). |
| TBA 2 | Unattended runner: `scripts/venue/fee_drift_evidence_pull.py` plus `deploy/systemd/breezy-fee-evidence-pull.{service,timer}` at 11:10 UTC (§2 A0). |
| ARCH 7 | Claude-only routing (Overview). |
| NB DoD 8 | `halt_enforced` digest line is corroboration, not a gate (§5 item 9). |
| NB §8 bullet 3 | Mapped to RULING_A1 plus AUD-02b tests (1) and (10) (§5 item 3). |
| NB step 5 | Expected outcome withheld from peers (removed from the plan). Qualifying-rate script, WP7b definition and freeze date are named. Step 5 runs in parallel with A0 (§3). |
| NB C-7 | Ends at AUD-18 §6.6 KILL. Choosing a successor venue is out of scope, and no Kalshi branch is named (§1 C-7). |
| NB B2 | B2 note asserts the live boot passes a non-None permit to the guard (§2 B2). |
| NB B3 LAUNCH claim | Dropped as unverified. (a) is recommended on the no-sending-family ground only (§2 B3). |

## Stage 0: AUD-02b deployment note, before Amendment C
The note goes at `docs/evidence/AUD-02b_halt_deployment_2026-09-2X.md`. tdd-guide runs the read-only commands, and doc-updater writes up the captured outputs. Contents:
1. **`breezy-set-family-halt --status`**: the store-path token (`MATCH` or `NO_NODE`) and `halted=True`, taken fresh on the day the note is written.
2. **Decoded payload**: a read-only sqlite read of `FAMILY_HALT_KEY` (`trial_day_latch.py:292`), decoded. It must name the A1 ruling in `reason`, and its `evidence_sha256` must equal `sha256(docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md)`.
3. **The 09-24 16:42Z set record**: the LIVE_GET source, verdict and token, from the CLI's own output in the journal. If the output was not kept, record it as NOT RECOVERABLE. Do not reconstruct it.
4. **Forced-submit refusal** naming `family_halt`: AUD-02b tests (1) and (10), run under `scripts/ci/run_tests_no_egress.sh`. Record the output.
5. **Node log excerpt** showing capture and the tally still advancing, plus the 17:05Z `self_check_fail_continuous_family_halted` line.

**If item 2 fails** (the payload is not the A1 policy halt): the set CLI refuses while the node holds the flock, and it exits 3 ("already halted") without rewriting. A re-set therefore has to happen in a node-down window, **after the probe-target fix is installed and before the node respawns**. In one window, in this order:
1. `breezy-clear-family-halt` (reason plus evidence);
2. `breezy-set-family-halt` with the A1 ruling as evidence (the LIVE_GET flat check is still required);
3. the before and after store-path tokens;
4. respawn.

No send is possible inside the window because the node is down. Then repeat items 1 and 2.

## 1. Amendment C: exact text (committed only after Stage 0)
How it satisfies AUD-02: §6.1 → C-1; §6.2 (verbatim) → C-3; §7 step 1 (a dated addendum in the same form as A and B) → heading and separator; §8 bullet 1 → C-1 and C-3. C-2 and C-4 through C-7 are additions this plan makes.

```markdown
---

# AMENDMENT C — AUD-02 status fold-in (2026-09-2X)

Authority: `docs/plans/backlog/AUDIT_2026-09-21/AUD-02-edge-discovery-programme-status-and-fold-in.md`
§6.1–6.2, §7 step 1. Amendments A and B remain binding; nothing here re-litigates them.

## C-1 — Work packages DONE (verified against git history)
- **WP-B0 (alert egress): DONE** — `f97c26f feat(wp-b0)`; tee to log AND webhook `bcb82d6`.
- **WP-R1 (zero-orders / all-refused detector): DONE** — `6aa9d92 feat(wp-r1)`,
  calibration fix `e83fc5c fix(wp-r1)`.
- **B2 (kernel guard): DONE** — `a49c7b4 feat(wp-b2)`, 2026-09-20, as ONE kernel guard per B-5
  (`PermitExpiredRefusedError`, `runtime/backtest_order_guard.py`). AUD-02 §3's "no matching
  commit" for B2 is CORRECTED here. Verification: `docs/evidence/WP-B2_verification_<date>.md`.

## C-2 — A1 is RULED (ii); enforcement record
A1: **(ii) STOP TRADING THIS SURFACE**, peer-ENDORSED —
`docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` (Rev 3; review
`docs/evidence/reviews/RULING_A1_review_2026-09-21.md`). Enforcement: `breezy-set-family-halt`
(`e837511`, AUD-02b); deployment and verification record
`docs/evidence/AUD-02b_halt_deployment_<date>.md` (the halt state as read from the node-resolved
store on that date, with decoded payload). `e3e8ac6` opened `pm_us_crh_v4` at θ=0.0695 before the
ruling; the ruling is the disposition of record. The node, capture, shadow valuation and the KILL
clock keep running; order submission (entry AND exit) is vetoed.

## C-3 — A1's precondition is WIDENED (applies to any FUTURE A1-class ruling)
Amendment B-1 required "a post-θ edge estimate for `pm_us_crh` itself." Add: "...and that edge
estimate must be computed WITHOUT relying on `P_HOLD_LOWER`/`P_HOLD_UPPER` cells whose gate-pass
conditioning the domain reviewer has ruled a collider (`DECISION_FUNNEL_2026-09-20.md`, 'Why
"recalibrate on the gate-pass subsample" is NOT the remedy') — i.e., A0's fee-drift evidence pack
alone cannot satisfy A1; a genuinely independent edge estimate is required, and if none can be
produced without real (non-synthetic) historical venue ladders, **(ii) STOP TRADING THIS SURFACE is
not merely the default, it is very likely the only defensible ruling.**" The independent estimate
is owned by AUD-18 (hand-off H5). A re-arm additionally needs HUNT-1 met and a NEW registration per
A-9 item 2 (A1's row cites "per L-34"; A-9 item 2 is the correct source).

## C-4 — Revised order (supersedes B's order for the remaining items)
    B3 (window posture — ruling)       ||  B2 (DONE — verification note only)
    WP-D1 (discovery attrition — study) ||  A0 (fee-drift evidence — unattended study + evidence test)
      A0's evidence set is closed only after WP-D1 confirms the day-list source (see A0).
    Step-5 re-evaluation of B1, WP-T1, WP-Q1, C0, C1, C2 (C-6)  || runs alongside A0
A0 is a precondition of any FUTURE A1-class ruling, no longer of A1 itself. AUD-12b's
`FeeDriftProbeActor` (`30dd034`) is a single-slug DETECTOR; A0 is the all-slug raw-wire EVIDENCE
pack; probe samples are excluded from A0's evidence set. Probe comparison target:
`docs/evidence/RULING_fee_drift_probe_target_2026-09-25.md`.
Permit cumulative coverage (mid-day relaunch re-mint) is a separate safety item, not B3.

## C-5 — Verification artefacts
B2, WP-D1 and A0 close on dated notes under `docs/evidence/`, never on a commit subject alone.

## C-6 — Re-evaluation under (ii)
Every WP in {B1, WP-T1, WP-Q1, C0, C1, C2} receives exactly one disposition in
`docs/evidence/RULING_post_forecast_wp_reevaluation_<date>.md`, a two-peer ruling meeting the
six acceptance criteria stated in the AUD-02 completion plan.

## C-7 — Goal state (no bare STOP)
(ii) is interim. The route back to forecast trading and learning: AUD-18 nightly triage (learning)
-> a CONFIRMED hypothesis (H5/H6) -> a NEW A1-class ruling -> a NEW registration -> operator-only
enablement. The programme's terminal non-trading state is AUD-18 §6.6's evidenced KILL: "nothing
arms," and PM.us daily-high rungs close as a programme. Choosing any successor venue is out of
scope of this plan and of AUD-18.
```

After the commit, add a one-line pointer to Amendment C beneath AUD-02's coordinator block. The reviewed body of AUD-02 (whose sha is recorded) is not edited.

## 2. Work package chain

### B3: window posture (**ruling**, plus a runbook section; no code)
- **Scope.** Choose (a) accept the gap, or (a′) move LAUNCH later. A-1 struck option (b). Ruled by trading-bot-architect + security-reviewer.
- **Out of scope.** The mid-day relaunch re-mint. security-reviewer is ruling that separately as "permit cumulative coverage", and B3 cites that item by name.
- **Worst-case multi-mint bound the ruling must print** (citations as supplied by the reviewers; the ruling re-reads each one):
  - relaunch cutoff and scheduling: `trade_supervisor.py:1352-1379`, `trade_supervisor_core.py:54-55,864-868`
  - TTL and mint: `safety.py:172,714`, `app/trade.py:651`
  - First mint: 16:50Z, expires 02:50Z. A relaunch at 00:59Z mints a permit that expires about 10:59Z.
  - Worst-case union of coverage: 16:50Z → about 10:59Z, roughly 18 h 09 m.
  - Gap until STOP_PRIOR at 16:40Z: about 5 h 41 m in the worst case, about 13 h 50 m in the single-mint case.
  - The ruling states these numbers and does not judge them. Judging them belongs to the separate item.
- **Runbook.** `docs/plans/R8_OPERATOR_RUNBOOK.md` gets a new section, "Permit window posture". It states the ruled option and the arithmetic, and says plainly: **the gap is accepted and NOT alerted until B1 exists.**
- **Recommendation: (a).** No family can send under (ii), so nothing is gained today. (a′) is re-opened at any new registration. Rev 1's claim that (a′) shifts the capture and KILL-clock schedules is **dropped** because it was not verified.
- **Acceptance.** The ruling doc and runbook section exist, and the bound figures are printed with their citations. The "supervisor test asserts the alert fires" clause moves to B1 (step 5).

### B2: kernel permit-expiry guard (**code, DONE; verification only**, python-reviewer)
The note goes at `docs/evidence/WP-B2_verification_<date>.md`. It must show:
- the WP-B2 tests passing, including A-5's `test_runtime_order_guard_permit_expiry.py::test_the_exec_chokepoint_still_refuses_an_expired_permit_with_this_guard_passing`;
- the refusal routed through the named refusal counter;
- the `safety.py` chokepoint test untouched;
- **A-6**: `ContinuousRungHoldBacktestStrategy._has_order_submission_permit` still has no permit object. If no test pins this, tdd-guide adds the pin test;
- **live wiring**: codegraph shows the live boot path (`app/trade.py`) passes a **non-None** permit, with its `expires_at_ns`, to the guard. With a None permit the guard would be inert in production.

### WP-D1: discovery attrition (**study**; becomes **code** only if the rule fails)
- **Tooling.** tdd-guide writes a read-only `scripts/analysis/discovery_set_equality.py` with tests.
- **Pre-registered closing rule.** Written into the note header, dated, before any data is read:
  1. **Day eligibility.** Count only days on or after the first node boot whose code includes `aa737f1`. The boot's git sha comes from the boot log line. If there is no such line, the first eligible day is the first 16:50Z launch after the merge time, stated as such.
  2. **Per-day comparison.** Compare the venue's weather-market list for the traded stations, **paged to eof**, with the node's discovered-slug snapshot **from the same discovery cycle** (the cycle within ±1 poll of the venue pull). The comparison is **set equality of slugs**, not counts. Both set differences are written out.
  3. **ERROR count.** `journalctl` for the node unit, filtered by the pre-registered regex `\bERROR\b.*(discover|provider|listing|instrument)`, with the whitelist `BREEZY-NWS subscribe` (cosmetic, per memory).
  4. **Close SUPERSEDED-BY AUD-08a** if there are **≥5 eligible days**, each with set equality and zero non-whitelisted ERROR matches. Otherwise, root-cause the difference as a new tdd-guide fix slice.
- **If the node emits no per-cycle discovered-set record,** that is a finding in itself. The minimal fix is one INFO line per cycle, delivered as a tdd-guide slice, after which the eligible-day count restarts.

### A0: fee-drift evidence pack (**unattended study, plus an evidence-only test; no `src/` change**)
- **Pull script** (tdd-guide): `scripts/venue/fee_drift_evidence_pull.py`.
  - It uses only unauthenticated public GETs (`fetch_wire_fee_coefficient`'s transport, `fee_drift_probe.py:146`).
  - Each run: (1) read the venue weather-market list, paged to eof, and store that response as the day's denominator; (2) GET every listed slug, paced, and keep the **raw wire JSON**. Taker and maker fields are recorded separately from the wire (B-7), never from `instrument.maker_fee`.
  - Output goes to `data/evidence/fee_drift/<UTC date>/`. Failed or missing slugs are **recorded with a reason, never dropped**.
  - Reuse the raw-capture pattern of `scripts/venue/polymarket_us_shape_capture.py` if it fits. No new transport.
- **Unattended runner** (tdd-guide): `deploy/systemd/breezy-fee-evidence-pull.service`, `Type=oneshot`, `MemoryHigh=384M`, `MemoryMax=512M`, `OnFailure=breezy-study-failed@%n.service`, in `Slice=breezy-studies.slice`. The paired `.timer` has `OnCalendar=*-*-* 11:10:00 UTC`, `Persistent=true`.
  - 11:10 is clear of the existing ticks (00/06/12/18:15, 01:35, 09:00, 09:20, 09:25, 13:30, 14:15, 14:30, 15:00, 15:20, 17:20, 17:40), clear of the 15-minute ingest ticks, and outside the protected window [16:35Z, 01:15Z). `tests/unit/test_deploy_timer_hours.py` enforces the collision check and must stay green.
  - The job is light, so it does not take `breezy-studies.lock`.
- **Pre-registered in the evidence doc header** (`docs/evidence/venue/polymarket_us/FEE_DRIFT_EVIDENCE_<date>.md`, written before the first pull):
  - **Evidence set.** Only this script's pulls, dated after 2026-09-17. AUD-12b probe samples are **excluded**.
  - **Complete day.** A day counts only if at least 95% of that day's venue-listed weather slugs returned a parseable `feeCoefficient`. Incomplete days are recorded, not counted.
  - **Required length.** ≥5 consecutive complete days.
  - **B-6 verdict, exactly:** **STEP CHANGE** if every post-09-17 observation across all complete days is a single value. **NON-STATIONARY** if there are ≥2 distinct post-09-17 values. Separately, the maker field's value set is reported for each day.
  - **Day-list check.** Before the evidence set is closed, WP-D1's result is cited to confirm the venue list is a complete source for each day.
- **Evidence-record test** (tdd-guide): extend `tests/unit/test_polymarket_us_fee_schedule_pin.py`.
  - The test asserts two things: the recorded observed set matches the evidence doc, and `DOCUMENTED_TAKER_FEE_COEFFICIENT == Decimal("0.06")` (A-3).
  - **Mutation evidence instead of RED-first (L-33):** in the agent's own worktree (with PYTHONPATH set), change `fees.py:86` to `Decimal("0.0695")`, capture the test **failing**, then revert. Record the captured output in the test PR and the evidence doc. This proves no edit to `fees.py` can turn the test green.
- **Acceptance.** The doc has the pre-registered header, ≥5 complete days and the verdict. The mutation run is captured. `git diff src/` is empty. The timer passes the collision test.

## 3. Step 5 re-evaluation: acceptance test (runs in parallel with A0)
- **Output.** `docs/evidence/RULING_post_forecast_wp_reevaluation_<date>.md`, ruled by prediction-market-reviewer + trading-bot-architect.
- **Brief rule.** The brief gives the peers the evidence and the criteria only. **No expected outcome goes to the peers.**
- **Input computed before the peers start: the B-2 qualifying rate.**
  - Script: `scripts/analysis/wp7b_market_as_forecaster.py`, reusing its existing region predicate. If it has no date-window or YES-only mode, tdd-guide adds that flag as a pure addition. No new predicate.
  - Definition, from `docs/evidence/WP7b_MARKET_AS_FORECASTER_2026-09-20.md:203-208`: `yes_ask ≥ 0.70` AND `Σask over the complete partition ≤ 1.20` at the 09:00 LST instant. For this count only the YES side must be priced at L0, because the NO leg is not captured.
  - The region was frozen 2026-09-20, so the window is climate days on or after **2026-09-21**.
  - Output: qualifying events per station-day, with n station-days.
- **Pass criteria (all required):**
  1. Each of B1, WP-T1, WP-Q1, C0, C1 and C2 gets exactly one disposition: KEEP, RESCOPE (with new acceptance text), SUPERSEDED-BY (id + sha), PARK-UNTIL (trigger), or CLOSE.
  2. Every disposition cites a commit SHA, an evidence path, or a measured number.
  3. Every PARK trigger is a named quantity with the script or command that computes it.
  4. Every PARK, CLOSE or SUPERSEDED names which item carries the capability forward toward trading and learning. The C1/C2 disposition must be sent to AUD-18 §6.3's NO-side triage input, so that class is not orphaned.
  5. Nothing that protects the parts still running (the node, capture, shadow valuation, the KILL clock) is CLOSED unless a replacement is named.
  6. Every "superseded" claim is checked against code with codegraph. Candidates:
     - WP-Q1 against `2fa5274` and the aud-01b merge;
     - C1 against the stall-followups F-1 NO-side work, including whether `^no` dirs exist in `order_book_depths`;
     - WP-T1 against AUD-12b and AUD-13b.

## 4. Overlaps and dependencies (by ID)
| ID | Relationship |
|---|---|
| **AUD-18** | Owns the independent edge estimate (H5 → a future A1-class ruling), and its §6.6 KILL is C-7's terminal branch. The step-5 C1/C2 disposition feeds AUD-18 §6.3's NO-side class. It is not a completion dependency of AUD-02. |
| **AUD-09b** | Replay runner, not built. It feeds AUD-18 (H4) and AUD-10b (H3). WP-Q1's disposition affects its sufficiency census. |
| **AUD-10b** | Proposal generator, P2, not built. Moot for `pm_us_crh_v4` until a new A1-class ruling. It must cite C-2. |
| **AUD-11** | Merged `af6f92b`. The A0 pull script and any C2 readout must pass its point-in-time guard, which covers the WP-D1/A0/C2 paths (AUD-11:211-212). |
| AUD-12b (adjacent) | Same halt key. Its comparison target is ruled in `RULING_fee_drift_probe_target_2026-09-25.md`. Excluded from A0's evidence. |
| AUD-03 (adjacent) | `halt_enforced` is delivered (`622f888`), which satisfies AUD-02 §7 step 4. |
| "permit cumulative coverage" | security-reviewer's separate safety item. B3 cites it and does not rule on it. |

## 5. Definition of Done for the AUD-02 parent
1. **Amendment C present.**
   - `tr -s '[:space:]' ' ' < POST_FORECAST_PHASE_2026-09-20.md` contains C-3's quoted sentence, with the source AUD-02 §6.2 text normalised the same way, byte for byte.
   - For each of `f97c26f`, `6aa9d92`, `e83fc5c`, `a49c7b4` and `e837511`, the SHA appears in the amendment AND `git merge-base --is-ancestor <sha> HEAD` exits 0.
2. **Stage 0 note exists before Amendment C's commit**, checked with `git log` ordering. It contains:
   - `--status` showing `MATCH` or `NO_NODE` and halted, with the before and after tokens;
   - a decoded payload whose `reason` names the A1 ruling and whose `evidence_sha256` equals the ruling file's sha256. If not, the re-set path in Stage 0 was run and the check repeated;
   - the forced-submit refusal output and the node log excerpt.
3. **AUD-02 §8 bullet 3 met.** The signed ruling is `RULING_A1_…` Rev 3. "A family_halted state plus a test that the node refuses to arm it" is met by AUD-02b tests (1) (set, then the veto returns `family_halt`) and (10) (forced submit refused), with passing output recorded in the Stage 0 note.
4. **B3.** Ruling doc and runbook section exist. The worst-case bound is printed with its citations. The "not alerted until B1" sentence is present. The separate item is cited by name.
5. **B2.** Verification note exists with A-5, A-6 and non-None live-permit wiring confirmed.
6. **WP-D1.** Note exists with the pre-registered header dated before the data, ≥5 eligible days, the set differences, the ERROR counts, and a verdict (SUPERSEDED-BY AUD-08a, or a filed fix slice).
7. **A0.**
   - The evidence doc and pre-registered header exist, with ≥5 consecutive complete days and the B-6 verdict.
   - The mutation run is captured.
   - `git diff src/` is empty.
   - The timer and service are deployed, and `test_deploy_timer_hours.py` is green.
   - `systemctl --user list-timers` shows `breezy-fee-evidence-pull.timer`.
8. **Step 5.** The ruling passes criteria 1–6, and the C1/C2 disposition has been sent to AUD-18.
9. **Corroboration only, not a gate:** one delivered AUD-03 digest showing `halt_enforced: yes`.
10. **Gates.** `scripts/ci/run_tests_no_egress.sh` and `lint-imports` pass after every write slice. No safety, settlement or contract test is modified. The AUD-02 coordinator status block is appended, and PROGRESS.md's stale WP-R1 entry is trimmed.

## 6. Risks and mitigations
- **The halt payload is not the A1 policy halt (MEDIUM).** Found by the decoded-payload check. The fix is the Stage 0 re-set path in a node-down window, done before the probe-fixed respawn.
- **The 09-24 set output is unrecoverable (LOW).** Record it as NOT RECOVERABLE. The fresh `--status` and decoded payload are what count.
- **A0 day-list source incomplete or venue pagination drifts (MEDIUM).** Paging runs to eof, the list response is stored, the completeness threshold applies, missing slugs are recorded, and WP-D1 confirms the source before the set closes.
- **A0 read load on the venue (LOW).** Pacing, public GETs only, one run per day.
- **Criteria chosen after seeing the data (MEDIUM).** Every closing rule is dated in its doc header before the first read. Step-5 peers never see an expected outcome.
- **Step 5 turns into a bare STOP (MEDIUM).** Blocked by criteria 4 and 5 and by C-7.
- **Shared tree (LOW).** Separate scratchpads and worktrees; commit files by explicit path; never stash; mutation runs happen only in the agent's own worktree.

## Trade-offs decided
- **B3 (a):** there is no sending family, and (a′) is re-opened at any new registration.
- **A0 runs in parallel with WP-D1**, gated only when the evidence set closes. This saves about 5 days, and the list is captured independently of the lister.
- **A0 gets its own timer rather than extending the AUD-12b probe.** The probe is an in-node actor. Widening it would change live node behaviour and mix detection with evidence.
- **B2 is not rebuilt.** Verification only.

## Confidence
| Claim | Confidence | Basis |
|---|---|---|
| Amendment C clauses match AUD-02 §6.1–6.2 | High | Quoted from source |
| B2 DONE at `a49c7b4` | High | Reflog plus `backtest_order_guard.py:133` |
| B2's live permit is non-None at the guard | Medium | Not yet traced; checked in the B2 note |
| Halt set with the A1 payload | Medium-low | Memory plus coordinator fact (i); Stage 0 decides |
| WP-D1 superseded by AUD-08a | Medium | Plausible; the ≥5-day rule decides |
| A0 timer slot 11:10 UTC collision-free | High | Every `OnCalendar=` line read this session |
| `wp7b_market_as_forecaster.py` can be restricted to post-freeze YES data without a new predicate | Medium | Script exists; its flags were not read |
| B3 citation line numbers | Medium | Supplied by the reviewers, not re-read by me; the ruling re-reads them |
| Probe fix deploys before any restart | Given | Coordinator fact (i) |

Key files:
- /home/jon/breezy/docs/plans/POST_FORECAST_PHASE_2026-09-20.md
- /home/jon/breezy/docs/plans/backlog/AUDIT_2026-09-21/AUD-02-edge-discovery-programme-status-and-fold-in.md
- /home/jon/breezy/docs/plans/R8_OPERATOR_RUNBOOK.md
- /home/jon/breezy/docs/evidence/WP7b_MARKET_AS_FORECASTER_2026-09-20.md
- /home/jon/breezy/scripts/analysis/wp7b_market_as_forecaster.py
- /home/jon/breezy/src/breezy/strategy/current_rung_hold/fee_drift_probe.py
- /home/jon/breezy/src/breezy/runtime/backtest_order_guard.py
- /home/jon/breezy/tests/unit/test_deploy_timer_hours.py
- /home/jon/breezy/deploy/systemd/breezy-study-failed@.service

## Rev 2.1 (coordinator, 2026-09-25) — binding corrections from the round-2 review

Round 2: architect REQUEST_CHANGES (one blocking item; 7/7 Rev-1 items confirmed resolved), trading-bot-architect APPROVE (B3 arithmetic independently re-derived). With these corrections the plan is APPROVED; they override the text above where they conflict.

1. **Stage 0 re-set path (fail-closed; supersedes the ordered list under "If item 2 fails").**
   a. Choose a window outside the supervisor's LAUNCH (16:40–17:05Z), mid-day watch (to 01:00Z) and self-check phases, OR stop the supervisor via `systemctl --user stop` (never a signal to its pid). Record the window start/end and method in the note.
   b. BEFORE any clear: `breezy-set-family-halt --status` shows `MATCH`/`NO_NODE` AND the LIVE_GET flat-and-known check passes. If either fails, do nothing further; record it; alert.
   c. Only then `breezy-clear-family-halt` immediately followed by `breezy-set-family-halt` citing the A1 ruling; the set MUST exit 0.
   d. HARD STOP: the node may be respawned (or the supervisor restarted) ONLY after `--status` reports halted AND the decoded payload's `evidence_sha256` equals the A1 ruling file's sha256. If the set fails at any point the node stays down and an alert is emitted; the halt is re-attempted before any respawn.
2. **A0 unit guard.** The pull script exits 0 without pulling when started inside [16:35Z, 01:15Z) (a `Persistent=true` catch-up), marking the day INCOMPLETE in its output. Its docstring cites the exact pacing constant/pattern reused from `scripts/venue/polymarket_us_shape_capture.py` (or states the inter-request delay it uses).
3. **WP-D1 note additions.** Report the total unfiltered ERROR count beside the regex-filtered count; a day with no node discovery cycle is INELIGIBLE (never counted as equal).
4. **A0 raw-data retention.** `data/evidence/fee_drift/` is outside git: the evidence doc records each day's raw directory sha256 manifest, and the directory is never pruned by any retention job (name it as excluded in the doc).
