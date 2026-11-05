# RULING — R-1 (FillReport commission unit) and R-2 (may a reconciled OrderFilled reach `on_order_filled`)

Status: ENDORSED 2026-09-21 — independent peer review ENDORSE, no required change, on Revision 3 (`docs/evidence/reviews/RULING_R1_R2_review_2026-09-21.md`). Rulings delegated to engineering peers by the operator.

Peer role: independent, silent-failure / error-propagation focus. Blind — no other
agent's output consulted or cited.

**Revision 2 (2026-09-21, same session).** Independent peer review
(`docs/evidence/reviews/RULING_R1_R2_review_2026-09-21.md`) verdict
ENDORSE-WITH-REQUIRED-CHANGES; one HIGH defect and one MEDIUM defect, both verified
against source before this revision (`src/breezy/adapters/polymarket_us/fees.py:277-316`,
`docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md:47-113`). Fixed:
O4's modelled-fee fallback now MUST resolve theta as-of `record.ts_event` (fill time),
never off the reconciliation-time `Instrument`; `feeSource` renamed `RECORDED` /
`MODELLED_AT_FILL_TIME`; the withdrawn "byte-identical to today's 0.01" claim is
called out explicitly at its origin (§4) rather than silently removed; one new RED
test and one new B0 field (`fee_coefficient_at_fill`) added to §6 consequences; §7
overturn section re-grounded from hypothetical to confirmed. R-2 and findings 1-9 are
UNCHANGED — the review found no defect in R-2 or in findings 1, 2, 3, 5, 6, 7, 8, 9.
Everything below this note is the revised text; nothing from Revision 1 was deleted
without a replacement clause covering the same ground.

**Revision 3 (2026-09-21, same session).** Delta review verdict
ENDORSE-WITH-REQUIRED-CHANGES; prior HIGH confirmed fixed, one new MEDIUM: the pin
document evidences only two dated points, not a resolved step function — 2026-08-25
(0.06) and three drift alerts timestamped 17:00/18:00/20:00 UTC on 2026-09-17 (0.0695)
— and does not establish the 2026-09-17 intraday cutover instant (the pin doc itself
calls this "open, out of scope"). Verified against
`FEE_SCHEDULE_PIN_2026-09-18.md:58,73,81-86` this session: the 2026-09-16 baseline
(53,624/53,624 rows) is 0.06 all day, and the first evidenced 0.0695 `ts_event` is
`2026-09-17T17:00:00.508472Z`, essentially coincident with the first alert. Fixed: §4's
fallback is now stated as closed intervals (`< 2026-09-17T00:00:00Z` → `0.06`;
`>= 2026-09-17T17:00:00Z` → `0.0695`) with an explicit AMBIGUOUS window in between
(`[00:00Z, 17:00Z)` on 2026-09-17) inside which a legacy fill MUST refuse rather than
default to either side; one more required RED test added for a fill inside that
window; §6 gains a matching acceptance item. R-2 and all other R-1 findings unchanged.

## 1. Questions ruled (verbatim)

From `docs/core/PROGRESS.md:70-71` (rulings queue), blocking
`docs/plans/backlog/AUDIT_2026-09-21/AUD-13-native-venue-reconciliation-from-durable-records.md`
§12 (13b/13c), whose design is `docs/plans/RECONCILIATION_NATIVE_REPORTS_2026-09-12.md` §8
(cited in PROGRESS as "P3 §8"):

- **R-1**: "Fee unit on the reconciled `FillReport`: O1 recorded / O4 hybrid + `feeSource`
  admissible without amendment (reviewer: recommend O4); O2 bare modelled fee needs an
  amendment; O3 raw-else-refuse likely yields no report on today's record."
- **R-2**: "May a reconciled `OrderFilled` reach `on_order_filled` (`external_order_claims`)?"

## 2. Options considered

