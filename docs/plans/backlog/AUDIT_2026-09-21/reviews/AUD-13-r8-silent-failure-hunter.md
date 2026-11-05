# AUD-13 — Round 8 review (silent-failure-hunter, re-confirmation after architect's fix)

**Plan file:** AUD-13-native-venue-reconciliation-from-durable-records.md
**SHA256:** 7cc2d01e0e0dee1fe4778dcf72175af49e6c5fc2854fb94b71c6b7c2bd6b827e (verified via `sha256sum`)
**Round:** 8 (delta, four hunks, +78/-17)
**Reviewer:** silent-failure-hunter (independent, blind)

## Verification against source

| Claim | Status |
|---|---|
| `_THETA_NAME = re.compile(r"(?i)(theta\|taker_fee_coefficient)$")` — end-anchored | CONFIRMED exact, `:128` |
| `_literal_decimal` (`:156-172`) handles only `Decimal("...")` calls, bare int/float constants, and unary-negated forms; falls through to `return None` for anything else (tuple/dict/set are not among the `isinstance` branches) | CONFIRMED — read the full function body |
| `_module_level_bindings` (`:175-188`) collects only `ast.Assign`/`ast.AnnAssign` targets; does not resolve an `ast.Name` value (an alias) through `_literal_decimal`, which has no `ast.Name` branch | CONFIRMED |
| `study_theta_sites_from_analysis_scripts` (`:212-220`) globs `scripts/analysis/*.py` only — cannot reach `src/` | CONFIRMED — round 7's "widen that census" framing was imprecise; round 8 correctly pivots to calling `study_theta_sites_from_source` directly with a new, separate `src/`-scoped expected set, leaving `STUDY_THETA_BY_VENUE`/its test untouched, which is the technically correct fix |
| `MAKER_FEE_COEFFICIENT` (`fees.py:77`) does not match the end-anchored `taker_fee_coefficient$`/`theta$` pattern | CONFIRMED by direct string comparison — "MAKER_FEE_COEFFICIENT" and "TAKER_FEE_COEFFICIENT" are the same length and differ at the first character, so no suffix of the former equals the latter; the maker rebate stays invisible to the taker census as claimed |
| `test_every_in_scope_theta_site_agrees_with_its_venue_constant` (`:240-252`) pins `crh == DOCUMENTED_TAKER_FEE_COEFFICIENT` / `ladder == DOCUMENTED_TAKER_FEE_COEFFICIENT` at `0.06` | CONFIRMED, unchanged and unedited by this plan revision (it is a planning document; the acceptance claim that this test stays green and byte-unedited is a forward, verifiable criterion, not a current-state claim) |

## Attack: can `_fee_coefficient_as_of` silently return the wrong era or a default?

No. The plan states the three-way split with exact, non-overlapping comparison operators: `ts_event < 2026-09-17T00:00:00Z ⇒ 0.06`; `ts_event >= 2026-09-17T17:00:00Z ⇒ 0.0695`; everything in between (the closed-open `[00:00Z,17:00Z)` window) or before the earliest pinned date or in any future unpinned gap returns `None` — restated unchanged in this round ("returns `None` inside the AMBIGUOUS window and every unpinned gap, exactly as above"). The strict-`<`/`>=` pairing leaves no boundary instant unclassified or double-classified, so no off-by-one can produce a silent wrong-era value. The caller-side contract this round did not touch — a legacy record REFUSES (latch/reason `fee_coefficient_ambiguous`, WARN `detail="FEE_COEFFICIENT_AMBIGUOUS"`, "never defaulted to either coefficient") on a `None` result — remains stated immediately above the new Encoding sub-bullet, unweakened by it; this round only changes how the two scalar values are *declared*, not how a `None` result is *consumed*.

## Sweep of all four hunks

No regression, no relaxed pin, no new silent-failure path. The change is a pure encoding-mechanics correction (composite table → two named scalars + boundary constants) driven by a real constraint in the reused AST parser that this revision correctly identified and verified from source (`_literal_decimal` cannot see a dict/tuple; `_THETA_NAME` is end-anchored so a dated-suffix name would silently miss). `polymarket_us_fee` (`fees.py:277`) remains explicitly unmodified; the pre-drift branch correctly reuses the existing public `DOCUMENTED_TAKER_FEE_COEFFICIENT` rather than duplicating it under a second name (verified: an alias would be invisible to the census anyway, so duplicating would be the only way to make it visible, and duplication is explicitly forbidden as a second source of truth).

## Per-criterion points

| Criterion | Cap | Points |
|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 |
| Technical correctness and evidence grounding | 20 | 20 |
| Implementation specificity and feasibility | 15 | 15 |
| Acceptance criteria and validation quality | 20 | 20 |
| Autonomous operation, failure handling, recovery | 15 | 15 |
| Portfolio objective alignment, scope, dependencies | 10 | 10 |
| **Total** | **100** | **100** |

## Required changes

None. No defect found; the architect's round-7 defect is closed correctly and precisely, with two of its own suggested details (dated-suffix naming, "widen the existing test") corrected against source rather than copied uncritically.

## Blockers

None. Unchanged from round 7 — R-1/R-2 are RULED and peer-ENDORSED.
