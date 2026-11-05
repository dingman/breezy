# AUD-05 review — round 7 (delta, FINAL) — mle-reviewer (statistical validation / measurement engineering lens)

Plan: AUD-05-live-family-tally-unit.md
sha256: 75d1221ccd86162b5c5aff2569ac6ab7a1c80f47a39685324270bdb65acbf49b
Round: 7 (delta review of the ruling application: `RULING_live_family_tally_scope_2026-09-21.md`
Revision 3, ENDORSED, for BLOCKER-1/2/3 and R-4)

## Citations independently re-verified against source — all exact, no fabrication found

Across this large (+402/−44) revision I re-checked every load-bearing citation directly, not from the
plan's or the ruling's account:

- `assert_family_only` (`src/breezy/settlement/family_barrier.py:52-96`): d0 lower-bound check, and
  the **inclusive** `terminal_climate_day` upper-bound check (`row.climate_day > terminal`) — CONFIRMED
  exact, including the "SUPERSEDED family went on admitting its successor's rows" docstring language.
- `filter_rows_to_manifest_prefix` call at `family_tally_v2.py:602` and `assert_family_only(...)` at
  `:622` — CONFIRMED exact.
- `score_live_trials.py`: `if climate_day < since_climate_day:` at `:722`, `def main(...)` at `:1748`,
  `since_climate_day = manifest.d0_climate_day` at `:1789` — CONFIRMED exact; independently grepped the
  whole file for `terminal_climate_day` and got **zero matches**, matching the plan's and ruling's claim
  precisely.
- `score-live-trials-run.sh`: the literal `FAMILY_MANIFEST=".../pm_us_crh_v2.json"` at `:47` with its
  "R-4, SP-1 I5" deferral comment at `:40-46`, the per-`(city, manifest)` scorer loop writing to
  `--derived-dir "$STORE_DIR/$FAMILY_ID"` — CONFIRMED exact.
- `breezy-trade-supervisor.service:115`: `Environment=BREEZY_SENDING_FAMILY_ID=pm_us_crh_v4` —
  CONFIRMED exact. `settings.py`: `SENDING_FAMILY_ID_VAR` at `:112`,
  `_validate_sending_family_manifest` def at `:373` — CONFIRMED, matches `:373-393`.
- `structural_dead_stop.py`: `manifest_sha256` present at `:304,318,349,391` — CONFIRMED. The
  fail-closed wrapper posture (`rm -f "$CJSON"` before invoking, `exit 1` before removing the file on
  failure) — CONFIRMED at the cited lines.
- `read_scored_trials` def at `persistence/scored_trial_store.py:118`, used at
  `family_tally_v2.py:1288` — CONFIRMED, the plan's "same function, no new I/O path" claim holds.

## Coordinator's specific checks

**Is the BLOCKER-3 statistic specified correctly for mixed-side rows under the LD-OBF/Wilson boundary
and `cell_dead` gate?** Yes, and this round strengthens rather than merely restates the derivation
verified in prior rounds: the ruling independently corroborates `pi = mean(BE_i)` (side-symmetric by
construction, `E[held_i] = BE_i` on both legs) against the REGISTERED text itself — PREREG v3 §10
("Frozen from v2... no side field") and the NO-side amendment's own §7 restatement ("Strata: pooled...
station (cell_dead), ask-band (cell_dead)") — rather than resting on a derivation alone. `StratumV2`
still gains no field, `build_stratum_v2`'s body (`:424-428`) stays byte-unchanged, and `cell_dead`'s
gating mechanics (`any_cell_dead` → `look_verdict`/`terminal_look`, independently re-verified in
earlier rounds of this batch) are untouched — the ruling changes *authority*, not *arithmetic*.

**Is the interim `PENDING_STRATA_RULING` retirement coherent?** Yes. The plan requires the sentinel and
its withholding branch be **removed in the same change** that lands BLOCKER-3's option (a) — not a
follow-up — which is the correct sequencing: leaving the interim withholding path alive alongside the
now-ruled strata computation would create an ambiguous state where a NO-bearing corpus could take
either branch depending on deploy order. The strict `xfail` on
`test_a_mixed_station_stratum_renders_the_side_mix_label` converting to a plain passing test in the
same change is the right mechanism — that marker existed specifically to force this transition, not to
be carried indefinitely.

