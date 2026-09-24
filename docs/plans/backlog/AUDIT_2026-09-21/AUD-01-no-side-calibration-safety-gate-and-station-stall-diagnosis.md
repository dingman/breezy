# AUD-01 — Gate NO-side pricing on the confirmed-invalid `p_hold` table; diagnose the two-of-four station stall

## 1. ID and actionable title

**AUD-01.** Add a fail-closed no-trade gate on the NO side of `pm_us_crh_v4`
(and any sibling family reading `archive_table.P_HOLD_UPPER`), because the
frozen calibration is now CONFIRMED invalid for live use. Separately
diagnose (verification only) why LAX and MDW stopped evaluating on 09-20
while inside their own decision windows.

Two independently actionable slices:
- **AUD-01a (P0, build):** NO-side no-trade gate.
- **AUD-01b (P2, verification):** LAX/MDW stall root-cause.

## 2. Source finding, verdict, class

Gap **G-01** — "Nothing reaches pricing" (`AUTONOMY_ROI_AUDIT_2026-09-21.md`
line 32-36, verdict FALSE/verified). Primary evidence:
`docs/evidence/DECISION_FUNNEL_2026-09-20.md` (measured, read-only over the
live tape, corroborated by an independent `python-reviewer` audit and a
`prediction-market-reviewer` domain review, both returned).

Class: **AUD-01a is an implementation defect** (a calibration table is
consumed by the live decision path without the no-trade gate its own
confirmed miscalibration requires — this repo's own calibration-architecture
principle: "if a stratum's rolling error exceeds threshold, not-trading is
the default path"). **AUD-01b is a verification gap** (cause not yet
established; two candidate mechanisms, no code change implied yet).

## 3. Current behaviour, required behaviour, gap

**Current:** `evaluate_decision` (`src/breezy/strategy/current_rung_hold/decision.py:326-372`)
gates every decision on `RunningMax.spans` (`observation_ambiguous`,
`:343-344`) then `_is_legal_cell` (`illegal_cell`, `:350-351`). **Both gates
are CONFIRMED CORRECT, not defects** — established facts, not this plan's
judgement call:
- Gate 1 (`observation_ambiguous`): verified against source AND data — every
  one of 1,968 `running_max_exact=True` rows resolved a rung; every one of
  35,980 `observation_ambiguous` rows was non-exact. The live NWS 5-minute
  feed is genuinely whole-degree-C; no fix narrows an interval the data does
  not support. Three candidate remedies (METAR-only estimand, IEM
  `asos1min.py`, IEM MADIS 5-minute) were each measured and REJECTED —
  `DECISION_FUNNEL_2026-09-20.md` "Consolidated: every identified fix is now
  closed" table. **No live sub-degree high-cadence observation source
  exists.** This door is shut; AUD-01 does not reopen it.
- Gate 2 (`illegal_cell`): `_is_legal_cell` (`decision.py:291-302`) refuses
  `width_code == 2` (the open-ended bottom-tail rung) **unconditionally, by
  documented design** — "NEVER legal... Enforced here so a caller cannot
  pass an out-of-policy key and reach a `Take` merely because the frozen
  table happens to have that cell populated (L-22: unforgeable, not
  offered)." This is policy, confirmed from the function's own docstring,
  not a bug.

Once both gates pass, the surviving decisions are NOT safe by construction.
`_evaluate_no_side` (`decision.py:425-449`) reads `P_HOLD_UPPER.get(key)` and
computes `p_miss_lower = 1 - p_hold_upper` as the NO-side edge estimand fed
to `_finalize_take` (`:442-449`). The frozen table
(`scripts/analysis/generate_current_rung_hold_archive_table.py` →
`build_archive_table`) was calibrated on a population `RunningMax.spans` is
**never called against** (`build_hold_cases` filters only on
`is_complete_day`). Re-derivation of the frozen table (Decimal-exact,
240/240 match) plus a station-day-clustered bootstrap over the gate-pass
subsample gives a CONFIRMED, non-provisional result: gate-pass retention is
a near-oracle that trims the tails without relocating the centre, and
**against the correct bound (`P_HOLD_UPPER`), 233/240 cells (97%) overstate
the true miss probability the NO side is priced against, mean +0.094**,
clustered 95% CI excluding zero at every level down to 4 fully independent
station groups. Domain review: "**Recalibrating on the gate-pass subsample
is INVALID**" (79/240 cells conditioned to p≈1.0 with n below the corpus's
own `N_MIN=90` — a collider, not a calibration) and "**the family is
currently UNSALVAGEABLE, not merely miscalibrated**" absent real (not
synthetic) historical venue ladders, which do not exist.

