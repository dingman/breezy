# AUD-10 — Review record (Round 5, delta on the in-place-edited final revision)

- Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-10-evidence-gated-promotion-proposal.md
- Plan file sha256: dceb37d75d733ed556fd1d8e6bc3e9d332739006235b3e4713228962f9a5cd55
- Round: 5 · Reviewer: trading-bot-architect (promotion-gate/risk-architecture lens)
- Total: 100/100 · Readiness: READY

## Correction to my round-4 verdict

My round-4 review scored this plan 100/100 and missed **10-5**, the most safety-critical defect this
lens should have caught: the `C-KILL` provenance rule bound the clock to the *champion* manifest, but
the deployed counter JSON is produced under a hard-coded, different family
(`score-live-trials-run.sh:47`, `pm_us_crh_v2.json`, d0 2026-09-05, vs. the champion `pm_us_crh_v4.json`,
d0 2026-09-20). As written, the generator would have refused every run forever, contradicting the
plan's own C8, and the re-derived verdict would have mixed two families' scopes — exactly the
"statistic attached to the wrong family" error this item exists to prevent. I also missed **10-6**
(= AUD-09's 09-5, the wrapper-invocation-count contradiction). The architect found both and the
coordinator verified 10-5 in source. I re-derived both fixes myself this round.

## 10-5 fix verified against source (independent re-derivation)

- `score-live-trials-run.sh:47` hard-codes `FAMILY_MANIFEST="$REPO/deploy/families/pm_us_crh_v2.json"`,
  passed at `:125` (`--family-manifest "$FAMILY_MANIFEST"`) — confirmed by reading `:40-47,123-126`.
- `structural_dead_stop.py:347-349` takes `fetch_start`, `cities` **and** `manifest_sha256` from
  whichever manifest `--family-manifest` names — confirmed by reading `:335-349`
  (`fetch_start = dt.date.fromisoformat(manifest.d0_climate_day)`; `manifest_sha256 =
  manifest.manifest_sha256`).
- `pm_us_crh_v2.json:5` is `"d0_climate_day": "2026-09-05"`; `pm_us_crh_v4.json:5` is
  `"d0_climate_day": "2026-09-20"` — confirmed by grepping both files directly.
- The wrapper's own comment at `:40-46` states the pin "stays v2-scoped only, tracked separately
  (R-4, SP-1 I5)" — confirmed verbatim.
- The plan's withdrawn citation (`:152-160` as a "mirror" of a champion-manifest provenance check) is
  correctly withdrawn: I read `:152,157` myself and confirmed the comparison is against
  `V1_D0_LITERAL="2026-09-05"` (defined at `:62`) — the PREREG v1 D0 literal, not any manifest field.
- The fix: a **champion-scope rule**, evaluated first, comparing the counter file's `manifest_sha256`
  against the champion manifest's own (`family_manifest.py:185,220` — I confirmed `manifest_sha256:
  str` is a struct field and is computed as `hashlib.sha256(raw).hexdigest()` over the manifest
  file's raw bytes in `load_family_manifest`). Unequal ⇒ `C-KILL = INERT` with
  `inert_reason="NO_CHAMPION_SCOPED_KILL_CLOCK"`, never `true`/`false`, mirroring the `C-PAIRED`
  treatment already in this plan, and barred from `PROPOSAL` by the existing, already-generalised C14.
  This makes the deployed steady state (`INERT`, not a refusal) reachable, and C8/C17(a) are restated
  against it — I checked C8's new text names both `C-PAIRED` and `C-KILL` as `INERT` in the expected
  steady state, and C17 gains a seventh arm (g) asserting the manifest-identity check fires **before**
  staleness/provenance/depth checks, which is the correct order (a wrong-family file's age says
  nothing about the champion).
- The two rejected alternatives (admit the v2-scoped verdict as the champion's; have the generator
  compute its own champion-scoped counter inside AUD-09b's 3-4GB-capped cgroup) are both argued with
  reasons I find sound: the first is the wrong-family error itself and a permission rather than a
  bar; the second stands up a second KILL clock the round-3 binding already refused and is an
  unbounded catalog scan inside a memory envelope sized for a single-day replay.
- The dependency (a deployed wrapper counting the armed family) is named with an owner, citing
  **PROGRESS R-4** — I confirmed `docs/core/PROGRESS.md:73` states exactly the v3-scoped-count
  requirement the plan cites — and AUD-05 by id only, never assuming its content.

## 10-6 (= AUD-09 09-5) fix verified against source

§6b.4 now cites AUD-09's B18 by name and states `promotion_proposal.py` as the sanctioned third
invocation of the wrapper; §10's deploy line matches. I cross-checked AUD-09's revision-5 text (its
own B18) and confirmed the property is stated identically in both files, and that AUD-10 adds **C19**
testing the coupling from its own side (script-path set, lock, ordering). Both plans are
character-identical on this decision.

## c1 (line-range drift) verified against source

`score-live-trials-run.sh:118-127` corrected to `:115-129`; `structural_dead_stop.py:110-130`
corrected to `:111-132`; `_write_output_json`'s range corrected to `:297-330`. I re-read the actual
line numbers myself: `CJSON=` is at line 115, `rm -f "$CJSON"` at 122, the invocation at 123-126, the
`say`/`exit 1` block at 127-128, `fi` at 129 — matches the corrected `:115-129` exactly.
`structural_dead()`'s `def` is at 111, its closing `)` at 132 — matches `:111-132` exactly.

## Full re-scan for anything else of the kind

Re-read §6b.3's full `C-KILL` binding table and the champion-scope rule in context, plus C8, C17,
and C19. Found no further family-scope mismatch, no further wrapper-coupling gap, no further citation
drift. The `combine_station_day` seven-refusal-shape fix (round-3 c1) and the C18 boot-log pin
(round-3 c2) remain correct and unchanged.

## Defects

None found in this revision.

## Per-criterion points

| Criterion | Max | Score | Reason |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | 10a closes REG-1 across all six sites; 10b's steady state is now reachable against the deployed artefacts (`INERT`, not an unconditional refusal), and the family-scope mismatch that would have made the item non-functional as designed is closed. |
| Technical correctness and evidence grounding | 20 | 20 | Every citation I independently re-derived this round is exact, including the previously-missed v2/v4 scope mismatch and the withdrawn false "mirror" citation. |
| Implementation specificity and feasibility | 15 | 15 | The champion-scope rule is fully decided (comparison, evaluation order, literal verdict, `inert_reason`); the wrapper-invocation contract is a property that survives AUD-10 landing. |
| Acceptance criteria and validation quality | 20 | 20 | C17's seventh arm makes the manifest-identity check and its evaluation order a test; C8 is reachable against deployment for the first time; C19 tests the cross-plan coupling from this side. |
| Autonomous operation, failure handling, recovery | 15 | 15 | The most safety-critical predicate in this cluster (`C-KILL`) no longer refuses every run unconditionally nor silently mixes two families' scopes; it correctly reports INERT and bars PROPOSAL. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Unchanged; the new KILL-scope dependency is named with an owner citing PROGRESS R-4 and AUD-05 by id only, not absorbed as if closed. |
| **Total** | **100** | **100** | |

## Required changes to reach 100

None.

## Blockers (recorded, not scored)

- **Strategy lead — 10b cannot be judged *correct* without a ruling:** whether R5-7/R5-8, written for
  the closed forecast programme, transfer to a `continuous_rung_hold` family. No plan change resolves
  this.
- **Strategy lead:** whether a `MECHANISM_ONLY` replay result may feed any criterion (default: no).
- **Deferred change with a named owner:** `C-PAIRED` stays `INERT` until the driver gains
  `--family-manifest`.
- **Dependency with an owner:** the deployed KILL clock is v2-scoped; `C-KILL` stays `INERT` until a
  wrapper counts the armed family — named with PROGRESS R-4 and AUD-05 cited by id only.
- **Operator:** arming, live enablement, the two reserved caps. Untouched.
