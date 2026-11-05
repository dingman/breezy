# AUD-12 review (round 1, mle-reviewer)

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-12-cost-model-slippage-and-fee-drift.md
sha256: a4cb6adcb9a4483af1dae947afb10349fc5837f1a9d966868239688cc3863541
Round: 1
Reviewer: mle-reviewer (backtesting / statistical-validation lens)

## Claims verified against source (this session, direct reads)

- `src/breezy/strategy/weather_common/costs.py:59` module docstring —
  CONFIRMED: "`slippage_prob` is UNMEASURED... the instrumentation obligation
  in s8.5 that is expected to replace the 0.01 placeholder with a figure
  derived from realised fills." Quoted accurately.
- `docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md` s8.5 (read in
  full this round, lines 667-742) — CONFIRMED: the required per-station-day
  record is exactly as quoted in the plan (`station, climate_day,
  cli_received_ts, ..., level0_ask, ask_size, vwap_ask_at_intended_size,
  fee_coefficient, computed edge at slippage_prob in {0.000, 0.010}, and the
  FIRST gate that stopped it`). **However**: this record is specified to be
  written **for every trigger, "regardless of whether an order forms"**
  (line 695), to make N0/N1/N2/N3 nulls decodable offline (the four-row
  table at lines 670-677). It is NOT specified as "compute realised slippage
  from filled orders" — that is `costs.py`'s own (pre-existing, not written
  by this plan) narrower paraphrase. AUD-12(a) implements only the
  fills-derived sub-case (n=6, post-fill `fill_px - decision_ask`), not the
  full per-decision record s8.5 actually specifies (which would also cover
  every REFUSED station-day, decodable for the N1/N2 distinction the section
  is built around).
- `src/breezy/adapters/polymarket_us/fees.py`: `DOCUMENTED_TAKER_FEE_COEFFICIENT
  = Decimal("0.06")` — CONFIRMED present (module fee-schedule pin section).
- `src/breezy/strategy/current_rung_hold/decision.py:331-332` — CONFIRMED
  EXACTLY: `if inputs.fee_coefficient != inputs.config.required_fee_coefficient:
  return Refuse("fee_schedule_mismatch")`. Line number precise.
