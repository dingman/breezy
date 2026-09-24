# AUD-12 — Round 3 — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-12-cost-model-slippage-and-fee-drift.md
SHA256: 72be9e70b2bfafe6da7a09b678c5fac34a56c6853a51437fb46cd826ea925ceb
Round: 3
Reviewer: prediction-market-reviewer (independent, blind)
Lens: fee formula, IOC slippage reference price, fail-closed fee-drift
handling without editing the pin, alert delivery that actually reaches
someone.

## §13 review-history reconciliation

- Round-2 MATERIAL (mle-reviewer): §7 step 0's pre-check queried
  `TrialDayLatch`/`StateStore`, which never durably records a `Refuse`.
  Plan re-points step 0 at `offer_tape_<date>.jsonl` and adds a
  field-by-field s8.5-vs-`OfferTapeRecord` comparison (§6 item 2). VERIFIED
  this round (see below) — both corrections are accurate.
- Round-2 MATERIAL (prediction-market-reviewer): §7 step 5/§8 offered
  `breezy-check-alerts` exit 0 OR the boot-time `log_alert_egress_status`
  line as interchangeable evidence of delivery; the boot-log line cannot
  prove delivery. Plan now states `breezy-check-alerts` exit 0 as the SOLE
  sufficient evidence, demoting the boot-log line to configuration-only
  support. VERIFIED FIXED this round by direct, independent re-read of
  `health.py:629-665` (see below) — this round does not merely trust the
  round-2 citation, it re-derives the same conclusion from source.
- Round-2 MINOR: SDK snapshot path typo (`docs_snapshots/...` instead of
  `docs/evidence/venue/polymarket_us/sdk_snapshot/...`). VERIFIED FIXED —
  §6 item 3/§8 now cite the real path, confirmed to exist via direct read.

## Claims verified this round (direct source read, not inherited from prior rounds)

- `src/breezy/runtime/health.py:629-665` (`log_alert_egress_status`): reads
  only `alert_egress_configured(env)` (itself `bool(env.get(ALERT_WEBHOOK_URL_ENV_VAR))`),
  logs one INFO/WARNING line, returns a bool — **never constructs a sink,
  never calls `.emit()`, has no exit code.** Matches the plan's claim
  exactly; it can prove configuration only, never delivery.
- `src/breezy/runtime/check_alerts_cli.py` (full body read): genuinely calls
  `sink.emit(payload)` inside a try/except that converts the real outcome
  into exit 0 (delivered)/2 (not configured)/3 (configured, not delivered);
  on failure it withholds the exception message specifically because "it can
  embed the webhook URL" — matches the plan's "never prints the webhook URL"
  and exit-contract claims precisely.
- `src/breezy/strategy/current_rung_hold/decision.py:331`:
  `if inputs.fee_coefficient != inputs.config.required_fee_coefficient:
  return Refuse("fee_schedule_mismatch")` — CONFIRMED exact-`!=` equality,
  matching the plan's "mirroring `decision.py:331`'s existing check" claim.
- `OfferTapeRecord.to_dict` (`src/breezy/strategy/current_rung_hold/offer_tape.py:183-248`,
  read in full this round): field-by-field cross-check against the plan's
  §6 item 2 table — CONFIRMED accurate in every row: `station`,
  `climate_day`, `instrument_id`, `ask`, `size`, `fee_coefficient`, `reason`
  present verbatim; no `cli_received_ts`/`printed_value`/`is_final`/
  `correction_flag`/`revision_seq`/`hours_to_settlement`/raw bucket bounds;
  `width_code`/`m_code` present as partial bucket-geometry encoding, not raw
  bounds — exactly as the plan states.
- s8.5's field list (`docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md:694-696`,
  read verbatim this round): `station, climate_day, cli_received_ts,
  printed_value, is_final, correction_flag, revision_seq,
  mapped_instrument_id, bucket bounds, hours_to_settlement, level0_ask,
  ask_size, vwap_ask_at_intended_size, fee_coefficient, computed edge at
  slippage_prob in {0.000, 0.010}, and the FIRST gate that stopped it` —
  matches the plan's §2 quote and §6 item 2 table's left column exactly,
  word for word.
- `RefusalCounter` (`src/breezy/strategy/weather_common/refusals.py:121-139`)
  — CONFIRMED in-memory only, docstring states "never persisted... a restart
  starts the count at zero," matching the plan's §2 round-3 correction.
- `TrialDayLatch`'s durable write paths (`record_attempt`,
  `record_with_legacy_fallback` [a read, not a write], `consume_if_absent`,
  `record_duplicate_fill`) — traced via codegraph this round — all fire only
  on a genuine Take/fill; no `Refuse` branch writes to the store. Matches
  the plan's §2 claim exactly.