**Is the anti-partition regression floor intact?** Yes — `test_no_stratum_label_carries_a_side_suffix`
is explicitly kept GREEN through the transition and is referenced at four separate points in the plan
body (§7 step 1, step 9, §8, §9), including an explicit note that "partitioning is rejected by the
ruling too," so the regression floor's continued relevance is stated, not merely assumed to survive.

**Does D-G's RED-test list cover boundary days and open-ended families?** Yes, and specifically:
`test_the_terminal_day_bound_is_inclusive_on_both_edges` (a row exactly on `terminal_climate_day` KEPT,
a row exactly on `d0_climate_day` KEPT, mirroring `family_barrier.py`'s inclusive bounds) and
`test_an_open_family_with_no_terminal_day_is_unbounded_above` (`terminal_climate_day: None` preserves
today's behaviour) are both present alongside the core RED/non-regression pair. This is the correct
test set for a symmetric-bound extension — it exercises both edges and the unbounded-above case
explicitly, not just the interior.

**Does BLOCKER-2's read-only pre-check never mutate evidence?** Yes, stated and enforced multiple
times: the new §5 exclusion "No store row is ever deleted or rewritten," step 0(h)'s explicit "This
step writes nothing and repairs nothing," and the ruling's own "evidence is never mutated, full stop"
— all consistent. `read_scored_trials` is a pure read (confirmed by its signature and existing use at
`:1288`), so there is no new write path introduced by the pre-check.

## Regression sweep

Checked that D-D's removal (superseded by D-G) doesn't leave a dangling reference anywhere in §4/§6/§7;
checked the AC renumbering (AC #12 becomes interim-only, new AC #16 replaces it on BLOCKER-3 landing —
no collision with the existing 1-15 range); checked that D-H/INC-SP1I5 is stated to share no code with
D-A/D-B/D-G and is independently sequenced, consistent with its file footprint
(`score-live-trials-run.sh`, `structural_dead_stop.py`'s inputs) not overlapping D-A/D-B/D-G's
(`current_rung_hold_v2.py`, `fill_time_count.py`, `family_tally_v2.py`, `score_live_trials.py`). No
regression found.

## Per-criterion points (cap in parentheses)

- Fidelity to the gap and completeness (20): **20** — all three blockers and R-4 are applied
  completely, with every ruled consequence (no manifest re-issue, scorer guard, BLOCKER-2's two-branch
  pre-check, BLOCKER-3's option (a) with sentinel retirement, champion-scoped counter) present in the
  plan body.
- Technical correctness and evidence grounding (20): **20** — every citation independently re-verified
  exact across a large, complex diff; the BLOCKER-3 statistic is now doubly grounded (derivation plus
  registered-text corroboration).
- Implementation specificity and feasibility (15): **15** — D-G's date-bound extension, the
  champion-resolution mechanism (single source of truth via the running unit's environment, fail-closed
  on absence/mismatch), and the pre-check's read-only scope are all concretely specified.
- Acceptance criteria and validation quality (20): **20** — D-G's tests cover both boundary edges and
  the open-ended case; the anti-partition floor and the sentinel-retirement sequencing are both
  explicitly tested, not merely narrated.
- Autonomous operation, failure handling, recovery (15): **15** — unaffected by this revision beyond
  the new D-G/D-H mechanisms, which are themselves fail-closed (refuse on absent/mismatched champion
  data, never silently reuse a stale counter).
- Portfolio objective alignment, scope, dependencies (10): **10** — unaffected; the RULING_A1 sibling
  cross-reference correctly clarifies that a halted `pm_us_crh_v4` still needs its tally (n may
  legitimately stay 0), without conflating measurement scope with trading enablement.

**Total: 100/100**

## Remaining defects and required changes

None found this round.

## Blockers

None requiring further ruling for this item's own scope. BLOCKER-1/2/3 are RULED (peer-ENDORSED,
`RULING_live_family_tally_scope_2026-09-21.md` Revision 3); R-4 is RULED with AUD-05 named as the
implementing vehicle for `SP-1 I5`. Any *future* re-registration of the `pm_us_crh_cont`/`pm_us_crh_v4`
lineage remains governed prospectively by `POST_FORECAST_PHASE_2026-09-20.md` §A-9 item 2 and by
`RULING_A1`'s own re-arm bar (§7) — neither is this item's to resolve, and nothing in this revision
approaches either.