- `TrialDayRecord` (`src/breezy/strategy/current_rung_hold/trial_day_latch.py:432`)
  — CONFIRMED: `ask: Decimal` field, `venue_order_id: str | None` field
  (optional/trailing, matches plan's join-key claim).
- `FillReport` construction (`src/breezy/adapters/polymarket_us/exec/reports.py`,
  ~1297-1322) — CONFIRMED: `venue_order_id=VenueOrderId(...)`, `last_px=
  _leg_price_field(...)`. Join key and field name both check out.
- `StateStore` Protocol (`.get(key) -> bytes | None`) — CONFIRMED identical
  shape in `gate.py`, `gaps.py`, `submit_intent.py`; plan's claim that this
  is "the same Protocol already used by gate.py/gaps.py/product_index.py" is
  structurally accurate (each module declares its own copy of the same
  two-method shape, deliberately, per each file's own docstring — not
  literally one shared class, but functionally interchangeable, which is
  what the plan's script needs).
- `resolve_alert_sink` (`src/breezy/runtime/health.py:579-610`) — CONFIRMED:
  returns `LoggingAlertSink` when unset, `TeeAlertSink(Logging, Webhook)`
  when `BREEZY_ALERT_WEBHOOK_URL` is set — matches plan's "becomes a real
  delivery once WP-B0 lands" framing.
- `continuous_family_check` / `family_halted` (`src/breezy/runtime/
  trade_supervisor_core.py:299-375`) — CONFIRMED real, matches plan's reuse
  claim (`family_not_halted` field, `ContinuousFamilyCheck.passed`).
- `POST_FORECAST_PHASE_2026-09-20.md` — CONFIRMED contains `WP-B0` (line 257,
  "alert egress. Blocks B1, B2, B3, R1"), `FAIL_CONTINUOUS_FAMILY_HALTED`
  (line 347). Plan's dependency claims are not fabricated.
- n=6 honesty (§3(a), §6 item 2, §8): the plan explicitly forbids an invented
  confidence interval and requires the doc state "n=6 cannot support
  replacing the 0.01 placeholder with confidence" — CONFIRMED as written;
  no point estimate is silently promoted to a new constant (§6 item 4, §8
  bullet 3: the constant stays byte-unchanged unless the doc's own
  recommendation section is acted on with its own RED test).

## Defects

**MATERIAL** — The plan's title and §1/§2 frame AUD-12(a) as fulfilling "the
BL-19 s8.5 obligation as written," but s8.5 specifies a broader, always-on
per-decision record (every triggered station-day, filled or refused) built
to decode N0/N1/N2/N3 nulls — not a post-hoc join over the 6 realised fills
only. AUD-12(a) delivers a real and useful measurement (realised execution
slippage on the fills that occurred), but it is a DIFFERENT, narrower
artefact than s8.5's literal ask, and the plan never states this distinction
— a reader could reasonably conclude "s8.5 done" when only the
narrower "slippage from realised fills" question is answered, and the
broader instrumentation (recording every REFUSED station-day's inputs, which
is what s8.5 says makes a null "decodable offline") remains unbuilt with no
tracking item named.
Required change: state explicitly in §3(a)/§12 that this item satisfies only
the fills-derived slippage sub-question `costs.py` names, NOT the full
per-station-day (fill-or-refuse) instrumentation record s8.5 specifies, and
either scope a follow-up id for the broader record or state why it is judged
unnecessary now (e.g., "no refused-but-priced station-days exist yet to
instrument" — an empirical claim that should be verified, not assumed).

**MINOR** — §6 item 1's sign-convention safety check ("a live fill better
than the decision ask is the same L-25 defect signature") is well-grounded
(matches `ImpossibleFillPriceError`'s own stance verified this round), but
the plan does not say what the script does numerically with a flagged
fill when computing mean/median/range for the n=6 report — excluded
entirely (dropping the sample size below 6 silently) or included with a
loud footnote. Required change: state the disposition explicitly in §6/§8
so the eventual doc's "n=6" is not silently n=5 or fewer without saying so.

**MINOR** — (b)'s probe interval is left fully open ("hourly? daily?") with
only a qualitative sufficiency rule ("materially shorter than the fee's
observed drift cadence"). That is a defensible deferral (not a material
design decision, per §12), but a probe that runs, say, once every 48h would
technically satisfy "materially shorter than one week" while still leaving
a two-day undetected-halt window comparable in kind (if not degree) to the
3-day failure this item exists to prevent. Suggest tightening to an explicit
numeric floor (e.g., "no coarser than every 2h, matching the mid-day
relaunch cadence already in place") rather than leaving the sufficiency
judgement entirely to the implementer.

## Per-criterion points

- Fidelity to audit gap and completeness: 15/20 — both G-09 sub-claims are
  addressed with real designs, but (a)'s relationship to s8.5's actual scope
  is mischaracterized as complete rather than partial.
- Technical correctness and evidence grounding: 19/20 — every cited
  mechanism (TrialDayRecord, FillReport, StateStore, decision.py:331,
  resolve_alert_sink, continuous_family_check, WP-B0) verified exact against
  source this round; only the s8.5-scope mismatch above is a correctness
  gap, not a citation-accuracy gap.
- Implementation specificity and feasibility: 13/15 — join keys, file
  locations, and the Actor/timer extension point are concrete; consistent
  with the self-score.
- Acceptance criteria and validation quality: 17/20 — n=6 honesty and the
  three-valued AGREE/DISAGREE/UNKNOWN probe are both structurally enforced
  in §8, not just asserted; no criterion tests whether the flagged-fill
  disposition is stated, and no criterion distinguishes "s8.5 fully closed"
  from "s8.5's fills-derived sub-question closed."
- Autonomous operation, failure handling, recovery: 14/15 — fail-closed
  UNKNOWN state directly reuses the audit's own named lesson (Amendment
  A-2); solid.
- Portfolio alignment, scope, dependencies: 9/10 — WP-B0 dependency named by
  id, A0 non-duplication explicit, no invented ROI number.

**Total: 87/100.**

## Required changes to reach 100

1. State explicitly that AUD-12(a) resolves only the "slippage from realised
   fills" sub-question, not s8.5's full per-station-day (including refused)
   instrumentation record, and name the residual gap (tracked or explicitly
   deferred with reasoning).
2. State the disposition of a flagged (sub-ask) fill in the mean/median/range
   computation — excluded-and-noted, or included-with-flag.
3. Tighten the fee-drift probe interval to an explicit numeric floor rather
   than a purely qualitative sufficiency rule.

## Blockers

None requiring an operator/strategy-lead ruling for (a). (b) already names
its own correct blocker (WP-B0 landing first) — not a new one raised by this
review.

## Score

87/100 — APPROVE WITH WARNINGS (mechanism and evidence grounding are strong;
the s8.5-scope mischaracterization is the one defect worth blocking a
"fully done" claim, but does not block the underlying measurement/probe
design from proceeding).
