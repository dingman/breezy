# Adversarial peer review — RULING_live_family_tally_scope_2026-09-21.md

Status: REVIEW — independent peer (statistical/evaluation-methodology), BLIND run.

**Verdict: ENDORSE-WITH-REQUIRED-CHANGES** (BLOCKER-2, BLOCKER-3, R-4 hold; BLOCKER-1's
framing and interaction with a sibling ruling must be fixed before this artefact is acted on).

## Defects

**[CRITICAL] Silent conflict with `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`.**
File: `docs/evidence/RULING_live_family_tally_scope_2026-09-21.md` (whole document).
Issue: a second, same-day, same-repo ruling rules `pm_us_crh_v4` **HALTED — STOP TRADING**
(RULING_A1 §4) and explicitly states re-arm is not pre-authorized (RULING_A1 §7: "this
document does not pre-authorize [re-arm]; a new A1-class ruling would still be required").
The reviewed ruling never mentions RULING_A1's existence, yet its BLOCKER-1 disposition
(re-issue the manifest, reset n=0) is exactly one of RULING_A1 §7's five listed
preconditions for *overturning* the halt. Worse, on the identical underlying fact — does
the shared `trial_id_prefix` violate A-9 clause 2 — the two rulings reach opposite
conclusions: reviewed ruling says "the deployed manifest **already violates** its own
governing acceptance criterion" (§4, BLOCKER-1); RULING_A1 §3.8 examines the same clause
and finds it "LITERALLY NOT MET — **however, this is BY DESIGN, not a defect**": the
`d0_climate_day`/`terminal_climate_day` boundary is the real, working discriminant and
"the protection itself holds." The brief for this review explicitly requires the ruling be
"correct under both outcomes" of a pending STOP ruling; it is not — it must either (a)
explicitly reconcile with RULING_A1 (state that manifest re-issue is a measurement-scope
action orthogonal to the trading halt, does not itself re-arm anything, and does not
concede or contest A-9 clause 2's compliance status pending A1's own disposition), or (b)
defer BLOCKER-1 until A1 is finalized.
Fix: add a subsection acknowledging RULING_A1, state explicitly that re-issuing v4's
manifest (i) is for tally/measurement purposes only, (ii) does not change `status` or any
trading-enablement gate, and (iii) is not to be read by an implementer as satisfying
RULING_A1 §7's re-arm bar on its own. Cross-link both documents' "Consequences" sections.

**[HIGH] BLOCKER-1 evidence overstates the collision risk by citing only one of two guards.**
File: `docs/evidence/RULING_live_family_tally_scope_2026-09-21.md:83-91` (evidence),
vs `scripts/analysis/family_tally_v2.py:596-622` and `src/breezy/settlement/family_barrier.py:52-96`.
Issue: the ruling's evidence quotes `filter_rows_to_manifest_prefix`
(`family_tally_v2.py:532-564`) — which indeed cannot discriminate by prefix alone — and
infers the tally "cannot discriminate cont from v4 rows landing in the same store." But
`build_family_tally_v2` calls `assert_family_only` immediately after the prefix filter
(`family_tally_v2.py:622`, comment at `:600-601` even says "runs BEFORE... so a v3 row
cannot trip the v2 family barrier either" — misleadingly implying the barrier is skipped,
when in fact it always still runs), and `assert_family_only` independently refuses rows by
`climate_day` against `d0_climate_day`/`terminal_climate_day` (`family_barrier.py:80-91`).
Verified directly: `pm_us_crh_cont.json` declares `terminal_climate_day: "2026-09-19"`;
`pm_us_crh_v4.json` declares `d0_climate_day: "2026-09-20"` — contiguous, non-overlapping.
So a cont-dated row is refused from v4's tally and vice versa **today, with the shared
prefix, at tally time**, by the same barrier the ruling itself quotes for the "fatal
asymmetry" point (`family_barrier.py:66-73`) without noticing that quoted docstring
describes the exact fix that is already in place for this pair. The D-D claim ("simply
enabling a v4 instance would admit every v3 row into v4's n", cited from AUD-05) is not
re-verified against `assert_family_only` in this ruling and may describe a **scorer-time**
risk (`score_live_trials.py`, not read in this ruling) rather than a **tally-time** one —
the ruling conflates the two admission points under one "live data-integrity defect" label.
Fix: soften "already violates ... a live data-integrity defect" to state precisely which
admission point (scorer vs. tally) is actually unguarded, re-verify `score_live_trials.py`'s
store-selection logic before asserting a scorer-level collision, and downgrade the framing
from "active bug" to "defense-in-depth hygiene fix consistent with A-9" if only the scorer
path (not the tally barrier) is actually exposed.

**[MEDIUM] Unresolved citation split for the n-reset authority, left for the reader to notice.**
File: `docs/evidence/RULING_live_family_tally_scope_2026-09-21.md:133-140` (evidence item on
L-34) vs `docs/plans/POST_FORECAST_PHASE_2026-09-20.md:45` ("n reset to 0 **per L-34**") and
`:217-218` (A-9 item 2, "n reset to 0", no L-34 reference). The ruling correctly flags that
L-34's actual text is about trigger-pinning, not n-reset, and picks A-9 item 2 as the
"authoritative" source instead — but the underlying plan itself ties the same requirement
to two different named authorities in two different rows (A1's own row says "per L-34"; the
A-9 elaboration section does not cite L-34 at all). RULING_A1 (the sibling ruling) quotes
the plan's "per L-34" wording verbatim without flagging the mismatch. Neither ruling
proposes fixing the plan text itself.
Fix: add to §6 (consequences) a required text change to
`docs/plans/POST_FORECAST_PHASE_2026-09-20.md` A1 row (`:45`): drop or correct the "per
L-34" citation there to point at A-9 item 2, so the two authorities in the same plan stop
disagreeing about their own citation.

**[LOW] BLOCKER-2's retirement instruction assumes a currently-failing unit can produce
"one final terminal run" without further diagnosis.**
File: `docs/evidence/RULING_live_family_tally_scope_2026-09-21.md:161-166`. Issue: the
ruling's own evidence (`:96-98`) records `pm_us_crh_cont`'s tally service as `Active:
failed`, exit 1, on its last two runs (09-19 ×2, 09-20). BLOCKER-2 requires D-A/D-B's
general fixes land first, then "ONE final on-demand tally run is produced ... to close its
evidentiary record" — reasonable, but the ruling does not name what happens if that run
*still* fails after D-A/D-B (e.g. a cont-specific defect the general fixes don't cover) —
is the timer disabled anyway with the record left incomplete, or does disabling wait
indefinitely? Underspecified, not wrong.
Fix: one sentence — if the post-fix run still fails, disable the timer regardless and
record the residual failure reason in the same evidentiary note, rather than leaving
disablement contingent on an unbounded retry.

## Not defects (checked and hold)

- BLOCKER-3's "plain reading of §10" is corroborated by an independent source the ruling
  does not cite: `docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md:186` restates
  "Strata: pooled (sequential monitor), station (cell_dead), ask-band (cell_dead)" with no
  side field, in the very amendment that made NO rows admissible — this strengthens
  BLOCKER-3's option (a); it should be added as a citation.
- R-4's "owner SP-1 I5" is a live, `REQUIRED`/`KEPT` item (`LIVE_FILL_SCORING_CHAIN_2026-09-05.md:236,311,313`),
  not orphaned — verified.
- `family_manifest.py` (`load_family_manifest`) has no in-place edit/patch path; every
  manifest is loaded whole from a JSON file, so "re-issue" necessarily means writing a new
  JSON file (new or edited `deploy/families/pm_us_crh_v4.json`) — consistent with how both
  rulings treat it. No separate re-registration-vs-edit ambiguity found in the loader itself.

## Unverifiable in this session

- `score_live_trials.py`'s store-selection/write path (does it write one fill into two
  family stores under a shared prefix?) — not read; needed to settle the [HIGH] item above.
- `structural_dead_stop.py:349`'s `manifest_sha256` comparison (R-4/AUD-10) — not
  independently re-read here either; both rulings already flag this as unverified.

Decision: ENDORSE-WITH-REQUIRED-CHANGES
Primary risks: internal contradiction between concurrent PREREG-governance rulings
(BLOCKER-1 vs RULING_A1); overstated urgency/evidence framing on the collision claim.

## Delta review (Revision 2)

**File verified:** `docs/evidence/RULING_live_family_tally_scope_2026-09-21.md`,
sha256 `3b02807498622aeee94de4d7e63a353a9f1eb4651f4a604b4a1c627245d76a5c` — matches.

**Scorer-time gap claim: VERIFIED TRUE, independently re-derived.**
`scripts/analysis/score_live_trials.py:722` — `if climate_day < since_climate_day:
continue` is the only date check in `read_filled_trials_state_db`; exhaustive grep of the
whole file for `terminal_climate_day` returns zero matches (re-run directly, not trusted
from the ruling). `deploy/systemd/score-live-trials-run.sh:77-94,181-187` confirms the
wrapper loops over every `*.json` under `FAMILIES_DIR` and invokes the scorer once per
`(city, manifest)` with `--derived-dir "$STORE_DIR/$FAMILY_ID"` (`:187`) — so a fill dated
on/after 2026-09-20 does satisfy both `pm_us_crh_cont` and `pm_us_crh_v4`'s
`since_climate_day` and would be written into both stores. The claim is real, not
overstated, and correctly distinguishes "refused loudly at tally time" from "not admitted
at scorer time" — this is the fix I asked for.

**All four Revision-1 defects: genuinely fixed, not reworded.**
- CRITICAL (silent conflict with RULING_A1): now an explicit §"Reconciliation" naming the
  halt, stating the scorer guard is orthogonal to re-arm, and requiring a cross-link. Held.
- HIGH (tally-time overclaim): withdrawn explicitly ("Revision 1's framing ... WITHDRAWN as
  stated"), evidence corrected to name `assert_family_only` as the operative guard. Held.
- MEDIUM (L-34 vs A-9 citation split): now a required text-fix line for
  `POST_FORECAST_PHASE_2026-09-20.md:45`. Held.
- LOW (BLOCKER-2 unbounded retry): explicit unconditional-disable sentence added. Held.
No regressions found in BLOCKER-3 or R-4's substance (R-4 ownership change is a disclosed
coordinator decision, checked against source and not contradicted).

**[MEDIUM, new] BLOCKER-2's "one final terminal run" for `pm_us_crh_cont` may already be
un-runnable because of the exact contamination BLOCKER-1 just proved.** If the scorer has
run at least once since `bcb82d6` (2026-09-20) under `pm_us_crh_cont.json` while a
v4-dated (>= 09-20) fill existed, that row would already be sitting in
`$STORE_DIR/pm_us_crh_cont` — and `assert_family_only` refuses the **entire** batch (not a
per-row drop) the moment `pm_us_crh_cont`'s own tally next runs, per
`family_barrier.py:52-96`'s "any of which refuses the ENTIRE batch." The ruling's BLOCKER-2
"final run" instruction does not check for this pre-existing contamination before assuming
a clean terminal run is possible, and its own new BLOCKER-1 evidence is the reason to
suspect it. Not independently verified here (would require reading
`$STORE_DIR/pm_us_crh_cont`'s parquet contents, out of this review's read-only/no-heavy-job
scope) — flagged as a required pre-check, not asserted as fact.
Fix: before BLOCKER-2's final run, the implementer checks whether
`$STORE_DIR/pm_us_crh_cont` already contains any row with `climate_day >= 2026-09-20`; if
so, land the scorer-time guard (BLOCKER-1 disposition) FIRST, or manually except those
already-contaminated rows, before attempting the "final" run — otherwise the final run
raises `FamilyBarrierRefusal` on first attempt and the evidentiary record cannot close as
written.

Decision: ENDORSE-WITH-REQUIRED-CHANGES
Primary risks: none blocking (prior CRITICAL/HIGH resolved); one new MEDIUM sequencing gap
between BLOCKER-1's new finding and BLOCKER-2's "final run" instruction.

## Delta review (Revision 3)

**File verified:** sha256 `c15835331cbc4b48cbc8791ed24b309c913e1d88147804de43e2617b5b9b3795` — matches.

**My Revision-2 [MEDIUM] is genuinely fixed, mechanism re-verified directly (not taken on
trust).** `assert_family_only` refuses the whole batch on the first offending row
(`family_barrier.py:75-96`, no per-row drop), and `family_tally_v2.py` has no existing
in-bounds filtered-read path before `build_family_tally_v2` — confirmed `read_scored_trials`
(`src/breezy/persistence/scored_trial_store.py:118-134`) is the same, already-used, plain
read function the new pre-check reuses; no new I/O surface, no mutation. Both outcomes are
now explicitly ruled: clean → run once, disable; contaminated → rows never touched, one
attempted run whose expected `FamilyBarrierRefusal` plus the pre-check's findings (specific
out-of-bounds `trial_id`/`climate_day`) together become the recorded terminal evidentiary
state, timer disabled either way. This correctly treats "evidence" as the refusal-plus-diagnosis,
never a fabricated verdict, consistent with the ruling's own fail-closed posture elsewhere.

**No regressions:** BLOCKER-1, BLOCKER-3, R-4, and the RULING_A1 reconciliation are
unchanged from Revision 2 (spot-checked); only BLOCKER-2's mechanism and its §6 consequence
line gained the pre-check step, as claimed.

**Decision: ENDORSE — no further required changes.**
