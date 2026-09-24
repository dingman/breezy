# RULING — live family tally scope (BLOCKER-1, BLOCKER-2, BLOCKER-3, R-4)

Status: ENDORSED 2026-09-21 — independent peer review ENDORSE, no required change, on Revision 3 (`docs/evidence/reviews/RULING_tally_scope_review_2026-09-21.md`). Rulings delegated to engineering peers by the operator.

Repo: `/home/jon/breezy`. Author runs blind (no sibling peer output consulted or cited).

## Revision 2 (2026-09-21) — changes made in response to independent review

Independent review: `docs/evidence/reviews/RULING_tally_scope_review_2026-09-21.md`
(verdict ENDORSE-WITH-REQUIRED-CHANGES). Every defect re-verified against source directly
before editing (`src/breezy/settlement/family_barrier.py`, `scripts/analysis/
score_live_trials.py` — the latter genuinely unexamined in Revision 1, per the review).
Also read `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` (PROPOSED,
sibling ruling: `pm_us_crh_v4` HALTED — no SEND — pending a separate re-arm bar) per the
coordinator's hand-down.

- **[CRITICAL], applied:** BLOCKER-1 rewritten. Verified the reviewer's central claim
  directly: `assert_family_only` (`family_barrier.py:52-96`), called unconditionally at
  `family_tally_v2.py:622` (and again, structurally, via the same guard chain at `:602`'s
  prefix filter), already refuses a `pm_us_crh_cont`-dated row from a `pm_us_crh_v4` tally
  and vice versa, via the `d0_climate_day`/`terminal_climate_day` bounds — **at tally
  time**, this collision is not live. Separately verified `scripts/analysis/
  score_live_trials.py` (not read in Revision 1): `since_climate_day = manifest.d0_climate_day`
  is the ONLY temporal bound `main()` passes to `score_live_trials`/
  `read_filled_trials_state_db` (`:1789`, `:1399`, `:722` — `climate_day < since_climate_day`
  is the sole date check); there is no `terminal_climate_day` upper bound anywhere in this
  file (confirmed by exhaustive grep — zero matches). **So the scorer-time risk is real**:
  because both manifests share one `trial_id_prefix`, `score-live-trials-run.sh`'s
  per-(city, manifest) loop (`:180-194`) invokes the scorer once for each of `pm_us_crh_cont`
  and `pm_us_crh_v4`; any fill dated on/after 2026-09-20 satisfies BOTH manifests'
  `since_climate_day` and would be scored and WRITTEN into both
  `$STORE_DIR/pm_us_crh_cont` and `$STORE_DIR/pm_us_crh_v4` today. The tally-time barrier
  then converts that into a loud `FamilyBarrierRefusal` on cont's next tally run (fail
  closed, not silent corruption) — but the underlying double-write, wasted scorer work,
  and a *new* failure mode on cont's tally are real and unguarded. Ruling revised
  accordingly (§4) to be correct under both the "barrier already protects" fact and
  RULING_A1's halt: no manifest re-issue now; a scorer-time guard/test is what AUD-05 must
  add; any FUTURE re-registration (a precondition RULING_A1 §7 governs, this ruling does
  not) uses a new family id, new prefix, n=0.
- **[HIGH], applied:** §3 evidence corrected to include `assert_family_only`'s actual
  tally-time behaviour (previously cited only its docstring's general rationale, not its
  effect on THIS pair) and `score_live_trials.py`'s scorer-time gap, both verified above.
- **[MEDIUM], applied:** §6 gains a required text fix flagging
  `POST_FORECAST_PHASE_2026-09-20.md:45`'s "n reset to 0 per L-34" against `:217-218`'s
  uncited A-9 item 2 — the plan itself disagrees with its own citation; this ruling does
  not silently pick one, it names the fix.
- **[LOW], applied:** BLOCKER-2 gains one sentence — if the post-fix terminal run for
  `pm_us_crh_cont` still fails, the timer is disabled anyway and the residual failure is
  recorded as the terminal evidentiary state, never left enabled-and-failing indefinitely.
- **Not-a-defect items adopted as citations:** `docs/evidence/
  PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md:186` added to BLOCKER-3 (independent
  corroboration, no side field, in the amendment that made NO rows admissible).
- **R-4 ownership — coordinator decision, adopted; no contradicting source evidence
  found.** `SP-1 I5` (`docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md:236,311,313`) is
  confirmed live and REQUIRED/KEPT — re-verified directly, unchanged from Revision 1 — but
  has no scheduled backlog vehicle; `AUD-05` is the backlog vehicle with an open Stage-1
  slot and a scoring/counter surface already in its blast radius (it already touches
  `deploy/systemd/family-tally-v2-run.sh` and the family-manifest/scorer chain). Per the
  coordinator's decision, ownership is exactly one: **SP-1 I5 stays the spec of record;
  AUD-05 gains a named increment that implements it; AUD-10 only consumes the resulting
  champion-scoped counter, never builds it.** I looked for source evidence that would make
  this wrong (a competing scheduled vehicle, an explicit AUD-05 scope exclusion that
  cannot be lifted, or a structural reason the two cannot share a plan) and found none:
  AUD-05's own §5 exclusion of `score-live-trials-run.sh`/`structural_dead_stop.py` is
  this plan's own text, not an external constraint, and is exactly what a "named
  increment" amends.


