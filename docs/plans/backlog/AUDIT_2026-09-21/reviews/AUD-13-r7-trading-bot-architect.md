# AUD-13 round-7 delta review — trading-bot-architect

Plan: AUD-13-native-venue-reconciliation-from-durable-records.md
SHA256: 7812b68e16cc2016944ef9b602c5b22225145894b79cf75c465edb10606c7c0a
Round: 7 (delta, FINAL for this cluster)
Reviewer: trading-bot-architect (blind)

## Verified against source

- `_redact_order_id` (`exec/client.py:414-416`), `venue_order_id: str` (`:667`), `ts_event: int`
  (`:675`) — all CONFIRMED, matching the new named-refusal text exactly.
- `test_polymarket_us_fee_schedule_pin.py` module docstring ("CORPUS REFRESH POLICY: ... widen,
  never relax `==`") CONFIRMED at `:15-23` — the plan's "widen, never relax" framing is the
  module's own stated policy, not an invented exception mechanism.
- `test_every_in_scope_theta_site_agrees_with_its_venue_constant` (`:240`) CONFIRMED: it asserts
  `extracted == STUDY_THETA_BY_VENUE` (exact set equality, unrelaxed) over
  `study_theta_sites_from_analysis_scripts()`, plus two separate `== DOCUMENTED_TAKER_FEE_COEFFICIENT`
  checks for the two `src/` config sites. Widening the *expected* frozenset with a new dated member
  does not touch either `==` operator — the plan's "never a relaxation" claim is structurally true
  for the assertion shape itself.

## Defect found (technical/evidence-grounding, this revision's own new material)

**The census cannot see the schedule it is being asked to pin.** `study_theta_sites_from_source`
(`:195-208`) finds module-level bindings and keeps only those whose value parses via
`_literal_decimal` (`:156-171`): a bare `Decimal("...")` call or a numeric constant, optionally
negated — nothing else. A dated fee schedule keyed on `ts_event` (the ruling's own shape,
`{("2026-08-25", Decimal("0.06")), ("2026-09-17", Decimal("0.0695"))}` or equivalent) is a
composite literal — a set/dict of tuples — which `_literal_decimal` returns `None` for and which
`_module_level_bindings` would therefore drop entirely. **Widening the census to `fees.py` does
not, by itself, make the 0.0695 schedule member visible to it**, because the scanner cannot parse
the structure the ruling requires the schedule to hold. §7 step 1d's claim that the census will
show "the dated schedule... declared in `fees.py`" and §8 item 18's claim that it is "green,
showing the dated schedule... declared" both assume a capability this machinery does not have as
written, and the plan states neither (a) that the schedule must instead be encoded as N separate
scalar constants each individually name-matched to `_THETA_NAME`'s pattern (`(?i)(theta|taker_fee_
coefficient)$`, `:128`) — e.g. `_TAKER_FEE_THETA_BEFORE_20260917`/`_TAKER_FEE_THETA_FROM_20260917`
— so each dated value is its own simple `Decimal(...)` binding the existing parser already
handles, nor (b) that `_literal_decimal`/`_module_level_bindings` themselves need extending to
parse a composite structure, which would be a change to the test module the plan does not mention
or scope. Either is a small, closeable gap — but as written, step 1d's RED test and item 18's
acceptance are not buildable against the scanner that exists today.

**Required change:** one sentence in §6 or §7 step 1d stating which of the two: either (recommended,
cheaper, and consistent with the existing single-scalar `MAKER_FEE_COEFFICIENT`/
`DOCUMENTED_TAKER_FEE_COEFFICIENT` pattern) the dated schedule is encoded as separate,
individually-named scalar `Decimal` constants in `fees.py`, each matching `_THETA_NAME` and each
added to `STUDY_THETA_BY_VENUE` as its own dated exception — never a dict/set the scanner cannot
parse — or the scanner itself gains composite-literal support, named as an explicit, scoped change
to `test_polymarket_us_fee_schedule_pin.py`. Without this, the no-fork pin (this revision's own
fix for my round-6 defect) cannot actually verify what it claims to verify.

## Sweep of the other five hunks

- The named refusal (`fee_coefficient_ambiguous` latch/detail/counter, distinct from
  `positions_read_failed`/`record_venue_disagreement`) is internally consistent, uses the same
  redaction and detail-enum discipline as the rest of §6, and the new distinguishability test
  (driving all three refusals in one reconciliation) is the correct falsifiability shape — no
  regression found.
- `polymarket_us_fee` (`fees.py:277`) is confirmed untouched by this revision's own description
  ("not forked and not modified") — consistent with what I verified in round 6.
- The counts-line breakout (`refusals_<cause>=<n>` per latch) is additive and does not change the
  existing `refusals=<n>` total's meaning.
- Acceptance items 17/18 and the eighteen-item total are correctly cross-referenced; no dangling
  reference to the old sixteen-item count remains in the diff.
- §12 and §10 (rollback/blockers) are untouched by this revision, correctly — neither change alters
  scope, deployment, or reversibility.

No other regression found in the six hunks.

## Per-criterion scoring

| Criterion | Cap | Points | Rationale |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | Both round-6 required changes are applied to every section the ruling's design touches; no material left un-incorporated. |
| Technical correctness and evidence grounding | 20 | 17 | Every citation checked against source and correct. Deducted 3: the census-widening claim (this revision's own centerpiece fix for my round-6 defect) rests on a scanning capability (`_literal_decimal`) that does not parse the composite schedule structure the ruling requires — a real, freshly-introduced grounding gap, not a carried one. |
| Implementation specificity and feasibility | 15 | 12 | The named-refusal mechanism is fully literal and buildable as written. Deducted 3: step 1d/item 18 are not buildable against the existing scanner without the encoding decision above, which the plan does not make. |
| Acceptance criteria and validation quality | 20 | 19 | Eighteen items, with 17/18 both falsifiable and correctly scoped. Deducted 1: item 18's "green" claim inherits the step-1d gap and cannot be satisfied as stated until the encoding question is resolved. |
| Autonomous operation, failure handling and recovery | 15 | 15 | The fourth refusal is now named, distinguishable, and alerted exactly like its siblings; fail-closed posture on money is preserved and strengthened by the distinguishability test. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | No operator-reserved value touched; no scope, deployment or rollback change; blockers correctly still none. |
| **Total** | **100** | **93** | |

## Required changes

One: state explicitly how the dated fee schedule is encoded so the existing AST-based theta census
can actually see it — either as separate individually-named scalar `Decimal` constants (matching
`_THETA_NAME`) added to `STUDY_THETA_BY_VENUE`, or by naming an explicit, scoped extension to
`_literal_decimal`/`_module_level_bindings` to parse a composite structure. Without this, §7 step
1d and §8 item 18 describe a test that cannot pass as specified.

## Blockers

None. R-1/R-2 remain RULED and peer-ENDORSED; nothing in this revision reopens either.