**R-1**: O1 (record.cumulative_fee raw), O2 (modelled fee unconditionally), O3
(raw-venue-fee-or-refuse), O4 (O1/O2 hybrid + durable `feeSource` field), and "leave
open" (not acceptable — AUD-13's own goal state requires 13b to ship, and `commission=`
is a required `Money`, `execution/reports.py:639-641`; there is no code path that skips
assigning it, so leaving R-1 open blocks 13b entirely with no partial-credit path).

**R-2**: R2-A (no claim, book stays `-EXTERNAL`), R2-B (claim via
`external_order_claims`), "leave open" (not acceptable for the same reason: 13c has a
defined RED-first test plan gated only on this ruling, and leaving it open is
indistinguishable from ruling R2-A except that R2-A is a stated, evidenced decision
rather than an omission).

## 3. Evidence (file:line, verified this session)

1. `FillReport.commission: Money` is REQUIRED, non-nullable — `.venv/lib/python3.13/site-packages/nautilus_trader/execution/reports.py:639-641,676,700` ("If no commission then use a zero `Money` amount"). No omit option exists; R-1 cannot be deferred inside 13b.
2. `DurableFillRecord` (`src/breezy/adapters/polymarket_us/exec/client.py:641-707`) carries `cumulative_fee: Decimal`, `fee_reconciled: bool`, `venue_fee_raw: str | None`, `trade_id: str | None`, `order_qty: Decimal | None`. The one record in the store today is **resolver-path**: `cumulativeFee "0"`, `feeReconciled false`, `venueFeeRaw null` (plan `:134`) — i.e. UNKNOWN-recorded-as-zero, not a genuine zero.
3. **Trial scoring already refuses to trust this ambiguity and does NOT read Nautilus's `event.commission`.** `_per_contract_reconciled_fee`/`_recorded_fee_for` (`src/breezy/strategy/current_rung_hold/continuous_strategy.py:340-364`): returns `None` unless `record.fee_reconciled` AND `cumulative_qty > 0`, and the docstring states explicitly: *"Deliberately NEVER `event.commission`: the resolver path emits a synthetic `Money(0)` there, indistinguishable from a genuine zero fee."* This is the SAME finding AUD-13a step 3 asks to grep-prove — verified true for the scoring path.
4. **But the O1-evidence claim ("no Breezy artefact reads `Position.realized_pnl`/`OrderFilled.commission`") is FALSE as stated, and this is the load-bearing finding of this ruling.** `src/breezy/settlement/exit_guard.py:84-105` (`TradeReturnInput.realized_pnl`) is a Breezy module whose field docstring REQUIRES sourcing from Nautilus `Position.realized_pnl`, explicitly because it is fee-inclusive: *"MUST be sourced from Nautilus `Position.realized_pnl`... fee-INCLUSIVE: on every fill it seeds from `-fill.commission.as_f64_c()`... A caller that instead computes `(close_px - open_px) * qty` and drops commission would understate the loss... and the per-trade return `r_i`... would be silently optimistic."* This module is not yet wired to a live actor (module docstring: "landed ahead of the actor"; no `SettlementExitActor` exists in `src/`), so it is currently dead code with respect to a running process — but it is a committed, reviewed Breezy artefact that specifies `Position.realized_pnl` (hence `OrderFilled.commission`, since Nautilus seeds `realized_pnl` from it) as its REQUIRED input for the very thing R-9's BCa bootstrap will consume. A future wiring of this actor onto a reconciled position whose commission was silently booked at 0 (O1) would feed a fee-EXCLUSIVE number into a field this module's own docstring says must never be fee-exclusive — with no marker anywhere that the number is degraded. `trial_scorer.py:8-15` independently confirms `Position.realized_pnl` is deliberately NOT used by the live scoring path today, for the same reason.
5. `event.commission` IS read live in two other places: `exit_wiring.py:219` and `continuous_strategy.py:2434` (`_consume_or_flag_duplicate`'s duplicate-fill diagnostic payload) — both read it as a `Decimal(0)`-on-`None` diagnostic/exit-fee value, not as the entry-fill scoring input. A wrong commission on a *reconciled entry* fill therefore does not corrupt `station_day_admission`/trial scoring (finding 3) but DOES corrupt (a) any future `exit_guard`-based realized-PnL consumer (finding 4) and (b) the fee value logged/used at EXIT time if the exit leg itself is ever reconciled rather than live-observed.
6. `DailySpendLedger.authorize_order_cost`/`release_booking`/`true_up_booking` are called ONLY from the exec client's own submit/resolver code paths (`exec/client.py:2030,2155,3524,3536,3542,3681,3720,3735`) — never from `on_order_filled` or anywhere in `src/breezy/strategy/`. **A reconciled `OrderFilled` reaching `on_order_filled` cannot double-book spend against `DailySpendLedger`**; that ledger is keyed to the exec client's own submit-time booking, which for a reconciled boot never re-runs (no new POST is issued).
7. Idempotency for a replayed reconciled fill is keyed on `venue_order_id`, not on wall-clock or boot count: `trial_day_latch.py:780-825` (`consume_if_absent` — read-check-write under a process-wide flock) and `continuous_strategy.py:2416-2433` (`existing.venue_order_id == venue_order_id` ⇒ silent no-op, comment: *"a replayed fill for the SAME order — idempotent no-op"*). This is genuinely a guard against re-arm/re-entry/duplicate-scoring, not merely a docstring claim — it is exercised by increment C's characterisation test (09-12 plan `:80`, `test_a_replayed_reconciled_fill_writes_no_duplicate_bucket_and_no_halt`, `test_three_consecutive_reconciliations_leave_the_halt_key_absent`), which AUD-13's §7/§12 already treats as a precondition for R2-B ("Recommendation... R2-B, gated on C landing GREEN first" — 09-12 plan `:128`).
8. **New defect found, bearing directly on R-2's safety, not previously named in either plan's rulings section:** `fill_records_for` (`exec/client.py:2905-2932`) returns a **tuple of every durable fill record for an instrument**, and `DurableFillRecord.order_side` (`:670`) explicitly "keeps its sign" so that "a SELL record NETS against the longs (an R-8/R-9 partial exit)" — i.e. exit/partial-exit fills ARE written as separate SELL-side durable records alongside the BUY entry record for the same instrument. But the 09-12 plan's §3 "Outputs per record" (`:66`) hardcodes `OrderStatusReport(..., order_side=BUY, ...)` **unconditionally** for every reported record, with no branch on `record.order_side`. If a partial-exit SELL record exists for an instrument the venue still reports open (residual long after a partial exit — exactly the gating rule's admission condition), 13b as currently specified would report that exit fill as a phantom BUY. `on_order_filled` (`continuous_strategy.py:2271-2278`) branches on `event.order_side is OrderSide.SELL` to route to `_on_exit_order_filled`; a mis-tagged BUY would instead fall into the entry `consume_if_absent`/duplicate-fill machinery — silently doubling the reported entry size, never running exit provenance/kill-rule bookkeeping (`trial_day_latch.py:916+`), and (under R2-B) attributing a phantom entry to the strategy's own position book. This is an execution-path silent-failure risk, evidenced from source, independent of which R-1/R-2 option is chosen.
9. F5 (`live/execution_engine.py:3336-3345`, overfill reject on a mismatched `trade_id`) already fails the WHOLE boot (`kernel.py:1024-1039`) rather than silently double-applying a fill — orthogonal to R-1/R-2 but confirms the reconciliation path is fail-closed on identity mismatches generally, which is the same posture this ruling extends to order-side mismatches (finding 8).

