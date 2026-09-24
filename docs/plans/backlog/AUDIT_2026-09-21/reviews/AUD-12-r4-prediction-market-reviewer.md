# AUD-12 — Round 4 — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-12-cost-model-slippage-and-fee-drift.md
SHA256: 82e708c5e8c050704582b5ac33a1af1b70e92feeaaf63ac462da86cc705f5ffc
Round: 4 (final budgeted round)
Reviewer: prediction-market-reviewer (independent, blind)
Lens: fee formula, IOC slippage reference price, fail-closed fee-drift
handling without editing the pin, alert delivery that actually reaches
someone.

## §13 review-history reconciliation

Round-3 MINOR (this reviewer, the only defect I found at round 3 — total was
99/100): §6 item 3's single-representative-slug fee-drift probe design is
reasonable and supported by evidence already in the repo (the 2026-09-17
drift was uniform across 3 stations), but the plan did not cite that
evidence or state the residual per-instrument-drift risk.

**Disposition: VERIFIED FIXED.** §6 item 3's round-4 addition now states:
"empirical support ... `FEE_SCHEDULE_PIN_2026-09-18.md`'s captured offer-tape
excerpt shows the SAME drifted value `0.0695` across 3 different stations
(MIA/MDW/SFO) and 6 different instrument rows on the same day
(2026-09-17)," and explicitly states the residual risk: a hypothetical
future drift confined to a single instrument would not be caught by a
single-slug probe, covered instead by the existing per-order
`decision.py:331` check once any decision reaches pricing again (currently
silent while G-01 holds). §9 and §12 both restate this as a named,
non-blocking residual risk. §8 requires the citation to appear in the
output doc.

Re-verified this round, directly against the primary file (not inherited
from the round-3 review's description): `docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md`
lines 58-60 (WARN log lines for `ContinuousRungHoldStrategy-MIA`, `-MDW`,
`-SFO`, all `fee_schedule_mismatch` on 2026-09-17) and lines 73-78 (six offer-
tape JSONL rows, stations MIA×2/MDW×2/SFO×2, every row
`"fee_coefficient": "0.0695"`) — the plan's citation is accurate: three
distinct stations, six distinct instrument rows, one uniform drifted value,
same day. The plan neither overstates ("proves no per-instrument drift is
possible" — it does not claim this) nor understates (it does state the
residual risk explicitly) this evidence.

## Claims verified this round (direct source read)

- s8.5's field list (`docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md:694-698`,
  read verbatim, counted by hand this round): `station, climate_day,
  cli_received_ts, printed_value, is_final, correction_flag, revision_seq,
  mapped_instrument_id, bucket bounds, hours_to_settlement, level0_ask,
  ask_size, vwap_ask_at_intended_size, fee_coefficient, computed edge at
  slippage_prob in {0.000, 0.010}, [and the FIRST gate that stopped it]` —
  counted directly: 16 comma-separated items. Matches the plan's round-4
  corrected "16 fields" claim (round 3 had miscounted this as 15).
- `OfferTapeRecord.to_dict` (`src/breezy/strategy/current_rung_hold/offer_tape.py:183-248`,
  full body read this round): verbatim fields present — `station`,
  `climate_day`, `instrument_id`, `ask`, `size`, `fee_coefficient`, `reason`
  (7); `width_code`/`m_code` present as partial bucket-geometry encoding, not
  raw bounds; no `cli_received_ts`, `printed_value`, `is_final`,
  `correction_flag`, `revision_seq`, `hours_to_settlement`. Cross-checked
  against the plan's §6 item 2 table row by row — every row's "present" /
  "missing" / "partial" classification matches the actual dataclass exactly.
  Re-summed independently: 7 present + 1 present-by-equivalence
  (`vwap_ask_at_intended_size`, valid only at `order_quantity=1`) + 1 partial
  (edge proxies) + 7 missing = 16, matching both s8.5's own 16-item list and
  the table's 16 rows. The plan's round-4 arithmetic correction ("seven
  missing," not round 3's "six") is independently confirmed correct.
- `FEE_SCHEDULE_PIN_2026-09-18.md`'s uniformity evidence — independently
  re-read from the primary file this round (see above), not merely trusted
  from the round-3 review's paraphrase. Accurate.
- `DOCUMENTED_TAKER_FEE_COEFFICIENT = Decimal("0.06")`
  (`src/breezy/adapters/polymarket_us/fees.py:86`) and
  `decision.py:331`'s `!=` equality check — unchanged from round 3, re-spot-
  checked, still accurate; the plan does not touch either (§6 item 4, "No
  `src/` constant change").

## Defects

None found this round, MATERIAL or MINOR. The round-3 MINOR defect (uncited
single-slug justification) is fixed with an accurate, independently
re-verified citation and an explicit residual-risk statement. No new defect
introduced by the round-4 edit.

## Per-criterion points (caps: 20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 20/20 — both G-09 sub-claims
  (measured slippage honest about n=6; fee-drift detection unattended,
  alerting, fail-closed, never editing the pin) are addressed with concrete,
  source-grounded closing criteria; the s8.5 residual-scope question is
  answered with a verified field-by-field table rather than assumed.
- Technical correctness and evidence grounding: 20/20 — every mechanism
  claim I checked this round (s8.5's 16-field count, `OfferTapeRecord`'s
  actual fields, the FEE_SCHEDULE_PIN uniformity evidence) matched the
  plan's description on direct, independent re-read of the primary source,
  not inherited from a prior round's citation.
- Implementation specificity and feasibility: 15/15 — concrete join keys
  (`venue_order_id`), concrete file paths, concrete extension point (Actor +
  `set_timer_ns`, no new systemd timer), and now a concrete, cited
  justification for the single-slug design with its residual risk named
  rather than left implicit.
- Acceptance criteria and validation quality: 20/20 — the sole-sufficient-
  evidence rule for (b) (`breezy-check-alerts` exit 0 against the live
  process, not the boot-time log line) is unambiguous; (a)'s field-by-field
  table conclusion is corrected and honest ("seven fields missing," neither
  "unbuilt" nor "fulfilled"); the flagged-fill disposition (excluded from
  aggregate, reported by count and value) is explicit.
- Autonomous operation, failure handling, recovery: 15/15 — three-valued
  AGREE/DISAGREE/UNKNOWN probe design, fails closed on unreadable wire data,
  unauthenticated-path requirement enforced by its own RED test, idempotent
  `family_halted`/alert side effects, and the residual per-instrument-drift
  risk is named rather than silently accepted.
- Portfolio alignment, scope, dependencies: 10/10 — dependency framing
  accurate (WP-B0 already landed; (b)'s closure is verification-gated, not
  landing-blocked); no duplication of A0; no invented ROI number; the
  conditional blocker on (b) (operator must set/confirm
  `BREEZY_ALERT_WEBHOOK_URL` if `breezy-check-alerts` does not exit 0) is
  precisely scoped and correctly left as a blocker, not decided away.

**Total: 100/100.**

## Required changes to reach 100

None.

## Blockers

Whether the live node's process actually resolves `TeeAlertSink` and
delivers (§7 step 5's `breezy-check-alerts` live run) remains a genuine,
correctly-named conditional blocker on closing sub-item (b) — not resolvable
by this reviewer (no secrets/process access) and not a scoring deduction,
since the plan already states it as a blocker rather than assuming success.
This is the only blocker; it does not prevent the plan itself from scoring
100 (a plan can score 100 while correctly naming an execution-time blocker
outside its own build authority).
