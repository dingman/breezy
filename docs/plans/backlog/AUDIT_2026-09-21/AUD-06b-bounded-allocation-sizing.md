# AUD-06b — MP-B Increment B: depth-capped, cent-safe, envelope-clamped sizing, gated behind TWO code-enforced, sha-pinned preconditions

## 1. ID and actionable title

**AUD-06b** — Execute MP-B (`MULTI_POSITION_PER_STATION_2026-09-14.md` §3 Increment B: S2 sizing +
S4b qty through scorer/store) **as amended by AUD-06a's envelope**, so order quantity is derived
from the per-position cap, clamped by executable depth and by the validated qty envelope, and never
logged — with **both** preconditions (validated envelope AND demonstrated edge) enforced by
sha-pinned artefacts that a test reads, never by a commit-message assertion.

## 2. Source finding and class

- **Gap:** G-11 (`AUTONOMY_ROI_AUDIT_2026-09-21.md:82-84`). Verdict **FALSE (alignment)**:
  `order_quantity=1`, no allocation logic; MP-B blocked on R-11 (V);
  `weather_common/equity.py`'s `max_equity_fraction` unused by the live family (A).
- **Existing item updated, not duplicated:** **MP-B** (`PROGRESS.md:53`), whose plan is
  `docs/plans/MULTI_POSITION_PER_STATION_2026-09-14.md` §3 Increment B (`:85-110`). This backlog
  entry re-scopes that increment; it does not restate its design.
- **Class:** **missing capability**, correctly withheld. Nothing is defective; a capability is
  absent and its two preconditions are unmet.

## 3. Current behaviour, required behaviour, concrete gap

**Current.** `quantity=config.order_quantity` (`current_rung_hold/decision.py:306-312`) with
`order_quantity` pinned to 1 and anything else refused (`config.py:253-256`, verified verbatim:
"order_quantity must be exactly 1, was {self.order_quantity!r}"). Every order spends ~one ask,
regardless of the per-position cap. On the scoring side `ScoredTrial` carries no `qty`;
`score_live_trials._admit_fill` excludes `q != 1`; `_assert_no_partial_or_multi_fill` enforces it.
Increment A (merged `b5a7c04`) already made the statistic qty-weighted and correct by construction,
so the scoring layer is prepared and inert at qty=1.

**Required.** `qty = min( floor_cent_safe(cap / ask / lot) * lot, executable_size_at_limit,
Q_MAX_VALIDATED )` with `lot = instrument.size_increment`, carried through the scorer and store,
bounded by both operator caps, never printed — and unreachable until two artefacts, each pinned by
sha and each checked by a test, exist.

**Concrete gap, and the honest statement of it.** The gap is *not* that sizing is hard — the MP plan
already specifies the formula, the files and the tests. The gap is that **sizing multiplies whatever
edge exists, including a negative one**. The live record is: no family has a proven edge, admissible
`n = 0`, the forecast programme is TERMINAL (`RULING_forecast_edge_programme_closes_2026-09-20.md`),
and nothing has reached pricing since 2026-09-15 (G-01). Deriving qty from the per-position cap
today converts a ~$0.30 loss per order into a cap-sized one with no offsetting evidence. That is why
this item's controlling content is its **gate**, not its formula — and why round 1 was right that a
gate enforced by human diligence is not a gate.

## 4. Priority, rationale, dependencies, execution order

**Priority: P3.** Lowest in this cluster, deliberately. It is the only item here that can *lose
money*, it is the only one whose benefit is entirely conditional on a fact not in evidence, and it
is blocked twice over by build preconditions and twice more by operator rulings.

**Dependency ordering (STAGE 3 — last, and gated):**
- **BLOCKER-A — AUD-06a** — the validated qty envelope **and its staleness predicate**. Without it
  the registered boundary over-spends alpha at mixed qty (R-11), so every trial the sized family
  generates would be inadmissible in the way that matters most: it would *look* significant sooner
  than it is.
- **BLOCKER-B — a demonstrated, family-scoped edge.** Sizing must not precede one. This is not
  conservatism; it is the arithmetic: `E[pnl] × qty` is more negative for larger qty whenever
  `E[pnl] < 0`. **Re-grounded 2026-09-21:** `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`
  (ENDORSED) rules that `pm_us_crh_v4` **may not send orders** on this surface, and the edge estimate
  is no longer AUD-02's to produce — it is owned by **AUD-18** (cited by id and path only; no result
  of it is assumed here). Consequence, stated honestly: **AUD-06b cannot be executed until an AUD-18
  hypothesis is CONFIRMED and a NEW family is registered to carry it.** BLOCKER-B is an *evidence*
  precondition — no peer ruling can manufacture it, and none has.
- **BLOCKER-C (R-12) and BLOCKER-D are RULED BUILD-SIDE and are no longer operator blockers** —
  `docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md` RULING 2 + Revision 2
  addendum A2 (ENDORSED, `docs/evidence/reviews/RULING_study_ceiling_exit_review_2026-09-21.md`).
  They are removed from this dependency list; their build-side consequences, the residual **R2-a**
  and BLOCKER-D's **conditional** closure are recorded in §12. **This changes nothing about A or B.**
- **Depends in fact on AUD-05** (by id): the family-scoped edge estimate — **AUD-18's since the A1
  ruling** — cannot exist until a live family has a tally that runs and an `n` that can grow.
- **Hard prerequisite for EVALUATION: AUD-04.** Round 1 correctly noted the previous revision
  treated this as a soft read. AC #8 now requires AUD-04's versioned report (its `schema_version`
  reader) to exist before the first sized order is judged — because otherwise the effect of sizing
  is unmeasurable, and shipping an unmeasurable change to the only money-moving path is the failure
  mode this whole backlog exists to close.

**Execution order:** AUD-06a envelope (+ staleness predicate) → AUD-18 CONFIRMED hypothesis and a
newly registered family carrying it (the edge artefact G2 consumes) → AUD-04 report
live → gate artefacts pinned → S2 → S4b → **pre-merge realised-qty sweep** → merge gate → bounded
first cohort → unbounded. **A is pure sequencing behind a planned item; B is not — it waits on
evidence that does not exist today.**

## 5. Scope and explicit exclusions

**In scope:** exactly the two slices MP-B already names — **S2** (`decision.py:290-293,306-312`,
`config.py:198-201,230,253-256`, `continuous_strategy.py:836-852,1280-1306`,
`operator_controls.py:163-169,220-234`) and **S4b** (`trial_scorer.py:81-86`, `_admit_fill`,
`ScoredTrial.qty` trailing-and-additive) — plus the envelope clamp AUD-06a introduces, the **two
sha-pinned gate artefacts** (§6 G1/G2), and the parity gate.

**Explicitly excluded:**
- **No operator-reserved value is read, restated, defaulted or assigned** (`PROGRESS.md:17-24`,
  L-39). The cap is consumed only through `DailySpendLedger`'s existing authorisation seam; the
  sizing code sees a ledger, never a number it may print. **No value is assigned to either cap by
  this item, its first-cohort bound, or its tests.**
- **No log line, alert or persisted record carrying the derived qty alongside a price or a cost**
  (MP plan S6, `:90`). **R4 CORRECTION — revision 3's description of the current code was WRONG and is
  withdrawn.** There is no `qty_present` token anywhere in the repo; no redaction mechanism for a
  derived qty exists today. The actual line, read from source, is `continuous_strategy.py:2519-2525`
  inside `_maybe_submit`'s unarmed early-return branch:
  `"TAKE recorded, no submit (order_submission_permit=…): {instrument_id} qty={decision.quantity}
  px={decision.limit_price} p_hold_lower={…} break_even={…}"` — i.e. it prints the **raw derived
  quantity and the limit price together** (`:2523`). At today's constant `qty = 1` that carries no
  information; the moment this item derives qty from the per-position cap, `qty × px` reconstructs
  that operator-reserved value to within one lot. **Closing this is therefore work this item must do
  (§6 D6-R), not a property it may assume.** It stays inside MP-B's "log-redacted sizing" scope and is
  not new scope: the exclusion always intended this rule, it merely mis-stated the mechanism.
- **No relaxation of the per-order notional cap.** `RiskEngineConfig.max_notional_per_order` is
  NATIVE and already wired (`.venv/lib/python3.13/site-packages/nautilus_trader/risk/config.py:44`,
  installed per instrument `risk/engine.pyx:192-196`, read `:675-679`, denial
  `NOTIONAL_EXCEEDS_MAX_PER_ORDER` `:912-917`; built at `src/breezy/runtime/node_config.py:565-622`,
  installed `:822`) — independently re-verified by both round-1 reviewers. It becomes load-bearing
  the moment qty stops being 1 — it is *relied on*, never widened.
- **No `allow_short`, no exit sizing, no multi-contract exit** (`submit_chain.py` exit path stays
  "only a 1-contract order is mappable; refusing" — exits are AUD-07's domain and remain 1-lot).
- **No re-solve of the boundary artefact**, no change to α/`n_max`/`i_max`/`look_step`.
- **No arming of anything.** This item changes order size on a family that is already armed by an
  earlier decision; it introduces no new enablement and touches no permit.
- **No new depth-freshness policy** — see §6 D3; the executable size comes from the frame that
  triggered the decision, so there is no second cached ladder to bound.

## 6. Proposed changes grounded in inspected code

**Null hypothesis (L-1), and it is mostly satisfied.** The MP plan already established that the
per-order notional cap is native and wired (above) — **nothing is built for it**. What is genuinely
Breezy's is the *derivation* of qty from a cap under a venue lot size and a depth ladder, which has
no Nautilus equivalent (`RiskEngine` denies an oversized order; it never sizes one).
`weather_common/risk.py`'s `max_equity_fraction` clip (`:557-563`, gated `signed_qty_delta > 0` by
T-4 D2) is Breezy's own equity-fraction policy and is currently unused by the live family — this
item is the first that could make it load-bearing, which is a design question in §12, not a silent
adoption. The gate-artefact loader pattern (G1/G2) is likewise not native and is **not new**: it is
the existing `src/breezy/persistence/gs_boundary_artefact.py` idiom (load a JSON artefact, recompute
and compare `inputs_sha256`, refuse on mismatch), applied to two more artefacts.

### G1 / G2 — TWO sha-pinned gate artefacts, enforced symmetrically (R1 MATERIAL fix)

