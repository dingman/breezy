# AUD-10 — Review record (Round 4, FINAL)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: 3d1c9b58a6bab2816df5f028bdb69367a43abcd3bb259b011a504a1ff4e85755 (filled by coordinator at save time)
- Round: 4 · Reviewer: architect (code-architect lens)
- Total: 90/100 · Readiness: NOT READY (one material defect that stops the item reaching its goal
  state, author-resolvable)

## Round-3 dispositions, verified against the plan body AND against source

| R3 defect | Claimed | Verified? |
|---|---|---|
| **10-4** — `C-KILL` bound only to a producing script: no path, keys, reader or staleness rule, while its absence refuses the whole run; `C-ESTIMATOR`/`C-N` likewise named by producer | ACCEPTED IN FULL | **MOSTLY FIXED — and the artefact was genuinely found, not assumed.** Verified at source: the counter JSON path `${BREEZY_LIVE_TALLY_OUTPUT_DIR:-~/.local/share/breezy/derived}/covered_listed_station_days_<UTC-day>.json` (`score-live-trials-run.sh:55,115`); `rm -f` then `structural_dead_stop.py --output`, **exit 1 on counter failure** (`:122-129`; the plan cites `:118-127`, a few lines off — trivial); exactly six keys `count, depth_root_present, fetch_end, fetch_start, manifest_sha256, stations` (`_write_output_json:297-330`), contract pinned at `:288-293`; atomic `mkstemp`+`os.replace` (`:322-327`). `count_filled_takes(source_path, *, family_prefix, since_climate_day) -> int \| None` is at `fill_time_count.py:101-118` and its docstring says **"Returns `None` — fail closed, never zero"** exactly as quoted; `structural_dead` (`structural_dead_stop.py:111-132`) sets `evaluable = filled_takes is not None` and `fired=False` when not evaluable — so the plan's "that `False` means *unknown*, not *clear*; refuse on `evaluable is False`" is **correct and is the right call**, and C17(f) tests it. `KILL_CLOCK_MAX_AGE_SECONDS = 26*3600` with stale⇒refuse identical to absent, four enumerated `refusal_reason`s, and C17's six arms are all real. `C-ESTIMATOR`/`C-N` now name the store **directory** (`score-live-trials-run.sh:54` confirmed: `STORE_DIR=${BREEZY_SCORED_TRIALS_DIR:-…/derived/scored_trials}`) and its sidecars, read through `load_realized_draws(store_dir)` — artefacts, not producers, as required. **Residual, and it is material: the provenance rule binds the clock to the WRONG manifest — see 10-5.** |
| **c1** — "four documented refusals" under-counts by three | ACCEPTED | **FIXED the better way.** All seven shapes are enumerated with line refs, and **the base-class catch is stated as the contract** (`StationDayAdmissionRefusal(ValueError)` at `:184` parenting both private refusals), so an eighth future shape is covered. C15 is restated over all seven **and** pins `StationDayAdmissionRefusal.__bases__`, which is more than I asked for and is the right guard. §9's line is corrected from four to seven; §7 step 10 requires seven fixtures. |
| **c2** — the §10 boot-log observable is unpinned | ACCEPTED | **FIXED.** New **C18** asserts the composed station set **and** the manifest's `family_id` against captured log text, hosted in the C3 golden test that already composes the live v4 manifest — the cheapest true home, as I suggested. §7 step 4 and §10 both point at it. |

10a is unchanged and remains correct: the six `SUPPORTED_STATIONS` sites with per-site dispositions,
the guard-domain narrowing at `:319`, the non-`app` caller enumeration, and C4's attainable literal
grep. No new defect in 10a.

## Defects found in revision 4

