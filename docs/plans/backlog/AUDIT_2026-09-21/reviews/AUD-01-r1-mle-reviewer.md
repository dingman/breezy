# AUD-01 — Round 1 review (mle-reviewer, ML/production-engineering lens)

Plan: AUD-01-no-side-calibration-safety-gate-and-station-stall-diagnosis.md
sha256: 17a956c71f84ef96c8a37e2dd0576e066612459fdb1f366dcf92fa250f982427
Round: 1
Reviewer: mle-reviewer (independent, blind)

## Claims verified against source (codegraph_explore, projectPath=/home/jon/breezy)

- `decision.py:326-372` `evaluate_decision` gate order (fee → staleness →
  `spans` ambiguity → `_is_legal_cell` → dispatch) — CONFIRMED verbatim.
- `Refuse("observation_ambiguous")` at `running_max.spans(...)` check,
  `Refuse("illegal_cell")` at `_is_legal_cell` check — CONFIRMED (both are
  the literal `reason` strings that land in `REFUSAL_REASONS` and in the
  offer-tape `reason` field).
- `RunningMax.spans` (`weather_common/running_extreme.py:172-202`) and
  `value_at` (`:265-305`, `lower_f`/`exact_f` computed `:286-297`) —
  CONFIRMED: fails closed on any endpoint outside a listed rung; `exact_f`
  only set on a METAR row. Matches the plan's train/serve-skew framing.
- `_is_legal_cell` (`decision.py:291-302`) docstring — CONFIRMED verbatim
  quote ("NEVER legal... L-22: unforgeable, not offered").
- `_evaluate_no_side` (`decision.py:425-449`): bid/bid_size executability
  check at `:436-437`, `P_HOLD_UPPER.get(key)` at `:440` — CONFIRMED exact,
  gate-placement citation is precise to the line.
- `P_HOLD_UPPER` dict literal starts at `archive_table.py:287` — CONFIRMED
  exact.
- `build_hold_cases` (`mb_current_rung_edge_study.py:309-342`) filters only
  on `is_complete_day` — CONFIRMED; does not call `RunningMax.spans` or any
  gate-pass predicate. This is the train/serve population-mismatch claim
  and it is correct: the archive table is fit on a population the live path
  never restricts to (gate-pass), so a naive "recalibrate on what we
  actually see" is a collider, as the plan (citing the domain reviewer)
  states.
- `RefusalWatch._conditions` (`refusals.py:220-235`) iterates
  `self._counter.counts` (not a fixed/closed reason set) — CONFIRMED, so
  the plan's claim that a new reason needs "no new plumbing" is correct
  (and the plan itself correctly hedges this as unverified pending
  implementer check, §7 step 4).
- `STRUCTURAL_HALT_REASONS` (`halt_detector.py:138-154`) = `{fee_schedule_
  mismatch, shorts_disabled, instrument_unresolved, settlement_halt,
  no_side_first_order_pending}` — CONFIRMED; `no_side_calibration_unsafe`
  correctly would not belong there per the plan's own reasoning (§6.5).
- WP-B0/WP-R1 commit citations (`f97c26f`, `6aa9d92`, `e83fc5c`) —
  CONFIRMED present in `git log`.

## Claims REFUTED / not supported by source