Round 1's central finding: BLOCKER-A was machine-enforced while BLOCKER-B — the one whose violation
**loses money** — rested on a commit-message assertion. That asymmetry is closed. Both constants
live in **one new module, `src/breezy/persistence/sizing_gates.py`**, structured exactly like
`gs_boundary_artefact.py` (the round-1 request to name `Q_MAX_VALIDATED`'s home module):

- **G1 — `Q_MAX_VALIDATED`** plus `ENVELOPE_ARTEFACT_SHA256`, `ENVELOPE_BE_PRIOR_SUPPORT` and
  `envelope_is_stale(live_ask_summary) -> bool`, all loaded from AUD-06a's published artefact.
- **G2 — `EDGE_GATE`**: `family_id`, `EDGE_ARTEFACT_PATH`, `EDGE_ARTEFACT_SHA256`,
  `edge_ci_lower`, `edge_ci_upper`, loaded from the published family-scoped edge artefact —
  **produced by AUD-18 since the 09-21 A1 ruling** (formerly attributed to AUD-02; the interface
  obligations below are unchanged and now bind AUD-18, named by id only).

**Both are fail-closed at the sizing call site**: `derive_order_quantity(...)` raises
`SizingGateUnsatisfiedError` — it does not fall back to qty=1 and it does not warn — when any of the
following holds:
1. either artefact is absent, or its recomputed sha does not match the pinned value;
2. `EDGE_GATE.family_id != the family being sized` (the B-1 error
   `POST_FORECAST_PHASE_2026-09-20.md` documents, and that this repo has already made twice);
3. `edge_ci_lower <= 0` (the CI does not exclude 0). **UNIT CONVENTION, DEFINED AT THE EDGE-ARTEFACT
   PRODUCER'S INTERFACE — AUD-18 (R2 fix; re-attributed R7).** `edge_ci_lower`/`edge_ci_upper` are **USD of expected P&L per ONE contract,
   after fees** — the same unit and currency `order_cost_usd` works in, so §3's `E[pnl] × qty`
   framing is literally true. They are explicitly **not** a probability-scale edge (`p_hold − BE`),
   **not** a per-dollar rate, and **not** a percentage. `sizing_gates.py` records the unit as a
   literal string field `edge_unit: "usd_per_contract_after_fees"` on the loaded artefact and
   **refuses** any artefact whose `edge_unit` is absent or different — a producer that changes units
   fails closed rather than being silently reinterpreted. **Plus a structural unit-sanity assertion**,
   so a unit confusion is caught even if a producer mislabels: refuse when
   `abs(edge_ci_lower) > 1.0` or `abs(edge_ci_upper) > 1.0` USD per contract, since a binary
   contract settles in `[0, 1]` and no per-contract edge can exceed the whole payout — a
   probability-scale or percentage value mistakenly published as USD trips this. This is an interface
   obligation on **AUD-18** (named by id, stated here as the consumer's requirement) AND a gate this
   item enforces regardless;
4. `envelope_is_stale(...)` is true for the trailing-14-day live ask summary (AUD-06a's predicate);
5. `Q_MAX_VALIDATED < 1`.

A raise on the decision path is safe here precisely because the refusal is *upstream of submission*
and leaves the family at its pre-change behaviour class (no order), which is the same fail-closed
posture every other clamp in this item takes.

### D1 — S2 sizing, per the MP plan's own formula (`:90`), with two additions

`qty = min( floor_cent_safe(cap / ask / lot) * lot, executable_size_at_limit, Q_MAX_VALIDATED, COHORT_QTY_CEILING )`.
`lot = instrument.size_increment` (venue `minimumTradeQty`, never a literal); cent-safe floor
decrements while `order_cost_usd(ask, qty) > cap` using the ledger's own `ROUND_UP` function so
authorisation and sizing cannot disagree (`operator_controls.py:213-215`, `_round_cost_up_to_cent`,
re-verified in round 1). `COHORT_QTY_CEILING` is §7 step 7's bounded first cohort.

### D6-R — the qty/price co-emission surface, enumerated from source and redacted site by site (R4)

The rule is one line: **no artefact this repo writes may carry a derived `qty` in the same record,
line or payload as a price or a cost.** Two numbers that individually say nothing reconstruct the
per-position cap when printed together. What follows is the complete enumeration of sites returned by a literal
`/usr/bin/grep -rn "qty=" src/breezy/strategy src/breezy/adapters/polymarket_us/exec
src/breezy/runtime`, recorded in the evidence pack per §7 step 3.

**Enumeration reconciled against the command actually run (R5 — pm defect #1, MATERIAL).** Revision 4
claimed this table was "the complete enumeration" while listing only the v3 continuous family's
take/submit path — narrower than the command it cited. **The command was re-run verbatim on
2026-09-21, and re-run again in round 6.** It returns **58 text matches** across **20 distinct
files** (`/usr/bin/grep -rl --binary-files=without-match "qty=" src/breezy/strategy
src/breezy/adapters/polymarket_us/exec src/breezy/runtime | wc -l` -> `20`). **R5 correction: revisions
4-5 said "14 files"; that figure was a transcription error and is withdrawn.** The row-level
accounting was and is complete — every one of the 20 files is named by an R-row below — so only the
headline number was wrong, and a headline number inside a "checkable, not asserted" claim that itself
fails a check is a defect, which is why §7 step 3 and AC #5 now assert the file count mechanically
(plus `__pycache__/*.pyc` binary
matches, which are build artefacts of the same sources and are excluded by `--binary-files=without-match`
in the recorded invocation). Every one of those 58 lines is accounted for below: the previously
listed sites keep their dispositions, and **seven further groups (R7–R13) are added**, including the
two co-emissions the reviewer named — `cli_settlement_print_lock/strategy.py:938` and
`runtime/backtest_harness.py:845` — which were genuinely absent from revision 4's table. The
disposition vocabulary is fixed: **REDACT** (must change), **OUT OF SCOPE, NOT REACHABLE FROM THE
LIVE SIZED PATH** (with the reason stated), or **ALREADY SAFE** (no qty/price co-emission today, held
that way by the standing scan).

**One further correction found while reconciling, not named by either reviewer, recorded rather than
quietly folded in:** the scan test's forbidden price/cost token list in revision 4 was
`limit_price`, `last_px`, `fill_px`, `price`, `cost`. `edge` belongs on it — in these strategies the
edge is `model_p - ask_p - cost` (`cli_settlement_print_lock/decision.py:112`, read from source), a
price-domain per-contract quantity, and it is co-emitted with a qty at
`running_extreme_lock/strategy.py:430-431` and `cli_settlement_print_lock/strategy.py:938-939`. The
list is **widened, never narrowed**, to `limit_price`, `last_px`, `fill_px`, `avg_px_open`,
`avg_px_close`, `limit`, `price`, `cost`, `fee`, `edge`. `p_hold_lower` and `break_even` remain
dimensionless and stay.

| # | Site | What it emits today | Required disposition |
|---|---|---|---|
| R1 | `continuous_strategy.py:2523` (`_maybe_submit` unarmed early-return INFO) | `qty={decision.quantity} px={decision.limit_price}` **in one line** | **Must change.** Drop the `qty=` field entirely; the line's diagnostic purpose (which instrument, at what price, under what permit state) is fully served without it. `p_hold_lower`/`break_even` are dimensionless and stay. |
| R2 | `continuous_strategy.py:2439` (`_latch.record_duplicate_fill(qty=…, fill_px=…, fee=…)`) | a **persisted** duplicate-fill record carrying qty and fill price together | **Must be brought into the redaction contract.** This is a record, not a log line, and today's redaction surface does not cover it (see below). Disposition: **keep the qty** (it is load-bearing for duplicate-fill accounting; it is written to the host-local `StateStore` under `DUPLICATE_FILL_KEY_PREFIX = "continuous_rung_hold/duplicate_fill/"` as `{"qty": …, "fillPx": …, "fee": …}`, `trial_day_latch.py:290`, `:893-904`, read from source) and mark the record as cap-bearing — it must never be copied into an alert `detail`, an evidence artefact, or any off-host payload. **Enforcement, restated accurately (R5 — pm defect #2 / mle defect 1): revision 4 claimed "the scan test below, which covers alert payloads and evidence writers", but no test in §7 step 3 scanned an evidence-writer path.** The alert-payload half is enforced by `test_no_alert_payload_detail_carries_a_quantity_and_a_price_together`; the evidence-writer half is enforced by the **new fifth test** `test_no_evidence_artefact_writer_copies_the_duplicate_fill_records_qty_and_price_together` (§7 step 3, AC #5). Neither is satisfied by deleting the field. |
| R3 | `strategy.py:682`, `:689`, `:702`, `:741` (the non-continuous `current_rung_hold` strategy) | the same `qty=…` shapes on fill/order/position/take lines | **Out of this item's live scope but IN the scan test's scope**: that strategy is not the family this item sizes, so its qty stays constant at 1 and leaks nothing today. The scan test covers it anyway, so sizing can never be extended to it without a RED test first. |
| R4 | `backtest_only.py:112` | same shape, backtest only | No live surface; covered by the scan test for the same reason as R3. |
| R5 | `offer_tape.py` `OfferTapeRecord.to_dict` (`:183-248`) | **no order-quantity field today** — its `size` is the venue book's size at the quote and `ask`/`exit_limit_price` are prices | **Must stay that way.** A regression test forbids adding a derived-qty field to this record: the offer tape is a persisted JSONL sidecar that this repo already copies into evidence packs. |
| R6 | `DurableFillRecord` / the fill store | the venue's own filled qty and fill price | **Unchanged and out of scope** — this is the venue's record of what happened, is required for reconciliation (AUD-04, AUD-07), and is not a Breezy-derived sizing decision. Named here so the enumeration is complete rather than silently partial. |
| R7 | `cli_settlement_print_lock/strategy.py:938` (+`:939`) — `f"ORDER {contract.instrument_id} qty={signed_delta:+.1f} " f"limit={limit_price} intent=LONG_YES edge={decision.edge:.3f} "` | **a qty, a limit PRICE and an edge co-emitted in one log record** — the site pm defect #1 named, absent from revision 4's table | **OUT OF SCOPE, NOT REACHABLE FROM THE LIVE SIZED PATH, but IN the standing scan's scope.** Reason: this is a different strategy family, not the v3 continuous family this item sizes; its `signed_delta` is derived from that family's own position-delta logic and from no operator cap, so it leaks nothing today. **It is registered in the scan test's exception registry with its exact qty expression (`signed_delta`) pinned, PLUS the two content hashes D6-R's "what the registry pin actually guarantees" paragraph requires** (emitting `_submit_delta` `:901-941` and the assigning `_maybe_submit` at `:837`), so the day anyone derives a cap-bearing qty here — at the line OR upstream of it — the test goes RED before the line ships. The expression pin alone would not have caught the upstream case. Not redacted now: redacting a dormant family's diagnostics is an unrequested change to code this item does not own. |
| R8 | `runtime/backtest_harness.py:845` (+`:846`) — `f"{position.instrument_id} qty={position.quantity} " f"(avg_px_close={position.avg_px_close})"` built into a `detail` string | **a qty and a close PRICE co-emitted** — the second site pm defect #1 named, absent from revision 4's table | **OUT OF SCOPE (backtest harness, no live surface), IN the standing scan's scope**, same registry treatment as R7 with `position.quantity` pinned and the emitting function `_refuse_open_positions` (`:833-...`) hashed; its `assigned_at` is the stated-limit Nautilus case (no Breezy assignment to hash). `position.quantity` is the Nautilus position's own observed size, not a Breezy sizing decision — but once sizing engages it becomes cap-derived downstream, which is exactly why the pin matters. |
| R9 | `running_extreme_lock/strategy.py:430` (+`:431`), `forecast_mispricing/strategy.py:498`, `calibration_mean_reversion/strategy.py:524`, `forecast_revision/strategy.py:513` | `FLATTEN`/`ORDER` lines carrying a qty; **no price token** on any of them, and `edge` on `running_extreme_lock:431` only | **ALREADY SAFE on the price axis; `running_extreme_lock:430-431` is a qty+`edge` co-emission under the widened token list and is registered like R7/R8, with both content hashes** (emitting `_submit_delta` `:410-432`, assigning `_maybe_submit` `:359-408`, `assigned_at :408`). All four are dormant non-live families; the other three are pinned by the registry with no annotation needed beyond the same two hashes. |
| R10 | `current_rung_hold/exit_authorization.py:136` — `working_sell_qty={self.working_sell_qty}` inside an `AssertionError`-class message | a qty with **no price token in the same emitted string** (`self.limit_price` is read at `:138`, in a separate check, never interpolated into this message) | **ALREADY SAFE**, and held that way: the widened scan covers this file, so adding a price to this message is RED. This is the `order_enablement.py:86-92` "name the failed precondition, never a value" precedent already in force. |
| R11 | `current_rung_hold/monitor_records.py:210`, `:390`; `monitor_evidence.py:329`; `position_monitor.py:478`, `:616`, `:637`; `exit_decider.py:302` | **persisted** monitor records: `PositionMonitorSummary.to_dict` writes `"fill_px"` and `"held_qty"` in the same mapping (`monitor_records.py:357-358`, read from source), and `PositionMarkRecord` carries `held_qty` (`:175`) | **Same class as R2 — brought into the redaction contract, not deleted.** `held_qty` is the position's observed holding (load-bearing for the exit seam, AUD-07), but once sizing engages it is cap-derived, and it sits beside `fill_px` in a persisted artefact. Disposition: keep the fields, mark these records cap-bearing, and cover them by the **same fifth evidence-writer test as R2** — which is why that test is scoped to the persisted-record surface generally and not to the duplicate-fill latch alone. |
| R12 | `runtime/paper_replay.py:357` (`qty=` beside `fill_px=` at `:355`) | a replay-constructed `FilledTrial` carrying qty and fill price | **OUT OF SCOPE, NOT REACHABLE FROM THE LIVE SIZED PATH** — offline replay over a recorded tape, never a live order. IN the widened scan's scope and registered, because replay output IS routinely pasted into evidence artefacts, so the fifth test covers it too. |
| R13 | `adapters/polymarket_us/exec/reports.py:1129`, `:1143`, `:1303`; `client.py:740`, `:759`, `:1903`, `:2119`, `:2141`, `:2207`, `:3652`, `:3659`, `:3706`; `submit_chain.py:1038`, `:1192`, `:1217`, `:1243`, `:1252`, `:1275`, `:1290`; `runtime/submit_intent.py:81` | venue-report **keyword arguments** (`filled_qty=`, `cumulative_qty=`, `order_qty=`, `last_qty=`), one resolver log line carrying `filled_qty` with **no price** (`client.py:1903`), and one code COMMENT (`submit_intent.py:81`) | **ALREADY SAFE / R6 class.** These are the venue's own observed quantities on the adapter boundary — argument passing and dataclass construction, not emitted artefacts; where a qty and a price are adjacent (`client.py:2207-2208`, `:3706-3707`, `submit_chain.py:1038-1039`) they are `last_qty=`/`last_px=` **kwargs of one venue fill report**, which is R6's "the venue's record of what happened", required for reconciliation. `client.py:1903` is a log line and carries no price token. All are inside the widened scan's directory scope and stay covered. |

**Line-by-line accounting (so "complete" is checkable, not asserted).** The 58 matches map as: R1 `continuous_strategy.py:2523`; R2 `:2439`; R3 `strategy.py:682,689,702,741`; R4 `backtest_only.py:112`; R7 `cli_settlement_print_lock/strategy.py:938`; R8 `backtest_harness.py:845`; R9 `running_extreme_lock/strategy.py:430`, `forecast_mispricing/strategy.py:498`, `calibration_mean_reversion/strategy.py:524`, `forecast_revision/strategy.py:513`; R10 `exit_authorization.py:136`; R11 `monitor_records.py:210,390`, `monitor_evidence.py:329`, `position_monitor.py:478,616,637`, `exit_decider.py:302`; R12 `paper_replay.py:357`; R13 the twenty adapter/runtime sites listed in its row. The remaining matches are non-emitting constructor kwargs in the dormant families (`forecast_mispricing/strategy.py:316,511,512`; `calibration_mean_reversion/strategy.py:332,343,537,538`; `running_extreme_lock/strategy.py:454,455`; `cli_settlement_print_lock/strategy.py:988,989`; `forecast_revision/decision.py:283,292`, `strategy.py:330,526,527`) — `PortfolioSnapshot`/decision-call arguments that reach no artefact; **R9's registry entry covers those files, so a price arriving next to any of them is RED.** R5 (`OfferTapeRecord`) and R6 (`DurableFillRecord`) carry no `qty=` token and so do not appear in the command's output at all; they are listed above because the enumeration is of the co-emission SURFACE, not only of one grep's syntax.

**Scan-test scope is made EQUAL to the cited command's scope (R5).** Revision 4 cited a three-tree
command while scoping the standing scan test to `src/breezy/strategy/current_rung_hold/` and
`src/breezy/adapters/polymarket_us/exec/` only — so AC #5's backing grep output would have
contradicted the table it was meant to validate. The scan test is **widened** to exactly
`src/breezy/strategy`, `src/breezy/adapters/polymarket_us/exec`, `src/breezy/runtime` (§7 step 3).
Narrowing the cited command instead was considered and **rejected**: it would have made the claim
accurate by shrinking the guard, and R7/R8 are real co-emissions that deserve a standing pin. To
make a widened scan GREEN without weakening it, the test carries an explicit
`_REGISTERED_CONSTANT_QTY_SITES` registry — file path, line-anchored symbol, and the **exact qty
expression text** — for R7–R13's non-cap-derived sites. A new co-emission anywhere in scope is RED;
a registered site whose qty expression text changes is RED; adding a registry entry requires the
same per-site disposition as the table above. The registry is a **named allowlist with pinned
expressions**, never a directory exclusion.

**What the registry pin actually guarantees, stated honestly, and the gap closed mechanically (R5 —
pm defect, MINOR).** The expression pin is **syntactic and local to the emission statement**. It
catches the realistic majority of edits — a price token added beside the pinned qty expression, the
qty variable renamed, the emitted string reshaped. It does **not**, on its own, catch a change that
leaves the emission text byte-identical while making the pinned expression's *value* cap-derived
upstream: if a later item sized `running_extreme_lock` by re-deriving `signed_delta` from a
per-position cap, `f"ORDER {contract.instrument_id} qty={signed_delta:+.1f} "` is unchanged, the pin
still matches, and the scan stays GREEN while the line reconstructs an operator-reserved value.
Revisions 4-5's R7/R9 wording ("the day anyone derives a cap-bearing qty here the test goes RED
before the line ships") claimed a guarantee the syntactic pin does not deliver; **that claim is
withdrawn and replaced by the mechanism below**, which does deliver it. Nothing in *this* item's own
diff re-derives any of these expressions (S2/S4b touch only the continuous family's `decision.py`,
`config.py`, `continuous_strategy.py`, `operator_controls.py`, `trial_scorer.py`), so this is a
strengthening of a standing guard, not a change in today's behaviour.

**Smallest correct strengthening: each registry entry pins TWO content hashes, not one string.**
Per site: (i) `emitting_fn_sha256` — a sha256 over the normalised source text (comments and blank
lines stripped, whitespace collapsed) of the function that *contains* the emission, and (ii)
`assigning_fn_sha256` — the same hash over the function that contains the **named upstream
assignment** of the pinned expression, recorded as an explicit `assigned_at` `file:function:line`.
Either hash changing is RED, which forces the change's author back to the per-site disposition. This
is hashing two named functions per entry, not "each family's whole order-construction path", so it
stays inside this item's scope. **Feasibility verified at three real sites, read from source:**
- **R9 — `running_extreme_lock/strategy.py:430`.** Emitting function `_submit_delta`
  (`running_extreme_lock/strategy.py:410-432`); `signed_delta` is its parameter, assigned by the
  caller at `:408` (`self._submit_delta(contract, risk_decision.clipped_quantity, decision)`) inside
  `_maybe_submit` (`:359-408`). Both functions are small, named and stable -> `assigned_at =
  running_extreme_lock/strategy.py:_maybe_submit:408`. A cap-derived rewrite of the delta necessarily
  edits `_maybe_submit` (or `decision.quantity`'s producer, reached through the same edit), so the
  second hash fires.
- **R7 — `cli_settlement_print_lock/strategy.py:938`.** Identical shape: emitting function
  `_submit_delta` (`:901-941`), `signed_delta` assigned by the caller at `:837`
  (`self._submit_delta(contract, risk_decision.clipped_quantity, decision, quote)`) inside
  `_maybe_submit` (`:761-...`) -> `assigned_at = cli_settlement_print_lock/strategy.py:_maybe_submit:837`.
- **R8 — `runtime/backtest_harness.py:845`.** Emitting function `_refuse_open_positions`
  (`:833-...`); `position.quantity` is a **Nautilus** position attribute with no Breezy-side
  assignment, so there is no second function to hash. The entry records
  `assigned_at: "nautilus:Position.quantity (no breezy assignment)"` and carries the emitting hash
  only — and that is recorded as a **stated limit**, not a silent one: a Breezy change can only make
  this value cap-derived by first sizing the order, which is the continuous family's path this item
  already guards, and Nautilus is immutable. R13's adapter kwarg sites take the same `assigned_at`
  disposition for the same reason (they carry the venue's own reported quantities).

RED test for the strengthening: `test_a_registered_site_goes_red_when_its_upstream_assignment_changes`
— mutate `_maybe_submit`'s computation of the value passed at
`running_extreme_lock/strategy.py:408` while leaving line `:430`'s emitted text byte-identical, and
assert the scan test FAILS; a negative control leaves both untouched and it passes (§7 step 3).

**The existing redaction contract does not cover any of this, and the plan must not pretend it does.**
`src/breezy/adapters/polymarket_us/redaction.py` is a **credential** redaction surface only: it
re-exports `redact_url` from `ingest/http.py:272-299` and adds `SENSITIVE_HEADERS`
(`x-pm-access-key`, `x-pm-signature`, `x-pm-timestamp`, `authorization`, `cookie`, `set-cookie`) plus
`redact_secure`/`redact_text`. It has no concept of an operator-reserved economic value, and neither
does `runtime/health.py`'s alert-payload allowlist. The adjacent precedent that IS correct to follow
is `runtime/order_enablement.py:86-92`: `OrderSubmissionRefused`'s docstring — "Every subclass names
the FAILED PRECONDITION only, never a value: no config content, no permit field, no cap amount ever
appears in a message raised from here." **D6-R extends that same principle from refusal messages to
log lines, alert payloads and evidence artefacts, and does so by editing the named sites above — not
by adding a second redaction policy** (the null hypothesis `redaction.py:7-11` itself argues for).

### D2 — S4b, qty through scorer and store

Per `:96`: `pnl = ((1 if held else 0) − fill_px − fee)·qty` with fee per contract; `_admit_fill`
drops the `qty != 1` branch and keeps `fill_below_ask` and `fee_unverified`; `ScoredTrial.qty` is
trailing and additive with legacy rows reading `qty=1` (the `TrialDayRecord.venue_order_id` compat
discipline, `trial_day_latch.py:235-242`).

### D3 — `executable_size_at_limit` comes from the TRIGGERING frame (R1, partially rejecting the "depth-staleness bound" request)

Round 1 asked for an explicit depth-staleness bound. **Inspection says a new bound would be a new
failure mode, not a control.** The decision path is *triggered by* the Depth10 frame it prices
against — PREREG v3 §2 registers the selection population as "every Depth10 ask update", and
`decision.py`'s executable gate already reads the top-of-book size off that same frame in the SAME
contracts unit as `config.minimum_displayed_size`, never dollar notional
(`_evaluate_no_side:426-446`, N2-11: "a 0.1-contract bid against a 1-contract `order_quantity`
correctly refuses"), returning `Refuse("not_executable")` when `inputs.bid`/`inputs.bid_size` (or the
YES-side equivalents) are `None`. So:

- `executable_size_at_limit` is **`inputs.ask_size` (YES) / `inputs.bid_size` (NO) from the frame
  that triggered this evaluation** — not a separately cached ladder, not a re-read of
  `strategy/depth10.py best_order`. There is nothing to go stale between the trigger and the sizing.
- Absent size → the existing `not_executable` refusal already fires, before sizing runs.
- **Therefore no new staleness constant is introduced.** Adding one would create a second freshness
  policy alongside `config.stale_observation_minutes` (`decision.py:335`) governing a different
  input, and two freshness policies on one decision is exactly how a silent divergence starts.
- A test pins this: `test_the_executable_clamp_reads_the_triggering_frame_not_a_cached_ladder`.

### D4 — Re-pins, named in advance (L-12 — widen, never relax)

`test_current_rung_hold_config.py::test_order_quantity_other_than_one_is_refused` becomes
`test_order_quantity_is_derived_not_configured`; `test_order_quantity_zero_is_refused` STAYS;
`tests/contract/test_current_rung_hold_wiring_contract.py` re-pinned.
`test_operator_control_assignment_scan.py` is **extended, never narrowed**.

## 7. Ordered implementation steps (RED first)

0. **GATE CHECK, IN CODE, BEFORE ANY SIZING CODE.** Author `sizing_gates.py` (G1/G2) and its tests
   FIRST, so the gate exists before the thing it gates. The gate asserts, by reading artefacts and
   recomputing shas: AUD-06a published a non-empty envelope **and its staleness predicate evaluates
   false today**; **AUD-18** published an edge estimate **for the family actually being sized** whose
   CI excludes 0 (and that family is registered and permitted to send orders — `pm_us_crh_v4` is
   not, per `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md`); and
   AUD-04's report is readable through its `schema_version` reader. If any is absent, **stop**: the
   correct outcome is "not built". The commit message still records the artefact paths and shas — but
   as documentation of what the tests already enforce, never as the enforcement itself.
1. **RED (gates):**
   `test_the_envelope_constant_carries_the_artefact_sha_it_was_derived_from`;
   **NEW** `test_the_edge_gate_constant_carries_the_artefact_sha_it_was_derived_from`;
   **NEW** `test_sizing_refuses_when_the_edge_artefact_is_for_a_different_family`;
   **NEW** `test_sizing_refuses_when_the_edge_ci_does_not_exclude_zero`;
   **NEW** `test_sizing_refuses_when_the_envelope_is_stale`;
   **NEW** `test_sizing_refuses_rather_than_falling_back_to_qty_one_when_a_gate_is_unsatisfied`;
   **NEW (R2)** `test_sizing_refuses_an_edge_artefact_whose_edge_unit_is_absent_or_unexpected` — the
   unit contract at the AUD-18 producer interface (`edge_unit: "usd_per_contract_after_fees"`);
   **NEW (R2)** `test_sizing_refuses_an_edge_ci_bound_exceeding_one_dollar_per_contract` — the
   structural unit-sanity check that catches a probability-scale or percentage value mislabelled as
   USD, independently of the producer's own label;
   **NEW (R2)** `test_the_pinned_envelope_sha_has_a_matching_pre_merge_sweep_record` — a bump of
   `ENVELOPE_ARTEFACT_SHA256` without a matching `ENVELOPE_SWEEP_RECORD_SHA256` is RED;
   **NEW (R2)** `test_a_gate_lapsing_mid_session_refuses_new_orders_and_cancels_nothing` — with a
   gate made stale between two sizing calls, assert the second call raises
   `SizingGateUnsatisfiedError` upstream of `_maybe_submit`, and assert **no** cancel/modify command
   is issued and no open position is touched (§12's in-flight rule; the family's orders are
   `TimeInForce.IOC`, `continuous_strategy.py:2531-2538`, so nothing rests to cancel);
   **NEW (R2)** `test_the_premerge_sweep_reads_no_operator_reserved_value` — the sweep driver and its
   published record contain no cap read, no currency figure and no cap-derived quotient;
   **NEW (R2)** `test_sizing_applies_the_side_mix_scoped_envelope_value_when_one_is_published`;
   **NEW (R7 — RULING 2 §2.3 point 3, as narrowed by addendum A2)**
   `test_a_session_stopped_on_the_derived_session_process_order_count_ceiling_is_named_distinctly_from_a_budget_stop`
   — a session stopped on the derived **session (this-process) order-count** ceiling
   (`safety.py:591-606`) must carry a **distinct, dimensionless refusal reason AND a distinct alert
   event** from one stopped on the dollar ledger (`operator_controls.py:347-426`), so a truncated
   trading day can never be read as a quiet market (the standing no-trade-day diagnosis gap). Both
   the reason and the event name the bound as the session/per-process count ceiling, and neither
   carries a value — the `order_enablement.py:86-92` "name the failed precondition, never a value"
   discipline;
   **NEW (R7 — addendum A2, on which BLOCKER-D's closure is CONDITIONAL)**
   `test_the_first_cap_sized_order_emits_a_valueless_sized_to_cap_event_once` — the **first** live
   order sized to the per-position cap under the new sizing path emits `ORDER_SIZED_TO_POSITION_CAP`,
   **logged AND delivered through the shipped alert sink** (a detector without delivery is not a
   control), deduped to that first occurrence, **carrying no qty, no price, no cost and no fee**
   (D6-R). Negative controls: a second cap-sized order emits nothing, and a non-cap-sized (depth- or
   lot-clamped) order emits nothing;
   **NEW (R7 — RULING 2 §2.3 point 2)**
   `test_no_shipped_unit_or_env_template_sets_the_explicit_session_count_override` — the
   `_session_count` env override (`safety.py:621-625`) must be **absent** from every shipped
   systemd unit and env template; setting it would create a third operator-supplied value in
   violation of `PROGRESS.md:19-24`. The test asserts absence of the variable NAME only and reads no
   operator file.
2. **GREEN (gates).**
3. **RED (S2), the MP plan's own list (`:89`) plus the clamps:**
   `test_quantity_is_the_cap_divided_by_the_ask_floored_to_the_venue_lot`;
   `test_the_derived_quantity_never_exceeds_the_position_cap_after_round_up` (property test over
   asks × caps);
   `test_quantity_is_capped_by_executable_depth_at_the_limit`;
   **NEW** `test_the_executable_clamp_reads_the_triggering_frame_not_a_cached_ladder` (D3);
   `test_a_thin_book_fill_smaller_than_requested_is_accepted_not_excluded`;
   `test_a_cap_smaller_than_one_lot_refuses_rather_than_rounds_up`;
   `test_quantity_is_never_assigned_a_literal_in_this_repo`;
   **R4, replacing the generic round-3 wording with site-named coverage:**
   `test_the_unarmed_take_log_line_carries_no_quantity_field` — RED today against
   `continuous_strategy.py:2523`, asserting the emitted line matches the instrument/price/permit shape
   and contains no `qty` token at all;
   `test_no_log_or_alert_line_in_the_take_path_carries_a_quantity_and_a_price_together` — the scan
   test. **(R5) Its scope is now EQUAL to the grep command §6 D6-R cites**: every f-string and
   logging call under `src/breezy/strategy`, `src/breezy/adapters/polymarket_us/exec` and
   `src/breezy/runtime` — widened from revision 4's two-directory scope, never narrowed. It fails if
   any single emitted string interpolates a quantity expression (`decision.quantity`, the derived-qty
   variable, `event.last_qty`, `position.quantity`, `held_qty`, `signed_delta`, `filled_qty`)
   together with a price or cost expression from the **widened** token list (`limit_price`,
   `last_px`, `fill_px`, `avg_px_open`, `avg_px_close`, `limit`, `price`, `cost`, `fee`, `edge`),
   **except** at a site present in `_REGISTERED_CONSTANT_QTY_SITES` with its exact qty expression
   text pinned **and its two content hashes recorded — `emitting_fn_sha256` and, where a Breezy-side
   assignment exists, `assigning_fn_sha256` with an explicit `assigned_at` `file:function:line`**
   (§6 D6-R, R7–R13). A new co-emission anywhere in scope is RED; a registered site whose pinned
   expression text changes is RED; **a registered site whose emitting OR assigning function's
   normalised source hash changes is RED, even when the emitted line is byte-identical** — the
   syntactic pin alone does not cover an upstream semantic change (§6 D6-R);
   the registry is an expression-and-hash-pinned allowlist, never a directory exclusion. It is RED today at `continuous_strategy.py:2523`, which is deleted rather
   than registered;
   **NEW (R5, pm MINOR — the upstream-semantics gap in the registry pin)**
   `test_a_registered_site_goes_red_when_its_upstream_assignment_changes` — RED by construction:
   mutate the computation of the value passed at `running_extreme_lock/strategy.py:408` (inside
   `_maybe_submit`, `:359-408`) while leaving the emitted line `:430` byte-identical, and assert the
   standing scan FAILS on the changed `assigning_fn_sha256`; a negative control that touches neither
   function passes. A second case does the same at `cli_settlement_print_lock/strategy.py:837`
   against the emission at `:938`. This is the test that makes R7/R9's "RED before the line ships"
   claim true rather than overstated;
   **NEW (R5, the fifth test — closes the evidence-writer half of R2/R11's enforcement claim, which
   pm defect #2 and mle defect 1 independently found unbacked)**
   `test_no_evidence_artefact_writer_copies_the_duplicate_fill_records_qty_and_price_together` — a
   scan over the **evidence-writing** code paths, named explicitly because no other test in this
   item touches them: every module under `scripts/analysis/` and `scripts/venue/` that writes a
   `docs/evidence/**` artefact, plus `src/breezy/persistence/residual_fills.py` and
   `realized_draws.py`. It fails if any of them reads a cap-bearing persisted record — the
   `DUPLICATE_FILL_KEY_PREFIX` bucket (`trial_day_latch.py:290`, payload keys `qty`/`fillPx`/`fee`,
   `:895-904`), `PositionMonitorSummary` (`monitor_records.py:357-358`, keys `fill_px`/`held_qty`),
   `PositionMarkRecord` (`:175`) or a replay `FilledTrial` (`paper_replay.py:355-357`) — and emits
   its quantity together with its price or fee into the artefact. Negative control in the same test:
   a writer emitting the price alone, or the qty alone, passes, so the test forbids the PAIR rather
   than banning the data;
   `test_the_offer_tape_record_never_gains_a_derived_quantity_field` — pinned against
   `OfferTapeRecord.to_dict`'s key set (`offer_tape.py:183-248`);
   `test_no_alert_payload_detail_carries_a_quantity_and_a_price_together` — over the
   `AlertPayload`/`emit_alert` surface, so the D6-R rule covers the off-host path too.
   **Evidence requirement (R5 — tightened so it can be satisfied honestly):** the literal output of
   `/usr/bin/grep -rn --binary-files=without-match "qty=" src/breezy/strategy
   src/breezy/adapters/polymarket_us/exec src/breezy/runtime` is pasted into the evidence pack with
   its match count, **its DISTINCT-FILE count from the same run
   (`... | cut -d: -f1 | sort -u | wc -l`), and a line-by-line mapping of every match to an R-row in
   §6 D6-R**. The scope-equality test additionally asserts that the file count stated in §6 D6-R's
   prose equals `len({file for file, _line, _text in matches})` from the same grep run, so this exact
   number can never again drift from the artefact without going RED (the round-5 "14 files" error). Revision 4's
   version of this requirement could not be met: the command's real output contradicted the table it
   was meant to back. A match with no R-row now fails the criterion (AC #5) rather than being absorbed;
   `test_the_derived_quantity_never_exceeds_the_validated_envelope`;
   **NEW** `test_the_derived_quantity_never_exceeds_the_first_cohort_ceiling_while_it_is_active`.
4. **GREEN S2.**
5. **RED (S4b), per `:95`:** `test_pnl_scales_with_qty`; `test_the_scored_trial_schema_carries_qty`;
   `test_held_matches_pnl_sign_under_qty_weighting`;
   `test_a_partial_fill_below_one_lot_is_still_excluded`;
   `test_a_thin_book_multi_contract_fill_is_scored_not_excluded`;
   plus `test_a_legacy_row_without_qty_reads_as_one`.
6. **GREEN S4b.** Update the paper-replay `FilledTrial` constructions
   (`current_rung_hold_paper_replay.py`, `whole_tape_paper_replay.py`, `runtime/paper_replay.py`)
   and re-run `test_current_rung_hold_study_replay_equivalence.py` (MP plan `:109`).
7. **PRE-MERGE realised-qty sweep (R1 MATERIAL fix — was post-merge).** Round 1 correctly observed
   that a validation which runs only after the code ships is a detector, not a gate. It does not need
   to be post-hoc: the realised qty distribution is **deterministic given the ask series and the
   cap-shape**, so it is derivable offline from the sizing function plus the historical ask tape,
   with no order placed. Therefore:
   - **(a) PRE-MERGE GATE (primary), run CAP-FREE over a dimensionless ratio grid (R2 MATERIAL
     fix).** Round 2 correctly found that "drive the sizing function over the historical ask tape to
     produce *the* realised qty distribution" cannot be executed without a concrete `cap`, which §5's
     first exclusion forbids this item from reading — and that AUD-06a solved the identical problem
     by dimensionless parameterisation while this plan did not say so. **It is resolved the same way,
     by reuse rather than by a second scheme:** the sweep runs over **AUD-06a's own `cap-shaped`
     dispersion axis**, i.e. the dimensionless budget-to-ask ratio `R` with
     `qty_i = clip(floor(R / ask_i), 1, Q_MAX_VALIDATED)` and `ask_i` drawn from the historical ask
     tape, `R` swept over AUD-06a's recorded grid `{2, 3, 5, 8, 13, 21}` — **imported from AUD-06a's
     artefact, never re-chosen here**, so the two sweeps cannot diverge.
     - The output is therefore a **curve**, not a single number: a crossing rate with a
       Clopper-Pearson one-sided 95% upper bound **per `R`**. The gate is
       `max over the swept R of CP_upper(R) ≤ 0.025` — i.e. it must hold at **every** `R`, so no
       admissible operating point is left unvalidated and none has to be identified.
     - **No cap is read, in memory or otherwise.** The sweep never learns which `R` the live system
       occupies; that is precisely why it must hold across the whole grid. The published artefact
       records `R` values and crossing rates only — no currency figure, no cap quotient, nothing from
       which a cap could be reconstructed (D6's rule, extended to this artefact).
     - **Where the envelope is `side_mix`-scoped** (AUD-06a AC #4 may publish `Q_MAX_VALIDATED` per
       `side_mix`), the sweep runs per `side_mix` too and the gate must hold in each, with
       `derive_order_quantity` applying the value matching the station-day it is sizing.
     - If a cell's raw `floor(R / ask_i)` exceeds the envelope, the clamp is what saves it — assert
       that it **binds**, rather than assuming it does not. **Merge is blocked on this.**
     - **Driver (R2 fix — named, not left to the implementer).** No existing driver does this: the two
       replay drivers in the repo, `scripts/analysis/whole_tape_paper_replay.py` (module docstring:
       "Classifies live quote-tape instances, selects one CLEAN winner per `(station, climate_day)`…
       replays only the `nws_integer_c` precision arm") and
       `scripts/analysis/current_rung_hold_paper_replay.py`, replay **decisions** over a tape, not a
       qty sweep over a ratio grid. A **new, small offline driver** is therefore built as part of this
       step: it reads the ask tape, applies `derive_order_quantity` under swept `R`, and hands the
       resulting qty distribution to AUD-06a's existing sweep entry point. It places no order, reads
       no cap, and imports `derive_order_quantity` itself rather than re-implementing the formula —
       re-implementation would defeat the gate's purpose.
     - **RE-RUN TRIGGER (R2 fix).** Step 7a is a one-time CI gate, while G1's sha pin is a runtime
       check — so a *later* re-derivation of AUD-06a's envelope (which AUD-06a §9 explicitly
       anticipates) would otherwise take effect with only the sha pin updated and no fresh sweep.
       **Standing rule: `ENVELOPE_ARTEFACT_SHA256` may not be re-pinned in `sizing_gates.py` without
       re-running step 7a's sweep against the NEW artefact in the same change.** Enforced by
       `test_the_pinned_envelope_sha_has_a_matching_pre_merge_sweep_record`: `sizing_gates.py` carries
       `ENVELOPE_SWEEP_RECORD_SHA256` alongside the envelope sha, and the test fails if the recorded
       sweep does not name the currently pinned envelope. A pin bump with a stale sweep record is a
       RED test, not a review question.
   - **(b) BOUNDED FIRST COHORT (defence in depth, not a substitute).** Even with (a) green, the
     first live cohort is explicitly bounded: `COHORT_QTY_CEILING = min(Q_MAX_VALIDATED, 2)` for the
     **first 10 sized orders**, after which the ceiling is lifted by a separate commit that cites
     AUD-04's report over that cohort. Both numbers are dimensionless build-side constants (a
     contract count and an order count); **neither is an operator-reserved cap and neither assigns a
     value to one**. The cohort is deliberately sized to be measurable without being material.
   - **(c) R-12 is RULED; the contingency is REPLACED by its consequence.** The previous revision
     made the cohort bound's adequacy contingent on an operator ruling. That ruling exists:
     `RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md` RULING 2 **KEEPS** the derived
     session order-count ceiling as a fail-closed bound (`safety.py:591-606`), with the dollar
     ledger the binding and only per-DAY control. Consequence for the cohort, stated rather than
     deferred: a 10-order cohort at qty ≤ 2 **consumes session order count faster per dollar than a
     cap-sized order does**, and the count ceiling is per-PROCESS (§12, residual R2-a), so a
     cohort spanning a mid-day relaunch gets a fresh count but not fresh spend authority. That is
     fail-closed in both directions and requires no change to the bound. **"Sizing must not merge
     before R-12 rules" is withdrawn as satisfied; merge remains blocked by BLOCKER-A and
     BLOCKER-B alone.** The count-stop must be distinguishable from a budget stop — §7 step 1's
     `..._named_distinctly_from_a_budget_stop` test.
8. **MERGE GATE (MP plan `:110`):** at qty=1 with one rung per station-day, S4a+S4b output is
   **byte-identical** to today's tally. Plus `scripts/ci/run_tests_no_egress.sh`, `lint-imports`, and
   the integration branch re-gated after the merge (L-43).

## 8. Measurable acceptance criteria and required evidence

1. **Both gates are enforced by tests, symmetrically.** `sizing_gates.py`'s six tests (§7 step 1)
   are green, and a mutation of either artefact's sha, the edge artefact's `family_id`, or its CI
   lower bound makes sizing REFUSE. Evidence: the RED→GREEN output plus a deliberate
   negative-control run showing each refusal. **Commit-message citation is documentation, not
   evidence.**
2. Property test proves `order_cost_usd(ask, qty) ≤ cap` for every `(ask, cap)` in the swept domain
   **after** round-up — the A2 property, not a spot check.
3. `qty ≤ Q_MAX_VALIDATED` (and `≤ COHORT_QTY_CEILING` while active) proven by test for every path
   that can emit an order.
4. Byte-identity at qty=1 (merge gate) — the single most important criterion, because it proves the
   change is inert until sizing actually engages.
5. **No journal line, alert payload or evidence artefact carries a derived qty together with a price
   or a cost — enforced at the NAMED sites, not by a generic scan alone (R4; extended R5).**
   `continuous_strategy.py:2523` is shown by diff to have lost its `qty=` field;
   `test_the_unarmed_take_log_line_carries_no_quantity_field` is RED before that change and GREEN
   after; **all SIX** scan/pin tests in §7 step 3 are green (five from R5 plus the round-6
   `test_a_registered_site_goes_red_when_its_upstream_assignment_changes`) — the fifth being
   `test_no_evidence_artefact_writer_copies_the_duplicate_fill_records_qty_and_price_together`, with
   its own RED→GREEN pair, which is what makes R2's and R11's "never copied into an evidence
   artefact" claim an enforced property rather than an assertion; and the §6 D6-R enumeration's
   backing grep output is in the evidence pack. **(R5) That grep output must now AGREE with the
   table:** the evidence pack carries the verbatim output of
   `/usr/bin/grep -rn --binary-files=without-match "qty=" src/breezy/strategy
   src/breezy/adapters/polymarket_us/exec src/breezy/runtime`, its match count, and a line-by-line
   mapping of every match to an R-row — a match with no row is a FAILING criterion, not a
   documentation gap. **(R5) The scan test's directory scope is asserted EQUAL to that command's
   scope by the test itself** (a constant shared between the test and the recorded invocation), so
   the two cannot drift apart again; **the evidence pack's DISTINCT-FILE count (20 at the round-6
   re-run) is asserted equal to `len(set(files))` from the same run**, so the headline number is
   checked mechanically rather than by re-review; and `_REGISTERED_CONSTANT_QTY_SITES` is asserted to
   contain only sites carrying a disposition in the §6 D6-R table, **each with its
   `emitting_fn_sha256` and (where a Breezy-side assignment exists) its `assigning_fn_sha256` +
   `assigned_at`**. `test_a_registered_site_goes_red_when_its_upstream_assignment_changes` is green,
   with its RED→GREEN pair, so the registry's guarantee covers an upstream semantic change and not
   only the emission text. Review is not evidence for this criterion.
   **Coverage claims re-checked against the §7 test list this revision (R5), since an unbacked one
   was what both reviewers caught:** log lines → test 1 and test 2; the offer-tape record → test 3;
   alert payloads → test 4; evidence-writer paths and persisted cap-bearing records → test 5;
   **upstream semantic drift at a registered constant-qty site → test 6**. No
   other coverage is claimed anywhere in §6, §7 or §8; the R7–R13 dispositions claim only the
   standing scan (test 2) plus, for R11/R12, test 5, plus test 6 for the registry's hashes — and
   R8/R13's `assigned_at` limit (no Breezy-side assignment to hash) is stated in §6, not claimed away.
6. **The PRE-MERGE realised-qty sweep (R2 — restated over a well-defined, reproducible quantity).**
   The sweep is run over AUD-06a's imported dimensionless `R` grid `{2, 3, 5, 8, 13, 21}`, and the
   criterion is `max over swept R (and over each published side_mix) of the Clopper-Pearson one-sided
   95% upper bound on the crossing rate ≤ 0.025` — a curve with a stated maximum, not an
   underspecified "realised qty distribution". The clamp is shown to bind at every `R` where raw
   `floor(R / ask_i)` exceeds the envelope. **No cap value is read to produce it**, proven by
   `test_the_premerge_sweep_reads_no_operator_reserved_value`, and the published sweep record carries
   no currency figure. Evidence: the per-`R` table, the driver's source, and the sweep record whose
   sha is pinned as `ENVELOPE_SWEEP_RECORD_SHA256`.
7. Full RED→GREEN output; suite totals move by exactly the tests added, with `skipped/deselected/
   xfailed` counts accounted for (the MP/T-4 merge-gate discipline).
7b. **(R2) The G2 edge unit is enforced, not trusted.** An artefact whose `edge_unit` is absent or
   not `"usd_per_contract_after_fees"` makes sizing REFUSE, and so does one whose CI bound exceeds
   `1.0` USD per contract. Evidence: two negative-control runs.
7c. **(R2) The envelope pin cannot advance without a fresh sweep.**
   `test_the_pinned_envelope_sha_has_a_matching_pre_merge_sweep_record` is green, and a deliberate
   mutation of `ENVELOPE_ARTEFACT_SHA256` alone turns it RED. Evidence: the negative control.
7d. **(R2) A mid-session gate lapse refuses NEW orders only and alters nothing already submitted.**
   Proven by `test_a_gate_lapsing_mid_session_refuses_new_orders_and_cancels_nothing`.
7e. **(R7) A count-ceiling stop is legible, and the cap-sized transition is announced.** Two
   acceptance items from the 09-21 ruling: (i)
   `test_a_session_stopped_on_the_derived_session_process_order_count_ceiling_is_named_distinctly_from_a_budget_stop`
   is green — a session stopped on the derived session/per-process order-count ceiling carries a
   distinct dimensionless refusal reason **and** a distinct alert event from a dollar-ledger stop,
   with a negative control showing a budget stop still produces the budget reason; and (ii)
   `test_the_first_cap_sized_order_emits_a_valueless_sized_to_cap_event_once` is green —
   `ORDER_SIZED_TO_POSITION_CAP` is **logged and delivered through the shipped alert sink** on the
   first cap-sized order only, carrying no qty, price, cost or fee, with negative controls for the
   second cap-sized order and for a clamped order. **BLOCKER-D's build-side closure is CONDITIONAL
   on (ii): without that event the qty=1 → cap-sized transition is a silent behaviour change**
   (addendum A2). Evidence: the RED→GREEN pairs plus a captured sink delivery.
7f. **(R7) No third operator-supplied value is introduced.**
   `test_no_shipped_unit_or_env_template_sets_the_explicit_session_count_override` is green: the
   `_session_count` override (`safety.py:621-625`) is absent from every shipped unit and env
   template. Evidence: the test output; no operator file is read.
8. **Post-merge, live, over the bounded first cohort:** the first sized order's cost appears in
   AUD-04's report (read through its `schema_version` reader) and in `DailySpendLedger`'s
   authorisation, and the two agree to the cent. AUD-04 being live is a **hard** precondition of
   this criterion, not a soft read.
9. **Cohort review before the ceiling lifts:** realised P&L after fees and capital deployed over the
   10-order cohort, from AUD-04's named fields, compared against the matched pre-sizing period
   against B0/B1 — recorded in the lifting commit.

## 9. Validation: failure cases, integration, autonomous operation

- **A gate artefact is missing, mis-family, stale or its CI includes 0** → `SizingGateUnsatisfiedError`,
  refuse. **Never a silent fall-back to qty=1**, because a silent fall-back would hide that the
  preconditions lapsed.
- **Cap smaller than one lot** → refuse, never round up. Rounding up is an assignment of a value
  above the operator's cap.
- **Thin book** → qty clipped to `executable_size_at_limit` from the triggering frame; a fill
  smaller than requested is ACCEPTED at its filled qty (M3), not excluded — but a fill below one lot
  stays `partial_fill`.
- **Depth absent on the triggering frame** → the pre-existing `not_executable` refusal fires before
  sizing (D3); no order is priced or sized off an unknown ladder (L-7/L-9).
- **Two arms racing on one station-day** → the account-wide `SubmitIntentLatch` still permits one
  order in flight (MP plan `:101`), and the duplicate-fill family halt still catches a second fill.
- **Daily exposure bound — ESTABLISHED for the per-DAY dimension (R7), by ruling.** Worst-case
  daily exposure is `min(daily budget, Σ cost_i)` with every `cost_i ≤ per-position cap`, enforced
  under one lock (`operator_controls.py:341-345`, `:347-426`); the formula is unchanged and only the
  number of `i` grows. The round-1 provisional label is **lifted**: RULING 2 keeps the derived count
  ceiling as a second, strictly conservative bound that can only stop the day EARLIER, never
  authorise more spend, and the dollar ledger is the binding per-DAY control. **What remains stated,
  not hidden:** the count bound is per-PROCESS (§12 residual R2-a), so only the dollar half of this
  bound survives a mid-day relaunch — which is precisely why the dollar ledger, not the count, is
  the per-day control.
- **The permit's session ORDER-COUNT ceiling** (`_derived_session_order_count`,
  `safety.py:591-606`) interacts with sizing: larger orders exhaust dollars sooner, smaller ones
  exhaust the count. **RULED build-side 2026-09-21: the ceiling is KEPT**, and a stop on it must be
  named distinctly from a budget stop (§7 step 1, AC #7e) so a truncated day is never read as a
  quiet market.
- **Autonomous operation:** sizing runs inside the existing live loop; no new unattended surface,
  no new timer, no new recovery path. The recovery property that matters is that every clamp AND
  every gate is fail-closed (refuse, not resize, not fall back) so an unattended node cannot spend
  its way out of a bad or lapsed input.

## 10. Deployment, observability, rollback

- **Deploy:** merged code takes effect at the next node respawn (a merged fix is not live until the
  node respawns — a lesson this repo has already paid for). No unit change.
- **Observability:** AUD-04's report is the primary read; `DailySpendLedger` authorisation lines and
  `SizingGateUnsatisfiedError` refusals are the runtime signal. **Deliberately no qty in the journal**
  — and after §6 D6-R that is true of `continuous_strategy.py:2523` too, which today prints one
  (R4 correction: revision 3 wrongly described this line as already redacted behind a `qty_present`
  token that does not exist).
- **Rollback:** revert to `order_quantity = 1`. The revert is safe and total *for future orders*;
  positions already opened at qty > 1 are not unwound by it, so the rollback statement is
  "stop sizing", never "undo". **Compensating control (R1 gap, now closed):** the bounded first
  cohort (§7 step 7b) is the compensation — it caps how much un-unwindable exposure a bad sizing
  decision can create before a human has read AUD-04's cohort numbers. State this explicitly at
  merge.

## 11. Relationship to portfolio-level ROI and how it is evaluated

**Channel: direct and bidirectional. This is the only item in the backlog that can move ROI in
magnitude rather than in knowledge — and it moves it in whichever direction the edge points.**

**The evaluation path, by field.** Evaluated **exclusively** through AUD-04's versioned report,
read through its `schema_version` reader, never by the sequential family verdict (different
estimand, L-2):

| Quantity | AUD-04 field | Comparison |
|---|---|---|
| realised return | `realised_pnl_after_fees_total` | cohort period vs matched pre-sizing period |
| denominator | `capital_deployed_total` | same, leg-summed |
| headline | `roi`, `roi_minus_b0`, `roi_minus_b1` | against AUD-04's registered B0/B1 |
| honesty gate | `n_fills`, `power_caveat` | read BEFORE any of the above |
| integrity | `unexplained_flow_days` | must be 0 for the comparison to mean anything |

**Baseline.** AUD-04's B0 (cash on the same deployed capital) and B1 (fee-drag null), both fixed
before the cohort runs, plus the matched pre-sizing period's own realised figures. No comparator is
chosen after the numbers are seen.

**Plausible vs demonstrated, separated explicitly:**

| Claim | Status |
|---|---|
| "Sizing scales returns by `(qty − 1)` where an edge exists" | **PLAUSIBLE, and strictly `sign(E[pnl]) × (qty − 1)`.** |
| "An edge exists for this family" | **NOT DEMONSTRATED today, and the family that would have carried it may not send orders** — `RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` halts `pm_us_crh_v4` on this surface; the edge estimate is owned by **AUD-18**, and a CONFIRMED hypothesis plus a newly registered family are prerequisites. That is BLOCKER-B, code-enforced (G2), never asserted. |
| "This item improves portfolio ROI" | **NOT CLAIMED, and not claimable until the cohort review (AC #9) reads AUD-04's fields over a matched period.** |
| "This item can reduce portfolio ROI" | **TRUE and load-bearing.** It is why the item is P3, gated twice in code and twice by ruling, and bounded on first exposure. |

**How it is evaluated.** AC #9: realised P&L and capital deployed over the bounded 10-order cohort
against the matched pre-sizing period and AUD-04's baselines, recorded in the commit that lifts the
cohort ceiling. A negative cohort result reverts to `order_quantity = 1` rather than being explained
away.

**Falsifier.** If sizing can ship while either gate artefact is absent, stale or mis-attributed —
or if the cohort ceiling can be lifted without an AUD-04-backed comparison — this item has failed
regardless of what the P&L happens to do.

**Dependency ordering.** Stage 3, last. Preconditions: AUD-06a (envelope + staleness), **AUD-18**
(the edge estimate, after the A1 ruling; itself downstream of AUD-05's tally) and the registration
of the new family it would apply to, AUD-04 (evaluation substrate). **R-12 and the per-position
spend question are no longer preconditions — both are RULED build-side (§12).**

## 12. Assumptions, unresolved questions, blockers

- **BLOCKER-A: AUD-06a** must publish a non-empty envelope **and a staleness predicate**, both
  consumed as sha-pinned artefacts (G1), not as a remembered number.
- **BLOCKER-B: a demonstrated, family-scoped edge** must be published as a sha-pinned artefact whose
  CI excludes 0, consumed by G2 and checked by tests — **symmetrically with BLOCKER-A**.
  **Re-grounded (R7):** `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` (ENDORSED)
  rules `pm_us_crh_v4` **may not send orders** on this surface, and the edge estimate is now owned by
  **AUD-18**, not AUD-02 (cited by id and path only; nothing about its outcome is assumed).
  **Therefore AUD-06b cannot be executed until an AUD-18 hypothesis is CONFIRMED and a new family is
  registered to carry it.** Unlike BLOCKER-A — which is pure sequencing behind a planned item —
  BLOCKER-B is an **evidence precondition: no peer ruling can manufacture it**, and the 09-21
  rulings did not.
- **~~BLOCKER-C~~ — R-12 (`PROGRESS.md:75`): RULED BUILD-SIDE 2026-09-21, no longer a blocker and
  not an operator question.** Artefact:
  `docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md` RULING 2, as amended by
  its **Revision 2 addendum A2**; peer trail `docs/evidence/reviews/RULING_study_ceiling_exit_review_2026-09-21.md`
  (ENDORSE). What it settles: the **derived session order-count ceiling is KEPT** as a fail-closed
  bound — it is arithmetic over the two caps (`_derived_session_order_count`, `safety.py:591-606`),
  carries no operator-supplied value, and can only ever stop the day EARLIER, never authorise more
  spend; **the dollar ledger is the binding and only per-DAY control**; **no explicit session-count
  override may be set** — the `_session_count` env path (`safety.py:621-625`) stays unset, because
  setting it would introduce a third operator-reserved value against `PROGRESS.md:19-24`, pinned by
  §7 step 1's absence test over shipped units and env templates (names only, no value); and a
  count-ceiling stop must be named **distinctly** from a dollar-ledger stop (§7 step 1, AC #7e).
  **§9's exposure bound is no longer provisional.**
- **Residual R2-a (addendum A2, recorded here verbatim as that addendum requires).** The dollar side
  reseeds **durably** across a relaunch — `DailySpendLedger.seed_spent`
  (`operator_controls.py:306-331`) and `seed_permit_budget_from_prior_spend` for the permit's
  notional (`safety.py:781-792`) — while a fresh mint sets `remaining_order_count` to the **full**
  derived ceiling every time (`safety.py:735-738`), the docstring being explicit that seeding never
  touches the order-count budget, "which counts orders this permit itself authorises, not
  prior-process spend" (`safety.py:786-789`). With the documented 3×/day mid-day relaunch, **the
  count ceiling is per-PROCESS, not per-DAY.** The **dollar ledger remains the only per-DAY bound**,
  and that is what the "can only ever stop the day earlier, never authorise more spend" claim rests
  on — it survives, because a relaunch restores order *count*, never spend authority. **Per-process
  is ACCEPTED as fail-closed**; the count is **not** made durable, because doing so would add new
  durable state to the permit seam — the highest-consequence seam in the repo — for protection the
  dollar ledger already provides. Conditions carried: (1) the distinct refusal/alert event names the
  bound as the **session (this-process) order-count** ceiling, so a count-stop can never be read as
  a day stop; (2) these per-process semantics are stated **here, in AUD-06b §12**, rather than filed
  as a new item. **Making order count a per-DAY control would be a separate new durable-state item —
  it is not this one, and it is not an operator value and never becomes one.**
- **~~BLOCKER-D~~ — the per-position spend question: RULED BUILD-SIDE 2026-09-21, CLOSED
  CONDITIONALLY, not a no-op.** Same artefact (RULING 2 §2.3 point 4 as **superseded** by addendum
  A2). The per-position cap's semantics are unchanged by AUD-06b: it authorises **per order** today
  and after sizing, through the same `DailySpendLedger.authorize_order_cost` seam
  (`operator_controls.py:347-426`), which this item consumes as a seam and never as a number. Asking
  the operator to re-affirm a value they have already set would make them an input to a decision the
  contract assigns to us. **The closure stands only if this item emits a distinct, dimensionless,
  VALUELESS `ORDER_SIZED_TO_POSITION_CAP` event — logged and delivered through the shipped alert
  sink, deduped to the FIRST live order sized to the per-position cap under the new sizing path,
  carrying no qty, price, cost or fee (D6-R)** — §7 step 1 and AC #7e(ii). Without it the qty=1 →
  cap-sized transition is a silent behaviour change; with it, no operator input is needed and no
  value is restated. **No value is stated, proposed or implied here or anywhere in this plan.**
- **What these two closures do NOT do.** They remove two *mis-classified* gates, not the two real
  ones. **BLOCKER-A and BLOCKER-B stand untouched**, and sizing an unproven edge still multiplies a
  negative expectation (§3).
- **DECISION (R2 — was a recommendation; round 2 correctly asked for a decision with a named
  re-evaluation trigger):** `max_equity_fraction` (`weather_common/risk.py:557-563`) is **NOT adopted
  as a fourth clamp in this increment.** Reason, unchanged and load-bearing: its denominator is the
  UNVERIFIED `currentBalance` semantics (T-4 §4), so adding an equity-denominated clamp in the same
  change that introduces sizing would introduce a new failure mode on an unestablished quantity.
  **Named re-evaluation trigger, now a criterion rather than an implication:** this decision is
  re-opened — and a follow-up item filed — **when AUD-04 publishes its balance-semantics finding**
  (its step-0 evidence doc plus the `schema_version`-read balance series), which is the artefact that
  would make the denominator verified. Until that artefact exists the question is not re-litigated;
  once it exists, not re-opening it is itself a defect. This is recorded so the deferral cannot
  quietly become permanent.
- **Build-side constants, stated not escalated:** `COHORT_QTY_CEILING = min(Q_MAX_VALIDATED, 2)` and
  a 10-order first cohort. Both are dimensionless (a contract count, an order count), both are
  build-side like `order_quantity` itself, and **neither is nor assigns an operator-reserved cap**.
- **DISPOSITION OF IN-FLIGHT ORDERS WHEN A GATE LAPSES MID-SESSION (R2 fix — round 2 asked what
  happens to an in-flight but unfilled order when e.g. the envelope goes stale intraday).** Verified
  against the execution path before answering: the live family submits with
  `time_in_force=TimeInForce.IOC` and `post_only=False`
  (`src/breezy/strategy/current_rung_hold/continuous_strategy.py:2531-2538`, inside `_maybe_submit`),
  through `self.submit_order(order)` at `:2540`. **Consequences, stated as the rule:**
  1. **An IOC order never rests**, so there is by construction no resting order derived under a
     now-stale gate to cancel. The in-flight window is one venue round trip; it either fills or
     expires at the venue.
  2. **Fail closed for NEW orders only.** A gate lapse makes `derive_order_quantity` raise
     `SizingGateUnsatisfiedError` at the next sizing call, upstream of `_maybe_submit`, so no further
     order is submitted. This is the same fail-closed posture as every other clamp here.
  3. **Never cancel, modify, or otherwise alter the safety behaviour of an order already submitted,
     and never touch an open position.** A gate lapse is a sizing-authority condition, not a market
     event; introducing a cancel path would add a new order-path behaviour under exactly the
     condition in which this item has least confidence, and would touch the execution seam this plan
     otherwise leaves alone. An already-filled position is managed by the existing (unarmed) exit
     seam and by settlement, unchanged by this item.
  4. **The resting-bid family is out of scope and unaffected:** `pm_us_crh_rest_v5` is shadow-only,
     is not sized by this item (§5), and if it is ever armed the rule in (1) must be revisited
     because a resting order *can* outlive a gate lapse. Recorded here so that revisit is not missed.
  Covered by `test_a_gate_lapsing_mid_session_refuses_new_orders_and_cancels_nothing` (§7 step 1) and
  AC #7d.
- **Assumption:** the node respawns daily, so the change lands within 24h of merge.
- **Assumption (load-bearing for §7 step 7a), NARROWED by the R2 cap-free restatement:** the qty
  distribution **at a given dimensionless `R`** is reproducible offline from `derive_order_quantity`
  and the historical ask tape. The round-2 version of this assumption ("*the* realised qty
  distribution") was the defect — it silently required a cap. The narrowed form requires only the ask
  series, which the tape carries. If even this fails — e.g. if `executable_size_at_limit` turns out to
  depend on live-only depth the tape does not carry, in which case the sweep must state that the clamp
  is evaluated only at its unbounded limit — then step 7a cannot be a pre-merge gate and the
  disposition falls back to the bounded cohort alone, **which must be recorded as a weakening at
  merge**, not absorbed silently.

## 13. Review history

**Baseline self-score (2026-09-21, author), 74/100** — carried-forward weaknesses folded into the
Revision 2 table below.

### Round 1 (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| mle-reviewer (statistical validation / measurement engineering) | 73/100 |
| prediction-market-reviewer (portfolio accounting / risk) | 69/100 |

**Dispositions:**

| # | Reviewer | Defect | Disposition |
|---|---|---|---|
| 1 | pm | MATERIAL — the two hard preconditions are enforced asymmetrically, and the more dangerous one (BLOCKER-B, the edge) is unenforced | **ACCEPTED IN FULL; this is the largest change in the revision.** Verified: the previous §7 step 0 gated BLOCKER-B on "assert in the commit message", while BLOCKER-A had a sha-checking test — exactly the asymmetry described, on the precondition whose violation loses money. New §6 G1/G2 put both constants in one new module `src/breezy/persistence/sizing_gates.py`, built on the existing `gs_boundary_artefact.py` sha-recompute idiom, and `derive_order_quantity` raises `SizingGateUnsatisfiedError` on any of five conditions (artefact absent, sha mismatch, **wrong `family_id`** — the B-1 error, CI not excluding 0, stale envelope). Five new RED tests (§7 step 1), AC #1 requires a negative-control run per refusal, and §7 step 0 now builds the gate BEFORE the code it gates. Commit-message citation is explicitly demoted to documentation. |
| 2 | mle | MATERIAL — the envelope re-check runs post-merge; it is a detector, not a precondition | **ACCEPTED, taking option (i) AND adding (ii).** §7 step 7a makes the realised-qty sweep a **pre-merge gate**, justified by the observation that the realised qty distribution is deterministic given the ask series and cap-shape, so it is derivable offline with no order placed — the reviewer's premise that it "runs only after sizing has gone live" was itself avoidable. §7 step 7b **additionally** bounds the first cohort (`COHORT_QTY_CEILING = min(Q_MAX_VALIDATED, 2)`, first 10 sized orders, ceiling lifted only by a commit citing AUD-04's cohort numbers), so the reviewer's fallback is carried as defence in depth rather than as an alternative. §7 step 7c states the bound's **contingency on R-12** explicitly. §12 records the load-bearing assumption behind 7a and requires any fallback to the cohort-only posture to be recorded as a weakening at merge. |
| 3 | mle | §7 step 0's gate should assert AUD-06a's re-validation trigger, not just "an envelope was published" | **ACCEPTED.** G1 carries `ENVELOPE_BE_PRIOR_SUPPORT` and `envelope_is_stale(...)` from AUD-06a's artefact; condition 4 of the §6 gate makes a stale envelope a refusal, and `test_sizing_refuses_when_the_envelope_is_stale` enforces it. AUD-06a ships the predicate precisely so this consumer can check it. |
| 4 | pm | MINOR — §9's exposure bound is stated as unconditional when it is contingent on R-12 | **ACCEPTED.** §9's bound is relabelled PROVISIONAL with the contingency stated inline, and §7 step 7c plus §12 BLOCKER-C repeat it. |
| 5 | both | `Q_MAX_VALIDATED`'s home module unspecified | **ACCEPTED.** `src/breezy/persistence/sizing_gates.py`, beside `gs_boundary_artefact.py` and following its loader idiom. |
| 6 | both | The depth-staleness bound for the clamp is unspecified | **PARTIALLY REJECTED, with the underlying concern accepted and closed differently.** Inspection of `decision.py`'s executable gate (`_evaluate_no_side:426-446`) plus PREREG v3 §2 ("trigger every Depth10 ask update") shows the decision is triggered by the very frame it prices against, and the gate already refuses `not_executable` when the frame carries no size. There is therefore **no separately cached ladder that can go stale**, and introducing a staleness constant would create a second freshness policy alongside `config.stale_observation_minutes` (`decision.py:335`) — a divergence risk, not a control. §6 D3 instead pins the source (`inputs.ask_size`/`inputs.bid_size` from the triggering frame) and adds `test_the_executable_clamp_reads_the_triggering_frame_not_a_cached_ladder`. This also **corrects the previous revision**, which wrongly described the clamp as reading "the cached Depth10 ask ladder via `strategy/depth10.py:31 best_order`". |
| 7 | author-carried | AC #8 depends on AUD-04 shipping first, stated as a soft read | **ACCEPTED.** §4 and AC #8 make AUD-04 a **hard** precondition of evaluation (not of the build), and §7 step 0's gate checks that AUD-04's report is readable through its `schema_version` reader. |
| 8 | author-carried | Rollback is honestly partial (open positions are not unwound), with no compensating control | **ACCEPTED.** §10 names the bounded first cohort as the compensating control and requires the statement at merge. |
| 9 | both | "Portfolio objective alignment" 3/10 | **ACCEPTED in cause; the low-EV reality is NOT softened.** The cause was that §11 asserted conditionality without an evaluation contract. §11 now gives the field-level path into AUD-04, the registered baselines, a four-row plausible-vs-demonstrated table that explicitly includes "this item can REDUCE ROI" as load-bearing, the AC #9 cohort review rule, a falsifier, and the dependency stage. The item remains P3, gated twice in code and twice by ruling, and its expected value today is still negative — restated, not dressed up. |

**Rejections:** one partial (#6 — a new depth-staleness constant is rejected as a control on the evidence that the sizing clamp reads the triggering frame; the concern is closed by pinning the source and adding a test). All four blockers remain blockers; none is resolved by this revision or by any reviewer.

**Revision 2 self-score (2026-09-21, author), 84/100:**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 17 | Re-scopes MP-B rather than duplicating it, and now adds the edge-gate artefact the audit could not have known about. Still loses points for deferring `max_equity_fraction` — which G-11 names — to a later item, and for leaving the deferral as a recommendation rather than a decision. |
| Technical correctness and evidence grounding | 20 | 18 | Native per-order notional cap verified against installed Nautilus source and re-confirmed by both reviewers; the previous revision's incorrect description of the depth clamp's source is corrected against `decision.py`; the gate-loader pattern reuses an existing module idiom. Loses points because the formula and most tests are still inherited from the MP plan and re-verified by reading it rather than independently against current line numbers. |
| Implementation specificity and feasibility | 15 | 13 | Gate module, five refusal conditions, clamp source, cohort constants, re-pins and merge gate are all named. Loses points because §7 step 7a's offline replay of the sizing function over the ask tape is specified by intent rather than by harness — the implementer must establish which existing replay driver can carry it. |
| Acceptance criteria and validation quality | 20 | 18 | Byte-identity merge gate, a property test, symmetric gate negative-controls, a pre-merge envelope re-check and a cohort review. Loses points because AC #8 and AC #9 cannot be exercised at all until trading resumes (G-01) — the item can be merged and still be unevaluable for an unbounded period. |
| Autonomous operation, failure handling, recovery | 15 | 13 | Every clamp AND both gates are fail-closed with no silent fall-back to qty=1; the partial rollback now has a named compensating control. Loses points because rollback remains genuinely partial for already-open positions, and because a gate that lapses mid-session refuses new orders but cannot act on existing exposure. |
| Portfolio objective alignment, scope, dependencies | 10 | 5 | §11 is now a field-level evaluation contract with registered baselines, an explicit "this can reduce ROI" row, a cohort-review decision rule and a falsifier; the money-losing precondition is code-enforced rather than asserted. Still the lowest score in the cluster, correctly: this is the only item that can lose money, its expected value today is negative with no proven edge anywhere, and it is blocked on two build items and two operator rulings it does not own. |

### Round 2 (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| prediction-market-reviewer (portfolio accounting / risk) | 89/100 |
| mle-reviewer (statistical validation / measurement engineering) | 74/100 |

**Round-2 readiness is the LOWER of the two: 74/100.**

**Dispositions (every defect, both reviewers):**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | mle | MATERIAL | §7 step 7a's pre-merge sweep — the round-1 fix that made the envelope re-check a merge gate — does not say how it obtains a qty distribution without reading the operator-reserved cap that §5 forbids. `derive_order_quantity` is a monotonic function of `cap`, so "drive it over the ask tape to produce *the* realised qty distribution" either reads the cap or is underspecified; AUD-06a solved the same problem by dimensionless parameterisation and said so, this plan did not | **ACCEPTED in full — the reviewer's reading is correct and the defective article is literally the word "*the*".** Resolved by **reuse, not by a second scheme**, exactly as the reviewer asked: step 7a now runs over **AUD-06a's own `cap-shaped` axis**, `qty_i = clip(floor(R / ask_i), 1, Q_MAX_VALIDATED)` with `ask_i` from the historical ask tape and `R` — a dimensionless budget-to-ask ratio — swept over AUD-06a's recorded grid `{2, 3, 5, 8, 13, 21}`, **imported from AUD-06a's artefact rather than re-chosen here** so the two sweeps cannot diverge. The output is a **curve, not a number**: a Clopper-Pearson upper bound per `R` (and per `side_mix` where AUD-06a publishes one), and the gate is `max over the grid ≤ 0.025` — it must hold at **every** admissible operating point, so the sweep never needs to learn which one the live system occupies. No cap is read, in memory or otherwise; the published record carries `R` values and rates only, no currency figure and no cap quotient, enforced by `test_the_premerge_sweep_reads_no_operator_reserved_value`. §12's load-bearing assumption is narrowed accordingly (the old wording "*the* realised qty distribution" was the defect; the narrowed form needs only the ask series, which the tape carries). |
| 2 | mle | MATERIAL (consequent) | AC #6's merge-blocking Clopper-Pearson criterion cannot be objectively verified because its underlying quantity is ambiguous | **ACCEPTED.** AC #6 is restated over a well-defined, reproducible quantity: `max over the swept R (and each published side_mix) of CP_upper ≤ 0.025`, with the per-`R` table, the driver's source and a sha-pinned sweep record as evidence. |
| 3 | pm | MINOR | Step 7a's pre-merge gate is a one-time CI check while G1's sha pin is a runtime check, so a later re-derivation of AUD-06a's envelope (which AUD-06a §9 anticipates) could take effect with only the pin updated and no fresh sweep | **ACCEPTED.** A standing rule is added: `ENVELOPE_ARTEFACT_SHA256` may not be re-pinned without re-running step 7a against the NEW artefact **in the same change**. It is enforced mechanically, not by review: `sizing_gates.py` carries `ENVELOPE_SWEEP_RECORD_SHA256` alongside the envelope sha and `test_the_pinned_envelope_sha_has_a_matching_pre_merge_sweep_record` goes RED on a pin bump with a stale sweep record. AC #7c and a negative control carry it. |
| 4 | pm | MINOR | G2's `edge_ci_lower <= 0` refusal assumes a sign/unit convention for "edge" that this plan does not define, and AUD-02 (the producer) is outside the review set — a unit mismatch is the one thing that can lose money here | **ACCEPTED, and hardened past the request.** §6 G2 now states the convention explicitly: `edge_ci_lower`/`edge_ci_upper` are **USD of expected P&L per ONE contract, after fees** — the same unit `order_cost_usd` uses, so §3's `E[pnl] × qty` framing is literally true — and explicitly not probability-scale, per-dollar or percentage. Two independent enforcements rather than one: (i) a **contractual** `edge_unit: "usd_per_contract_after_fees"` field the gate refuses when absent or different, so a producer that changes units fails closed instead of being reinterpreted; (ii) a **structural** sanity assertion refusing `abs(edge_ci_*) > 1.0` USD per contract, since a binary settles in `[0, 1]` and no per-contract edge can exceed the whole payout — this catches a mislabelled probability or percentage even if the producer's own label is wrong. Two new RED tests; AC #7b. The interface obligation on AUD-02 is named by id, per the brief's cross-item rule. |
| 5 | pm | MINOR | The `max_equity_fraction` deferral is a recommendation, not a decision with a re-evaluation trigger | **ACCEPTED.** §12 now records it as a **DECISION** — not adopted this increment, with the unchanged reason (an equity-denominated clamp on the UNVERIFIED `currentBalance` semantics, T-4 §4, would add a new failure mode in the same change that introduces sizing) — plus a **named re-evaluation trigger that is itself a criterion**: the decision re-opens, and a follow-up item is filed, when AUD-04 publishes its balance-semantics finding. Stated explicitly so the deferral cannot quietly become permanent: once that artefact exists, *not* re-opening the question is itself a defect. |
| 6 | pm | MINOR | The offline-replay harness for step 7a is specified by intent, with no named driver | **ACCEPTED, and answered by inspection rather than by deferral.** Both existing replay drivers were read: `scripts/analysis/whole_tape_paper_replay.py` (module docstring — "Classifies live quote-tape instances, selects one CLEAN winner per `(station, climate_day)`… replays only the `nws_integer_c` precision arm at the live lags") and `scripts/analysis/current_rung_hold_paper_replay.py` both replay **decisions** over a tape; neither performs a qty sweep over a ratio grid. **Conclusion stated in the plan: none exists and a new small driver must be built** as part of step 7a — it reads the ask tape, applies `derive_order_quantity` under swept `R`, and hands the distribution to AUD-06a's existing sweep entry point, importing the sizing function rather than re-implementing it (a re-implementation would defeat the gate). |
| 7 | pm | MINOR | Rollback cannot act on already-open positions, and the plan does not state whether an in-flight but unfilled order is affected when a gate lapses mid-session | **ACCEPTED, and answered from source rather than by assertion.** Verified before writing: the live family submits with `time_in_force=TimeInForce.IOC` and `post_only=False` at `src/breezy/strategy/current_rung_hold/continuous_strategy.py:2531-2538` inside `_maybe_submit`, via `self.submit_order(order)` at `:2540`. §12 therefore states the rule in four parts: (1) an IOC order **never rests**, so by construction there is no resting order derived under a stale gate to cancel; (2) **fail closed for NEW orders only** — the lapse raises `SizingGateUnsatisfiedError` at the next sizing call, upstream of `_maybe_submit`; (3) **never cancel, modify or otherwise alter the safety behaviour of an order already submitted, and never touch an open position** — a gate lapse is a sizing-authority condition, not a market event, and adding a cancel path under precisely the condition of least confidence would introduce new order-path behaviour at the execution seam this item otherwise leaves alone; (4) the shadow resting family `pm_us_crh_rest_v5` is out of scope and, if ever armed, forces (1) to be revisited because a resting order *can* outlive a lapse — recorded so the revisit is not missed. New test and AC #7d. |
| 8 | pm | MINOR | AC #8/#9 cannot be exercised until trading resumes, and would benefit from a stated fallback if the drought continues | **ACKNOWLEDGED, no change — and it is named as a blocker rather than designed around.** AC #8/#9 measure a live cohort; any "fallback measurement" that did not observe live fills would be a different and weaker criterion, and softening a money-path acceptance criterion to make it reachable during a trading drought is exactly the move this backlog forbids. The dependency is BLOCKER-B plus the drought, already named in §12. Recorded here so round 3 sees it was considered and declined on purpose. |
| 9 | mle | scoring note | Portfolio alignment 5/10 attributed to "the honest structural ceiling", with **no named defect** ("I find no remaining defect to name in this section specifically") | **RECORDED, no change made — round 3 must justify or award.** The prediction-market reviewer scored the same §11, unchanged, at **10/10**, calling the low expected value "a fact about the live record… not a defect of this plan's construction". A deduction with no named defect and no requested change is not actionable. If round 3 deducts here it must name a concrete gap; otherwise the points should be awarded. |

**Rejections:** one, partial and explicit — defect #8's suggested "stated fallback measurement" is declined, because it would weaken a money-path acceptance criterion to make it reachable during a drought; the underlying dependency stays a named BLOCKER instead. No other scope was removed and no criterion softened — AC #6 was tightened and AC #7b/#7c/#7d added. No operator-reserved value is read, restated, defaulted or assigned anywhere in this revision, and the R2 cap-free sweep exists precisely to keep that true; `allow_short` is untouched; the four BLOCKERs remain blockers, with BLOCKER-C and BLOCKER-D operator-only rulings this plan poses without answering.

**Revision 3 self-score (2026-09-21, author) — deliberately conservative, scored against the lower round-2 total:**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 17 | Re-scopes MP-B rather than duplicating it, adds the edge-gate artefact the audit could not have known about, and `max_equity_fraction` is now a decision with a trigger rather than a recommendation. Loses points because G-11's `max_equity_fraction` element is still deferred rather than delivered by this item. |
| Technical correctness and evidence grounding | 20 | 16 | The IOC disposition, the two replay drivers' actual scope, the native notional cap, the cent-rounding reuse and the depth-clamp source were each read from source before being claimed. Held below the pm reviewer's mark: the `R` grid and the `1.0` USD sanity bound are reasoned constructions, and the cap-free sweep's fidelity to the real operating point rests on the gate holding across the whole grid rather than on observing it. |
| Implementation specificity and feasibility | 15 | 11 | The sweep is now executable as specified — parameterisation named, grid imported, driver situation resolved by inspection, re-run trigger mechanised. Held well below full marks because the new offline driver is scoped but unwritten, and step 7a now depends on an AUD-06a entry point that does not exist until that item ships. |
| Acceptance criteria and validation quality | 20 | 16 | AC #6 is now objectively verifiable; AC #7b/#7c/#7d add the unit, pin-freshness and in-flight criteria, each with a negative control. Loses points because AC #8/#9 remain unexercisable until trading resumes — declined rather than softened, but still an open acceptance gap. |
| Autonomous operation, failure handling, recovery | 15 | 12 | Both gates and every clamp are fail-closed with no silent fallback; the mid-session lapse rule is now stated and tested; the bounded cohort is a named compensating control. Held below the round-2 mark: rollback still genuinely cannot act on already-open positions, and that is a property of the venue, not something this plan fixes. |
| Portfolio objective alignment, scope, dependencies | 10 | 5 | §11 is a field-level evaluation contract with fixed baselines, an explicit "this item can REDUCE ROI" row treated as load-bearing, a cohort-review revert rule and a falsifier. Held at the lower reviewer's mark pending round 3 naming a defect or awarding the points (disposition #9); this remains the only P3, four-times-gated, money-losing-capable item in the cluster. |

### Round 3 (2026-09-21) — independent blind peer review

| Reviewer | Total |
|---|---|
| prediction-market-reviewer (portfolio accounting / risk) | 76/100 |
| mle-reviewer (statistical validation / measurement engineering) | 82/100 |

**Round-3 readiness is the LOWER of the two: 76/100.**

**Dispositions (every defect, both reviewers):**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | pm | MATERIAL | §5's no-leak exclusion cites a `qty_present` token that does not exist; `continuous_strategy.py:2523` in fact logs `qty={decision.quantity} px={decision.limit_price}` together, and would leak the operator-reserved per-position cap the moment qty is derived | **ACCEPTED in full and independently re-verified before writing.** Read from source: `_maybe_submit` at `continuous_strategy.py:2514`, the unarmed early-return INFO at `:2519-2525` with the qty/px pair at `:2523`, submission at `:2532-2540`. A literal `/usr/bin/grep -rn "qty_present"` returns zero hits repo-wide — **revision 3's claim was wrong and is withdrawn, not softened.** Changes: §5's exclusion is rewritten to state what the line actually does and that closing it is this item's own work; §6 gains **D6-R**, which enumerates the whole co-emission surface from source (R1 `:2523` log; R2 `:2439` `record_duplicate_fill(qty=…, fill_px=…)`, a **persisted** record the reviewer's fix did not reach; R3 `strategy.py:682/689/702/741`; R4 `backtest_only.py:112`; R5 `OfferTapeRecord.to_dict` `:183-248`, which carries no order qty today and must not gain one; R6 `DurableFillRecord`, the venue's own record, correctly out of scope) with a per-site disposition; §7 step 3 replaces the generic `test_the_take_log_line_never_carries_a_derived_quantity` with four site-named tests including the alert-payload path; AC #5 requires the `:2523` diff, the RED→GREEN pair and the backing grep output rather than review. |
| 2 | pm | required change 3 | Add an evidence step that greps the decision/take/submit path for qty-with-price f-strings so the scan test's coverage is demonstrably complete | **ACCEPTED.** §7 step 3 now requires the literal grep output behind D6-R's table in the evidence pack, and AC #5 requires it as evidence. |
| 3 | pm | (implicit in the fix) | The redaction mechanism was assumed to exist | **ACCEPTED and answered from source.** `src/breezy/adapters/polymarket_us/redaction.py` is a **credential** surface only (re-exports `redact_url` from `ingest/http.py:272-299`, adds `SENSITIVE_HEADERS` and `redact_secure`/`redact_text`); it has no concept of an operator-reserved economic value, and neither does `health.py`'s alert-payload allowlist. D6-R follows the existing correct precedent instead — `order_enablement.py:86-92`'s "never a value: ... no cap amount ever appears in a message raised from here" — and edits the named sites rather than adding a second redaction policy, which `redaction.py:7-11`'s own null-hypothesis note argues against. **The persisted records (offer tape, duplicate-fill latch) were NOT inside any redaction contract; D6-R states that explicitly instead of implying coverage.** |
| 4 | mle | none found | "No new material defect found"; step 7a genuinely reads no cap value; the AC #9 n-power caveat is correctly inherited through AUD-04's schema; the four BLOCKERs are correctly named rather than decided | **NOTED, no change.** Carried unchanged. |
| 5 | mle | carried, structural | The offline sweep driver is scoped but unwritten, and AC #8/#9 depend on trading resuming — "neither is closable by a text change alone" | **ACCEPTED as accurate, no change and no softening.** Both remain named open items in the self-score below rather than being written down to a weaker criterion. |
| 6 | both | scoring note | §11 awarded 10/10 by both reviewers with no named defect, resolving round-2 disposition #9 | **RESOLVED and awarded.** The revision-4 self-score raises this criterion from 5/10 to 10/10; both round-3 records state the item's low expected value is a fact about the live record, not a construction defect. |

**Rejections:** none. **No scope was removed and no criterion softened** — AC #5 was strengthened from a generic scan to a named-site diff plus RED→GREEN plus grep evidence, and D6-R adds work (the `:2523` edit and the persisted-record rule) rather than excusing it. **No value is assigned to either operator-reserved cap anywhere in this revision**, and D6-R exists precisely to keep one from being reconstructable. BLOCKER-A through BLOCKER-D all stay blockers; BLOCKER-C and BLOCKER-D remain operator-only.

**Points withheld in round 3 without a named defect or requested change — round 4 must justify or award:**

- **mle, "Fidelity" 17/20, "Technical correctness" 16/20, "Implementation specificity" 11/15, "Acceptance criteria" 16/20, "Autonomous operation" 12/15.** Every one is recorded as "matches round 2/3 self-score" with the same carried weaknesses and an explicit "no new material defect found ... none found this round". Round 4 should either name a remaining gap in the revised text or award against it.
- **pm, "Autonomous operation" 12/15.** Attributed solely to rollback not being able to unwind already-open positions — which the same record calls "a venue property this plan correctly does not claim to fix". That is a fact about the venue, not a plan defect; no change is requested.
- **pm, "Fidelity" 16/20, "Technical correctness" 14/20, "Implementation specificity" 9/15, "Acceptance criteria" 15/20.** All four deductions are attributed to the single MATERIAL log-leak finding, now remedied in full by dispositions #1–#3. Round 4 must re-score these against the revised §5/§6/§7/§8 rather than carry the deduction.

**Revision 4 self-score (2026-09-21, author) — deliberately conservative, scored against the lower round-3 total (76):**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 17 | Re-scopes MP-B faithfully, adds the edge-gate artefact, and now closes the cap-leak surface G-11's "no allocation logic" gap implies rather than wrongly assuming it closed. Loses points because G-11's `max_equity_fraction` element is still deferred rather than delivered. |
| Technical correctness and evidence grounding | 20 | 17 | The single highest-stakes correctness claim in the plan was wrong and is now corrected against source with the full co-emission surface enumerated by grep, including two sites (the persisted duplicate-fill record and the offer tape) that neither reviewer named. Held below full marks: the `R` grid and the `1.0` USD sanity bound remain reasoned constructions, and the cap-free sweep's fidelity rests on the gate holding across the whole grid. |
| Implementation specificity and feasibility | 15 | 11 | D6-R turns the redaction work from "unwritten and mis-specified" into a per-site table with named dispositions and four named tests. Held at the round-3 mle mark because the new offline sweep driver is still scoped but unwritten and step 7a still depends on an AUD-06a entry point that does not exist yet. |
| Acceptance criteria and validation quality | 20 | 16 | AC #5 now names the call site, requires a diff and a RED→GREEN pair, and extends to alert payloads and persisted records; AC #6 stays objectively verifiable; AC #7b/#7c/#7d keep their negative controls. Loses points because AC #8/#9 remain unexercisable until trading resumes — declined rather than softened. |
| Autonomous operation, failure handling, recovery | 15 | 12 | Both gates and every clamp stay fail-closed with no silent fallback to qty=1; the mid-session lapse rule is grounded in the IOC submission path. Held below the round-2 mark: rollback genuinely cannot act on already-open positions, a venue property this plan does not claim to fix. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | §11 is a field-level evaluation contract with fixed baselines, an explicit "this item can REDUCE ROI" row treated as load-bearing, a cohort-review revert rule and a falsifier; both round-3 reviewers awarded 10/10 with no named defect. |

**Latest score:** 83/100 (Revision 4 self-score); round-3 peer readiness 76/100.
**Readiness: NOT READY — round 4 peer review pending. BLOCKER-A, BLOCKER-B, BLOCKER-C and BLOCKER-D all remain open; BLOCKER-C and BLOCKER-D are operator rulings no reviewer may resolve.**

### Round 4 (reconciled) (2026-09-21) — independent blind peer review, with scoring reconciliation

| Reviewer | Total |
|---|---|
| prediction-market-reviewer (portfolio accounting / risk) | 80/100 |
| mle-reviewer (statistical validation / measurement engineering) | 98/100 |

**Round-4 readiness is the LOWER of the two: 80/100** — the widest reviewer spread in this cluster,
and the lower mark is the operative one because it rests on a defect the higher reviewer did not test
for: the pm reviewer **ran the plan's own cited grep command** and found the table disagreed with it.

**Dispositions (every defect and every note, both reviewers):**

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | pm | **MATERIAL** (−3 Fidelity, −4 Technical correctness, −5 Acceptance criteria) | §6 D6-R's "complete enumeration" is **not complete relative to its own stated method**. Running the cited `/usr/bin/grep -rn "qty=" src/breezy/strategy src/breezy/adapters/polymarket_us/exec src/breezy/runtime` surfaces two genuine qty+price co-emissions absent from the table — `cli_settlement_print_lock/strategy.py:938` (qty + `limit=`) and `runtime/backtest_harness.py:845` (qty + `avg_px_close`) — and the standing scan test's scope (`current_rung_hold/` + `polymarket_us/exec/`) is narrower than the command, so AC #5's backing grep output would contradict the table it is meant to validate; AC #5 as written could not be satisfied honestly | **ACCEPTED in full. The command was re-run verbatim by this reviser** (not taken from the review): it returns **58 text matches across 14 files** [**round-6 correction: the match count 58 is right; the file count is 20, not 14 — a transcription error in this row, corrected in §6 D6-R and now asserted by test**], plus `__pycache__` binary matches now excluded via `--binary-files=without-match`. Both named sites are CONFIRMED exact, read from source. Changes made: (a) the D6-R lead-in states the re-run, the match count, and that every match is accounted for; (b) **seven groups R7–R13 are added** with a fixed disposition vocabulary (REDACT / OUT OF SCOPE, NOT REACHABLE FROM THE LIVE SIZED PATH, with the reason / ALREADY SAFE) — R7 and R8 are the two named sites; R9–R13 cover the dormant-family FLATTEN lines, `exit_authorization.py:136`, the persisted monitor records, `paper_replay.py:357` and the twenty adapter/runtime kwarg sites; (c) a **line-by-line accounting paragraph** maps all 58 matches to an R-row, so "complete" is checkable rather than asserted; (d) the scan test's scope is **widened to exactly the cited command's three trees** (option (b), not the narrowing option (a) — narrowing would have made the claim true by shrinking the guard, and R7/R8 deserve a standing pin), made GREEN without weakening by an expression-pinned `_REGISTERED_CONSTANT_QTY_SITES` allowlist rather than a directory exclusion: a new co-emission in scope is RED, and a registered site whose pinned qty expression changes is RED; (e) AC #5 and §7 step 3's evidence requirement now demand the grep output, its count and a per-match R-row mapping, with a match lacking a row a **failing criterion**, plus a test-level assertion that the scan's scope equals the recorded command's scope so they cannot drift apart again. **Found while reconciling and recorded rather than folded in quietly:** `edge` (`model_p - ask_p - cost`, `cli_settlement_print_lock/decision.py:112`) is a price-domain token and was missing from the forbidden list; the list is **widened** to include `avg_px_open`, `avg_px_close`, `limit`, `fee` and `edge`. |
| 2 | pm (MINOR) + mle (MINOR, −1 Implementation specificity, −1 Acceptance criteria) — **independently the same finding** | MINOR | R2's disposition claims the persisted duplicate-fill record is "enforced by the scan test below, which covers alert payloads and evidence writers", but **none of the four tests in §7 step 3 scans an evidence-writer path** — they cover log lines, the offer-tape record shape and alert payloads. The enforcement claim is broader than what is specified | **ACCEPTED in full; the claim was genuinely unbacked.** Changes made: (a) a **fifth, site-named test** — `test_no_evidence_artefact_writer_copies_the_duplicate_fill_records_qty_and_price_together` — scanning every module under `scripts/analysis/` and `scripts/venue/` that writes a `docs/evidence/**` artefact plus `persistence/residual_fills.py` and `realized_draws.py`, failing if any reads a cap-bearing persisted record and emits its quantity together with its price or fee; it forbids the PAIR, with a negative control asserting either value alone passes. Source read before naming the record shapes: `DUPLICATE_FILL_KEY_PREFIX = "continuous_rung_hold/duplicate_fill/"` (`trial_day_latch.py:290`) with payload keys `qty`/`fillPx`/`fee` (`:895-904`). (b) R2's row is restated to name which test enforces which half instead of claiming both. (c) **AC #5 extended** to require all five tests and the fifth's own RED→GREEN pair. (d) **A coverage re-check of every claim in §6/§7/§8 was run as the reviewers' finding demands, and surfaced a site class neither named:** `PositionMonitorSummary.to_dict` persists `fill_px` and `held_qty` in one mapping (`monitor_records.py:357-358`, read from source) and `PositionMarkRecord` carries `held_qty` (`:175`) — the same class as R2. These are now **R11**, covered by the same fifth test, which is why that test is scoped to the persisted cap-bearing record surface rather than to the duplicate-fill latch alone. AC #5 now states the complete claim→test mapping explicitly and states that no other coverage is claimed anywhere. |
| 3 | mle | reconciled, awarded | Fidelity (−3) for `max_equity_fraction` being a deferral; Technical correctness (−3) for the `R` grid and the `1.0` USD bound being "reasoned, not measured"; Implementation specificity (part) for the unwritten sweep driver and the not-yet-existing AUD-06a entry point; Autonomous operation (−3) for rollback being unable to act on open positions | **NOTED, no change.** Each was awarded back on re-examination: the deferral is a §12 DECISION with a named re-evaluation trigger; the `R` grid is IMPORTED from AUD-06a's registered sweep rather than re-chosen here, and the `1.0` USD bound is **structural** (no per-contract edge can exceed a binary's whole `[0,1]` payout), true by construction — the mle record explicitly retracts calling it a weakness; the unwritten driver and the missing entry point are already what **BLOCKER-A** names; and IOC orders never rest (`continuous_strategy.py:2531-2538`), so there is no resting order to cancel — a venue property this plan correctly does not claim to fix. |
| 4 | pm | note, no change | The persisted-record containment does not violate the operator-control contract (`docs/core/PROGRESS.md:17-24`): that text governs where the RAW cap VALUE lives, not whether an internal host-local record is reconstructable by someone holding both numbers | **NOTED, no change.** Containment (never deletion) of operationally load-bearing data remains the disposition for R2 and now R11. **No operator-reserved value is read, restated, defaulted or assigned anywhere in this revision.** |
| 5 | pm + mle | blockers, not deductions | BLOCKER-A (AUD-06a's validated envelope and staleness predicate), BLOCKER-B (AUD-02's family-scoped edge with a CI excluding 0), BLOCKER-C (operator, R-12 session order-count ceiling), BLOCKER-D (operator, whether the per-position cap is still the intended per-order spend once qty is derived from it) | **NOTED, unchanged, and all four STAY BLOCKERS.** BLOCKER-C and BLOCKER-D are operator rulings this plan poses and does not answer; BLOCKER-B remains the largest structural reason this item is P3. |

**Rejections:** one, partial and explicit — defect #1's remedy option (a) ("narrow the cited grep command to match the current table") is **declined**, because it would have made the completeness claim true by shrinking the guard rather than by widening it; option (b) is taken instead, and the scan scope is widened to the full cited command. **No scope was removed and no criterion softened:** the forbidden token list is widened, the scan directory scope is widened, a fifth test is added, AC #5 is strengthened into a falsifiable grep-to-table mapping, and the `_REGISTERED_CONSTANT_QTY_SITES` allowlist pins exact expressions rather than excluding directories. `allow_short` is untouched. No operator-reserved value is assigned.

**Revision 5 self-score (2026-09-21, author) — deliberately conservative, scored against the lower round-4 total (80):**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 17 | The completeness claim is now backed by the re-run command, a 58-match line-by-line accounting and seven added site groups with explicit dispositions, so the defect that cost 3 points is closed at its root rather than patched. Holds points back because G-11's `max_equity_fraction` element is still a §12 DECISION deferred to a trigger rather than delivered by any item, and because R7/R8 are registered rather than redacted — a deliberate choice not to edit dormant families this item does not own, but genuinely less than removal. |
| Technical correctness and evidence grounding | 20 | 17 | Every site in the table was read from source this revision, the two omitted co-emissions are confirmed exact, the `edge` token gap was found and the list widened, and the persisted `fill_px`/`held_qty` pairing at `monitor_records.py:357-358` was found by re-checking coverage rather than by a reviewer. Holds points back because a table this size is only as good as its next re-run — the standing defence is now the scope-equality assertion in AC #5, which is itself unexercised until the test is written. |
| Implementation specificity and feasibility | 15 | 11 | D6-R is a thirteen-row per-site table with fixed disposition vocabulary, five named tests, a pinned-expression registry and a falsifiable evidence requirement. Holds at the round-4 mark because the offline sweep driver is still scoped but unwritten, step 7a still depends on an AUD-06a entry point that does not exist yet (BLOCKER-A), and the widened scan plus its registry is materially more implementation surface than revision 4 specified. |
| Acceptance criteria and validation quality | 20 | 16 | AC #5 can now be satisfied honestly: it demands the grep output, its count, a per-match R-row mapping, five green tests, the fifth's RED→GREEN pair, and a test-asserted scope equality — and it states the complete claim→test mapping so an unbacked coverage claim cannot recur silently. Holds points back because AC #8/#9 remain unexercisable until trading resumes (declined rather than softened), and AC #5's own strength is now conditional on a registry an implementer populates. |
| Autonomous operation, failure handling, recovery | 15 | 12 | Both gates and every sizing clamp stay fail-closed with no silent fallback to qty=1; the mid-session IOC lapse rule is grounded in the actual submission path. Held at the round-4 mark: rollback genuinely cannot act on already-open positions, a venue property this plan does not claim to fix. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | §11 is a field-level evaluation contract with fixed baselines, an explicit "this item can REDUCE ROI" row treated as load-bearing, a cohort-review revert rule and a falsifier; awarded 10/10 with no named defect by both reviewers in rounds 3 and 4. |

**Latest score:** 83/100 (Revision 5 self-score); round-4 peer readiness 80/100.
**Readiness (as recorded at round 5): NOT READY — round 5 delta review pending. BLOCKER-A, BLOCKER-B, BLOCKER-C and BLOCKER-D all remain OPEN; BLOCKER-C and BLOCKER-D are operator rulings no reviewer and no plan text may resolve.**

### Round 6 (2026-09-21) — revision against the round-5 delta reviews

| Reviewer | Total | New defects |
|---|---|---|
| mle-reviewer | 98/100 | 1 MINOR — the "checkable, not asserted" claim's file count |
| prediction-market-reviewer | 94/100 | 1 MINOR — the registry pin's guarantee is overstated |

**Round-5 readiness is the LOWER of the two: 94/100.** No MATERIAL defect remains; both round-5
findings are MINOR and both are fixed by this revision.

| # | Reviewer | Severity | Defect | Disposition |
|---|---|---|---|---|
| 1 | mle | MINOR | §6 D6-R's lead-in says the cited grep returns matches "across 14 files"; the real distinct-file count is **20**, and the row-level accounting already covers all 20 — only the headline number was wrong, inside the very claim whose point is to be checkable | **ACCEPTED in full; the count was re-derived here rather than taken from the review.** Re-ran `/usr/bin/grep -rl --binary-files=without-match "qty=" src/breezy/strategy src/breezy/adapters/polymarket_us/exec src/breezy/runtime \| wc -l` -> **20**, and the match count independently re-confirmed at **58**. §6 D6-R now states 20, names the command that produces it, and **explicitly withdraws** the "14 files" figure; the §13 round-4 row carries an inline correction rather than being silently rewritten. The number is no longer prose-only: §7 step 3's evidence requirement adds the DISTINCT-FILE count to the pasted artefact, and AC #5 / the scope-equality test now assert the stated count equals `len(set(files))` from the same run — the reviewer's requested mechanical check, so this class of drift is caught by a test rather than by re-review. |
| 2 | pm | MINOR | `_REGISTERED_CONSTANT_QTY_SITES` pins the **emission site's expression TEXT**, which is syntactic: a later change could make a dormant family's qty cap-derived upstream while the pinned text — and the scan — stay unchanged, so R7/R9's "RED before the line ships" claims a guarantee the mechanism does not deliver | **ACCEPTED in full, taking the reviewer's option (b) rather than (a).** Option (a) (state the limit + a review-time convention) was considered and **declined**: this repo's own record is that a guard enforced by human diligence is not a guard (§3, round 1), and the reviewer offered (b) as sufficient. Both halves are done: (i) the guarantee's scope is now **stated honestly** in a new §6 D6-R paragraph, with the overstated R7/R9 wording explicitly withdrawn; (ii) the gap is **closed mechanically** by the smallest correct strengthening — each registry entry pins two normalised content hashes, `emitting_fn_sha256` and `assigning_fn_sha256` with an explicit `assigned_at` `file:function:line`, rather than the disproportionate "hash each family's whole order-construction path". New RED test `test_a_registered_site_goes_red_when_its_upstream_assignment_changes` mutates the upstream computation while leaving the emitted line byte-identical and must FAIL, with a negative control. **Feasibility verified at three real sites, read from source, not assumed:** R9 `running_extreme_lock/strategy.py:430` (emitting `_submit_delta` `:410-432`; assigned at `:408` in `_maybe_submit` `:359-408`); R7 `cli_settlement_print_lock/strategy.py:938` (emitting `_submit_delta` `:901-941`; assigned at `:837` in `_maybe_submit` `:761`); R8 `runtime/backtest_harness.py:845` (emitting `_refuse_open_positions` `:833`; `position.quantity` is a **Nautilus** attribute with no Breezy-side assignment, so the entry carries the emitting hash only and records that as a **stated limit**, which R13's venue-reported kwargs share). |

**Rejections:** one, partial and explicit — defect #2's option (a), the review-time convention, is
declined in favour of the mechanical option (b) the same reviewer named as sufficient. **No scope was
removed and no criterion softened:** a sixth test is added, AC #5 gains two assertions, the evidence
requirement gains a field, and the registry pins two hashes per entry instead of one string.
`allow_short` is untouched. No operator-reserved value is read, restated, defaulted or assigned by
this revision. **BLOCKER-A, BLOCKER-B, BLOCKER-C and BLOCKER-D all remain OPEN and unchanged**;
BLOCKER-C and BLOCKER-D are operator rulings no reviewer and no plan text may resolve.

**Revision 6 self-score (2026-09-21, author) — scored against the lower round-5 total (94):**

| Criterion | Max | Score | Named remaining weakness |
|---|---|---|---|
| Fidelity to the gap and completeness | 20 | 19 | The enumeration is complete and its headline number is now correct and test-asserted. Holds a point back because G-11's `max_equity_fraction` element is still a §12 DECISION deferred to a trigger rather than delivered. |
| Technical correctness and evidence grounding | 20 | 19 | The 58-match/20-file counts were re-derived from the commands themselves this round, and the hash strengthening was feasibility-checked at three named sites against source. Holds a point back because R8/R13's `assigned_at` limit is real: where the quantity originates in Nautilus or the venue there is no Breezy function to hash, and the guard is emitting-site-only there. |
| Implementation specificity and feasibility | 15 | 12 | The two-hash registry entry, its normalisation rule and its RED test are named with verified enclosing functions. Held below full marks because the offline sweep driver (step 7a) is still scoped but unwritten and depends on an AUD-06a entry point that does not exist yet (BLOCKER-A), and the hash normalisation is one more piece of test surface an implementer must build. |
| Acceptance criteria and validation quality | 20 | 19 | AC #5 now asserts the file count and the registry's hashes mechanically, closing both round-5 findings in the criterion rather than the prose. Holds a point back because AC #8/#9 remain unexercisable until trading resumes — declined rather than softened. |
| Autonomous operation, failure handling, recovery | 15 | 12 | Unchanged: both gates and every clamp stay fail-closed; rollback genuinely cannot act on already-open positions, a venue property this plan does not claim to fix. |
| Portfolio objective alignment, scope, dependencies | 10 | 10 | Unchanged: §11's field-level evaluation contract, fixed baselines, "can REDUCE ROI" row and falsifier were awarded 10/10 by both reviewers in rounds 3-5. |

**Latest score:** 91/100 (Revision 6 self-score); round-5 peer readiness 94/100.
**Readiness (as recorded at round 6): NOT READY — round 6 delta review pending. BLOCKER-A,
BLOCKER-B, BLOCKER-C and BLOCKER-D all remain OPEN; BLOCKER-C and BLOCKER-D were recorded there as
operator rulings no reviewer and no plan text may resolve — superseded by round 7 below, which
records the rulings that closed them build-side.**

### Round 7 (2026-09-21) — revision against two ENDORSED rulings (no peer review this round)

| # | Ruling artefact | Consequence applied | Where |
|---|---|---|---|
| 1 | `docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md` RULING 2 + **Revision 2 addendum A2** (ENDORSED; trail `docs/evidence/reviews/RULING_study_ceiling_exit_review_2026-09-21.md`) | **BLOCKER-C (R-12) and BLOCKER-D are RULED BUILD-SIDE** — neither is an operator question. Derived session order-count ceiling **KEPT** as a fail-closed bound (`safety.py:591-606`); dollar ledger is the binding and only per-DAY control; the explicit session-count override (`safety.py:621-625`) stays unset, pinned by an absence test over shipped units/env templates (names only). | §4, §7 step 1, §7 step 7c, §8 AC #7e/#7f, §9, §12 |
| 2 | Same artefact, addendum A2 | **Residual R2-a recorded verbatim**: the count ceiling is per-PROCESS (reset at each permit mint, `safety.py:735-738`, `:786-789`, i.e. each mid-day relaunch) while `DailySpendLedger.seed_spent` reseeds durably (`operator_controls.py:306-331`). ACCEPTED as fail-closed; making count durable is a **separate new item**, not this one. §9's exposure bound is no longer provisional. | §12, §9 |
| 3 | Same artefact, addendum A2 | **BLOCKER-D's closure is CONDITIONAL**, not a no-op, on `ORDER_SIZED_TO_POSITION_CAP` — valueless, logged **and** delivered through the shipped alert sink, first occurrence only. Two new RED tests added (`..._named_distinctly_from_a_budget_stop`, `..._valueless_sized_to_cap_event_once`) with acceptance items. | §7 step 1, §8 AC #7e |
| 4 | `docs/evidence/RULING_A1_pm_us_crh_v4_disposition_2026-09-21.md` (ENDORSED) | **BLOCKER-B re-grounded, and it STANDS.** `pm_us_crh_v4` may not send orders; the edge estimate is owned by **AUD-18** (by id/path only, no outcome assumed). AUD-06b cannot be executed until an AUD-18 hypothesis is CONFIRMED **and a new family is registered**. **BLOCKER-A stands** as pure sequencing behind a planned item; **B is an evidence precondition no peer ruling can manufacture.** | §4, §6 G2, §7 step 0/1, §11, §12 |

**No scope was removed, nothing was renumbered, no criterion was softened, and no test was deleted**:
three RED tests and two acceptance items were added, and two blockers were converted from "operator
must rule" to "ruled, with build-side consequences this item now owns". `allow_short` is untouched.
**No operator-reserved value is read, restated, defaulted or assigned by this revision**, and none
is stated, proposed or implied by either ruling.

**Latest score:** unchanged at 91/100 (Revision 6 self-score); round-6 peer marks stand. Round 7 is
a ruling-application revision, not a re-scored revision; a re-score belongs to the next peer round.
**Readiness: NOT READY — BLOCKER-A and BLOCKER-B remain OPEN. BLOCKER-C and BLOCKER-D are CLOSED
build-side (BLOCKER-D conditionally, on the `ORDER_SIZED_TO_POSITION_CAP` event), which does NOT
unblock this item: an unproven edge sized to the cap still multiplies a negative expectation.**

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-22) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `5a75991eec475c719745aebc5fa43a32d3c4b2b62f21fe2b9c940dca425a7ae0`
- **Baseline self-score:** 74/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `mle-reviewer` round 7: 100/100 — `reviews/AUD-06b-r7-mle-reviewer.md`
  - `prediction-market-reviewer` round 7: 100/100 — `reviews/AUD-06b-r7-prediction-market-reviewer.md`
- **Readiness:** **NOT READY**
- **Unresolved blockers / notes:**
  - BLOCKER-B (unavailable evidence): a CONFIRMED edge hypothesis from AUD-18 plus a newly registered family to carry it. No ruling can manufacture this.
  - Sequencing only, not a blocker: AUD-06a's validated quantity envelope must land first.
  - Closed build-side by ruling (`docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md` RULING 2 + addendum A2): R-12 and the per-position question; D's closure is conditional on the `ORDER_SIZED_TO_POSITION_CAP` event this plan now specifies.
- **Full review history:** 14 records, `reviews/AUD-06b-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
