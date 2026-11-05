# AUD-12 — Round 1 — prediction-market-reviewer

Plan: docs/plans/backlog/AUDIT_2026-09-21/AUD-12-cost-model-slippage-and-fee-drift.md
SHA256: a4cb6adcb9a4483af1dae947afb10349fc5837f1a9d966868239688cc3863541
Round: 1
Reviewer: prediction-market-reviewer (independent, blind)
Lens: fee formula correctness, slippage vs actual executable price, settlement
timing, what was tradable at decision time.

## Claims verified

- `DOCUMENTED_TAKER_FEE_COEFFICIENT = Decimal("0.06")` at `fees.py:86` —
  CONFIRMED verbatim, with the docstring's own statement that it is public
  "because the schedule-pin capture test is the only legal cross-package
  reader -- nothing in `src/` may import it," matching the plan's Amendment
  A-3/A-9 "never edit the pin in place" framing.
- `FEE_SCHEDULE_PIN_2026-09-18.md` — CONFIRMED: 2026-09-17 drift to `0.0695`,
  exactly 3 journal lines, `decision.py`'s `!=` exact-equality refusal is the
  only existing signal, and the doc explicitly forbids an in-place pin edit
  ("Resolving that is a new family revision plus D0, never an in-place pin
  edit"). The plan's (b) design (never touch the pin, drive the existing
  `family_halted` state, alert instead) is consistent with this constraint.