- **§6.3 and §9 ("Failure case")**: the plan asserts the safety flag's
  arming path is "an explicit config change accompanying a future ruling
  artefact," gated so `CurrentRungHoldConfig`'s "existing frozen/validated
  construction path... rejects an attempt to set it via any of the
  currently-registered family manifests (`pm_us_crh_v4.json` etc.) unless a
  future manifest is deliberately authored to clear it." This is REFUTED by
  the actual composition wiring: `composition.py::_station_config`
  constructs `CurrentRungHoldConfig` directly in Python and threads exactly
  ONE field from the `FamilyManifest` — `required_fee_coefficient` (from
  `taker_fee_coefficient`). `family_manifest.py`'s `_REQUIRED_KEYS`/
  `_OPTIONAL_KEYS` (`family_manifest.py:96-125`) have no slot for a
  calibration-gate flag, and `load_family_manifest` (`:211-236`) refuses
  any unknown key outright. A future manifest CANNOT "clear" this flag as
  described — nothing reads such a key from a manifest today. The
  described §9 test ("rejects an attempt to set it via any of the
  currently-registered family manifests") is not executable as written
  because no code path today lets a manifest set (or attempt to set) any
  `CurrentRungHoldConfig` field other than `required_fee_coefficient`.

## Defects

**MATERIAL** — Safety-gate arming/rollback mechanism is misdescribed
(§6.3, §9). This is the exact control a fail-closed safety gate lives or
dies by: if the implementer follows §9 literally, they will write an
untestable assertion, or worse, wire the flag through `composition.py`
ad hoc without the "new, explicit, reviewed artefact" discipline the plan
intends, because the plan names the wrong mechanism (manifest-driven) for
what is actually a Python-code-only construction path.
Required change: name the ACTUAL arming path explicitly — either (a) the
flag stays a `CurrentRungHoldConfig` field flipped only by a code change to
`composition.py::_station_config` (which the plan should say plainly, and
scope the RED test to "a `composition.py` change is required to clear this,
never a manifest edit alone"), or (b) if manifest-driven arming is actually
wanted, the plan must additionally scope a `family_manifest.py` schema
change (`_OPTIONAL_KEYS` addition) and the `_station_config` threading code
to read it — which is new scope not currently in §6/§7. Either is fine;
leaving it unspecified is not, because it is precisely the "does clearing
require a new, explicit, reviewed artefact" property the safety design
depends on.

**MINOR** — `REFUSAL_REASONS` citation ("near the top... :106", §6.1) is
off by one; the `__all__` entry is at line 107 and the set literal begins
at line 120. Does not affect correctness, easily fixed by the implementer
re-reading source (which the plan already directs, §13 self-score).

**MINOR** — sibling-family exposure (`pm_us_crh_v2`, `pm_us_crh_cont`) to
the same `P_HOLD_UPPER` table is explicitly named open/out-of-scope. Per
the audit's own correction note, only `pm_us_crh_v4` is currently live
(`bcb82d6`), so this is not a live-money gap today, but it is a real blast-
radius gap if a sibling family is ever re-armed before that check runs.
Acceptable as stated (named, not silently dropped).

## Per-criterion points (out of the brief's rubric)

- Fidelity to audit gap and completeness: 18/20 — matches the plan's own
  self-score; both refusal gates are correctly characterised as correct-
  and-final rather than defects, exactly what the brief's challenge asks.
- Technical correctness and evidence grounding: 16/20 (down from the
  plan's self-scored 19) — every citation up to and including gate
  placement and line numbers is exact, but the config/manifest arming
  mechanism (§6.3/§9) is a load-bearing factual claim about how the safety
  control is armed, and it is wrong.
- Implementation specificity and feasibility: 12/20 (down from 16) — the
  gate placement itself is precise and implementable; the arming/rollback
  control — arguably the single most important design element of a
  fail-closed safety gate — is underspecified in a way that would mislead
  an implementer, not merely leave a detail open.
- Acceptance criteria and validation quality: 14/20 (down from 17) — the
  §9 "failure case" test as written cannot be implemented against current
  source; it must be rewritten once the arming mechanism is corrected.
- Autonomous operation, failure handling, recovery: 14/15 — unaffected by
  the above; the gate itself (pure function, no I/O, default False) is
  sound.
- Portfolio alignment, scope, dependencies: 9/10 — unaffected; correctly
  scopes the family-disposition question to AUD-02.

**Total: 83/100.**

## Required changes to reach 100

1. Correct §6.3/§9 to name the real arming path (composition.py code change
   vs. a scoped manifest-schema addition) and rewrite the §9 failure-case
   test to match whichever is chosen.
2. Fix the `REFUSAL_REASONS` line citation (minor, cosmetic).
3. Optional (does not block 100 given it is explicitly named): a one-line
   follow-up ticket reference for the sibling-family (`pm_us_crh_v2`/
   `pm_us_crh_cont`) exposure check, so it is not just prose in §12 but a
   tracked item.

## Blockers

None from this lens that require an operator/strategy-lead ruling — the
MATERIAL defect above is a plan-authoring correction, not an unavailable-
evidence or access blocker. The plan's own named BLOCKER (§12, the
strategy-lead ruling on YES-side/family retirement) is correctly scoped to
AUD-02 and is not this plan's blocker to resolve.
