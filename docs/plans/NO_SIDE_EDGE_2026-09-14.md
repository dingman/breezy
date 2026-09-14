# NO-side edge hunting — Increment 1 (Rev 1, 2026-09-14)

Ruling (operator, 2026-09-14): "It is a requirement to continuously hunt and identify edges on both yes and no."
Family: `pm_us_crh_cont` (PREREG v3). Backlog row NO-1. Supersedes BL-6.

Measured NO-side liquidity (quote tape, sole fully covered in-window day 2026-09-10): a non-empty YES bid exists in
44–86% of sampled rows (MDW 86.2%, LAX 58.8%, SFO 58.5%, MIA 44.4%); p10 bid depth 0.1 contracts. The NO leg is
therefore reliably executable only at MDW and frequently impossible at LAX. The other four days cannot support a
conclusion because their tape is stranded (ING-1). The executable gate must reflect this, not relax it.

## §1 L-1 null hypothesis — how Nautilus models the two outcomes

- Verdict: Nautilus already models this. Build the NO leg as a SECOND `BinaryOption`; build nothing new.
- Installed source `nautilus_trader/model/instruments/binary_option.pyx:80-81,120` documents `outcome : str` as a plain
  ctor arg. No side enum, no complement/sibling link, no two-outcome container. One `BinaryOption` == one outcome.
  Two outcomes ⇒ two instruments — the native shape, not a parallel model.
- Breezy already populates it: `parsing.py:1211-1221` picks the single `long=True` market side and uses its
  `description` as `outcome`; `parsing.py:1364` passes `outcome=outcome`. `exec/submit_chain.py:244-254`
  (`_outcome_token`) reads `instrument.outcome`, folds it to `"yes"`, emits `OUTCOME_SIDE_YES`.
- CAPTURED vs SDK divergence. SDK snapshot `docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/types/orders.py:9-14,111-126`
  has `intent: OrderIntent` and no `outcomeSide`/`action`. Breezy's live body (`submit_chain.build_order_body:297-318`,
  key set pinned at `ORDER_BODY_KEYS:78-91`) sends `outcomeSide=OUTCOME_SIDE_YES` + `action=ORDER_ACTION_BUY`, not
  `intent`. That body produced the 09-11 20:20Z SFO FILL, so the CAPTURED live schema is outcomeSide/action; the SDK's
  `intent` (incl. `BUY_SHORT`) is snapshot-only and never exercised. NO is `outcomeSide=OUTCOME_SIDE_NO`,
  `action=ORDER_ACTION_BUY` — a buy, premium-bounded. `BUY_SHORT` stays unused.
- Mapping: the NO leg keeps `raw_symbol=Symbol(slug)` (`build_order_body:303` reads `raw_symbol` for `marketSlug`)
  and gets a distinct `InstrumentId` whose symbol is `<slug>-no`.
- Downstream unchanged: NETTING/CASH one position per instrument (`exec/client.py:995-1001`); per-order cap
  `order_notional_usd = price × qty` (`submit_chain.py:222`) on the NO leg IS the premium; `allow_short=False` holds
  because a NO take is `OrderSide.BUY`; `BacktestOrderGuard._refuse_naked_short` (`runtime/backtest_order_guard.py:234-282`)
  never fires. Max loss = premium paid.
- Rejected: NO as a SELL on the YES instrument. Refused by `submit_chain.unmappable_order_reason:268-269`, the
  naked-short rule, and the guard's note that `CashAccount.balance_impact` returns +notional so no Nautilus cap can
  fire (`backtest_order_guard.py:262-266`). Economically wrong: a sell beyond net long is unbounded.
- Symbology/provider: `symbology.parse_weather_slug:474-506` and `_WEATHER_SLUG_RE:125-129` unchanged;
  `slug_to_instrument_id`/`instrument_id_to_slug` become side-aware (`-no` suffix → same slug). `provider.py`
  (`_weather_market_payloads:189-228`) emits two instruments per accepted market after S2. NO-leg `outcome` is derived
  from the non-long entry of `marketSides` (`parsing._market_sides:1188-1221`) — never a hardcoded `"No"`; no second
  side ⇒ no NO leg.
