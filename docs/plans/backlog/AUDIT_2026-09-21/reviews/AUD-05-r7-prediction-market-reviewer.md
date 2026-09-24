# AUD-05 — Round 7 (delta, post-ruling) — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-05-live-family-tally-unit.md
sha256: 75d1221ccd86162b5c5aff2569ac6ab7a1c80f47a39685324270bdb65acbf49b
Round: 7 (delta, post-ruling)
Reviewer: prediction-market-reviewer (portfolio accounting / risk)

## Citations verified against source (all exact except one)

- `SENDING_FAMILY_ID_VAR = "BREEZY_SENDING_FAMILY_ID"` (`settings.py:112`) and
  `_validate_sending_family_manifest` (`:373-393`, fail-closed `SettingsError` on unknown/missing/
  `DRAFT_NOT_REGISTERED`) — CONFIRMED exact.
- `Environment=BREEZY_SENDING_FAMILY_ID=pm_us_crh_v4` (`breezy-trade-supervisor.service:115`) —
  CONFIRMED exact, the single source of truth INC-SP1I5 resolves the champion from.
- `manifest_sha256` already emitted by `structural_dead_stop.py` at `:304` (param), `:318` (dict
  key), `:349` (loaded), `:391` (passed) — CONFIRMED exact; the counter JSON genuinely already
  carries the field a scope-verifying consumer needs.
- `score_live_trials.py` has **zero** occurrences of `terminal_climate_day` (grep-confirmed) and
  `since_climate_day = manifest.d0_climate_day` (`:1789`) with the sole bound `if climate_day <
  since_climate_day: continue` (`:722`) — CONFIRMED, so D-G's claim of an unguarded upper bound is
  real, not asserted.
- **One citation error, found and worth fixing.** §6 D-H's "the wrapper exits 1 before removing
  `$CJSON` — the same posture the counter already takes when `structural_dead_stop.py` fails
  (`:118-128`)" cites the wrong file: lines 118-128 of `structural_dead_stop.py` are inside the
  `structural_dead()` verdict function (a different, unrelated fail-closed property — `evaluable`
  on `filled_takes is None`), not wrapper-level `$CJSON` handling. The actual pattern (`rm -f
  "$CJSON"` then attempt-then-`exit 1`) lives at **`deploy/systemd/score-live-trials-run.sh:118-128`**
  — confirmed by reading that exact range. **The plan's own §9 failure-case bullet cites this
  correctly** ("Closed fail-closed: exit 1 with `$CJSON` absent… `score-live-trials-run.sh:118-128`"),
  so this revision is internally inconsistent between §6 and §9 on the same fact.

## Answering the coordinator's specific questions

1. **Champion resolution via `BREEZY_SENDING_FAMILY_ID` instead of the literal — sound and
   fail-closed**, verified against the exact settings-loader mechanism the node itself uses; no
   second literal is introduced, and the design explicitly rejects "whichever manifest looks
   newest."
2. **The counter JSON carrying `manifest_sha256`** is not new scope — verified the field already
   exists in `structural_dead_stop.py`'s output; INC-SP1I5's own obligation is only to prove (by
   test) that it carries the *champion's* sha, which is the correct, minimal claim.
3. **Is "KILL" well-defined for a family that may not send orders?** Yes, and the plan's own
   reasoning holds under scrutiny: `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` §4 explicitly
   rules the halt stops sending only, not the node/tape/KILL clock. "KILL" here means the structural
   absence of fills over a large-enough coverage window — a fact that remains true and meaningful
   whether the absence is caused by no edge or by a deliberate halt; the two causes are different
   policy questions but the same measured fact.
4. **Can a halted family's clock ever produce a verdict that misleads a consumer?** The plan
   explicitly forecloses the most likely misreading — "a halted family's clock is mistaken for a
   re-arm signal" is named as a failure case in §9 and closed by stating the counter is **never** a
   re-arm signal and that `C-KILL`'s consumption is scope verification only, never enablement. I
   looked for a second misreading risk — a HUMAN conflating "structurally KILLed while halted" with
   "this lineage has no edge" (a stronger, unwarranted claim) — and found the same §9 closure
   sufficiently addresses it: KILL's registered meaning (structural absence, not an edge verdict)
   is stated in §6 D-H itself, and AUD-18 (the new edge-discovery item per the A1 ruling) is
   explicitly where any edge question is decided, never this counter. No defect found here.
5. **D-G's scorer-time guard** correctly targets the real unguarded admission point
   (`score_live_trials.py`'s missing upper bound) rather than a manifest edit, verified against
   source above.
6. **No manifest under `deploy/families/` is edited.** §5 gains an explicit exclusion bullet to this
   effect, consistent with the ruling's BLOCKER-1 disposition (no re-issue of the registered v4
   manifest); D-D's task is correctly redirected to D-G's scorer guard rather than a manifest change.

## Regression sweep

- BLOCKER-1/2/3's dispositions in §4/§6/§12 accurately track the ruling's actual text (no re-issue;
  retire-with-pre-check; option (a) unpartitioned admission) — spot-checked against the ruling
  document's §4 RULING section and found faithful, including the ruling's own caveat that the
  pre-check is read-only and never repairs/deletes store rows.
- The BLOCKER-2 pre-check (§7 step 0(h)) correctly reuses `read_scored_trials` (the same function
  `family_tally_v2.py:1288` already calls) rather than introducing a new I/O path, exactly as the
  ruling requires.
- No operator-reserved value is read, restated, defaulted or assigned; no trading-enablement change;
  the plan is explicit that nothing here satisfies any part of `RULING_A1` §7's re-arm bar.

## Defects

1. **MINOR — §6 D-H mis-cites `structural_dead_stop.py:118-128` for a fact that actually lives at
   `score-live-trials-run.sh:118-128`**, and the plan's own §9 cites the correct file for the same
   claim, making this an internal inconsistency as well as a citation error. **Required change:**
   correct §6 D-H's citation to `score-live-trials-run.sh:118-128`, matching §9.

## Per-criterion points (cap in parentheses)

- Fidelity to gap and completeness (20): **19** — every ruled element (BLOCKER-1/2/3, R-4/INC-SP1I5,
  the A1 sibling-ruling bound) is applied faithfully with no scope creep and no silent narrowing.
  −1 for the citation inconsistency.
- Technical correctness and evidence grounding (20): **19** — dozens of citations independently
  re-verified exact (settings.py, the systemd unit, structural_dead_stop.py's existing
  `manifest_sha256` fields, score_live_trials.py's real unguarded bound). −1 for the one mis-cited
  file.
- Implementation specificity and feasibility (15): **15** — INC-SP1I5's resolution mechanism, D-G's
  guard, and the BLOCKER-2 pre-check are all concretely specified with named tests.
- Acceptance criteria and validation quality (20): **20** — AC #15's champion-scoping proof and the
  BLOCKER-2 dual-outcome requirement are both objectively checkable.
- Autonomous operation, failure handling, recovery (15): **15** — the fail-closed champion resolution
  and the halted-clock-is-never-a-re-arm-signal closure are both sound.
- Portfolio objective alignment, scope, dependencies (10): **10** — unaffected; the sibling A1 ruling
  is correctly bounded as limiting what this item can demonstrate (n may stay 0) without expanding
  this item's own scope.

**Total: 98/100**

## Required changes to reach 100

1. Fix the §6 D-H citation as detailed above.

## Blockers

None remaining for this item's own text-fixable scope. BLOCKER-1/2/3 are RULED; the only residual
dependency is `RULING_A1`'s own §7 re-arm bar, which this item explicitly does not approach.
