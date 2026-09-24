# AUD-12 round-3 review — mle-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-12-cost-model-slippage-and-fee-drift.md
SHA256: 72be9e70b2bfafe6da7a09b678c5fac34a56c6853a51437fb46cd826ea925ceb
Round: 3
Reviewer: mle-reviewer

## Round-2 defect disposition check
- Round-2 mle-reviewer MATERIAL defect (§7 step 0 queried `TrialDayLatch`/`StateStore`,
  which never holds a `Refuse`) — CONFIRMED FIXED. Re-traced this round: `record_attempt`,
  `record_with_legacy_fallback`, `record_duplicate_fill`, `consume_if_absent` are the
  latch's only durable write paths and all fire only on a submitted/filled `Take`;
  `RefusalCounter` is confirmed in-memory-only. §7 step 0 now points at
  `offer_tape_<date>.jsonl` via `OfferTape`'s existing read path — correct redirection.
- Round-2 prediction-market-reviewer MATERIAL defect (`breezy-check-alerts` exit 0 vs
  `log_alert_egress_status` treated as interchangeable) — CONFIRMED FIXED. §7 step 5/§8
  now state `breezy-check-alerts` exit 0 as the SOLE sufficient evidence; re-read
  confirms `log_alert_egress_status` never calls `.emit()` and has no exit code
  (inherited citation from round 2, not independently re-read this session — noted by
  the plan's own §13 self-score and re-confirmed structurally consistent with WP-B0's
  CLI description in §2).

## Claims verified against source (this round)
- `OfferTapeRecord.to_dict()` (`offer_tape.py:183-248`): read in full this round. The
  plan's §6 item 2 table is checked field-by-field:
  - `station`→`station`: present. CONFIRMED.
  - `climate_day`→`climate_day`: present. CONFIRMED.
  - `cli_received_ts`→missing: CONFIRMED, no such field.
  - `printed_value`/tmax_f→missing: CONFIRMED, no such field.
  - `is_final`→missing: CONFIRMED.
  - `correction_flag`→missing: CONFIRMED.
  - `revision_seq`→missing: CONFIRMED.
  - `mapped_instrument_id`→`instrument_id`: present. CONFIRMED.
  - bucket bounds→missing (partial via `width_code`/`m_code`): plausible given field
    names; no raw bound fields present. CONFIRMED as stated.
  - `hours_to_settlement`→missing (`minutes_since_window_open` is a different clock):
    CONFIRMED, no settlement-countdown field exists; `minutes_since_window_open` is an
    elapsed-since-open counter, a different quantity.
  - `level0_ask`→`ask`: present. CONFIRMED.
  - `ask_size`→`size`: present. CONFIRMED.
  - `vwap_ask_at_intended_size`→`ask` (equivalence at qty=1): present-by-equivalence,
    consistent with §2's `order_quantity=1` claim. CONFIRMED.
  - `fee_coefficient`→`fee_coefficient`: present. CONFIRMED.
  - computed edge at slippage_prob {0.000,0.010}→`p_bound`/`break_even`: CONFIRMED
    partial, not the exact dual-slippage computation.
  - first gate that stopped it→`reason`: present. CONFIRMED (`decision` field also
    exists, holding take/refuse; `reason` is the more specific gate-name field).
- `_default_offer_tape_path`/`_DECISIONS_DIRNAME` (`composition.py:96,473-485,557`):
  CONFIRMED, `catalog_root.parent / "decisions" / f"offer_tape_{day.isoformat()}.jsonl"`.
  §7 step 0 is answerable from this source: `decision`/`ask` fields both exist and are
  exactly what the step's query needs (count of `decision="refuse"` rows with non-null
  `ask`). CONFIRMED correct and answerable.
- `offer_tape.py:46` docstring "7.9 MB / 9612 rows in ONE hour for ONE station" —
  CONFIRMED verbatim.
- `WP-B0` commit `f97c26f` landing and `breezy-check-alerts` CLI semantics — not
  re-verified this session beyond the plan's own citations (inherited from round 2's
  independent confirmation); no reason found to doubt it.

## Defects