- Settlement: `MarketSettlement` is one `settlementPrice` per `marketSlug` (SDK `types/markets.py:92-97`). NO settles
  `1 − settlementPrice`. `VenueSettlementSnapshot` (`adapters/polymarket_us/tape_records.py:308`) and the
  `instrument_close` path apply the inversion by leg, keyed on the instrument's `outcome`.

## §2 Edge definition for NO (symmetric, same corpus)

- Estimand: `p_miss_lower := 1 − P_HOLD_UPPER[key]` is a valid 95% lower bound on `P(HIGH ∉ current rung)` because
  `P_HOLD_UPPER` is the 95% upper bound of the same Wilson interval. Same key
  `(station, season, hour_lst, width_code, m_code)`, same corpus, same `N_MIN=90`, same z.
- Take NO iff `p_miss_lower > NO_ask + fee(NO_ask)`, mirroring `decision.py:302-304`. `fee = θ·p·(1−p)` is symmetric
  under p→1−p, so `decision._fee:253-260` is reused verbatim; `θ=0.06` and the `fee_schedule_mismatch` gate unchanged.
- Generator: `scripts/analysis/generate_current_rung_hold_archive_table.py` gains a second emitted map `P_HOLD_UPPER`
  in `archive_table.py`. `CORPUS_SHA256` (`archive_table.py:32`) must not change; `STUDY_GIT_SHA` (:33) does.
  RED: regenerate and assert `P_HOLD_LOWER` is byte-identical and the diff is additions only. The archive-table pin
  contract test covers both maps and both shas.
- Increment 1 is CURRENT-RUNG NO only. The cell's `width_code`/`m_code` are `R(t)`'s own geometry, so `1 − p_hold` on
  that cell is the exact complement of the registered YES event. A NO on a non-current rung `r ≠ R(t)` is a different
  random variable absent from the table; "all-rungs NO" needs a new study keyed by `(d, width, margin)`, its own
  `N_MIN`, corpus pin and PREREG family. Out of scope.
- Legal-cell rule `_is_legal_cell:236-247` unchanged.
- Executable floor moves to the BID ladder. `market_quote_from_depth` (`strategy/depth10.py:44-74`) only optionally
  exposes `ask_ladder`; `MarketQuote` (`weather_common/models.py:50-95`) has no `bid_ladder`. NO_ask = `1 − YES_bid`,
  and the size available at NO_ask is the YES bid size. The NO executable gate reads the bid ladder, never
  top-of-book alone. Given the measured depth, NO will often refuse `not_executable`; that is correct.

## §3 Statistic — PREREG v3 amendment

Today's draw (`settlement/current_rung_hold_v2.py:148-200`) assumes mutually exclusive YES rungs:
`x = Σ qty_i(held_i − BE_i)`, `Var = Σ qty_i² BE_i(1−BE_i) − 2Σ_{i<j} qty_i qty_j BE_i BE_j`, admitted iff `Σ BE_i ≤ 1`.

Generalisation (drop-in; reduces byte-identically on YES-only days):

- Per leg: `s_i = +1` (YES) / `−1` (NO); `BE_i = ask_i + fee(ask_i)` on that leg's own ask; `held_i = 1{HIGH∈r_i}`
  for YES, `1{HIGH∉r_i}` for NO.
- Cell probability under H0: `q_i = BE_i` for YES, `q_i = 1 − BE_i` for NO. `q_i` is always `P(HIGH ∈ r_i)`.
- Identity: `held_i − BE_i = s_i (Y_{r_i} − q_{r_i})`, so `E[x] = 0`.
- `x = Σ qty_i (held_i − BE_i)` (unchanged form).
- `Var_H0(X_sd) = Σ qty_i² q_i(1−q_i) − 2 Σ_{i<j} qty_i qty_j s_i s_j q_i q_j`.
  Cov(Y_A,Y_B) = −q_A q_B ⇒ a YES/NO cross pair has `s_i s_j = −1` and adds `+2 q_A q_B` — the positive correlation
  the ruling names. All-YES ⇒ today's formula verbatim. `Var(S)=1` under H0 holds.