## Revision 3 (2026-09-21) — delta review, BLOCKER-2 mechanism fix

Independent delta review (appended to `docs/evidence/reviews/RULING_tally_scope_review_2026-09-21.md`):
Revision 2's four prior defects confirmed fixed and the scorer-time gap independently
confirmed real. One new **[MEDIUM]**: BLOCKER-2's "one final terminal run" for
`pm_us_crh_cont` may already be un-runnable if the scorer already wrote a v4-dated row
(`climate_day >= 2026-09-20`) into cont's store before Revision 2's scorer-time guard
exists — `assert_family_only` refuses the WHOLE batch, so the terminal run would raise
`FamilyBarrierRefusal` rather than produce a report.

**Mechanism verified directly, not taken on trust.** `assert_family_only`
(`src/breezy/settlement/family_barrier.py:52-96`) loops over every row and `raise`s on the
FIRST offending one (`:75-96`) — there is no per-row drop path, exactly as its own
docstring says ("any of which refuses the ENTIRE batch"). `build_family_tally_v2`
(`scripts/analysis/family_tally_v2.py:602,622`) calls `filter_rows_to_manifest_prefix`
first (which does **not** drop an out-of-bound row here — both manifests share one
`trial_id_prefix`, so a v4-dated row passes the prefix filter unchanged) and then
`assert_family_only` on the same, still-contaminated `rows` sequence. So if a v4-dated row
already sits in `$STORE_DIR/pm_us_crh_cont`'s parquet files (written by the unguarded
scorer gap Revision 2 identified, before that gap is closed), running `pm_us_crh_cont`'s
terminal tally today raises `FamilyBarrierRefusal` for the entire batch, confirming the
reviewer's finding. **I did not query the live store to determine whether contamination
has actually occurred** — that is precisely the pre-check this revision adds as a required
step, not something to assert from this session.

**Fix applied:** BLOCKER-2 (§4) gains a required pre-check step and a ruled outcome for
both branches — see below. No other section changed.

## 1. Questions ruled, verbatim from the blocked plan(s)

Source: `docs/plans/backlog/AUDIT_2026-09-21/AUD-05-live-family-tally-unit.md` §12
("Assumptions, unresolved questions, blockers") and `docs/core/PROGRESS.md:73`
(rulings queue, row R-4).

- **BLOCKER-1** (AUD-05 §12): `pm_us_crh_v4` is REGISTERED with a `trial_id_prefix`
  identical to `pm_us_crh_cont`'s. "The ruling must state: (a) is v4 re-issued with a new
  prefix (and if so, is `n` reset — A-9 says yes, and `n` is currently 0 so the cost is
  nil), or (b) is prefix-plus-`d0`/`terminal_climate_day` accepted as sufficient
  separation … ?"
- **BLOCKER-2** (AUD-05 §12): "Is `pm_us_crh_cont` retired now that it carries
  `terminal_climate_day: 2026-09-19`? If yes, its timer instance is disabled and its
  failures stop mattering; if no, D-A and D-B must green it too."
- **BLOCKER-3** (AUD-05 §12, §6): "Does admitting NO-side rows into
  `station_strata`/`ask_band_strata` require a PREREG ruling before it lands? … The
  ruling must state whether (a) NO rows are admitted unpartitioned with
  `pi = mean(BE_i)`, (b) the strata stay YES-only and NO rows are excluded from
  `cell_dead` entirely, or (c) some other disposition."