**Required behaviour:** per this repo's own calibration-architecture
principle (fail closed when a stratum's calibration is known-bad), the NO
side must not price against a table proven biased in the unsafe direction
until a valid calibration exists. The YES side is separately known
conservative ("costly, not dangerous") and carries no comparable safety
finding — AUD-01a does not touch it.

**Concrete gap:** no code path refuses a NO-side `Take` on the grounds that
`p_miss_lower` is drawn from a table CONFIRMED biased against the trader on
that side. `_evaluate_no_side` will keep computing and, on any
`illegal_cell`/`observation_ambiguous`-clearing snapshot with a bid,
returning a priced `Take` exactly as designed.

**On the pricing-gate goal state (coordinator requirement, resolved here):**
G-01's finding is "0 of ~40-54k decisions/day reach pricing (gates
`observation_ambiguous`, `illegal_cell`)." AUD-01a does **not** claim to
make qualified decisions reach pricing — it deliberately makes the NO side
refuse MORE, not fewer, decisions, because the decisions that would reach
NO-side pricing are the ones CONFIRMED unsafe. The goal state for G-01 as a
whole is therefore reached by **disposition, not reopening**: Gate 1 and
Gate 2 are CONFIRMED CORRECT (§3 above, re-affirmed after HUNT-1
reconciliation below) — no code change to either is proposed by any AUD
item, and none is warranted by evidence in hand. The three remedies capable
of relaxing Gate 1 were each measured and rejected (§3). The one remaining
lever that could let qualified decisions reach pricing at all — widening the
`[12:00,17:00)` window so more station-hours are even evaluated pre-gate
(HUNT-1) — is explicitly **not dispositioned by this plan** (see the
corrected §3/§12 HUNT-1 treatment below): it stays open at CRIT per
`PROGRESS.md:51` and is out of this plan's scope, not closed by it. So: G-01
reaches its goal state through the union of (i) AUD-01a (the safety gate,
shipped here), (ii) AUD-01b (station-stall diagnosis, this plan), (iii)
HUNT-1 (window-widening, tracked in PROGRESS.md, NOT this plan), and (iv)
AUD-02's A1 ruling (family disposition — does `pm_us_crh_v4` trade at all).
AUD-01 alone does not and cannot close G-01; it closes the safety half and
leaves the reach-pricing half correctly attributed to HUNT-1 and A1.

Separately: `DECISION_FUNNEL_2026-09-20.md`'s 22:43Z snapshot records LAX
stalled at 166 decisions and MDW at 0 all day, both strictly inside their own
`[12:00,17:00)` LST windows while SFO kept evaluating normally. Not explained
by observation-store shape (MDW: 298 rows stored, "normal shape"). Candidate
mechanisms named but not measured: market listing / instrument availability,
or the shared 10-subscription WS cap (`websocket.py:415,637` per
`CONTINUOUS_HUNTING_GAP`/`POST_FORECAST_PHASE` evidence). **Gap: unknown
whether this is a code defect, a discovery/listing gap, or a genuine
zero-liquidity day** — currently unverified either way.

## 4. Priority, rationale, dependencies, execution order

- **AUD-01a: P0.** Every live NO-side fill today prices against a table with
  a CONFIRMED, measured, directional safety defect; this is a live-money risk
  finding, not a hypothesis. No dependency on AUD-02/AUD-03. Independent of
  HUNT-1 (window widening) — see §12 for why HUNT-1 does not subsume this,
  and why this plan does not subsume HUNT-1 either.
- **AUD-01b: P2.** Observability/diagnosis only; no live-money risk (SFO/MIA
  hunt normally; the pricing gate is closed anyway per Gate 1/2 above, so a
  stalled station currently produces zero decisions either way — this is a
  correctness/coverage gap, not a safety gap). Independent of AUD-01a.
- **Execution order:** AUD-01a first (small, urgent); AUD-01b any time after.
  AUD-01a should land BEFORE any operator/strategy-lead ruling on AUD-02's
  family-disposition question (§12), so that question is answered about a
  bot that is not actively taking the confirmed-unsafe NO trades while the
  ruling is pending.

## 5. Scope and explicit exclusions