- `docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/client.py:79-133`
  — CONFIRMED to exist at this exact path (not `docs_snapshots/...`);
  `get()` defaults `authenticated=False`; `_request` routes
  `authenticated=False` to `self.gateway_base_url` with no auth headers,
  `authenticated=True` requires `key_id`/`secret_key` and routes to
  `self.api_base_url` — matches plan's §6 item 3 description exactly.
- Cross-check not previously made by either round-2 reviewer: the
  2026-09-17 fee-drift incident's own captured evidence
  (`docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md`, offer
  tape excerpt) shows the SAME drifted value `0.0695` across 3 different
  stations (MIA/MDW/SFO) and 6 different instrument rows on the same day —
  empirical support, already in the repo, that a theta drift is venue-wide
  rather than per-instrument. This substantiates §6 item 3's design choice
  to probe "one representative listed weather slug" as sufficient to detect
  the class of drift this item exists to catch, but the plan does not cite
  this evidence anywhere to justify that choice.

## Defects

**MINOR** — §6 item 3's fee-drift probe design checks a single representative
slug's `feeCoefficient` and treats a mismatch there as sufficient grounds to
halt the whole family. The design is reasonable and is, in fact, supported
by evidence already in the repo (the 2026-09-17 drift was uniform across 3
stations), but the plan does not cite that evidence to justify checking only
one slug rather than one per traded station/instrument. Since
`feeCoefficient` is parsed per-market (`parsing.py:639-645`,
`market.get("feeCoefficient")`), a hypothetical per-instrument-only drift
(not evidenced yet, but not structurally impossible) on an instrument other
than the probed slug would not be caught by this probe — it would still be
caught by the existing per-order `decision.py:331` check the moment a
decision reaches pricing, but G-01 (zero decisions reaching pricing) is
exactly the condition under which that backstop is currently silent.
**Required change:** cite the 2026-09-17 uniform-drift evidence in §6 item 3
as the empirical basis for the single-slug design, or extend the probe to
check one slug per currently-traded station as a stronger fail-closed
posture, whichever the implementer judges warranted — either is a small,
bounded addition, not a blocker.

No MATERIAL defect found this round. Every claim checked (alert-delivery
non-equivalence, `OfferTapeRecord` field table, `TrialDayLatch`/
`RefusalCounter` in-memory-only, fee exact-equality check, unauthenticated
SDK path, sole-sufficient-evidence closing criterion) was independently
re-derived from source this session, not merely trusted from §13 or from
the prior round's citations, and all matched the plan's claims.

## Per-criterion points (caps: 20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 20/20 — both G-09 sub-claims
  (measured slippage, fee-drift detection) are addressed with a concrete,
  source-grounded closing criterion for each; no gap found tied to a named
  defect.
- Technical correctness and evidence grounding: 20/20 — every mechanism
  claim independently re-verified against source this round matched
  exactly, including the one claim (`health.py:629-665`'s non-equivalence)
  the round-2 self-score flagged as "inherited... not independently
  re-read" — this round re-derived it directly and confirms it.
- Implementation specificity and feasibility: 14/15 — concrete throughout;
  the single-representative-slug probe design is sound but its
  justification is left uncited against evidence already in the repo (MINOR
  above).
- Acceptance criteria and validation quality: 20/20 — the sole-sufficient-
  evidence rule for (b) is now unambiguous and correctly distinguishes
  configuration from delivery; the field-by-field table for (a) is accurate
  and its "partially covered, six fields named" conclusion is honest.
- Autonomous operation, failure handling, recovery: 15/15 — three-valued
  AGREE/DISAGREE/UNKNOWN probe design, unauthenticated-path requirement, and
  idempotent `family_halted`/alert side effects are all sound and
  fail-closed.
- Portfolio alignment, scope, dependencies: 10/10 — dependency framing
  accurate (verification-gated, not landing-blocked); no duplication of A0;
  no invented ROI number; conditional blocker on (b) is precise.

**Total: 99/100.**

## Required changes to reach 100

- Cite the 2026-09-17 uniform-drift evidence (or otherwise justify) the
  single-representative-slug design in §6 item 3, or extend the probe to
  check one slug per currently-traded station.

## Blockers

None new. Whether the live node's process actually resolves `TeeAlertSink`
and delivers (§7 step 5's `breezy-check-alerts` run) remains the plan's own
correctly-named conditional blocker on closing (b) — not resolvable by this
reviewer (no secrets/process access), and not a scoring deduction since the
plan already states it as a blocker rather than assuming it away.