- `θ·p·(1-p)` fee formula reference (plan §9/context via B-9 in
  `POST_FORECAST_PHASE_2026-09-20.md:355`) — CONFIRMED present verbatim in
  that document ("C2's frozen statistic uses fee `θ·p·(1−p)`... θ is exactly
  what A0 measures"). AUD-12 does not itself change the formula; it only
  measures/monitors θ, which is the correct scope boundary.
- Amendment B-7 "pull raw wire JSON, never `instrument.maker_fee`" —
  CONFIRMED verbatim at `POST_FORECAST_PHASE_2026-09-20.md:341-342`, and the
  reason (parsing.py writes θ onto both `maker_fee`/`taker_fee` flat fields,
  making the maker field unreadable independently from the catalog) is
  confirmed in `FEE_SCHEDULE_PIN_2026-09-18.md:117-122`. The plan correctly
  reuses this finding rather than re-deriving it.
- `TrialDayRecord.ask` as "the DECISION-time ask `_hunt_tick` captured for
  this station-day" — CONFIRMED against `continuous_strategy.py`'s
  `_hunt_tick`: the decision reads `snapshot.ask` (top-of-book, gated by
  `executable_ask_lower < ask < executable_ask_upper` and
  `size >= minimum_displayed_size`) at the instant of evaluation, and this is
  the SAME ask fed into `evaluate_both_sides`/edge computation. Every entry
  order is a BUY IOC at `limit=entry_ask` (confirmed via
  `paper_replay.ImpossibleFillPriceError`'s docstring, D3: "fill_px < entry_ask
  ... impossible for that order shape"). **`fill_px - decision_ask` is
  therefore the correct reference price for this venue's IOC-at-the-ask take
  — not mid, not last trade** — and the sign convention (non-negative;
  better-than-ask is suspect, per L-25) is internally consistent with the
  paper-replay guard already enforcing the identical rule on the backtest
  side. This is the right answer to the specific challenge in the brief.
- `bl19_edge_and_cost_decision_2026-09-01.md` s8.5 record spec — CONFIRMED
  verbatim (`level0_ask, ask_size, vwap_ask_at_intended_size, fee_coefficient,
  computed edge at slippage_prob in {0.000, 0.010}`).
- WP-B0 (alert egress) status — **the plan's framing is STALE.** Commit
  `f97c26f` ("feat(wp-b0): alert egress -- give detection a destination"),
  dated 2026-09-20, already landed `resolve_alert_sink`, `WebhookAlertSink`,
  and `TeeAlertSink` in `src/breezy/runtime/health.py` (verified verbatim:
  `TeeAlertSink` fans out to local log + webhook, contained per-branch, with
  a loopback-TLS test proving real delivery). This predates the plan's own
  2026-09-21 authorship date. The user's own memory record confirms this:
  "alerts-reach-nobody FIXED 09-20 (f97c26f)."

## Defects

**MATERIAL** — §4 and §12 state WP-B0 as an unresolved future dependency
("If WP-B0 has not landed when this item is picked up, (b) is blocked until
it does") when the mechanism has, in fact, already landed one day before this
plan's own date. The plan's own binding instruction (§1 of the review brief,
and the plan's own evidence discipline elsewhere) is to verify load-bearing
claims against the artefact; `git log`/`health.py` were not checked here.
**Required change:** state plainly that WP-B0's code has landed (cite
`f97c26f`), and separate two distinct conditions the plan currently conflates
under "WP-B0 landing": (1) the delivery MECHANISM exists in `src/`
(confirmed done), vs. (2) the mechanism is actually CONFIGURED on the live
node — `resolve_alert_sink` returns a bare `LoggingAlertSink()` unless
`BREEZY_ALERT_WEBHOOK_URL` is set in the live process environment, which is
an operator action this plan neither checks nor lists as a precondition.

**MATERIAL** — following directly from the above: §8's acceptance criteria
prove the fee-drift Actor emits a CRITICAL through a *stub* alert sink in a
unit test (RED test 3, three-valued AGREE/DISAGREE/UNKNOWN) — this proves the
Actor's OWN logic is correct, but nothing in §8 requires confirming that the
LIVE node's `resolve_alert_sink()` actually resolves to a `TeeAlertSink`
(i.e., that the webhook URL is configured) before this item is considered
done. Given the brief's specific challenge — "does its alert actually reach
someone" — and given the exact failure this item exists to prevent (a
detector whose signal never left the log file, per the FEE_SCHEDULE_PIN
09-17 incident and the WP-B0 commit message's own "3 days... 11 hours...
neither delivered" framing), a probe that passes every test in this plan
while the live node's alert egress is still unconfigured would silently
reproduce the exact failure class this item is written to close. **Required
change:** add an acceptance criterion that inspects the live node's resolved
alert sink type (or the presence of `BREEZY_ALERT_WEBHOOK_URL` in its
environment) as a precondition for closing (b), not merely a stub-sink unit
test.

**MINOR** — §6 item 3 / §7 step 3 do not specify which base URL/auth mode the
wire-fee GET must use. The vendored SDK snapshot
(`docs_snapshots/.../client.py:84-133`) shows `authenticated=False` requests
route to `gateway_base_url` with no signed headers, while `authenticated=True`
requires `key_id`/`secret_key` and routes to `api_base_url`. The plan should
state explicitly that the probe must use the unauthenticated gateway path —
"a periodic, read-only probe... fetches the venue's currently-advertised fee
schedule" is directionally correct but leaves the implementer free to
default to an authenticated client, which would put a standing credential in
a periodic timer loop unnecessarily and widen this item's blast radius past
what "read-only GET, no order" implies.

**MINOR** — §6 item 1 / §9's `fill_px - decision_ask` convention is not
explicitly reconciled with bl19 s8.5's `vwap_ask_at_intended_size` (a
depth-walked reference distinct from `level0_ask`). Since
`CurrentRungHoldConfig.order_quantity` is pinned to 1 contract and the
decision gate already requires `size >= minimum_displayed_size` at the
top-of-book ask, `level0_ask` and `vwap_ask_at_intended_size` should coincide
for every live fill measured here — but the plan should state this
equivalence explicitly rather than leave it implicit, since a future reader
sizing above 1 contract would need a different reference price and this doc
would otherwise look silently wrong for that case.

## Per-criterion points

- Fidelity to audit gap and completeness: 16/20 (-2 for the stale WP-B0
  dependency framing, which misstates the audit gap's current state).
- Technical correctness and evidence grounding: 16/20 (-2: the one claim this
  round could check against `git log`/`health.py` and did not match the
  plan's framing).
- Implementation specificity and feasibility: 12/15 (-1: unauthenticated GET
  path not named explicitly).
- Acceptance criteria and validation quality: 15/20 (-3: missing the
  live-configuration acceptance criterion that is the actual point of (b)).
- Autonomous operation, failure handling, recovery: 13/15 (-1: the
  AGREE/DISAGREE/UNKNOWN three-valued design is sound and correctly reuses
  the A-2 lesson, but "alert reaches someone" is asserted, not verified, at
  the live-config layer).
- Portfolio alignment, scope, dependencies: 8/10 (-1: dependency-by-id is the
  right pattern, but the cited state of that dependency is wrong).

**Total: 80/100.**

## Required changes to reach 100

- Correct §4/§12 to state WP-B0's code has landed (`f97c26f`, 2026-09-20);
  reframe the remaining precondition as "alert egress CONFIGURED on the live
  node," not "WP-B0 landing."
- Add a §8 acceptance criterion verifying live alert-sink configuration
  (env var presence / resolved sink type), not just a stub-sink unit test.
- Name the unauthenticated `gateway_base_url` path explicitly for (b)'s probe.
- State the `level0_ask == vwap_ask_at_intended_size` equivalence (at
  `order_quantity=1`) explicitly in (a)'s methodology.

## Blockers

- Whether `BREEZY_ALERT_WEBHOOK_URL` is currently set on the live node's
  process environment is an operator-configuration fact this review could not
  check (secrets/config files are out of scope for this reviewer). The plan
  must not proceed to close (b) without that fact being verified by whoever
  implements it — this is the actual, not-yet-closed blocker behind "does the
  alert reach someone," and it is currently invisible in the plan's own
  dependency framing.