**10-5 (MATERIAL, NEW — `C-KILL`'s provenance rule binds the clock to the champion manifest, but the
deployed counter JSON is produced under a DIFFERENT, hard-coded family. As written the generator
refuses every run forever, and its re-derived verdict mixes two families' scopes).**
§6b.3's binding says: *"refuse unless `fetch_start == manifest.d0_climate_day` and
`set(stations) ⊆ set(manifest.stations)` — mirroring the drift guards the deployed wrappers already
apply to this same file (`score-live-trials-run.sh:152-160` …)"*, where `manifest` is the champion read
by `C-REVISION` (`deploy/families/<sending_family_id>.json`). Read at source, both halves fail:
1. **The counter is v2-scoped by a hard-coded literal.** The wrapper invokes the counter with
   `--family-manifest "$FAMILY_MANIFEST"` where `FAMILY_MANIFEST="$REPO/deploy/families/pm_us_crh_v2.json"`
   (`score-live-trials-run.sh:47`), and the counter takes `fetch_start = manifest.d0_climate_day`,
   `cities = manifest.stations`, `manifest_sha256 = manifest.manifest_sha256` from **that** manifest
   (`structural_dead_stop.py:336-349`). `pm_us_crh_v2.json:5` is `"d0_climate_day": "2026-09-05"`;
   the armed family the plan itself names, `pm_us_crh_v4.json:5`, is `"2026-09-20"`. So
   `fetch_start != manifest.d0_climate_day` **always**, and `C-KILL` refuses the whole run with
   `KILL_CLOCK_PROVENANCE_MISMATCH` on every night — which **contradicts C8's stated expected
   outcome** (`NO_PROPOSAL` citing `C-N`/`C-VALIDITY`, `C-PAIRED` `INERT`) and makes C17(a)'s
   happy-path arm unconstructable from the deployed artefact. The item does not reach its goal state.
2. **The cited "mirror" does not say what the plan claims.** `score-live-trials-run.sh:157` compares
   `FETCH_START` to `V1_D0_LITERAL="2026-09-05"` (`:62`) — the **PREREG v1 D0 literal**, not any
   champion manifest's `d0_climate_day`. That is a citation that does not support the rule drawn from
   it. The wrapper's own comment at `:44-46` is explicit that "the structural-dead-stop pin stays
   v2-scoped only, tracked separately (R-4, SP-1 I5)".
3. **The re-derivation therefore crosses families.** The plan computes
   `structural_dead(covered_listed_station_days=<v2-scoped count over v2 stations since 2026-09-05>,
   filled_takes=count_filled_takes(family_prefix=manifest.trial_id_prefix,
   since_climate_day=manifest.d0_climate_day))` — a **v4-scoped** fill count
   (`"continuous_rung_hold/trial/"`, since 2026-09-20). Two different families' scopes in one verdict
   is precisely the "statistic attached to the wrong family" error (`bss-headline-is-the-wrong-family`)
   that §11 names as this item's whole justification.
REQUIRED, one of: (a) bind `C-KILL`'s provenance to the **manifest that actually produced the file**
(read `manifest_sha256`/`fetch_start` and require they match `deploy/families/pm_us_crh_v2.json`), and
state plainly that the KILL clock available today is **v2-scoped**, so the re-derived verdict is about
that family and may not be read as the champion's — with C17(a) rewritten accordingly; or (b) have the
generator invoke `structural_dead_stop.py --family-manifest <champion> --output <own path>` itself, and
state the compute cost and its slice; or (c) record `C-KILL` as refusing with a named, owned blocker
(`NO_CHAMPION_SCOPED_KILL_CLOCK`) until the deployed wrapper counts the armed family — mirroring the
`C-PAIRED` `INERT` treatment. In every case, correct the `:152-160` "mirroring" claim and add a
`C-KILL` arm asserting the counter's manifest identity.

**10-6 (MATERIAL, NEW — the emission site contradicts AUD-09's revision-4 wrapper contract).**
§6b.4 emits from "the AUD-09b wrapper (`replay-daily-run.sh`)", §10 calls it "one extra line in the
AUD-09b wrapper", §7 step 13 greens "the script + wrapper line". AUD-09 revision 4 (its 09-4 fix)
specifies that wrapper as carrying **exactly two** `"$PY"` invocations and asserts it in **B18**. A
third invocation fails B18. The two plans, which are otherwise carefully kept character-identical on
shared decisions (layers, H2, §6c, C10==B10), disagree here.
REQUIRED: state the coordinated resolution in both files — AUD-10 §6b.4 cites AUD-09 **B18** and names
`promotion_proposal.py` as the sanctioned third invocation; AUD-09 B18 becomes a property assertion
over a named set rather than a count. (Add the criterion to C9/C12's neighbourhood so the coupling is
tested from this side too.)

**c1 (MINOR, NEW) — two line ranges in the new binding drift.** `score-live-trials-run.sh:118-127` is
really `:115-129` (the `CJSON` assignment, `rm -f` and the invocation); `structural_dead(...)` is
`:111-132`, not `:110-130`. Neither changes a conclusion. REQUIRED: correct both.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 18 | 10a closes REG-1 across all six sites and closes the zero-strategy boot path it would have opened; 10b binds every predicate to a real artefact. −2: on today's tree the generator's steady state is a **refusal**, not the C8-expected `NO_PROPOSAL` (10-5), so 10b does not reach its own goal state as written. G-07's "promotion is a unit-file commit" half is a human gate by design — not deducted. |
| Technical correctness and evidence grounding | 20 | 17 | The `C-KILL` artefact, its six keys, the atomic write, `count_filled_takes`'s `None`-fail-closed docstring, `structural_dead`'s `evaluable` semantics, the store directory and the seven refusal shapes all verified exact. −3: the provenance rule's cited mirror (`:152-160`) compares to a hard-coded v1 literal, not a manifest, and the v2/v4 scope mismatch is verified at `score-live-trials-run.sh:47` + `pm_us_crh_v2.json:5` vs `pm_us_crh_v4.json:5` (10-5); plus c1's drift. |
| Implementation specificity and feasibility | 15 | 13 | 10a is specified to the per-site edit, the call reorder and the mutation evidence. The `C-KILL` reader, keys, max-age and the `evaluable`-before-`structural_dead` rule are now decided to the line. −2: the implementer must still resolve which manifest scopes the clock, and the answer changes what the predicate means (10-5). |
| Acceptance criteria and validation quality | 20 | 18 | C1–C18 objective; C17's six arms are exactly the right arms; C15 covers all seven refusals via the base catch and pins `__bases__`; C14's INERT rule, C12's content-hash property, C16's `params_match` and C18's log pin are all real. −2: C17(a) and C8 are mutually unreachable against the deployed artefact (10-5), and nothing tests the wrapper-invocation coupling (10-6). |
| Autonomous operation, failure handling, recovery | 15 | 14 | A stale/absent/not-evaluable clock now refuses instead of reading permissively — the round-3 safety defect is genuinely closed. Three hard refusals, per-predicate absent-input behaviour, content-hash idempotency, read-only posture, clean rollback. −1: under 10-5 the nightly steady state is a refusal that looks identical to a real provenance drift, so the one signal that matters is saturated; independent alerting remains knowingly not taken. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Zero-ROI honesty; the correctness benefit named as correctness, not return; both strategy-lead blockers retained verbatim; the KILL-verdict dependency named with an owner and AUD-05 cited by id only; abandonment criterion scoped to 10b; arming, the two reserved caps and the NO-SEND path untouched, and no code here reads or proposes a cap value. No defect found. |
| **Total** | **100** | **90** | |

## Required changes to reach 100
1. Resolve `C-KILL`'s family scope — bind provenance to the v2 manifest that actually writes the file
   and say the clock is v2-scoped, or compute a champion-scoped counter, or declare the predicate
   blocked — and correct the `:152-160` "mirroring" claim, with a C17 arm on the counter's manifest
   identity (10-5).
2. State the coordinated wrapper-invocation resolution in both AUD-10 §6b.4/§10 and AUD-09 B18 (10-6).
3. Correct the two line ranges (c1).

## Blockers (recorded separately; not scored)
- **Strategy lead — 10b cannot be judged *correct* without a ruling.** R5-7/R5-8
  (`FORECAST_EDGE_PEER_REVIEW_2026-09-18.md:121-152`) were written for `pm_us_crh_fc_v1` under a
  programme ruled terminally CLOSED; whether they transfer to a `continuous_rung_hold` family, and
  what champion/challenger means when the champion's admissible n = 0, is a ruling. The
  `SOURCE=FORECAST_FAMILY_R5` tagging keeps the build executable and the transfer auditable.
- **Strategy lead** — whether a `MECHANISM_ONLY` replay result may feed any criterion. Default taken
  (no, via `C-VALIDITY`) is conservative and surfaced, not decided.
- **Deferred change with a named owner** — `C-PAIRED` stays `INERT` until the driver gains
  `--family-manifest`. Correctly excluded from both plans and recorded identically.
- **Dependency with an owner** — no deployed unit writes a machine-readable KILL *verdict*; the
  re-derivation is the stated interim. Correctly named rather than papered over. (10-5 is a defect
  *within* that interim, not a restatement of this blocker.)
- **Operator** — arming, live enablement, the two reserved caps. Named, untouched.

_Saved verbatim by the coordinator: the `architect` reviewer has no file-write tool._
