# AUD-13 round-8 delta review — trading-bot-architect

Plan: AUD-13-native-venue-reconciliation-from-durable-records.md
SHA256: 7cc2d01e0e0dee1fe4778dcf72175af49e6c5fc2854fb94b71c6b7c2bd6b827e
Round: 8 (delta, FINAL for this cluster)
Reviewer: trading-bot-architect (blind)

## Verified against source

- `_THETA_NAME = re.compile(r"(?i)(theta|taker_fee_coefficient)$")` (`test_polymarket_us_fee_schedule_pin.py:128`) CONFIRMED end-anchored. `_POST_DRIFT_TAKER_FEE_COEFFICIENT` ends in `taker_fee_coefficient` → matches. `_FEE_DRIFT_AMBIGUOUS_START_NS`/`..._END_NS` end in `_NS` → do not match. Both claims correct.
- `study_theta_sites_from_source(source, *, module_stem)` (`:195-208`) is a standalone function (parses, filters by `_THETA_NAME`, extracts via `_literal_decimal`) with **no** dependency on `ANALYSIS_DIR` — callable directly on `fees.py`/`exec/client.py` text exactly as the revision claims.
- `study_theta_sites_from_analysis_scripts` (`:212-220`) globs `ANALYSIS_DIR = REPO_ROOT / "scripts" / "analysis"` (`:72`) only — confirmed it cannot reach `src/`, so the revision's choice to call the lower-level scanner directly (never widening `STUDY_THETA_BY_VENUE`) is the only correct route, not a stylistic preference.
- `DOCUMENTED_TAKER_FEE_COEFFICIENT = Decimal("0.06")` at `fees.py:86` CONFIRMED a plain module-level `Assign` with a bare `Decimal(...)` call — exactly the shape `_literal_decimal` parses, and its name ends in `TAKER_FEE_COEFFICIENT` → already census-visible. Reusing it for the pre-drift branch (rather than declaring a second `0.06` literal) is both correct and the cheaper option.
- `STUDY_THETA_BY_VENUE` (`:86-123`) already carries a precedent entry — `hourly_ask_relative_edge`/`TAKER_FEE_COEFFICIENT`/`0.0695` — with the identical "widen the expected set, never relax `==`" comment discipline the revision cites for its own new member. `test_every_in_scope_theta_site_agrees_with_its_venue_constant` (`:240`) asserts exact-set equality only against `study_theta_sites_from_analysis_scripts()` output plus two `src/`-imported config checks — `fees.py`/`exec/client.py` are outside its scope entirely, so the revision's claim that this test is **untouched** and its `==` **unrelaxed** is correct by construction, not merely by omission.
- `MAKER_FEE_COEFFICIENT` (`fees.py:77`) does not end in the theta pattern — confirmed it stays invisible to any taker-scoped census, consistent with the revision's closing claim.

## Defects

None found, MATERIAL or MINOR. This closes my round-7 defect precisely: the RED test in step 1d
now names a real function, a real call signature, the real 4-tuple shape, and two concrete
`frozenset` expected values, and I independently confirmed both the positive claim (the new
`fees.py` member IS visible to `study_theta_sites_from_source`) and the negative claim (the
pre-existing pin's `==` is neither touched nor weakened, because it scans a disjoint file set).
The two corrections the revision makes to my own round-7 sketch (end-anchored name matching
ruling out dated-suffix names; `study_theta_sites_from_analysis_scripts`'s scripts-only glob
ruling out widening `STUDY_THETA_BY_VENUE`) are both verified true and are improvements on what I
proposed, not workarounds. No new fork risk, no duplicate `0.06` literal, no parser change to the
test module.

## Sweep of the four hunks

- §6 Encoding block: internally consistent with the rest of the ruled-design section; correctly
  states `_fee_coefficient_as_of` is a function (not a scalar), so its name is irrelevant to the
  census regardless of the `_THETA_NAME` pattern.
- §7 step 1d: fully rebuilt against the real API; the "RED today because `fees.py` declares only
  the first member" framing is falsifiable and correct given `_POST_DRIFT_TAKER_FEE_COEFFICIENT`
  does not exist yet at HEAD.
- §8 item 18: the "unedited in the diff" claim for the pre-existing test is itself a checkable
  acceptance artifact (a `git diff` on that one function), not an assertion left to trust.
- Round-8 history note: accurately summarizes the round-7 defect and its fix, including both
  corrections to my own suggested naming, without overstating what changed.

## Per-criterion scoring

| Criterion | Cap | Points | Rationale |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | Applies the round-7 required change fully, to every section it touches. |
| Technical correctness and evidence grounding | 20 | 20 | Every citation re-verified from source this session, independent of the plan's own account; both the positive (new member visible) and negative (existing pin untouched) claims hold. |
| Implementation specificity and feasibility | 15 | 15 | The RED test is now literal — function, arguments, both expected frozensets, and the falsifiable "RED today" reasoning. |
| Acceptance criteria and validation quality | 20 | 20 | Item 18 is concrete and checkable, including the negative (unedited pre-existing test) as its own evidence of non-relaxation. |
| Autonomous operation, failure handling and recovery | 15 | 15 | Unaffected by this hunk set; unchanged from round 7's clean scoring here. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | No operator-reserved value touched; no scope, deployment or rollback change. |
| **Total** | **100** | **100** | |

## Required changes

None.

## Blockers

None. R-1/R-2 remain RULED and peer-ENDORSED; nothing in this revision reopens either.