- Reconciliation of the two H0s: `BE_A` (YES) and `BE'_A` (NO) both price cell A and agree only if
  `BE_A + BE'_A = 1`. The conflict is removed by prohibition, not averaging: a YES fill and a NO fill on the SAME
  instrument-day are opposite bets and are FORBIDDEN (S4 pin). Across distinct rungs each `q_r` is set by the single
  leg that touches `r`.
- Admission gate replacing `Σ BE_i ≤ 1`: `Σ over DISTINCT rungs r of q_r ≤ 1`, i.e.
  `Σ_{YES} BE_i + Σ_{NO} (1 − BE_j) ≤ 1`. Same-rung same-side duplicates fold into `qty`; same-rung opposite sides
  raise before the gate. Refusal at draw construction (`StationDayAdmissionRefusal:137-146`), never post-hoc. A cheap
  NO contributes ~0.8 of probability mass, so NO plus a YES on another rung is usually inadmissible — correct.
- LD-OBF must be re-validated. Re-run `_run_h0_monte_carlo`
  (`tests/unit/test_multi_position_validation_2026_09_14.py`) extended to emit mixed-side station-days (YES-only,
  NO-only, mixed across distinct rungs, k=1..4) and confirm one-sided family-wise α ≤ 0.025 at every look n=10..160.
- Proposed ruling: AMENDMENT to v3, not a new family — side is a registered covariate, the mixed draw reduces exactly
  to v3's on YES-only days, accrued YES trials are preserved, the amendment is prospective from the deploy commit.

## §4 Slices (RED-first). First shippable increment = S1 + S6a (zero live behaviour change).

- S1 calibration. Generator + `P_HOLD_UPPER` in `archive_table.py`, `CORPUS_SHA256` unchanged, `STUDY_GIT_SHA` new,
  evidence artefact + pin test. RED: `P_HOLD_LOWER` byte-identical; `P_HOLD_UPPER[k] ≥ P_HOLD_LOWER[k]` ∀k. MUST NOT
  touch `decision.py` or any live path.
- S2 NO-leg modelling. `parsing.parse_binary_option:1274-1367` (second instrument, `outcome` from the non-long
  `marketSides` entry, `raw_symbol=Symbol(slug)`, id symbol `<slug>-no`, `info` copied incl. `FEE_COEFFICIENT_KEY`),
  `symbology.slug_to_instrument_id`/`instrument_id_to_slug`, `provider._weather_market_payloads`,
  `depth10.market_quote_from_depth` (+`bid_ladder`), `MarketQuote` (+`bid_ladder = None`, additive). RED: a NO leg
  built from a captured market payload prices `NO_ask == 1 − YES_bid` off the SAME recorded Depth10 frame. The
  recorder needs no change and no re-recording — the YES Depth10 tape is sufficient for the NO leg by inversion.
- S3 decision. `decision.py`: `Take` gains `side` (+ `p_miss_lower` additive), `DecisionInputs:164-190` gains `side`
  and the bid ladder, `evaluate_decision:263-312` branches at the executable gate (:290-295) and the table lookup
  (:297-304); `tick_eval.build_eligible_inputs:59`. MUST NOT change YES arithmetic — RED: every existing
  `test_current_rung_hold_decision.py` case passes unedited.
- S4 latch/ledger. `trial_day_latch._key:220-243` already keys per `(station, climate_day, instrument_id)`; the NO leg
  has its own instrument id, so per-leg keying is free. Add the same-rung YES/NO mutual-exclusion refusal (new
  closed-set reason) reading the sibling leg's TRIAL record. Per-order cap and `DailySpendLedger`/day-stop unchanged.