- **R-4** (`docs/core/PROGRESS.md:73`): "v3 §9 is 'unchanged from v2' with no carve-out,
  so the v3 tally MUST receive a v3-scoped count (own `--family-manifest
  pm_us_crh_cont.json`, d0 09-12, never v2's JSON); today no unit runs the v3 tally at
  all" — Blocks: `SP-1 I5`. Also raised at AUD-10 (`docs/plans/backlog/AUDIT_2026-09-21/
  AUD-10-evidence-gated-promotion-proposal.md:392-409,777-842`) as the `C-KILL`
  champion-scope dependency, which is `INERT` until this resolves.

## 2. Options considered

**BLOCKER-1.** (a) new `trial_id_prefix` for v4, `n` reset to 0 [recommended by AUD-05].
(b) keep the shared prefix, add a date-bound admission rule to
`filter_rows_to_manifest_prefix`. "Leave open": not acceptable — the collision is a live
data-integrity defect (two REGISTERED families can silently cross-pollinate `n` on a
sequential test that spends α), and it blocks D-D/D-C, which blocks the only unit that
can measure the live family at all.

**BLOCKER-2.** (yes) retire — disable `breezy-family-tally@pm_us_crh_cont.timer`. (no)
keep tallying it daily alongside v4 forever. "Leave open": not acceptable — AUD-05 AC #2
already requires a decision either way before merge; an undecided BLOCKER-2 leaves a
failing unit either un-fixed or fixed for no operational purpose.

**BLOCKER-3.** (a) admit NO rows unpartitioned, `pi = mean(BE_i)` [AUD-05
recommendation, derived from source]. (b) exclude NO rows from `cell_dead` entirely
(YES-only strata). (c) side-partition the strata (`"|no"` labels) — already considered
and withdrawn inside AUD-05 revision 4 after two independent round-3 reviewers rejected
it as inventing unregistered stratum entities. "Leave open": acceptable only as a
*meantime* behaviour (AUD-05 §6 item 3, `PENDING_STRATA_RULING`), which this ruling
adopts explicitly as the interim state until deployment — see §4.

**R-4.** (i) leave the 14:15Z counter hard-coded to `pm_us_crh_v2.json`. (ii) point it at
whichever family is the current node champion (today `pm_us_crh_v4`). (iii) run it once
per REGISTERED family. "Leave open": not acceptable — `C-KILL` (AUD-10) is `INERT` by
design until a champion-scoped clock exists, and PREREG v3 §9 binds the structural-dead
test to *this* family's own D0/coverage window, not v2's.

## 3. Evidence, each item verified file:line

- `deploy/families/pm_us_crh_v4.json:4` and `deploy/families/pm_us_crh_cont.json:4` —
  both `"trial_id_prefix": "continuous_rung_hold/trial/"`, byte-identical. Verified by
  direct read, 2026-09-21.
- `deploy/families/pm_us_crh_v4.json:5,17` — `d0_climate_day: "2026-09-20"`,
  `taker_fee_coefficient: "0.0695"`.
- `deploy/families/pm_us_crh_cont.json:5,18,19` — `d0_climate_day: "2026-09-12"`,
  `terminal_climate_day: "2026-09-19"`, `taker_fee_coefficient: "0.06"`, `status:
  "REGISTERED"`.
- `docs/plans/POST_FORECAST_PHASE_2026-09-20.md:211-227` (§A-9, "The invariant A1(iii)
  must satisfy to be a NEW FAMILY and not a pin edit") — item 2: **"New `trial_id_prefix`,
  new `d0_climate_day`, n reset to 0, LD-OBF α spent from zero."** This is a *prior,
  already-adopted* governing ruling for exactly this re-registration (v4, at drifted
  θ=0.0695), not a fresh question — the deployed `pm_us_crh_v4.json` as written **violates
  its own governing acceptance criterion**.
- **[Revision 2, corrected]** `src/breezy/settlement/family_barrier.py:52-96`
  (`assert_family_only`), called unconditionally inside `build_family_tally_v2` at
  `scripts/analysis/family_tally_v2.py:622` (after the prefix filter at `:602`, which
  itself never skips the barrier — re-verified by reading both call sites directly) —
  **already discriminates `pm_us_crh_cont` from `pm_us_crh_v4` today, at tally time**,
  via `climate_day` bounds (`family_barrier.py:80-91`): a row dated on/after
  `pm_us_crh_v4.json`'s `d0_climate_day` (`2026-09-20`) fails the lower-bound check
  against `pm_us_crh_cont.json`'s manifest (no `terminal_climate_day` exemption applies
  to v4's own rows), and a row dated on/after `pm_us_crh_cont.json`'s own
  `terminal_climate_day` (`2026-09-19`, exclusive per the inclusive-upper-bound check at
  `:85-91`) fails against it directly. The docstring at `:66-73` — "a SUPERSEDED family
  went on admitting its successor's rows … that silently pools trials priced against a
  different estimand" — describes the FIX already in place for this exact pair, not an
  open defect, as the review correctly found.
- **[Revision 2, added]** `scripts/analysis/score_live_trials.py` (examined this
  revision; not read in Revision 1) — `main()` passes exactly one temporal bound,
  `since_climate_day = manifest.d0_climate_day` (`:1789`), into `score_live_trials`
  (`:1794-1806`) and from there into `read_filled_trials_state_db` (`:1394-1401`), whose
  only date check is `climate_day < since_climate_day` (`:722`, lower bound only).
  Exhaustive grep of the file for `terminal_climate_day` returns zero matches: **no
  upper-bound filter exists at scorer time.** Because `deploy/systemd/
  score-live-trials-run.sh:180-194` (L-38) invokes the scorer once per (city, REGISTERED
  manifest) pair and both `pm_us_crh_cont` and `pm_us_crh_v4` share one
  `family_prefix`, a fill dated on/after 2026-09-20 satisfies BOTH manifests'
  `since_climate_day` and is scored and written into BOTH `$STORE_DIR/pm_us_crh_cont`
  AND `$STORE_DIR/pm_us_crh_v4` — a real, live, unguarded double-write at the point the
  rows are CREATED, even though the tally-time barrier above then refuses (fail-closed,
  loudly — `FamilyBarrierRefusal`) rather than silently mis-scoring once `pm_us_crh_cont`'s
  tally next reads its now-contaminated store. This is the D-D finding AUD-05 §6 already
  states ("simply enabling a v4 instance would admit every v3 row into v4's `n`") — this
  ruling now locates it precisely at the scorer, not the tally.
- `scripts/analysis/family_tally_v2.py:532-564` (`filter_rows_to_manifest_prefix`) —
  separates rows by `trial_id_prefix` alone and cannot itself discriminate cont from v4;
  it is not the operative guard for this pair — `assert_family_only`, which runs
  immediately after it on the same call path, is.
- `git show bcb82d6 --stat` — commit `bcb82d6248c49e459ba09838834ae5c6865fd608`,
  "fix(alerts): tee to log AND webhook; promote the unit to pm_us_crh_v4" (2026-09-20).
  Confirms the live node's champion family is `pm_us_crh_v4`, not `pm_us_crh_cont`, as of
  that commit.
- `systemctl --user status breezy-family-tally@pm_us_crh_cont.service` (read-only,
  2026-09-21) — `Active: failed`, last run 2026-09-20T17:20:51Z,
  `family-tally-v2-run.sh pm_us_crh_cont` exit 1. `systemctl --user list-units | grep
  breezy-trade` shows only `breezy-trade-supervisor.service` running — one node, one
  champion.
- `docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:197-199` (§9,
  "Structural-Dead Test (unchanged from v2)") — "Window `[12:00, 17:00)` LST … ≥15
  covered listed station-days denominator. Separate from D0+165 clock stop." Per-family,
  keyed to that family's own D0/coverage.
- `docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:203-215` (§10, "Frozen
  from v2 (unchanged)") — "Fixed strata: pooled (sequential), station (cell_dead@n≥60 vs
  `mean(BE_i)`), ask-band (cell_dead)." No side field, no side partition anywhere in the
  registered text; the comparison is `k/n` vs `mean(BE_i)`, which `StratumRow`'s own
  docstring (`src/breezy/settlement/current_rung_hold_v2.py:99-105`, cited and re-verified
  inside AUD-05 §6) makes side-symmetric by construction
  (`E[held_i] = BE_i` on both YES and NO legs).
- **[Revision 2, added]** `docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md:186`
  — independently restates, in the very amendment that made NO rows admissible, "Strata:
  pooled (sequential monitor), station (cell_dead), ask-band (cell_dead)" with no side
  field. Corroborates BLOCKER-3 option (a) from a second registered source, not only
  PREREG v3 §10.
- `deploy/systemd/score-live-trials-run.sh:40-47` — `FAMILY_MANIFEST="$REPO/deploy/
  families/pm_us_crh_v2.json"`, feeding `structural_dead_stop.py --family-manifest` at
  `:123-125` (the 14:15Z "covered-listed-station-days" counter). Comment at `:40-46`:
  "the structural-dead-stop pin stays v2-scoped only, tracked separately (R-4, SP-1 I5)."
- `docs/core/PROGRESS.md:60,63-64,73` — R-4 explicitly blocks `SP-1 I5`; the dependency
  chain line states "SP-1 I5 after R-4."
- `docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md:236-313` — `I5` ("end-to-end contract
  test") is the SP-1 increment `PROGRESS.md:60` names as needing "a v3 SCORER pass and a
  v3-scoped count, not only a tally unit" — the pre-existing plan item that owns this
  fix.
- `docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md:
  137-140,360,369-466,777-842` — `C-KILL` is designed to compare the counter JSON's
  `manifest_sha256` against the **champion manifest's own** `manifest_sha256`
  (`structural_dead_stop.py:349`, per AUD-10's citation), and is `INERT` today because the
  deployed counter is v2-scoped. AUD-10 explicitly excludes standing up this clock from
  its own scope (`:137-140`, "Named as a dependency … not taken here") and names
  `PROGRESS R-4 / AUD-05` only as *where the dependency is tracked*, not as an
  implementer — AUD-05 itself (§4, §5) also explicitly excludes this file. **Not
  independently re-run**: I did not execute `structural_dead_stop.py` or inspect its
  `:349` line directly in this session; I rely on AUD-05's and AUD-10's citations of it,
  both independently re-verified by prior review rounds per AUD-05 §13.
- `docs/core/LESSONS.md:1290-1303` (L-34) — **partial mismatch with the brief's gloss.**
  L-34's actual text is "The trial's TRIGGER is pinned; a re-look is a second snapshot" —
  it governs *when* a trial is observed, not directly "a re-registered family resets n to
  0." The n-reset requirement is stated authoritatively in
  `POST_FORECAST_PHASE_2026-09-20.md` §A-9 item 2, not in L-34 verbatim. Both apply the
  same class-C doctrine (a change that could select a different observation, or a
  different estimand, is class C), so the RULING_BRIEF's citation is directionally right
  but not a literal quote — flagged per the brief's "verify every citation" instruction.

## 4. RULING

**BLOCKER-1 — REVISED per independent review, [CRITICAL]. Ruled correct under BOTH
RULING_A1 outcomes (v4 halted from SEND, or a future v4 continuing):** **no re-issue of
the currently REGISTERED `pm_us_crh_v4` manifest now.** §3's Revision-2 evidence settles
this two ways at once:

1. **At tally time the barrier already suffices.** `assert_family_only`
   (`family_barrier.py:52-96`) discriminates `pm_us_crh_cont` from `pm_us_crh_v4` today by
   `d0_climate_day`/`terminal_climate_day` bounds, exactly as its own docstring describes.
   This is the fact `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` §3.8 independently
   verified and reached the same way ("clause 2 … LITERALLY NOT MET — however, this is BY
   DESIGN, not a defect … the protection itself holds"). **Revision 1's framing — "the
   deployed manifest already violates its own governing acceptance criterion," treated as
   settled fact — is WITHDRAWN as stated.** A-9 item 2's checklist prose ("new
   `trial_id_prefix`") is imprecise against the mechanism it protects, exactly as RULING_A1
   found; this ruling adopts that finding rather than re-litigating it.
2. **At scorer time there is a real, unguarded gap** — `score_live_trials.py` has no
   `terminal_climate_day` upper bound, so a live fill can be double-scored into both
   family stores under the shared prefix before the tally-time barrier ever runs. This is
   a genuine defect, but it is a **scorer hygiene gap**, not a manifest-identity violation,
   and fixing it does not require touching a REGISTERED manifest.

**Ruled disposition:** (i) `pm_us_crh_v4.json` is **not** re-issued or edited by this
ruling or by AUD-05 — re-issuing a REGISTERED manifest while a sibling ruling (RULING_A1)
is actively deciding that family's trading disposition would itself be a class-C action
taken outside that ruling's own process, which this ruling declines to do. (ii) AUD-05
gains a required test/guard, scoped to the scorer, not the manifest: `score_live_trials.py`
(or its systemd wrapper) must refuse — or provably cannot admit — a fill dated on/after a
REGISTERED family's own `terminal_climate_day` into that family's store, pinning the
barrier's protection at the point rows are CREATED rather than relying solely on the
tally-time refusal to catch it after the fact. A RED test reproducing today's gap (a
fixture fill dated 2026-09-21, scored under `pm_us_crh_cont.json`, currently admitted;
must be refused or excluded after the fix) is the acceptance evidence. (iii) **Any FUTURE
re-registration** of this lineage (a precondition governed by `RULING_A1`'s own §7, not by
this ruling) **MUST** take a new family id, a new `trial_id_prefix`, and `n` reset to 0,
per A-9 item 2 read as a **prospective** requirement for the *next* re-registration, not a
retroactive defect finding against the current one — this is the one point on which
Revision 1's conclusion survives unchanged, just relocated from "fix now" to "bind later."

**Reconciliation with `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` (both PROPOSED,
same day, same repo):** RULING_A1 rules `pm_us_crh_v4` HALTED from sending orders and
states re-arm is not pre-authorized by that document alone. Nothing in this ruling changes
that. The scorer-time fix above is a measurement-pipeline action: it affects which rows a
tally can see, never whether an order may be sent, and it touches no `status` field, no
halt latch, and no trading-enablement gate. An implementer must not read "AUD-05's scorer
guard landed" as satisfying any part of RULING_A1 §7's re-arm bar — the two are orthogonal
and neither this ruling nor AUD-05's resulting code closes any RULING_A1 precondition.
Cross-link: this ruling's §6 and RULING_A1's §6 should each reference the other's
consequences going forward.

**BLOCKER-2 — yes, `pm_us_crh_cont` is retired as of 2026-09-20 (commit `bcb82d6`).**
Its `terminal_climate_day: 2026-09-19` structurally forecloses any new row
(`assert_family_only`'s upper bound, `family_barrier.py:85-91`), and the live node's
champion moved to `pm_us_crh_v4` on that commit. Disposition: its
`breezy-family-tally@pm_us_crh_cont.timer` instance is disabled (per AC #2's "deliberately
disabled … with the reason recorded"). Its manifest `status` field stays `"REGISTERED"`
— it is not un-registered history, and downstream evidence consumers (AUD-02) may still
need its terminal sequential-test outcome. Before disabling the timer, D-A/D-B's general
fixes (which are family-agnostic — they fix `build_stratum_v2` and
`count_filled_takes`, not v4-specific code) are applied. **[Revision 2, LOW fix applied]**
If the final run still fails after those fixes — e.g. a `pm_us_crh_cont`-specific defect
the general D-A/D-B fixes do not cover — the timer is **disabled anyway, unconditionally**,
and the residual failure (exception class, file:line, and the fact that it is the terminal
state) is recorded in the same evidentiary note used to close the family's record.
Disablement is never made contingent on an eventual clean run; a failing enabled unit is
strictly worse than a disabled one with a documented terminal failure.

**[Revision 3, required pre-check added and both outcomes ruled.]** Before that final run
is attempted at all, AUD-05 gains a required, read-only pre-check step: load
`$STORE_DIR/pm_us_crh_cont`'s rows via `read_scored_trials` (`persistence/
scored_trial_store.py:118-134`, already the exact function `family_tally_v2.py:1288`
uses — no new I/O path) and inspect, in memory only, whether any row's `climate_day` falls
outside `pm_us_crh_cont.json`'s own `d0_climate_day`/`terminal_climate_day` bounds (i.e.
`climate_day >= pm_us_crh_v4.json`'s `d0_climate_day`, the exact condition the scorer-time
gap in BLOCKER-1 could have produced). This step performs no write of any kind. Ruled,
both branches:

- **Clean store (no out-of-bounds rows found):** run the terminal tally once as originally
  ruled, then disable the timer.
- **Contaminated store (an out-of-bounds row is found):** the store rows are **never
  deleted or rewritten — evidence is never mutated**, full stop. `family_tally_v2.py`'s
  CLI (`main()`, `:1212-1325`) has **no existing flag or code path that filters `rows` to
  an in-bounds subset before calling `build_family_tally_v2`** — verified by reading
  `main()` in full: it reads the whole store unconditionally at `:1288` and passes the
  unfiltered result straight through. Building such a filtered-view feature now would be
  new scope, not a surgical fix, so it is **not** added. Per this ruling's conservative
  default, the terminal run is attempted once as-is; when it raises
  `FamilyBarrierRefusal` (expected, per the mechanism above), that refusal — not a
  fabricated report — **is** the terminal evidentiary state: the pre-check's findings (the
  specific out-of-bounds `trial_id`(s)/`climate_day`(s)) and the refusal itself are both
  recorded verbatim in the same evidentiary note used to close the family's record,
  documenting that `pm_us_crh_cont`'s tally ends REFUSED-BY-BARRIER, with the reason on
  record, rather than SURVIVE/KILL/CONTINUE. **Either way, the timer is disabled** — a
  contaminated store is not a reason to keep a daily unit running any more than a clean
  one is.

**BLOCKER-3 — option (a), unpartitioned admission with `pi = mean(BE_i)`, confirmed
rather than merely recommended.** PREREG v3 §10 ("Frozen from v2, unchanged") registers
the `station`/`ask-band` `cell_dead` strata as testing `n≥60` vs `mean(BE_i)` with no side
field, no side partition, and no per-side formula anywhere in the registered text
(`docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:210`). `StratumRow`'s own
field semantics make that comparison side-symmetric by construction
(`E[held_i] = BE_i` on both legs). Option (a) is therefore not inventing a new rule; it is
the plain reading of the already-registered §9/§10 text applied to a row type (NO) the
amendment (`PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md`) already made admissible elsewhere.
Option (c) (side-partitioning) is affirmatively rejected — `docs/specs/
PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md:210` freezes the strata shape, and a
partition invents cells the registration never described, multiplying independent
`cell_dead` KILL triggers (AUD-05 §6, already argued and independently reached by two
round-3 reviewers). Option (b) (exclude NO rows from `cell_dead` entirely) is rejected as
the more permissive, not the more conservative, choice: it would let a genuinely dead
NO-heavy cell keep contributing looks by construction, the opposite of fail-closed on
statistical validity.

**Interim state before this ruling is implemented:** AUD-05's meantime behaviour (§6 item
3) — on a NO-bearing corpus, withhold `station_strata`/`ask_band_strata` and publish
`verdict = "PENDING_STRATA_RULING"` rather than a fabricated verdict — is **retained as
the deployed behaviour until the code implementing option (a) above lands and passes its
own RED→GREEN tests**. This ruling settles the *disposition*; it does not itself change
`current_rung_hold_v2.py` or `family_tally_v2.py`.

**R-4 — REVISED per coordinator decision on ownership.** The 14:15Z counter must count
for the current node CHAMPION family, not a fixed literal. Today that is `pm_us_crh_v4`
(post `bcb82d6`, unaffected by BLOCKER-1's disposition above since no manifest re-issue
occurs now). The counter is **not** re-pointed to `pm_us_crh_cont` (BLOCKER-2 retires it)
nor left on `pm_us_crh_v2` (that family's own D0 is 2026-09-05, unrelated to the champion's
coverage window).

**Ownership — exactly one, per the coordinator's decision, adopted after checking for
contradicting source evidence and finding none:** `SP-1 I5`
(`docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md:236,311,313`) **stays the spec of
record** — it is confirmed live, `REQUIRED`/`KEPT`, and already states the right shape
("a v3 SCORER pass and a v3-scoped count, not only a tally unit"), generalised here to
"champion-scoped, not merely v3-scoped." It has no scheduled backlog vehicle, however:
neither `PROGRESS.md` nor any file under `docs/plans/backlog/` schedules SP-1 I5's
implementation as a tracked increment. **`AUD-05` gains a named increment that
IMPLEMENTS SP-1 I5** — AUD-05 already has this file in its blast radius by adjacency
(`deploy/systemd/family-tally-v2-run.sh`, the family-manifest/scorer chain, Stage 1
sequencing) even though its current §5 text excludes it; that exclusion is this plan's own
prior scoping choice, not an external constraint, and is exactly what a new named
increment amends. **`AUD-10` only consumes** the resulting champion-scoped counter
artifact through `C-KILL`'s existing binding design — it does not build the counter
itself, consistent with its own §5 exclusion ("Named as a dependency … not taken here").
I looked for evidence that would make this assignment wrong (a second scheduled vehicle
already claiming this work, or a structural reason SP-1 I5 cannot be implemented from
within AUD-05) and found none — AUD-05 and SP-1 I5 share no conflicting file ownership,
and AUD-05's Stage 1 is explicitly "in parallel with AUD-04, sharing no code" with room
for an additional, independent increment.

## 5. Rationale, including the strongest argument against each ruling

**BLOCKER-1 [Revision 2].** Strongest counter: leaving the shared prefix alone forever is
complacent — A-9 item 2 says "new `trial_id_prefix`," and reading it as satisfied by the
date bounds alone lets checklist prose drift permanently out of sync with the mechanism it
was meant to specify. **It partially wins, and the ruling is written to concede exactly
that much**: the scorer-time gap (§3, §4) is real and IS fixed now, as a guard/test, not
deferred. What loses is the stronger claim that the REGISTERED manifest itself must be
re-issued today — RULING_A1 §3.8 independently verified the barrier holds, this ruling
independently re-verified the same code and agrees, and re-issuing a REGISTERED family's
identity while a sibling ruling is actively adjudicating that family's trading status
would be the more reckless action of the two, not the more conservative one. A-9 item 2
is preserved in full force as the bar for the NEXT re-registration, which is where L-34's
class-C doctrine actually bites (a NEW estimand, at a NEW θ, needs a NEW identity) — it is
not a mandate to retroactively edit an identity that is already discriminating correctly.

**BLOCKER-2.** Strongest counter: disabling a REGISTERED family's timer while its
`status` still reads `"REGISTERED"` could look like an undocumented halt, inviting a
future implementer to "helpfully" re-enable it. **It loses** because the ruling requires
the reason to be recorded (AC #2) and the timer file's own comment/README should say so —
that is a documentation obligation on the implementer, not a reason to keep a structurally
dead family's tally burning CPU and alert budget daily. **[Revision 3]** A second counter,
raised by delta review: attempting the terminal run at all, once contamination is
suspected, wastes effort on a run known to raise. **It loses too** — the pre-check is
read-only and cheap, and attempting the run once (rather than skipping it on the
pre-check's say-so alone) is what turns "we suspect contamination" into a citable,
recorded `FamilyBarrierRefusal` artefact instead of an inference.

**BLOCKER-3.** Strongest counter (this is the one two round-3 reviewers actually raised,
per AUD-05 §13 round 3 disposition #1): `cell_dead` is a live KILL disjunct in
`look_verdict`, so admitting NO rows under an *unregistered* convention could silently
change when evidence collection stops, in either direction. **It loses on the merits
already established in AUD-05, re-confirmed here from the registered text itself**: §10's
`mean(BE_i)` comparison is not merely "derived" by AUD-05, it is the literal registered
test, and the docstring math (`E[held_i]=BE_i` both sides) is arithmetic, not policy — the
alternative that would actually change the registered comparison is `pi := mean(q_i)`,
which AUD-05 already rejects with evidence (inverted for NO rows).

**R-4.** Strongest counter: "champion" is not itself a term PREREG defines, so pinning
the counter to "whichever family the node currently runs" could be read as inventing a new
concept rather than reading one off the manifest. **It loses** because AUD-10 already
built and reviewed `C-KILL`'s champion-scope binding (`manifest_sha256` equality against
the currently-armed family's manifest) across four review rounds without dispute — this
ruling adopts an existing, reviewed design rather than inventing one.

## 6. Consequences for affected backlog plans (text changes needed; not made here)

- **`docs/plans/backlog/AUDIT_2026-09-21/AUD-05-live-family-tally-unit.md`**: §12
  BLOCKER-1 moves from "not decided here" to "RULED — no manifest re-issue; a
  scorer-time `terminal_climate_day` guard/test is required instead (`docs/evidence/
  RULING_live_family_tally_scope_2026-09-21.md`)"; §4/§6 D-D's framing ("v4 gets its own
  identity … requires a ruling") is corrected to state the identity question is RULED
  closed for now, and D-D's task becomes the scorer guard, not a manifest edit.
  BLOCKER-2 and BLOCKER-3 each move from "not decided here" to "RULED — Ruled: (a)" as in
  Revision 1. §6/§7/§8's meantime-behaviour language ("until it is ruled") is updated to
  "until the ruled disposition is implemented." **New:** AUD-05 gains a named Stage-1
  increment implementing `SP-1 I5` (champion-scoped 14:15Z counter), per the R-4 ownership
  ruling below — sequenced independently of D-A/D-B/D-D, sharing no code with them.
  **[Revision 3] BLOCKER-2's step 0 (evidence pack, §7 of AUD-05) gains a required
  sub-step:** a read-only pre-check of `$STORE_DIR/pm_us_crh_cont` for rows with
  `climate_day` on/after `pm_us_crh_v4.json`'s `d0_climate_day`, using the existing
  `read_scored_trials` call already in `family_tally_v2.py:1288` — no new store-access
  path — run and its findings recorded BEFORE the terminal tally is attempted; AC #2 is
  restated to require both the pre-check's findings and the terminal run's outcome
  (SURVIVE/KILL/CONTINUE, or REFUSED-BY-BARRIER with the offending `trial_id`(s)) in the
  evidentiary note, and to state the timer is disabled in either case.
- **`docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md`**:
  every citation of "`C-KILL` `INERT`, owner PROGRESS R-4 / AUD-05" (§5, §6b.3, §11,
  §12, the C17(g)/C8 fixture descriptions) is updated to name **AUD-05's new increment**
  (implementing SP-1 I5) as the owner, with SP-1 I5 remaining cited as the spec of record
  — `C-KILL` stays `INERT` until that increment ships, but the ambiguity about *whose*
  backlog vehicle carries it is resolved.
- **`docs/core/PROGRESS.md`**: rulings queue row R-4 gets a `Ruled` marker pointing at
  this artefact, with the disposition restated as "champion-scoped (today `pm_us_crh_v4`
  post `bcb82d6`), never a fixed literal; spec SP-1 I5, implemented via a new AUD-05
  increment." Row is NOT removed — the increment still has to ship. **The A1 row
  (`docs/plans/POST_FORECAST_PHASE_2026-09-20.md:45`)** — see MEDIUM fix below — is a
  separate, required text change surfaced by this review, not this ruling's own row.
- **`docs/plans/POST_FORECAST_PHASE_2026-09-20.md`, A1 row (`:45`) [MEDIUM, Revision 2]:**
  the row's own text says "n reset to 0 **per L-34**" while §A-9 item 2 (`:217-218`),
  the elaboration of the same requirement two sections later in the SAME document, cites
  no L-34 at all. This is the plan disagreeing with its own citation, not merely a brief
  mis-cite (which is a separate, already-flagged issue in this ruling's own §3 evidence
  and in `RULING_A1` §7 item 4). Required text change: correct `:45`'s "per L-34" to "per
  A-9 item 2 below" (or drop the citation from `:45` entirely and let `:217-227` be the
  sole authority), so the two rows in one document stop citing different sources for one
  requirement.
- **`docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md`** (SP-1 I5's own plan): I5's
  acceptance text is generalised from "a v3 SCORER pass and a v3-scoped count" to "a
  champion-scoped SCORER pass and count, re-derived from whichever family's manifest is
  currently armed, never a second hard-coded literal" — unchanged from Revision 1. A
  header note is added: "Implemented via AUD-05 [increment name TBD by that plan's own
  numbering]; this document remains the spec of record."
- **`docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`** (sibling ruling,
  cross-link only, not edited by this ruling): its §6 consequences list should gain a
  pointer to this ruling's BLOCKER-1 disposition, so a reader of either document reaches
  the other — the two govern the same family's manifest from different angles
  (trading-enablement vs. measurement-scope) and neither supersedes the other.

## 7. What would overturn this ruling; what remains operator-only

**Overturning evidence:**
- BLOCKER-1: (i) the "no re-issue now" half is overturned if `assert_family_only` is ever
  found NOT to actually run on the live tally path (it does, verified `:622`), or if a
  concrete cont/v4 cross-contamination is observed in a produced tally despite the barrier
  (would indicate a bug in the barrier itself, not evidence for re-issuing the manifest
  as the fix). (ii) the "scorer guard required" half is overturned only if
  `score_live_trials.py` is shown to already bound reads by `terminal_climate_day`
  somewhere this review did not find — re-search `score_live_trials.py` and
  `read_filled_trials_state_db` for any date-upper-bound check before accepting that.
  (iii) the "future re-registration needs a new identity" half is overturned only by a new
  ruling explicitly superseding A-9 item 2.
- BLOCKER-2: a decision to resume trading `pm_us_crh_cont` specifically (rather than v4)
  would overturn the retirement — no evidence today suggests this; the node has run v4
  since `bcb82d6`.
- BLOCKER-3: a future PREREG amendment that explicitly registers a side-partitioned
  stratum shape (superseding §10's frozen list) would overturn option (a). Short of an
  amendment, nothing in this repo's current registered text supports (b) or (c).
- R-4: if the live family topology becomes genuinely multi-champion (more than one
  family armed simultaneously for real, not just tallied), "count for the champion" stops
  being well-defined and needs its own ruling — not the case today
  (`phase1_family_permits`'s exactly-one-sending-family invariant, cited at AUD-10 §5:148,
  is unchanged and untouched by this ruling).

**Operator-only (unaffected by this ruling, and this ruling assigns no value to
either):** the two budget caps (max daily budget, max per-position) and live-trading
enablement. Nothing here proposes, implies, or requires a change to either. All four
rulings above are PREREG-semantics/measurement-scope questions the operator has
delegated to the strategy-lead ruling process, exactly the class §16 of PREREG v3
("Registered 2026-09-11 UTC per operator delegation … strategy-lead ruling via
`docs/evidence/` decision artifacts") already describes.