**In scope (AUD-01a):** a fail-closed refusal in the NO-side decision path,
keyed on the family/table this finding was measured against
(`pm_us_crh_v4`'s `P_HOLD_UPPER` table); a named refusal reason; tests.

**In scope (AUD-01b):** read-only measurement of why LAX/MDW stopped
evaluating on 09-20 — WS subscription/requestId accounting, instrument
listing/discovery state, and quote-tape row presence for those two
stations/windows, cross-checked against the node log for the same period.

**Excluded (named, not this plan's call):**
- **Widening the trading window (HUNT-1).** CORRECTED after round-1 review:
  HUNT-1 is **not moot**. `DECISION_FUNNEL_2026-09-20.md` itself states "HUNT-1
  stays open but is de-prioritised behind these two [gates]" (line 98) — not
  "moot." `docs/core/PROGRESS.md:51` currently carries HUNT-1 at **CRIT**
  priority, restored same-day (commit `9ddcb8b`, "restore the item I
  deleted") on an explicit operator statement: "there is a definitive
  requirement that the trading bot's strategy must be continuously hunting,
  never inside just a specific window." The `[12:00,17:00)` gate is a direct
  consequence of `P_HOLD_LOWER` covering `hour_lst ∈ {12..16}` only —
  removing the window without an all-hours table yields `None`, not hunting.
  What IS measured and closed: widening the window ALONE, with the existing
  table, does not clear an edge threshold on any additional hour
  (`ALL_HOURS_EDGE_TABLE_2026-09-20.md`) — that narrower, measured claim is
  what "de-prioritised" means, not "the operator's requirement is satisfied
  or irrelevant." AUD-01 does not implement HUNT-1, does not rule on it, and
  does not diminish its CRIT status; it remains open, tracked in
  PROGRESS.md, and is a real, distinct, operator-mandated cause of decisions
  never reaching pricing outside the current window, layered on top of
  (never subsumed by) the two in-window gates this plan addresses. See §3's
  "goal state for G-01" note for how HUNT-1 relates to AUD-01a/b.
- Building a corrected observation feed (Options A/B/C) — CLOSED, all three
  rejected on measured evidence; not reopened.
- Retiring `pm_us_crh_v4` outright, or ruling on the YES side — a
  family-disposition and edge question, owned by **AUD-02** (G-02); AUD-01a
  is the minimum safety action available without that ruling.
- Recalibrating the archive table on the gate-pass subsample — the domain
  reviewer ruled this INVALID (collider bias); not proposed here.
- Fixing the two v3-tally admissibility defects in
  `RULING_v3_admissibility_divergence_2026-09-20.md` — different code path
  (`family_tally_v2`), different family (`pm_us_crh_cont`), unrelated to
  pricing; not this plan.

## 6. Proposed changes (AUD-01a)

Grounded in `src/breezy/strategy/current_rung_hold/decision.py:425-449` and
`src/breezy/strategy/current_rung_hold/archive_table.py:287` (`P_HOLD_UPPER`).

1. **New closed refusal reason** `no_side_calibration_unsafe`, added to the
   `REFUSAL_REASONS` frozenset literal (`decision.py:120-...`, set opens at
   line 120, `__all__` entry at line 107 — verified exact against current
   source, corrected from the round-1 draft's off-by-~13 citation), matching
   the existing `Refuse(reason)` convention (`Refuse.__post_init__` at
   `:240-242` validates membership; adding the string to the frozenset is
   the entire wiring needed for the reason to be legal).
2. **Gate placement:** inside `_evaluate_no_side` (`decision.py:425-449`),
   immediately after the `bid`/`bid_size` executability check (`:436-437`)
   and BEFORE the `P_HOLD_UPPER.get(key)` lookup (`:440`), so the refusal is
   unconditional for NO-side snapshots, fires strictly before the table is
   ever consulted, and does not depend on whether a cell happens to be
   defined. This is Nautilus-native in the sense that matters here: no
   Nautilus extension point is implicated (this is pure strategy-module
   logic, same layer as the existing gates), so no immutable-foundation
   question arises.
3. **Real arming/rollback path — CORRECTED after round-1 review.** The
   round-1 draft claimed a future `FamilyManifest` could "clear" this flag.
   That claim is REFUTED by source: `composition.py::_station_config`
   (`:387-421`) constructs `CurrentRungHoldConfig` directly in Python and
   threads exactly ONE field from the manifest — `required_fee_coefficient`
   (from `taker_fee_coefficient`, verified verbatim in current source).
   `family_manifest.py`'s `_REQUIRED_KEYS`/`_OPTIONAL_KEYS`
   (`family_manifest.py:96-125`) have no slot for a calibration-gate flag,
   and `load_family_manifest` (`:211-236`) refuses any unknown key outright.
   **A manifest cannot clear this flag today — no code path lets a manifest
   set any `CurrentRungHoldConfig` field other than `required_fee_coefficient`.**
   This plan therefore names the actual arming path explicitly, per the
   mle-reviewer's required-change (a): the flag is a
   `CurrentRungHoldConfig` field, `no_side_calibration_gate_cleared: bool =
   False` (`current_rung_hold/config.py`), defaulting closed, and it is
   cleared ONLY by a future code change to `composition.py::_station_config`
   (e.g. passing `no_side_calibration_gate_cleared=True` explicitly for a
   named station/family at construction) — never by a manifest edit alone,
   because no manifest-reading path exists for this field. Any future work
   to make this manifest-driven instead (adding an `_OPTIONAL_KEYS` entry
   and threading code in `_station_config`) is explicitly OUT OF SCOPE here
   and would be new scope for a separate plan. The discipline this mirrors
   is the EXIT-1 precedent ("BUILT, UNARMED") — build the safety mechanism
   now; arming requires a reviewed code change accompanying a future ruling
   artefact under `docs/evidence/`, this plan does not flip it and does not
   pretend a manifest edit alone could.
4. **No change to the YES side, to `_finalize_take`'s shared logic, to
   `_is_legal_cell`, or to `RunningMax.spans`** — both existing gates stay as
   measured-correct.
5. **Observability:** the new refusal reason is added to
   `weather_common/refusals.py`'s tracked reason set so it surfaces through
   the existing per-reason `AlertCondition` path (`RefusalWatch._conditions`,
   `refusals.py:220-235`) automatically — `RefusalWatch._conditions` iterates
   `self._counter.counts`, not a fixed/closed reason set (verified), so this
   is genuinely "no new plumbing," not merely asserted. **Not added to
   `STRUCTURAL_HALT_REASONS`** (`halt_detector.py:138-154`): this refusal is
   homogeneous by design once cleared to False, and adding it there would
   make the intended state page continuously — see AUD-03 for the digest
   that reports composition without treating this as a halt.

## 7. Ordered implementation or verification steps

**AUD-01a (RED-first):**
1. RED: `tests/unit/test_current_rung_hold_decision_no_side_2026_09_14.py` (or
   a new sibling test module) — a NO-side `DecisionInputs` with a defined,
   profitable `P_HOLD_UPPER` cell and `no_side_calibration_gate_cleared=False`
   must return `Refuse("no_side_calibration_unsafe")`, never a `Take`, even
   when every other gate would pass. Assert byte-identical YES-side behaviour
   is unaffected (reuse the existing "worked take example" fixture).
2. RED (strengthened per round-1 review): additionally assert, via a
   spy/mock on the `P_HOLD_UPPER` lookup (or an instrumented dict subclass
   substituted into the test's `archive_table` reference), that
   `P_HOLD_UPPER.get(key)` is **never called** when
   `no_side_calibration_gate_cleared=False` — not merely that the outcome is
   `Refuse`. This closes the round-1 gap where an implementer could satisfy
   the letter of "returns Refuse" by gating after the lookup, which would
   still compute (and could still leak, e.g. via logging) the unsafe
   estimand even though the `Take` itself was refused.
3. GREEN: implement the gate per §6 (steps 1-2 above are both RED against
   this single change).
4. RED: `tests/unit/test_halt_detector.py` (or `test_refusals.py`) — the new
   reason surfaces through `RefusalWatch` as its own `AlertCondition`, keyed
   independently, never conflated with an existing reason.
5. GREEN: confirmed no plumbing change needed (§6.5's reuse claim verified
   against source, not merely assumed) — if verification at implementation
   time shows otherwise, add the minimal plumbing then.
6. Full `test_current_rung_hold_decision*.py` suite green; `ruff`/`mypy` on
   changed files.
7. **RED (rewritten per round-2 review — TWO tests, neither optional):**
   the round-2 mle-reviewer found the Revision 2 version of this step (a
   single test iterating over currently-registered manifest files and
   asserting none sets the flag) executable but NOT provable-by-construction
   as claimed: it only shows TODAY's manifest set cannot set the flag, and
   would keep passing silently forever even if a future edit ever added
   `no_side_calibration_gate_cleared` to `_OPTIONAL_KEYS` and threaded it in
   `_station_config` — exactly the drift the safety design exists to catch.
   Replaced with both of the following, re-verified against current source
   this round (`family_manifest.py:96-125,211-236`, re-read directly):
   - **7a. Schema-membership assertion:**
     `"no_side_calibration_gate_cleared" not in (family_manifest._REQUIRED_KEYS
     | family_manifest._OPTIONAL_KEYS)` — fails the instant the schema is
     ever widened to accept the key, forcing a deliberate test update at
     exactly the point the safety design wants friction. This is the
     schema-level invariant; it says nothing about runtime behaviour and is
     not sufficient alone.
   - **7b. Adversarial construction test:** build an in-memory manifest JSON
     payload (a copy of any currently-registered manifest's fields, e.g.
     `pm_us_crh_v4.json`'s parsed dict — constructed entirely in test code,
     no on-disk file is edited) with `"no_side_calibration_gate_cleared":
     true` injected, write it to a temp path, call
     `family_manifest.load_family_manifest(temp_path)`, and assert it raises
     `family_manifest.FamilyManifestValidationError` with a message
     containing `"unknown key(s)"` — verified verbatim against the real,
     unmodified exception text at `family_manifest.py:234-236` (`unknown =
     keys - _REQUIRED_KEYS - _OPTIONAL_KEYS; if unknown: raise
     FamilyManifestValidationError(f"{path}: unknown key(s):
     {sorted(unknown)}")`). This is behaviourally-grounded proof against the
     REAL validation function for an adversarial payload, not merely a
     schema-membership check.
   **Correction, stated explicitly (coordinator requirement):** Revision 2's
   own prose rejected exactly this adversarial-construction approach ("not
   by an attempted-and-rejected manifest edit as the round-1 draft
   incorrectly described"). That rejection was WRONG, and is retracted here:
   the round-1 draft's original direction did not require any REGISTERED
   manifest file to carry the key — it only required constructing a
   synthetic payload in test code and feeding it to the real,
   already-shipped `load_family_manifest` function, which is trivially
   possible and requires no code change to attempt. Revision 2 conflated
   "no currently-registered manifest sets this key" (true, and the weaker
   claim 7a's schema check now makes precise) with "a test cannot construct
   and feed an adversarial payload that sets this key" (false — that
   payload is straightforward to build, and `load_family_manifest`'s
   existing, unmodified unknown-key refusal is exactly the mechanism that
   makes 7b pass today without any implementation work). Both 7a and 7b are
   now required; 7a alone would not have caught the class of drift the
   mle-reviewer is protecting against were it not paired with 7b's proof
   against actual runtime behaviour, and 7b alone would not pin the schema
   itself against a future accidental widening that a test author forgets
   to re-run.
8. GREEN: confirm both 7a and 7b pass without any implementation change if
   §6.3 is followed as specified — 7a passes by construction (the flag is
   never added to `_OPTIONAL_KEYS`); 7b passes because `load_family_manifest`'s
   existing, unmodified unknown-key refusal (§6.3, unchanged by this plan)
   already raises for any injected key, today. Confirm both before merging;
   neither requires new production code.

**AUD-01b (verification only, no RED/GREEN — no code changes proposed until a
cause is found):**
1. Pull the live node log for the 09-20 window (LAX/MDW hours in `[12,17)`
   LST) and grep for subscription/instrument-resolution lines for those two
   stations specifically.
2. Cross-reference `order_book_depths`/`quote_ticks` catalog coverage for
   LAX/MDW during their stalled windows against SFO's (which kept
   evaluating) for the same period — row counts, gaps, last-tick timestamps.
3. Check listed-instrument counts per station from the quote-tape discovery
   log (`breezy-quote-tape.service`) for 09-20, comparing LAX/MDW's active
   instrument count against SFO/MIA's.
4. Produce a dated finding under `docs/evidence/` stating which of (a) WS
   subscription starvation, (b) instrument/listing gap, (c) a code defect in
   the strategy's own per-station iteration, or (d) genuine zero-eligible-
   snapshot day, the evidence supports — or that it remains unverified with
   the specific missing data named.

## 8. Measurable acceptance criteria and required evidence

**AUD-01a:**
- New RED tests (§7 steps 1-2, 4, 7a, 7b) fail before the change, pass after
  (paste all runs).
- 100% of existing `test_current_rung_hold_decision*`,
  `test_no_side_*_2026_09_14.py`, `test_current_rung_hold_backtest_only.py`
  suites remain green (no YES-side behaviour change; byte-identical fixture
  test still passes).
- A replay or unit-level demonstration that, with
  `no_side_calibration_gate_cleared=False` (the shipped default), a NO-side
  snapshot that would otherwise have produced the 2026-09-11 SFO / 2026-09-13
  MIA style `Take` now returns `Refuse("no_side_calibration_unsafe")`
  **and the `P_HOLD_UPPER` table is never consulted** (spy assertion from
  §7 step 2).
- The §7 step 7b adversarial-construction test demonstrates
  `load_family_manifest` raises `FamilyManifestValidationError` with an
  "unknown key(s)" message for any payload carrying
  `no_side_calibration_gate_cleared` — not merely that today's registered
  manifests happen to omit it — and the §7 step 7a schema-membership
  assertion demonstrates the key is absent from the combined
  `_REQUIRED_KEYS | _OPTIONAL_KEYS` set at the time of the test run.
- `ruff check` / `mypy` clean on changed files; no change to files outside
  `current_rung_hold/` and their tests.

**AUD-01b:**
- A dated evidence doc under `docs/evidence/` stating the LAX/MDW cause (or
  the specific unresolved question) with citations to logs/catalog rows
  actually inspected, not inferred.

## 9. Validation: failure cases, integration behaviour, autonomous operation

- **Failure case — cleared-flag left True by mistake:** covered by (a) a
  test asserting the dataclass default is `False`; (b) the §7 step 7a
  schema-membership assertion,
  `"no_side_calibration_gate_cleared" not in (family_manifest._REQUIRED_KEYS
  | family_manifest._OPTIONAL_KEYS)`, which fails the moment a future schema
  change ever widens `_OPTIONAL_KEYS` to include it — pinned against DRIFT,
  not merely against today's registered files; and (c) the §7 step 7b
  adversarial construction test, which builds a synthetic manifest payload
  with the key injected and asserts `load_family_manifest` raises
  `FamilyManifestValidationError` ("unknown key(s)", verified verbatim at
  `family_manifest.py:234-236`) for that payload specifically — proving the
  real, current, unmodified validation function refuses the exact attack the
  safety design worries about, not just that no already-registered file
  happens to attempt it. **Corrected after round-2 review** (see §7 step 7's
  own correction note): Revision 2 explicitly rejected the
  adversarial-construction approach as untestable; that rejection was wrong
  and is retracted — the adversarial payload needs no registered manifest
  file, only test-code construction, and `load_family_manifest`'s
  unmodified unknown-key refusal is what makes the test pass today with zero
  production-code change. Clearing the flag for real still requires a
  `composition.py` code change (§6.3), which remains a reviewed diff, not a
  silent default drift.
- **Integration:** the gate must not alter `evaluate_decision`'s dispatch
  order for the YES side at all (`:359-368` untouched) and must sit
  downstream of the existing `not_executable` check so a thin NO book still
  refuses on the pre-existing, more specific reason first — order matters for
  operator diagnosis (§10's digest reads the reason).
- **Autonomous operation:** the gate runs on every tick with zero I/O,
  matching this module's existing pure-function decision style; it cannot
  hang, retry, or depend on network state. A crash mid-decision has no
  side effect to recover (no order was placed) — same failure profile as
  every other `Refuse` branch already in this function.

## 10. Deployment, observability, rollback

Ships as an ordinary code change behind the existing
`family_manifest`/composition path — no new unit, no new timer, no new
credential, no egress change. Observability: the new reason flows through
the existing `RefusalWatch`/alert-egress path (already delivering per
`f97c26f`), so an operator sees `no_side_calibration_unsafe` counts exactly
like any other refusal reason, without a new alert code path to test.
**Rollback:** reverting the diff restores prior behaviour; because the
config flag defaults closed, NO rollback is ever required to stop the
mitigation from taking effect — the safe direction is the shipped one.

## 11. Relationship to portfolio-level ROI and evaluation

This item does not create ROI; it prevents a MEASURED, signed loss driver
(mean +0.094 overstatement of `p_miss_lower` on 233/240 cells) from
continuing to price live orders while G-02's broader family-disposition
question (does `pm_us_crh_v4` have ANY edge at all, on either side) is still
open. It is evaluated by: (a) zero NO-side fills against the uncleared gate
from merge onward, verified against the exec ledger
(`~/.local/share/breezy/state/exec_polymarket_us.sqlite`); (b) no change to
YES-side fill rate or edge, verified against the same ledger pre/post merge.

## 12. Assumptions, unresolved questions, blockers

- **Assumption:** "fail closed on confirmed-bad calibration" is a build-side
  safety action, not an operator-reserved control (it touches neither the two
  reserved caps nor live-trading enablement/the NO-SEND firewall) — this
  mirrors the EXIT-1 precedent already accepted in this repo (build+unarmed,
  no operator sign-off needed to ship the safety mechanism itself).
- **Named BLOCKER (strategy-lead ruling, not decided here):** whether
  `pm_us_crh_v4`'s YES side should also be paused given the domain reviewer's
  "UNSALVAGEABLE, not merely miscalibrated" verdict, and whether the family
  should be retired outright. This is **G-02 territory** — see AUD-02, which
  owns the family-disposition question; AUD-01a is deliberately the smaller,
  immediately-actionable slice that does not require that ruling.
- **HUNT-1 relationship, corrected after round-1 review:** HUNT-1 (widen the
  `[12:00,17:00)` window) is NOT decided, NOT dispositioned, and NOT made
  moot by this plan. It remains a separate, open, operator-mandated CRIT item
  tracked in `PROGRESS.md:51`. AUD-01a's safety gate and AUD-01b's stall
  diagnosis are both independent of it: AUD-01a makes NO-side pricing safer
  within whatever window is evaluated; HUNT-1 is about how much of the day is
  evaluated at all. Neither subsumes the other. This plan does not implement
  HUNT-1 and takes no position on when it should be executed beyond noting it
  is out of scope here (§5).
- **Open, not decided:** whether the same `p_hold`-table exposure exists on
  any other registered family (`pm_us_crh_v2`, `pm_us_crh_cont`) — this plan
  only measured/gates `pm_us_crh_v4`'s consumption; a follow-up check of
  sibling families' manifests is recommended but out of scope here. Only
  `pm_us_crh_v4` is currently live (per `bcb82d6`), so this is not a
  live-money gap today, but it is a real blast-radius gap if a sibling
  family is ever re-armed before that check runs.
- **AUD-01b has no blocker**; it is pure read-only measurement and may return
  "genuinely zero-eligible day," which would close it with no further work.

## 13. Review history

**Round 1** (two independent reviewers; both scored "implementation
specificity" on a /20 scale though the rubric caps that criterion at 15 —
round-1 totals below are as reported by each reviewer and are NOT comparable
to the 20/20/15/20/15/10 rubric; they are superseded by the Revision 2
self-score at the end of this section, which uses the correct caps):

- **mle-reviewer: 83/100 (as reported).** MATERIAL: §6.3/§9's arming path
  ("a future manifest can clear the flag") is refuted by source —
  `composition.py::_station_config` threads only `required_fee_coefficient`;
  `family_manifest.py`'s closed key schema rejects any other field; the §9
  test as originally written was not executable. MINOR: `REFUSAL_REASONS`
  line citation off by ~13. MINOR (not required): sibling-family
  (`pm_us_crh_v2`/`pm_us_crh_cont`) exposure named open, acceptable as
  stated.
  **Disposition: ACCEPTED, both.** §6.3 rewritten to name the real arming
  path (`composition.py` code change only, no manifest path exists); §9's
  failure-case test rewritten to assert the correct, executable invariant
  (no manifest key maps to this field, provable by construction) instead of
  an "attempted manifest edit is rejected" claim that had no code path to
  attempt. `REFUSAL_REASONS` citation corrected to "set opens at line 120,
  `__all__` entry at line 107" (both verified against current source this
  round). Sibling-family follow-up left as a named open item (§12) per the
  reviewer's own "acceptable as stated" note — not elevated to a tracked
  ticket, since the reviewer marked it optional and no new gap evidence
  changes that.

- **prediction-market-reviewer: 86/100 (as reported).** MATERIAL: §5/§12
  called HUNT-1 "moot," which both misstates its own cited source
  (`DECISION_FUNNEL_2026-09-20.md` says "stays open... de-prioritised," not
  moot) and contradicts `PROGRESS.md:51`'s live CRIT status, restored same-day
  on an explicit operator continuous-hunting requirement. MINOR: RED test
  plan did not assert the `P_HOLD_UPPER` lookup is never reached, only that
  the outcome is `Refuse`.
  **Disposition: ACCEPTED, both.** Re-verified directly against
  `DECISION_FUNNEL_2026-09-20.md:98` and `PROGRESS.md:51` this round (both
  confirmed exactly as the reviewer states). §3, §5, and §12 rewritten to
  state HUNT-1 stays open at CRIT, is a distinct structural cause of
  decisions never reaching pricing, and is explicitly out of this plan's
  scope rather than closed by it; §3 gained a new "goal state for G-01" note
  per the coordinator's own requirement, showing how AUD-01a + AUD-01b +
  HUNT-1 + AUD-02's A1 ruling jointly reach G-01's goal state without this
  plan claiming to close HUNT-1 itself. §7/§8/§9 RED test strengthened to
  assert (via a spy on the lookup) that `P_HOLD_UPPER.get` is never called
  when the gate is closed.

**Revision 2 self-score** (correct caps: 20/20/15/20/15/10):
- Fidelity to audit gap and completeness: 19/20 — now explicitly states the
  G-01 goal-state relationship (coordinator requirement) and correctly
  reconciles HUNT-1 rather than mischaracterizing it; still does not resolve
  the sibling-family exposure question (named, not required).
- Technical correctness and evidence grounding: 20/20 — every claim now
  independently re-verified against current source this round, including
  the two refuted claims from round 1 (composition.py wiring; HUNT-1
  characterization), both corrected and re-confirmed by direct read.
- Implementation specificity and feasibility: 15/15 — the arming path is now
  the actual, executable mechanism (a `composition.py` code change only),
  and the §9 failure-case test asserts a provable-by-construction invariant
  instead of a nonexistent manifest-rejection path.
- Acceptance criteria and validation quality: 19/20 — the strengthened RED
  test (lookup-never-called spy) closes the round-1 gap; one point held back
  because exact new test file names are still left to implementer judgement.
- Autonomous operation, failure handling, recovery: 15/15 — unaffected by
  either correction; pure function, fail-closed default, explicit and now
  more precisely correct rollback/arming story.
- Portfolio alignment, scope, dependencies: 10/10 — HUNT-1 correction
  strengthens rather than weakens this: the plan now correctly attributes
  scope instead of silently absorbing or dismissing an operator-mandated
  item it does not own.

**Revision 2 total: 98/100. Status: NOT READY — round 2 review pending.**

**Round 2** (two independent reviewers, blind, against Revision 2; both
round-1 defects re-verified FIXED by both reviewers this round — see each
review file for the direct source re-checks):

- **mle-reviewer: 94/100.** New MATERIAL finding (not raised by either
  round-1 reviewer): the Revision 2 §9/§7-step-7 failure-case test is
  executable but proves only "no CURRENTLY-registered manifest sets the
  flag," not "the schema cannot be widened to allow it" — a future edit
  adding the key to `_OPTIONAL_KEYS` and threading it in `_station_config`
  would leave this test green forever. Required change: rewrite as BOTH a
  schema-membership assertion (`key not in _REQUIRED_KEYS | _OPTIONAL_KEYS`)
  AND an adversarial construction test (inject the key into a payload, feed
  it to `load_family_manifest`, assert `FamilyManifestValidationError`) —
  explicitly the round-1 draft's original direction, which Revision 2 had
  wrongly rejected as untestable.
  **Disposition: ACCEPTED.** §7 step 7 (now 7a/7b) and §8/§9 rewritten per
  the required change, re-verified directly against current source this
  revision (`family_manifest.py:96-125,211-236,234-236` re-read; exact
  exception text confirmed: `f"{path}: unknown key(s): {sorted(unknown)}"`
  at line 236). §7/§9 now state explicitly that Revision 2's rejection of
  the adversarial-construction approach was wrong and why (it conflated "no
  registered manifest carries the key" with "a test cannot construct one" —
  false; a synthetic payload requires no registered file).
- **prediction-market-reviewer: 100/100.** No defect found; both round-1
  corrections independently re-verified against current source (11 distinct
  file:line citations checked, all exact).

**Divergence:** mle-reviewer 94 vs prediction-market-reviewer 100 —
readiness is the LOWER score (94), driven by the mle-reviewer's MATERIAL
test-strength finding above, now fixed in this revision.

**Revision 3 self-score** (correct caps: 20/20/15/20/15/10; conservative,
against the fix actually applied this round, re-verified directly against
current source, not merely claimed):
- Fidelity to audit gap and completeness: 19/20 — unchanged from Revision 2;
  the sibling-family (`pm_us_crh_v2`/`pm_us_crh_cont`) exposure question
  remains named-open, correctly, per both round-1 and round-2 reviewers'
  agreement that it is acceptable as stated, not required.
- Technical correctness and evidence grounding: 20/20 — every citation in
  the rewritten §7/§9 (including the exact exception text at
  `family_manifest.py:234-236`) independently re-verified against current
  source this revision via direct codegraph read, not carried over from the
  reviewer's report.
- Implementation specificity and feasibility: 15/15 — both 7a and 7b are
  fully specified, executable against the real, unmodified
  `load_family_manifest` function, and require zero production-code change
  to pass (both pass by construction against §6.3 as specified).
- Acceptance criteria and validation quality: 20/20 — the schema-membership
  assertion pins the invariant against future schema drift; the adversarial
  construction test pins it against actual runtime behaviour for an
  attacker-shaped payload — together they close the exact non-vacuity gap
  the round-2 mle-reviewer identified, and the correction is explicit in the
  plan text (not merely a silent rewrite), including a stated retraction of
  Revision 2's wrong rejection.
- Autonomous operation, failure handling, recovery: 15/15 — unaffected by
  this round's fix; still a pure function, fail-closed default, zero I/O.
- Portfolio alignment, scope, dependencies: 10/10 — unaffected; scope
  attribution across AUD-01a/AUD-01b/HUNT-1/AUD-02's A1 unchanged and still
  correct.

**Revision 3 total: 99/100. Status: NOT READY — round 3 review pending.**

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-21) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `2a1ac1b140029d03c10e8d10138ad266cedc0263ebbb69d3701bd7b8fc7b6e67`
- **Baseline self-score:** 93/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `mle-reviewer` round 3: 100/100 — `reviews/AUD-01-r3-mle-reviewer.md`
  - `prediction-market-reviewer` round 3: 100/100 — `reviews/AUD-01-r3-prediction-market-reviewer.md`
- **Readiness:** **READY**
- **Unresolved blockers:**
  - None on this item's scope. Noted, owned elsewhere: AUD-02 ruling A1 on `pm_us_crh_v4`'s disposition.
- **Full review history:** 6 records, `reviews/AUD-01-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