## 4. RULING

**R-1: O4 — hybrid fee with a durable `feeSource` field, exactly as the 09-12 plan's
reviewer recommended, REVISED (Revision 2) to fix a HIGH defect a peer review found
in this ruling's own first draft: the modelled fallback MUST be computed from the fee
coefficient in effect AT `record.ts_event` (fill time), never from whatever
`Instrument` object the Nautilus cache holds at reconciliation-boot time. `fees.py`'s
`polymarket_us_fee` (`:277-316`) takes `theta` from the `Instrument` it is handed at
CALL time, with no time parameter of its own — it has no notion of "the coefficient
that applied when this fill happened." Platform-wide theta drifted `0.06 → 0.0695` on
2026-09-17 (`docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md:47-113`,
confirmed identically across MIA/MDW/SFO), and the one durable record in the store
today (`CEBPX0EVTTMX`, SFO 2026-09-11) predates that drift by six days. The original
draft's "byte-identical continuation of current behaviour (0.01 modelled)" claim is
**WITHDRAWN**: it assumed the fallback would reproduce today's 0.01 without checking
which theta the fallback would actually read at the NEXT reconciling boot — a boot
that happens on or after 2026-09-21, four days into the drift.**

- When `record.fee_reconciled` is `True` (and `venue_fee_raw` is present): `commission = Money(record.cumulative_fee, USD)`, `feeSource = "RECORDED"`.
- When `record.fee_reconciled` is `False` (today's resolver-path shape): `commission = Money(<theta-at-fill-time> * qty * p * (1-p), USD)`, banker's-rounded exactly as `polymarket_us_fee` (`fees.py:304-316`) does, but with `theta` resolved AS OF `record.ts_event`, never off the reconciliation-time `Instrument` object. `feeSource = "MODELLED_AT_FILL_TIME"` (renamed from the draft's bare `"modelled"` — the new name states what era the model used, which is the whole fix). **Concrete mechanism (both required, per the review's fix options (a) and (b), taken together rather than either/or):** (a) B0 gains one more optional-on-read `DurableFillRecord` field, `fee_coefficient_at_fill: Decimal | None`, populated at BOTH write sites (`exec/client.py:2769-2853`, `:1551-1656`) from the `Instrument` in hand at fill time — this is the authoritative source for every record written from here forward; (b) for the LEGACY record(s) written before this field existed (today: the one SFO 09-11 record, `fee_coefficient_at_fill=None`), the fallback consults a dated, evidence-pinned coefficient schedule keyed on `ts_event`, sourced from `FEE_SCHEDULE_PIN_2026-09-18.md`'s own dated table (`{("2026-08-25", Decimal("0.06"))}` plus the confirmed `("2026-09-17", Decimal("0.0695"))` drift point) — i.e. the SAME evidence this ruling already cites, turned into code rather than left as a doc a human must remember to re-check. **Revision 3 boundary clause (reviewer's exact wording, verified against `FEE_SCHEDULE_PIN_2026-09-18.md` this session):** the dated schedule is two CLOSED intervals, not two points — `ts_event < 2026-09-17T00:00:00Z` resolves to `0.06` (evidenced by the 2026-09-16 baseline: 53,624/53,624 offer-tape rows that whole day carry `fee_coefficient="0.06"`, `:81-86`); `ts_event >= 2026-09-17T17:00:00Z` resolves to `0.0695` (evidenced by the first drift alert, `17:00:00.610319588Z`, and the offer-tape row whose own `ts_event` is `2026-09-17T17:00:00.508472Z`, `:58,73` — converted and checked this session). **The interval `[2026-09-17T00:00:00Z, 2026-09-17T17:00:00Z)` is an explicit, named AMBIGUOUS window**: the pin document itself states this gap is "open, out of scope" (`:86`, "why 2026-09-17 holds 6 rows against 2026-09-16's 53624") — no evidence fixes which coefficient billed inside it. A legacy record (no `fee_coefficient_at_fill`) whose `ts_event` falls inside this window, or before the earliest pinned date, or in any future unpinned gap, is NOT defaulted to either coefficient — it is refused (no fill report for that record, loud + alerted, same posture as O3's refusal branch), because guessing a fee coefficient is exactly the "confident wrong number" this whole ruling exists to prevent. This does not block the one existing record (2026-09-11, well clear of the window on either side).
- `feeSource` is a new durable field on `DurableFillRecord` (B0-adjacent, one more optional-on-read field, same pattern as `trade_id`/`order_qty`), never read by `_recorded_fee_for`/trial scoring (which already ignores `event.commission` per finding 3) — its only consumers are diagnostics and any FUTURE `exit_guard`/`SettlementExitActor` wiring, which MUST check `feeSource == "RECORDED"` before treating `Position.realized_pnl` as fee-accurate (this is a new, explicit precondition this ruling adds to that not-yet-built consumer, forestalling finding 4's failure mode before it can occur). `feeSource == "MODELLED_AT_FILL_TIME"` is an explicit statement that the fee is a model output FOR THAT FILL'S ERA, not a claim that it matches today's schedule.
- **New RED test, required before B1 ships (review's HIGH-item fix, not optional):** a contract test constructing a durable record whose `ts_event` predates a pinned drift point, reconciled on a boot where the "current" schedule/Instrument reflects the LATER coefficient — asserting the booked `commission` uses the FILL-TIME coefficient (e.g. `0.06`-basis), not the reconciliation-time one (`0.0695`-basis). This is the direct regression test for the defect this revision fixes; its absence was the review's stated reason the original "byte-identical" claim was asserted rather than verified. **Revision 3 adds a second, required RED test:** a legacy durable record whose `ts_event` falls inside `[2026-09-17T00:00:00Z, 2026-09-17T17:00:00Z)` (the AMBIGUOUS window) must produce NO order/fill report for that record and a latched, counted refusal — never a silent default to `0.06` or `0.0695`. Both tests are acceptance items for 13b (§6 below).
- Rejected: **O1** — silently books `commission=0` on every resolver-path fill (the only kind in the store today), producing a Nautilus-native `Position.realized_pnl` that is fee-EXCLUSIVE with no marker, directly triggering finding 4's failure mode the first time `exit_guard`/a settlement actor is wired to it. This is the textbook "fallback that hides a real failure" this hunt exists to catch. **O2** — books a modelled value with no field distinguishing it from a venue attestation anywhere in the durable record, which is precisely the `grok_admission_exclusions_ack` Q2 violation the 09-12 plan already flagged (`:114,121`) and would leave a future reader unable to tell modelled from attested without re-deriving it. **O3** — verified in this session (finding 2) that the only record in the store today has `venueFeeRaw: null`; O3 would refuse to emit a fill report for it, defeating AUD-13's own goal state (`N ≥ 1` fill reports) on the one incident this item is built to fix (the 09-11 order-2 replay test, §7 13b step 4). O3 is the most "fail-closed on money" reading in isolation, but it fails the "still lets the programme move toward the goal state" half of the conservative-default instruction — it does not merely refuse the ambiguous case, it refuses the ONLY case that currently exists.

**R-2: R2-B (claim, `external_order_claims` set) — CONDITIONAL, with the condition
tightened beyond the 09-12 plan's own recommendation.**

R2-B is safe on the two axes checked here that the 09-12 plan's own rationale did not
fully cover:
- **No double-spend**: `DailySpendLedger` booking never runs from `on_order_filled` (finding 6) — a reconciled fill reaching the strategy cannot re-authorize or re-book spend.
- **No re-arm / duplicate scoring**: idempotency is keyed on `venue_order_id` through a process-wide flocked read-check-write (finding 7), and is a no-op on any replay, including a third+ consecutive boot.

R2-B is ruled **conditional on three items, not the one ("C landing GREEN") the 09-12
plan named**:

1. Increment C's characterisation test (`test_a_replayed_reconciled_fill_writes_no_duplicate_bucket_and_no_halt`, `test_three_consecutive_reconciliations_leave_the_halt_key_absent`) is GREEN before 13c ships — unchanged from the 09-12 plan.
2. **NEW — finding 8 must be closed before 13c, and arguably before 13b**: `generate_order_status_reports`/`generate_fill_reports` must report `order_side` from `record.order_side`, never hardcode `BUY`, and 13b's contract-test suite must add a case asserting a partial-exit SELL durable record reconciles to a SELL `OrderFilled` (or is refused, never silently up-flipped to BUY). Until this lands, R2-B (or even R2-A, since the EXTERNAL-position math is also side-sensitive) risks a phantom entry double-count on any instrument that has ever had a partial exit before a reconciling boot. This is a genuine gap in the plan under review, not a restatement of an existing item.
3. `feeSource` (R-1) is threaded through before B2 lands, so that when `external_order_claims` makes the reconciled fill visible to the strategy's own bookkeeping, any code path that later inspects the resulting position's commission (finding 4) has the provenance marker available rather than needing a second retrofit.

R2-A (no claim) was considered and is NOT ruled: it is safe by construction but leaves
the fill permanently unattributed and does not fix the actual observed incident (09-11
order 2, whose whole point was that Breezy's own evidence should win attribution) — and
none of the three findings above are actually specific to R2-B; finding 8 is equally a
hazard under R2-A's `EXTERNAL` book (a mis-sided EXTERNAL position is still a wrong
position, just not attributed to the strategy). Ruling R2-A would not avoid the defect
this ruling surfaces, only relocate who is confused by it.

## 5. Rationale, and the strongest argument against this ruling

**Strongest argument against O4 (R-1):** it costs one more field and one more
conditional versus O1's one-liner, and the reviewer's own recommendation was already
O4, so this ruling adds little beyond confirming it — a critic could say the ruling
should have picked O1 for simplicity since `_recorded_fee_for` (finding 3) already
proves Breezy's LIVE scoring path is immune to whatever `commission` value gets
booked. **This loses** because "immune today" is not "immune ever": finding 4 shows a
reviewed, committed module (`exit_guard.py`) that names `Position.realized_pnl` as its
required, fee-inclusive input for the R-9 BCa bootstrap this programme has already
planned. Choosing O1 now would plant a silent, undetectable defect for whoever wires
that actor — exactly the "graceful-looking path that makes downstream bugs harder to
diagnose" this review exists to catch — for a savings of one boolean field.

**Strongest argument against conditioning R-2 on finding 8:** it was not part of either
plan's own rulings section, so a critic could call it scope creep beyond what R-1/R-2
were asked to decide. **This loses** because R-2's question is literally "may a
reconciled `OrderFilled` reach `on_order_filled`" — answering that safely requires
knowing whether the `OrderFilled` reaching it can be wrong-sided, and finding 8 shows,
from source, that it currently can be for any instrument with a prior partial exit.
Ruling R2-B without naming this would be answering the question that was asked while
ignoring evidence that changes the answer's safety — the opposite of "verify premises
before briefing" (operator lesson, carried in MEMORY.md).

## 6. Consequences — exact text changes needed

**`docs/plans/RECONCILIATION_NATIVE_REPORTS_2026-09-12.md`:**
- §3 "Outputs per record" (`:66`): change `order_side=BUY` to `order_side=<record.order_side>`, and add one sentence: "A record with `order_side="SELL"` reports a SELL `OrderStatusReport`/`FillReport`; §1's goal-state assertion 4 (exactly one Position) must be re-read as holding per net position after netting, not per record."
- §8 R-1 table (`:118-123`): mark O4 RULED, with the fallback-value binding stated above — theta resolved AS OF `record.ts_event` via a new `fee_coefficient_at_fill` field (new writes) or the dated `FEE_SCHEDULE_PIN` schedule (legacy records), NEVER the reconciliation-time `Instrument` — and add the `feeSource` (`RECORDED` / `MODELLED_AT_FILL_TIME`) consumer precondition for any future `exit_guard` wiring. The original "byte-identical to 0.01" framing is withdrawn; no fallback VALUE is asserted in the plan text without first re-deriving it from the dated schedule.
- §8 R-2 (`:125-128`): mark R2-B RULED CONDITIONAL, list all three conditions from §4 above (not just C-green).
- §4 increments table (`:78`, row B1): add one RED test asserting a SELL-side durable record reconciles with `order_side=SELL`, not `BUY`; add a second RED test (this revision) asserting a pre-drift fill (`ts_event` before 2026-09-17) reconciled on a post-drift boot books the FILL-TIME coefficient, not the reconciliation-time one.
- §4 increments table (`:77`, row B0): add `fee_coefficient_at_fill: Decimal | None` to the B0 field list alongside `trade_id`/`order_qty`, written at both fill sites (`exec/client.py:2769-2853`, `:1551-1656`), optional-on-read for legacy rows.
- §9 UNVERIFIED item 3 (`:140`, venue populating `commissionNotionalTotalCollected`): still open: it now only matters for whether a record can ever get `feeSource="RECORDED"`, not for whether B1 can ship (O4 does not require it, unlike O3).

**`docs/plans/backlog/AUDIT_2026-09-21/AUD-13-native-venue-reconciliation-from-durable-records.md`:**
- §7 AUD-13b step 0 or a new step: add the order-side re-derivation/test from finding 8 to the checklist before generator bodies are written.
- §12 blockers: R-1/R-2 move from BLOCKED to RULED (this artefact), but 13c gains a new explicit dependency: "13c may not ship until the order-side fix (R-2 condition 2) is implemented and its contract test is green, in addition to R-2 condition 1 (C-green)."
- §8 acceptance criteria: add one item — "A durable SELL-side record for an instrument the venue still reports open reconciles to a SELL report, never BUY (finding 8, ruling R1_R2)."
- §8 acceptance criteria: add a second item (Revision 3) — "A legacy durable record whose `ts_event` falls in `[2026-09-17T00:00:00Z, 2026-09-17T17:00:00Z)` yields no report and a latched, counted refusal, never a defaulted coefficient (ruling R1_R2 Revision 3)."

## 7. What would overturn this ruling; what remains operator-only

**Overturning evidence for R-1 (§4's own fallback design already absorbs the scenario
below as of Revision 2 — this paragraph now states what remains, not a hypothetical):**
a demonstration that the venue's GET order response never populates
`commissionNotionalTotalCollected` even after a dedicated capture attempt (09-12 plan
UNVERIFIED item 3) would not change O4's ruling — O4 only upgrades to
`feeSource="RECORDED"` opportunistically and degrades gracefully to
`MODELLED_AT_FILL_TIME` either way. **The θ-drift scenario the first draft named as a
future hypothetical is CONFIRMED, not hypothetical**: `fees.py:277-316` reads `theta`
off the reconciliation-time `Instrument`, and the platform-wide 0.06→0.0695 drift on
2026-09-17 (`FEE_SCHEDULE_PIN_2026-09-18.md:47-113`) is dated and already in evidence;
the fix is folded into §4's binding text (`fee_coefficient_at_fill` + the dated
schedule), so it no longer overturns this ruling — it is what this ruling now
requires. What WOULD still overturn R-1: evidence that the dated coefficient schedule
itself is incomplete or wrong for a fill's actual date (a THIRD drift point not yet
pinned), or that a freshly-loaded `Instrument` for a specific slug does not report the
schedule's assumed value (the review's own "not independently re-verifiable" item) —
either would mean the fallback is confidently wrong rather than honestly degraded,
which the `MODELLED_AT_FILL_TIME` marker cannot detect on its own.

**Overturning evidence for R-2:** any future finding that `consume_if_absent`'s
process-wide flock is NOT actually held across a reconciliation boot's full mass-status
apply (i.e., idempotency finding 7 does not hold end-to-end through the real engine,
not just at the latch's own unit level) would downgrade R2-B to R2-A pending a fix.
AUD-13c's own RED-first engine-driven tests are exactly the check that would surface
this before merge.

**Nothing in R-1 or R-2 is an operator-reserved decision.** Neither touches a budget
cap, position cap, or live-trading enablement value; both were correctly scoped by the
09-12 plan as strategy-lead rulings, and this artefact resolves them within that scope.