- S5 exec. `submit_chain._outcome_token` (+`"no" → OUTCOME_SIDE_NO`), `build_order_body` (key set unchanged, only the
  `outcomeSide` VALUE varies), `unmappable_order_reason`. Requires lifting barrier X3 ("X3 bans the NO-outcome constant
  under `exec/`", `submit_chain.py:5-6`) by explicit ruling plus a replacement structural test banning
  `BUY_SHORT`/`SELL_*` instead. Fill parse / reconciliation / resolver GET carry the leg so a NO fill is never booked
  as YES: `lastPx` on a NO fill is the NO price; the durable record's `order_side` stays `BUY` and the leg is carried
  by `instrument_id`, not by sign. L-37: the first live NO order is RESIDUAL until its request/response shape is
  captured — cheapest evidence first is `/v1/order/preview` with `outcomeSide=OUTCOME_SIDE_NO`
  (SDK `resources/orders.py:68-74`), captured under the permit, before any create.
- S6 statistic + artefacts. (a) `current_rung_hold_v2.py`: `StratumRow` gains `side`, `combine_station_day:171-200`
  implements the §3 variance and gate, `score_combined` unchanged. RED: an all-YES station-day is byte-identical to
  today. (b) Monte-Carlo extension + LD-OBF re-validation + ruling artefact + PREREG v3 amendment doc.
- S7 parity. `backtest_only.py` subclass + paper-replay driver replay a NO take off the inverted YES tape and
  reproduce the live decision byte-for-byte.

## §5 Risk

- Worst-case exposure unchanged: both operator caps bind identically — the per-order cap is `price × qty` on the NO
  leg (= premium); the daily budget and day-stop marker are untouched. No new spend surface.
- New failure modes, each with a RED test: (1) inversion off-by-one on a 0.01-tick book — `Decimal` only, `exec/`
  already bans `float()`; (2) a NO fill parsed as YES — settlement sign flips; pin the leg through `instrument_id`
  end-to-end; (3) settlement sign — NO settles `1 − settlementPrice`; (4) hedged pairs — YES and NO on the same
  instrument-day forbidden in S4; (5) the `NO_ask = 1 − YES_bid` identity is documented, not captured
  (`backtest_order_guard.py:259-261` is prose) — it MUST be confirmed against a captured NO-side preview/book before
  S5 ships; if the venue runs a separate NO book, S2's inversion is wrong and the recorder DOES need a NO subscription.
- `BacktestOrderGuard`: no rule change; it needs the NO instrument in cache/portfolio so `_net_long` is per-leg; its
  naked-short message drops the stale "price inversion" hint in favour of "buy the NO leg instrument".
- Fee model: `PolymarketUSFeeModel` reads `info[FEE_COEFFICIENT_KEY]` — copy θ onto the NO leg; reconciliation on a
  NO fill uses the NO price.

## §6 NOT changed

Nautilus (extension only); the NO-SEND execution-egress firewall and its guard test; boot permit; account-wide
submit-intent latch; `DailySpendLedger` and both operator caps; `allow_short=False`; `ORDER_BODY_KEYS`;
`CORPUS_SHA256`; `θ=0.06`; the legal-cell rule; the v2 PREREG (closed); recorder, catalog and tape schemas; any
safety/settlement/contract test.

## §7 Operator-only

1. Whether the existing daily budget / per-order cap stay as-is once the take rate rises (NO roughly doubles the
   eligible surface), or a new ceiling is supplied.

---

## Rev 2 dispositions (2026-09-14, after adversarial round 1: architect / market-math / safety)

All three reviewers returned REVISE. Two findings were raised independently by two reviewers (leg attribution of
fills; the same-rung sibling lookup) and are merged below. One contradiction between reviewers is resolved at N2-6.

- **N2-1 (BLOCKER, architect).** `slug_to_instrument_id`/`instrument_id_to_slug` (`symbology.py:206-226`) are a hard
  bijection with 45+ call sites (`data.py:1347,1366,1385,1402,1195`, exec client, provider, scripts). Overloading them
  with a `-no` suffix breaks the round trip for the NO leg and makes `_reconcile_discovered_subscriptions`
  (`data.py:1189-1238`) blind to a missing NO instrument. **Disposition: accepted.** The existing pair stays a
  bijection and is untouched. The NO leg id uses the already-reserved composite separator
  `INSTRUMENT_SEPARATOR = "~"` (`symbology.py:106-107`): symbol `<slug>~no`. New explicit helpers
  `no_leg_instrument_id(slug)`, `sibling_instrument_id(instrument_id)`, `leg_of(instrument_id)`, each with a
  round-trip RED test; `_SLUG_RE`/`assert_valid_slug` gain the composite form. Discovery reconciliation is extended to
  assert BOTH legs are cached for every accepted market. §1 is amended accordingly; the `-no` scheme is withdrawn.
- **N2-2 (MEDIUM, architect).** The NO instrument never receives native market data: inbound frames publish under
  the id resolved from the wire `marketSlug`, i.e. the YES id; a later `_subscribe_order_book_depth(NO_id)` would
  stall silently. **Disposition: accepted.** The NO leg is market-data-inert by design; S2 adds a guard refusing any
  live data subscription against an instrument whose `outcome` is not the registered long side, with a RED test.
  NO pricing is a decision-layer synthesis off the YES Depth10 frame (unchanged claim, now stated).
- **N2-3 (HIGH, architect + market-math, merged).** Fill/order/position attribution on the GET path is a
  precondition of the whole increment, not an S5 footnote: `parse_fill_report` (`reports.py:1121-1222`,
  `_assert_market_matches`) cross-checks `marketSlug` only, and the venue `Order`/`Execution` shapes carry
  `marketSlug` + free-text `marketMetadata.outcome`, no `outcomeSide`. **Disposition: accepted; moved to §1 as a
  precondition.** Mechanism: the durable submit-intent record already carries `order.instrument_id` (safety review:
  `intent_fingerprint`, `submit_chain.py:226-237`, hashes the instrument id; the latch is an account-wide singleton).
  The create path and the resolver GET path book the fill to THE INTENT'S instrument id, never to a slug lookup.
  S5 RED tests: (a) a NO fill resolved through the intent lands on the NO instrument; (b) an execution whose
  `marketMetadata.outcome` contradicts `instrument.outcome` is refused as drift (once the field is captured, L-37).
  A NO-side `/v1/order/preview` capture is an S5 EXIT criterion (see N2-9), and until a NO fill's shape is captured
  the first live NO order is residual.
- **N2-4 (MEDIUM, market-math).** `build_frozen_table` quantises `P_HOLD_LOWER` to 4 dp from the raw float;
  independent quantisation of `P_HOLD_UPPER` can violate `UPPER ≥ LOWER` by 1e-4 at boundary cells.
  **Disposition: accepted.** S1 derives `P_HOLD_UPPER` from the same raw Wilson float, quantises once with the same
  rounding, and the RED test asserts `UPPER[k] ≥ LOWER[k]` for every key plus `P_HOLD_LOWER` byte-identity.
  Confirmed by the reviewer's derivation: `1 − P_HOLD_UPPER == wilson_lower(n − hold, n)` exactly, same z both
  tails (`archive_correction_probe.wilson_interval`), so §2's estimand stands.
- **N2-5 (MEDIUM, market-math).** The S6b Monte-Carlo must simulate the ACTUAL selection rule (take whichever
  side's edge test fires, sides set by exogenous BE under H0), not an unconditional random side mix, and the
  martingale argument (`E[x_i]=0` per leg because `BE_i` is exogenous to `held_i`) is written into the amendment.
  **Disposition: accepted**; S6b scope amended.
- **N2-6 (HIGH, safety; contradicts the architect).** X3 IS test-enforced: `BANNED_EXEC_DIRECTION_TOKENS =
  {"_SHORT","OUTCOME_SIDE_NO"}` at `test_execution_egress_firewall_guard.py:252`, pinned again as a `RulePin` at
  `test_cage_rule_constants_are_pinned.py:862-869` whose `narrowed` case is exactly the S5 edit. The architect's
  "no dedicated X3 test" is therefore wrong (the safety reviewer cited line numbers; trusted). §6 "firewall and its
  guard test NOT changed" contradicted S5. **Disposition: accepted.** §6 item struck. S5 lands a NEW `RulePin` for
  the replacement token set (bans `_SHORT`, `BUY_SHORT`, `SELL_`) with its own widened/narrowed matrix, never a bare
  edit of the existing pin's `expected=`; the change ships only with a ruling artefact and an explicit security
  sign-off on that diff.
- **N2-7 (MEDIUM, safety).** The AST `1 − x` complement-arithmetic ban under `exec/`
  (`find_exec_direction_violations`, guard test :1278-1309) is the retained compensating control after the token is
  lifted. **Disposition: accepted**; named in S5, with a RED test proving a planted `1 - price` under
  `exec/submit_chain.py` still trips after the narrowing.
- **N2-8 (HIGH, safety).** No slice carried a settlement-sign RED test; `VenueSettlementSnapshot`
  (`tape_records.py:308`) has no inversion today and a wrong-sign NO settlement would be silent.
  **Disposition: accepted.** New slice **S2b settlement**: applying a venue settlement to a NO instrument yields
  `1 − settlementPrice` keyed on `instrument.outcome`; a YES/NO pair on one slug settles to values summing to 1;
  `instrument_close` routes by leg. Ships with S2, before S3.
- **N2-9 (MEDIUM, safety).** The NO-side preview capture must be an S5 exit criterion, not sequencing advice.
  **Disposition: accepted.** S5 does not merge until a captured NO-side preview response (under the permit, no
  create) confirms `outcomeSide=OUTCOME_SIDE_NO` + `action=ORDER_ACTION_BUY` is accepted and its price is the NO
  price. If the venue runs a separate NO book, S2's inversion is withdrawn and the recorder gains a NO subscription
  before any further slice.
- **N2-10 (MEDIUM, safety).** S4's same-rung mutual exclusion needs a named sibling lookup and a mid-day relaunch
  ordering test. **Disposition: accepted**, folded into N2-1's `sibling_instrument_id`; S4 RED test: a relaunch
  between a YES fill and the NO leg's check still refuses the NO take once the boot reconcile has walked the YES
  instrument's fill index (`_seed_spend_from_durable_fills`, `client.py:1276-1344`, walks per instrument).
- **N2-11 (LOW, market-math).** `decision.py:290-295` compares `size >= minimum_displayed_size` unit-agnostically
  while measured p10 NO-side depth is 0.1 contracts (venue `minimumTradeQty` 0.01). **Disposition: accepted as an
  S3 RED test** that the bid-ladder size and the order quantity are compared in the same unit; no gate relaxation.
- **Clean bills (safety, item 5):** spend seeding walks per instrument id, so NO fills sum correctly into the one
  ledger; the intent fingerprint hashes the instrument id; `unmappable_order_reason` refuses any SELL before the
  outcome token; `_net_long` is per instrument id. No change to §5's exposure claim.
- **Confirmed (market-math, item 5; architect, item 4):** current-rung NO only is a defensible Increment 1; slice
  order has no mis-sequencing; S1+S6a remains a zero-live-behaviour first increment.

### Slice list after Rev 2
S1 calibration (N2-4) → S6a statistic → S2 NO-leg modelling with composite id + data-inert guard (N2-1, N2-2) →
S2b settlement sign (N2-8) → S3 decision (N2-11) → S4 latch + sibling exclusion (N2-10) → S6b Monte-Carlo with the
real selection rule + amendment (N2-5) → S5 exec with new RulePin, AST backstop test, intent-keyed booking, preview
capture as exit criterion (N2-3, N2-6, N2-7, N2-9) → S7 parity.

---

## Rev 3 dispositions (2026-09-14, after round 2 + two code verifications) — CONVERGED

Round 2 returned REVISE from all three roles. Every open item was then verified against code or by an empirical
probe; the corrections below supersede the Rev 2 text where they conflict. Two reviewer contradictions are resolved
here by evidence (R3-2, R3-3).

- **R3-1 (supersedes N2-1's separator).** Empirical probe in the venv: `Symbol("x~no")` and `InstrumentId` accept
  `~` and round-trip; `ParquetDataCatalog.write_data` and `instruments()` work; but EVERY Rust-session read
  (`quote_ticks`, `order_book_deltas`, `query`, hence backtest replay) raises
  `RuntimeError: SQL error: ParserError(... found: ~ ...)` because
  `nautilus_trader/persistence/catalog/parquet.py:3064 _sanitize_sql_identifier` replaces only `. - space ^ :`.
  Data written under a `~` id is unreadable. **`~` is withdrawn.** The composite separator must satisfy, by RED test:
  (a) refused inside a base slug by `assert_valid_slug`; (b) accepted by Nautilus `Symbol`; (c) a `QuoteTick`
  written under the composite id reads back through `catalog.quote_ticks`. Candidates that the sanitiser handles:
  `^` and `:`. The S2 implementer picks one by that test and updates `INSTRUMENT_SEPARATOR` (`symbology.py:106-107`)
  and its reserved-character doc/regex accordingly; the NO leg is still data-inert, but the replay driver and any
  diagnostic must be able to query under its id.
- **R3-2 (corrects N2-3; resolves safety vs architect).** The durable `SubmitIntent` persists only
  `intent_id, fingerprint, created_ns, state, retired_ns, retirement_reason` (`submit_intent.py:233-287`); the
  fingerprint is a one-way hash, so the Rev 2 sentence "the intent record carries the instrument id" is wrong
  (safety reviewer correct, architect wrong). The mechanism that DOES exist: the durable resolver context
  (`AmbiguousResolverContext`, written by `_note_ambiguous_open`) persists `instrument_id`, and
  `_resolve_ambiguous_intents` (`client.py:1375`) selects the instrument by
  `self._cache.instrument(InstrumentId.from_str(context.instrument_id))` (`:1564`) before
  `parse_order_status_report` / `_resolve_accept_fill` / `parse_fill_report`. The create path passes the order's own
  instrument. So fills are booked by the CONTEXT's instrument id on the GET path and by the order's on the create
  path; no slug lookup exists on either. `SubmitIntent` needs no new field. S5 RED tests: (a) a NO order's ambiguous
  context persists the NO id and the resolved fill books to the NO instrument; (b) an execution whose
  `marketMetadata.outcome` contradicts `instrument.outcome` is refused as drift once that field is captured.
- **R3-3 (corrects N2-6).** `CAGE_RULE_PINS` is a tuple keyed by `(module, attr)` with a fixed label, and
  `test_the_pin_table_covers_every_rule_constant_the_plan_names` (`:930`) asserts an exact label set, so a second pin
  with the same label is impossible and the existing pin's `expected`/`widened`/`narrowed` MUST change when the live
  constant changes. Rev 2's "never a bare edit of expected=" is unimplementable and is withdrawn. Rule instead: S5
  changes the three values of the `firewall.BANNED_EXEC_DIRECTION_TOKENS` pin in ONE commit that also lands the
  ruling artefact and the security sign-off, with `why` citing the ruling; the new `narrowed` neighbour must drop a
  token the new set introduces (e.g. `BUY_SHORT`) so the pin still proves it can fail in both directions.
  `BANNED_EXEC_DIRECTION_TOKENS` at `test_execution_egress_firewall_guard.py:252` changes in the same commit.
- **R3-4 (extends N2-7).** `_is_one` (`guard test :1261-1275`) detects `1`, `1.0`, and any single-argument
  constructor of `"1"`/`"1.0"`/`1`/`1.0` (so `Decimal("1") - x` and `Decimal(1) - x` are caught) but only as the
  LEFT operand of `ast.Sub`; a module constant `ONE - x` (an `ast.Name`; `submit_chain.py` already imports `ONE`)
  is NOT caught. S5 widens `_is_one` to accept an `ast.Name` bound to one at module level (additive widening of the
  guard) with a RED test planting `ONE - price` under `exec/`.
- **R3-5 (corrects N2-8's target).** No live path wires `InstrumentClose` to positions today: the only
  `on_instrument_close` implementations are diagnostic counters (`strike_ladder.py:248`, `harness_probe.py:218`);
  the settlement gate `assert_settlement_close_permitted` (`settlement/exit_guard.py:162`) is written for a future
  `SettlementExitActor`; realised PnL comes from `compute_trade_returns` (`:121`) via `Position.realized_pnl`.
  Trial outcomes for the tally come from NWS truth (`held_i`), not venue settlement. S2b is therefore re-scoped:
  (i) the tally/scorer's `held` for a NO leg is `1{HIGH ∉ r}` — lands in S6a with a RED test; (ii) any synthetic
  settlement close for a NO leg prices at `1 − settlementPrice` through `exit_guard`/`compute_trade_returns`, with a
  YES/NO pair summing to 1; (iii) `VenueSettlementSnapshot` inversion by leg as before. No live position path is
  silently wrong today because none exists; the risk is in the tally, hence (i) is the first-increment item.
- **R3-6 (corrects N2-2's location).** `_reconcile_discovered_subscriptions` is a slug-keyed subscription planner
  and the NO leg is never subscribed, so the both-legs assertion cannot live there. It lives in the provider
  immediately after the add loops (`provider.py:400-403` in `load_all_async`, `:462` in `_load_slugs`): after adding
  the YES leg, assert the NO leg was added for the same slug (or that the market had no second side), with a RED
  test. The data-inert subscribe guard stands.
- **R3-7 (NEW HIGH, market-math round 2).** The Σq ≤ 1 admission gate runs only at TALLY (`combine_station_day`,
  called from `family_tally_v2`), i.e. after fills; a mixed-side day that breaches it would have spent capital on
  fills later discarded, a non-random admission pattern. **Accepted.** S4 adds an ARM-time check: before arming a
  take, sum `q` over the station-day's existing TRIAL records (YES: `BE`, NO: `1 − BE`, from the recorded ask+fee)
  plus the candidate; if > 1 refuse with a new closed-set reason `station_day_admission` before any submit. The
  tally gate stays as defence in depth and must never fire on a day the arm-time gate admitted (RED test). Note
  that YES-only days cannot breach under the edge rule (`ΣBE < Σp_lower ≤ 1`), which is why Increment A was safe.
- **R3-8 (closes N2-5).** The amendment states the H0 assumption explicitly: conditional on the cell probability
  `q_i`, the realised `held_i` is independent of the quoted `BE_i` (no adverse selection beyond the calibrated
  price). The S6b Monte-Carlo adds a stress scenario with weak positive correlation between `BE_i` and `held_i`
  and REPORTS the false-positive inflation; the report is an input to the ruling, not a pass/fail gate.
- **R3-9 (closes N2-4).** Confirmed; S1 also pins that a `None` (below `N_MIN` / illegal) co-occurs in both maps.
- **R3-10 (closes N2-9, N2-10, N2-11).** Unchanged from Rev 2.

### Slice list after Rev 3 (first shippable increment = S1 + S6a, zero live behaviour change)
S1 calibration (R3-9) ∥ S6a statistic + NO `held` inversion (R3-5 i, §3 variance, RED byte-identity on all-YES) →
S2 NO-leg modelling with the RED-chosen separator, provider both-legs assertion, data-inert guard (R3-1, R3-6) →
S2b settlement (R3-5 ii, iii) → S3 decision (N2-11) → S4 latch: sibling exclusion + arm-time admission (N2-10,
R3-7) → S6b Monte-Carlo with the real selection rule + exogeneity stress + amendment (R3-8) → S5 exec: pin change
in one commit with ruling + sign-off, `ONE - x` guard widening, context-keyed booking test, preview capture as exit
criterion (R3-2, R3-3, R3-4, N2-9) → S7 parity.