**MATERIAL — the field-by-field count in §6 item 2 (and baked into §8's acceptance
criterion) is arithmetically wrong, understating the residual gap by one field.**
The plan's own §2 citation of bl19 s8.5 lists exactly 16 fields (verified against
`docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md:694-698` directly:
`station, climate_day, cli_received_ts, printed_value, is_final, correction_flag,
revision_seq, mapped_instrument_id, bucket bounds, hours_to_settlement, level0_ask,
ask_size, vwap_ask_at_intended_size, fee_coefficient, computed edge ..., and the FIRST
gate that stopped it` — 16 comma-separated items), and §6 item 2's own table has 16
rows matching that list one-for-one. But the plan states "`OfferTapeRecord` already
carries 7 of **15** s8.5 fields verbatim ... plus one present-by-equivalence ... and
one partial ... **Six** fields remain genuinely absent: `cli_received_ts`,
`printed_value`, `is_final`, `correction_flag`, `revision_seq`,
`hours_to_settlement`, and raw bucket bounds." The named-missing list itself contains
**seven** items (cli_received_ts, printed_value, is_final, correction_flag,
revision_seq, hours_to_settlement, raw bucket bounds), not six, and 7 present + 1
equivalence + 1 partial + 7 missing = 16, matching the table — not the stated "15"
total or "six" missing. This is not a stylistic nit: §8's acceptance criterion
literally requires the evidence doc to state "its explicit 'partially covered, six
fields missing, named' conclusion" — i.e. the plan's acceptance gate directly requires
publishing an inaccurate count as the deliverable's headline conclusion. For an item
whose entire round-3 contribution is correcting a prior miscount ("neither 'unbuilt'
... nor 'fulfilled'"), shipping a still-miscounted table undermines exactly the
sample-size/evidence-honesty standard this item exists to establish, and would mislead
any future item that cites this doc's field count when scoping the residual build.
**Required change:** correct §6 item 2's prose to "7 of 16" / "seven fields remain
genuinely absent", and correct §8's acceptance criterion text from "six fields
missing" to "seven fields missing" (or otherwise make the count self-consistent with
the table, which is correct as-is).

**MINOR — the field-by-field table's characterisation of `cli_received_ts` as flatly
"missing" does not address `OfferTapeRecord.observed_at_ns`/`ts_event`, both of which
are present fields that are timestamp-shaped and plausibly close in intent (`ts_event`
is the record's Nautilus event time; `observed_at_ns` is an explicit observation
timestamp).** The plan may be correct that neither is the CLI-receipt timestamp
specifically (a market-data-arrival clock, not an NWS-CLI-retrieval clock), but the
table states "missing" with no note explaining why `observed_at_ns`/`ts_event` were
considered and rejected as non-equivalents, unlike the `hours_to_settlement` row which
does explain why `minutes_since_window_open` doesn't count. This is inconsistent
diligence within the same table, not a wrong conclusion (I did not find evidence
`observed_at_ns` records CLI receipt time specifically). **Required change:** add one
clause to the `cli_received_ts` row's "Status" cell explaining why `observed_at_ns`/
`ts_event` are not treated as equivalents, mirroring the `hours_to_settlement` row's
treatment.

## Per-criterion scoring
- Fidelity to audit gap and completeness: 17/20 — (a)'s residual-scope framing is
  materially closer to the truth than round 2's "unbuilt" assumption, but the
  miscounted table (MATERIAL above) is itself the thing this round's fidelity gain
  depends on, and it's wrong.
- Technical correctness and evidence grounding: 15/20 — every structural claim
  (write-path tracing, `OfferTape` path, field presence/absence per row) verified
  correct against source this round; the arithmetic error is a correctness defect in
  the plan's own synthesis of facts it otherwise gathered accurately.
- Implementation specificity and feasibility: 13/15 — unchanged from round 3
  self-score reasoning; concrete join keys, file locations, extension points.
- Acceptance criteria and validation quality: 15/20 — the sole-sufficient-evidence
  rule for (b) is sound and closes the round-2 gap; (a)'s acceptance criterion for the
  field-by-field table directly requires restating the wrong count as the deliverable
  conclusion (MATERIAL above), which is a validation-quality defect, not just a prose
  slip.
- Autonomous operation, failure handling, recovery: 15/15 — three-valued probe design
  (AGREE/DISAGREE/UNKNOWN), unauthenticated-path requirement, idempotent
  `family_halted`/alert side effects unchanged and sound; no new defect found here.
- Portfolio alignment, scope, dependencies: 10/10 — dependency framing accurate,
  conditional blocker on (b) precise, no invented ROI number.

**Total: 85/100** (17+15+13+15+15+10)

## Required changes to reach 100
1. Correct the "15 fields" / "six missing" arithmetic throughout §6 item 2 and §8 to
   "16 fields" / "seven missing", consistent with the table's own 16 rows and the
   source s8.5 text's 16-item list.
2. Add a one-clause justification to the `cli_received_ts` table row explaining why
   `observed_at_ns`/`ts_event` don't count as equivalents (matching the diligence
   already shown for `hours_to_settlement`).

## Blockers
None requiring an operator/strategy ruling. Both required changes are precision fixes
within build authority. (b)'s existing conditional blocker — `breezy-check-alerts`
must exit 0 against the live node, else an operator action is required to set/confirm
`BREEZY_ALERT_WEBHOOK_URL` — remains correctly named in §12 and is not newly
introduced by this review.
