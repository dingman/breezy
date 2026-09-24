# AUD-12 — Replace the slippage placeholder with measured realised-fill slippage, and add unattended fee-schedule drift detection

## 1. ID and actionable title

**AUD-12** — (a) instrument `slippage_prob` from the 6 realised live fills'
**fills-derived sub-question only** (NOT the full BL-19 s8.5 per-station-day
record — see §3(a)), honest about n=6; (b) unattended, alerting, fail-closed
fee-schedule drift detection that never edits the pin, with `breezy-check-alerts`
exit 0 against the live node as the sole sufficient evidence of delivery
before this item can be considered closed.

## 2. Source finding

Gap **G-09** (`docs/evidence/AUTONOMY_ROI_AUDIT_2026-09-21.md:73-77`), verdict
**UNVERIFIED**. Evidence (V, re-verified this session against source):

- `src/breezy/strategy/weather_common/costs.py:59` (module docstring, "WHY TWO
  TERMS AND NOT ONE SCALAR"): `slippage_prob` is explicitly **UNMEASURED**,
  citing `docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md` s2/s8.2 and
  "the instrumentation obligation in s8.5 that is expected to replace the 0.01
  placeholder with a figure derived from realised fills."
- `docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md` s8.5 (re-read this
  session, lines 667-742; the field list re-counted this round — see the
  round-4 correction below): specifies the exact per-station-day record a
  capture must carry, "regardless of whether an order forms" (line ~694),
  covering the full N0/N1/N2/N3 null-decoding table (lines 672-677) — every
  REFUSED station-day too, not only realised fills. AUD-12(a) implements only
  the narrower, fills-derived sub-case `costs.py`'s own docstring names — see
  §3(a).
- `src/breezy/adapters/polymarket_us/fees.py:86` pins
  `DOCUMENTED_TAKER_FEE_COEFFICIENT = Decimal("0.06")`; θ drifted to 0.0695 on
  09-17 (`docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md:47`,
  V) and `current_rung_hold/decision.py:331`'s exact `!=` comparison against
  this pin is what currently halts the live node. That refusal only fires
  when an order is actually attempted. Since 09-15 zero decisions reach
  pricing at all (G-01), so a SECOND, unrelated fee drift today would
  currently be invisible.
- **(Round 2, corrects a stale R1 claim, retained.) WP-B0 (alert egress) has
  already LANDED**: commit `f97c26f`, 2026-09-20T14:08:33Z, confirmed via
  `git show --stat f97c26f`. It added `resolve_alert_sink`, `WebhookAlertSink`,
  `TeeAlertSink`, boot-time `alert_egress_configured()`/
  `log_alert_egress_status`, and the one-shot CLI `breezy-check-alerts` (exit
  0 delivered / 2 no egress / 3 configured-but-not-delivered). Coordinator-
  verified fact (2026-09-21, value never printed): `BREEZY_ALERT_WEBHOOK_URL`
  is present and non-empty in `~/.config/breezy/breezy-trade.env` (grep -c =
  1), which the supervisor unit loads via `EnvironmentFile=`. Whether the
  running NODE process actually resolves `TeeAlertSink` at runtime, and
  whether the endpoint truly delivers, are the two facts this item's (b)
  closing criterion must still establish — see §7 step 5 / §8.
- The two durable data sources needed for (a) already exist and are joinable:
  `TrialDayRecord.ask` (`src/breezy/strategy/current_rung_hold/continuous_strategy.py:2392-2399`,
  the decision-time ask `_hunt_tick` captured for this station-day, never the
  fill price) persisted per station-day via `TrialDayLatch`'s `StateStore`,
  and `FillReport.last_px` (`src/breezy/adapters/polymarket_us/exec/reports.py:1297-1322`)
  persisted per fill in `~/.local/share/breezy/state/exec_polymarket_us.sqlite`
  (schema read-only this session: single `state(key TEXT PRIMARY KEY, value
  BLOB)` table, keys under `exec/polymarket_us/fill/*` — no amounts
  reproduced here). Both key off `venue_order_id`/instrument. `TrialDayRecord.ask`
  is confirmed the top-of-book ask gated by `executable_ask_lower < ask <
  executable_ask_upper` and `size >= minimum_displayed_size`, the SAME ask
  fed into `evaluate_both_sides`. Since `CurrentRungHoldConfig.order_quantity`
  is pinned to 1 contract, `level0_ask` and s8.5's
  `vwap_ask_at_intended_size` coincide for every live fill measured here —
  stated explicitly so a future reader sizing above 1 contract knows this
  equivalence would need re-establishing.
- **(Round 3, corrects a round-2 MATERIAL defect — independently re-verified
  this session via `mcp__codegraph__codegraph_explore` against
  `continuous_strategy.py`/`trial_day_latch.py`/`offer_tape.py`.) A `Refuse`
  decision is NEVER written to `TrialDayLatch`/`StateStore`.** The latch's
  only durable write paths (`record_attempt`, `record_with_legacy_fallback`,
  `record_duplicate_fill`, `consume_if_absent`) all fire exclusively on a
  `Take` that is submitted or already filled; every `Refuse` branch only
  calls `self.refusals.record(decision.reason)` against
  `weather_common/refusals.py`'s `RefusalCounter` — confirmed in-memory-only
  by its own docstring ("never persisted... a restart starts the count at
  zero"). Round 2's §7 step 0 pre-check ("query whether any refused-but-
  priced station-day records exist in `TrialDayLatch`/`StateStore`") is
  therefore guaranteed to return zero regardless of what actually happened on
  the live node — a measurement-instrument defect the mle-reviewer correctly
  caught. **The correct durable source is `OfferTape`/`OfferTapeRecord`**
  (`src/breezy/strategy/current_rung_hold/offer_tape.py`), which records
  every eligible snapshot — Take AND Refuse — to a durable per-day JSONL
  sidecar at `catalog_root.parent / "decisions" / f"offer_tape_{day.isoformat()}.jsonl"`
  (confirmed at `composition.py:473-485,554-559`, `_default_offer_tape_path`/
  `_DECISIONS_DIRNAME`). §7 step 0 is re-pointed at this source below; §6
  item 2 below adds the field-by-field comparison against s8.5's specified
  record the mle-reviewer required.
- **(Round 4, corrects a round-3 MATERIAL arithmetic defect, independently
  found by mle-reviewer and re-counted directly this round.)** s8.5's field
  list, read verbatim from
  `docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md:694-698`:
  `station, climate_day, cli_received_ts, printed_value, is_final,
  correction_flag, revision_seq, mapped_instrument_id, bucket bounds,
  hours_to_settlement, level0_ask, ask_size, vwap_ask_at_intended_size,
  fee_coefficient, computed edge at slippage_prob in {0.000, 0.010}, and the
  FIRST gate that stopped it` — counted directly this round: **16**
  comma-separated items, not 15. Round 3's §6 item 2 table already listed all
  16 rows correctly but its prose summed them as "7 present + 1 equivalence +
  1 partial + six missing = 15" and named only six of the seven actually-
  missing fields. Re-summed this round: 7 present verbatim (`station`,
  `climate_day`, `mapped_instrument_id`, `level0_ask`, `ask_size`,
  `fee_coefficient`, "first gate that stopped it") + 1 present-by-equivalence
  (`vwap_ask_at_intended_size`) + 1 partial (computed edge) + 7 missing
  (`cli_received_ts`, `printed_value`, `is_final`, `correction_flag`,
  `revision_seq`, `hours_to_settlement`, raw bucket bounds) = 16, matching
  the table's own 16 rows. §6 item 2 and §8 below are corrected to "16
  fields" / "seven missing" throughout.

**Class:** verification gap, resolving to (a) **implementation defect** and
(b) **missing capability**.

## 3. Current behaviour, required behaviour, concrete gap

**(a) Slippage.** Current: `slippage_prob` is a hardcoded `0.01` (one tick),
labelled unmeasured. Required: a measured figure — `fill_px - decision_ask`
per fill, joined via `venue_order_id` between `TrialDayRecord` and
`FillReport` — reported alongside its n=6 sample, honest that n=6 cannot
support a CI that excludes the current placeholder with confidence, and
**not** substituted into `costs.py` as a new silent constant. **Explicit
scope statement (retained from round 2): this item satisfies ONLY the
"slippage derived from realised fills" sub-question — it does NOT build
s8.5's full per-station-day record.** **Round 3 addition, corrected round 4:**
that residual scope is no longer treated as a bare "unbuilt" claim — §6 item
2 below requires a field-by-field comparison of `OfferTapeRecord`'s existing
schema against s8.5's specified column list before any "remains unbuilt"
statement is made in the output doc, because `OfferTapeRecord` was found this
round to already cover a substantial fraction (7 of 16, verbatim; see §2) of
s8.5's fields for every eligible snapshot (Take and Refuse), not zero as
round 2 implicitly assumed by querying the wrong table. Gap: the join
(fills-derived) has never been run; the correct pre-check source for the
residual-scope question was misidentified in round 2 and is corrected here.

**(b) Fee drift.** Current: fee-schedule mismatch is detected ONLY as a
side-effect of an actual order attempt, and zero decisions reach pricing
today (G-01), so a second, independent drift would be invisible. Required:
an unattended, periodic, read-only probe of the venue's currently-advertised
fee schedule, independent of order attempts, alerting through a path whose
LIVE delivery is proven — not merely configured — and failing closed on any
θ disagreement, never by editing the pin. **Round 3 tightening (resolves the
round-2 prediction-market-reviewer's MATERIAL finding):** the closing
evidence for "delivered" is `breezy-check-alerts` exit 0 against the live
node's actual environment — alone, not interchangeable with the boot-time
`log_alert_egress_status` line, which can prove only that the env var is
non-empty at boot (it never calls `.emit()`, never sends, has no exit code)
and therefore cannot prove delivery. Gap: no probe exists; the closing
criterion previously treated two non-equivalent evidence types as
interchangeable "or" alternatives.

## 4. Priority, rationale, dependencies, execution order

**(a) P2.** Directly answerable from data that already exists, closes a
named instrumentation debt, but n=6 means the result cannot itself unblock a
trading decision. **(b) P1.** The bot is CURRENTLY fee-halted and every day
that halt runs undetected by an independent channel repeats the exact
three-day silent-halt failure `POST_FORECAST_PHASE_2026-09-20.md` names.

**Dependencies:**
- (a) depends on nothing new; reuses existing persisted state, read-only.
- (b) **shares scope with `POST_FORECAST_PHASE_2026-09-20.md`'s A0 and
  WP-B0/WP-R1.** WP-B0's code has already landed (`f97c26f`); this is no
  longer an upstream-landing dependency. The remaining precondition is
  verification-shaped: (b) may not be marked closed until
  `breezy-check-alerts` — run against the live node's actual resolved
  environment — exits 0. If it does not, closing (b) requires the operator to
  set/confirm `BREEZY_ALERT_WEBHOOK_URL` in the live process environment — an
  operator-configuration action, named as a conditional blocker (§12).

**Execution order:** (a) and (b) are independently actionable. (b)'s
implementation may proceed immediately (WP-B0 already landed); its CLOSURE
is gated on the live `breezy-check-alerts` run. (a) has no ordering
constraint within cluster D.

## 5. Scope and explicit exclusions

**In scope (a):** a script joining `TrialDayRecord.ask` and
`FillReport.last_px` for the 6 known live fills, computing `fill_px -
decision_ask` per fill, reporting mean/median/range and an explicitly-labelled
"n=6, underpowered" verdict with a stated disposition for any flagged
(sub-ask) fill (§6 item 1), and a decision on whether/how `costs.py`'s
placeholder documentation is updated to cite the measured figure (the
constant itself is NOT changed). Also in scope: the corrected §7 step 0
pre-check against `OfferTapeRecord` (not `TrialDayLatch`/`StateStore`) and
the field-by-field comparison table against s8.5 (§6 item 2), correctly
summed to 16 fields / 7 missing (round 4).

**In scope (b):** a periodic, read-only probe, no coarser than every 2
hours, fetching the venue's currently-advertised fee schedule via the
**unauthenticated `gateway_base_url` GET path** (no signed headers, no
standing credential in the timer loop), comparing to
`DOCUMENTED_TAKER_FEE_COEFFICIENT`, and on mismatch (i) alerting through the
delivered-alert path and (ii) driving the SAME `family_halted` fail-closed
state the existing order-path refusal already uses. Also in scope: closing
(b) only on `breezy-check-alerts` exit 0 against the live node (§7 step 5);
citing the existing evidence for the probe's single-representative-slug
design (§6 item 3, round 4).

**Excluded:** editing `DOCUMENTED_TAKER_FEE_COEFFICIENT` in place;
substituting a new slippage CONSTANT into `costs.py` without the same n=6
honesty; re-litigating the A0/A1 θ ruling; building WP-B0 (already landed,
not duplicated); building s8.5's full per-station-day record beyond the
field-by-field comparison this item now performs against `OfferTapeRecord`
(building any missing fields, if warranted, is a named follow-up, not built
here — §12); setting `BREEZY_ALERT_WEBHOOK_URL` on the live node if found
unconfigured (operator action, §12); reading or reproducing any fill AMOUNT
beyond an aggregate (mean/median/range); probing more than one slug per
currently-traded station for fee drift (§6 item 3 states this as a bounded,
evidence-justified design choice, not an unlimited exclusion — extending to
one slug per station remains a named, small option for the implementer).

## 6. Proposed changes, grounded in inspected code/config/data flows

1. **(a) Slippage measurement script**, `scripts/analysis/measured_slippage_from_fills.py`
   (new): reads the 6 fill `venue_order_id`s from
   `exec_polymarket_us.sqlite`'s `exec/polymarket_us/fill/*` keys (read-only
   `StateStore.get`), decodes each `FillReport`-shaped JSON for `last_px`,
   joins against the corresponding `TrialDayRecord.ask` read via
   `TrialDayLatch`'s existing read path — both keyed by `venue_order_id`.
   Computes `fill_px - decision_ask` per fill (non-negative by the same
   IOC-at-limit-ask logic `paper_replay.ImpossibleFillPriceError` already
   enforces for the paper path). **Disposition of a flagged fill (retained
   from round 2): excluded from mean/median/range, reported separately by
   count and value** — "n=5 included, 1 flagged" or "n=6 included, 0
   flagged," never a silent n-reduction. `level0_ask` is used as
   `decision_ask` directly (coincides with `vwap_ask_at_intended_size` at
   `order_quantity=1`, per §2).
2. **(a) Output**: `docs/evidence/MEASURED_SLIPPAGE_2026-09-21.md` — n (with
   included/flagged breakdown), each fill's slippage value, mean/median/range
   over included fills, an explicit statement that n=6 (or fewer) cannot
   support replacing the 0.01 placeholder with confidence, and the explicit
   fills-derived-only scope statement. `costs.py`'s docstring is updated to
   cite this doc — the `0.01` constant itself is UNCHANGED unless the
   measured mean gives the implementer explicit, written reason to believe
   0.01 is unsafe-low.
   **New this round (round 3), corrected round 4 — field-by-field s8.5
   comparison table (resolves the round-2 mle-reviewer's MATERIAL defect;
   arithmetic corrected per the round-3 mle-reviewer's MATERIAL defect):**
   the doc's scope-statement section includes a table comparing
   `OfferTapeRecord`'s existing fields (`to_dict`, `offer_tape.py:183-248`)
   against bl19 s8.5's specified 16-field per-station-day column list,
   stated exactly, not assumed:

   | s8.5 field | `OfferTapeRecord` equivalent | Status |
   |---|---|---|
   | `station` | `station` | present |
   | `climate_day` | `climate_day` | present |
   | `cli_received_ts` | — (`observed_at_ns`/`ts_event` are present but are NOT treated as equivalents: `ts_event` is the record's Nautilus event time and `observed_at_ns` is a market-data-arrival timestamp, neither measures the NWS-CLI-retrieval clock s8.5 specifies) | **missing** |
   | `printed_value` (tmax_f) | — | **missing** |
   | `is_final` | — | **missing** |
   | `correction_flag` | — | **missing** |
   | `revision_seq` | — | **missing** |
   | `mapped_instrument_id` | `instrument_id` | present |
   | bucket bounds | — (`width_code`/`m_code` encode cell geometry, not raw bounds) | **missing** (partial via width/m code, not the raw bounds) |
   | `hours_to_settlement` | — (`minutes_since_window_open` is a different clock) | **missing** |
   | `level0_ask` | `ask` | present |
   | `ask_size` | `size` | present |
   | `vwap_ask_at_intended_size` | `ask` (coincides at `order_quantity=1`, per §2) | present-by-equivalence, not a distinct field |
   | `fee_coefficient` | `fee_coefficient` | present |
   | computed edge at `slippage_prob` in {0.000, 0.010} | `p_bound`/`break_even` (edge proxies, not a dual-slippage computation) | **partial** — not the exact dual-value edge s8.5 specifies |
   | first gate that stopped it | `reason` | present |

   **Conclusion, stated explicitly in the doc, not left to inference —
   corrected round 4 (was "15 fields"/"six missing," an arithmetic error the
   round-3 mle-reviewer found: the named-missing list itself already
   contained seven items, and 7 present + 1 equivalence + 1 partial + 7
   missing = 16, matching s8.5's own 16-item field list and the table's own
   16 rows):** `OfferTapeRecord` already carries 7 of **16** s8.5 fields
   verbatim (station, climate_day, instrument_id, ask, size,
   fee_coefficient, reason) plus one present-by-equivalence
   (`vwap_ask_at_intended_size`, only true at `order_quantity=1`) and one
   partial (edge proxies, not the exact dual-slippage computation). **Seven**
   fields remain genuinely absent: `cli_received_ts`, `printed_value`,
   `is_final`, `correction_flag`, `revision_seq`, `hours_to_settlement`, and
   raw bucket bounds. The correct characterisation is therefore neither
   "unbuilt" (round 2's claim, shown inaccurate) nor "fulfilled" — it is
   **partially covered by an existing artefact**, with a concrete, named
   residual field list of seven items for any future item that chooses to
   close the gap.
3. **(b) Fee-drift probe**: a native Nautilus extension via a `Actor` with
   `self.clock.set_timer_ns` in `on_start` (the same extension point
   `POST_FORECAST_PHASE_2026-09-20.md`'s B-4 finding establishes for B1),
   NOT a new systemd timer. On each timer fire (no coarser than every 2
   hours): fetch the venue's currently-advertised `feeCoefficient` for one
   representative listed weather slug via the vendored SDK's **unauthenticated
   `gateway_base_url` path** (confirmed this session,
   `docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/client.py:79-133`
   — `get()` defaults `authenticated=False`; `_request` routes
   `authenticated=False` to `self.gateway_base_url` with no auth headers, and
   `authenticated=True` requires `key_id`/`secret_key` and routes to
   `self.api_base_url` — the probe MUST use the unauthenticated path),
   compare to `DOCUMENTED_TAKER_FEE_COEFFICIENT` by exact `Decimal` equality
   (mirroring `decision.py:331`'s existing check), and on mismatch: emit a
   CRITICAL alert through the resolved alert sink (`health.py`'s
   `resolve_alert_sink`, reused — its mechanism has already landed via
   `f97c26f`; this item verifies it is configured on the live node, not that
   it exists) and set the SAME `family_halted` state the order-path check
   already uses.
   **Round 4 addition (resolves the round-3 prediction-market-reviewer's
   MINOR finding): single-representative-slug design, justified.** The probe
   checks one representative listed weather slug, not one per traded
   station. This is justified by evidence already in the repo:
   `docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md`'s
   captured offer-tape excerpt shows the SAME drifted value `0.0695` across
   3 different stations (MIA/MDW/SFO) and 6 different instrument rows on the
   same day (2026-09-17) — empirical support that the one drift event
   observed to date was venue-wide, not per-instrument. **Stated residual
   risk:** since `feeCoefficient` is parsed per-market
   (`parsing.py:639-645`, `market.get("feeCoefficient")`), a hypothetical
   future drift confined to a single instrument (not evidenced yet, and not
   structurally impossible) would not be caught by a single-slug probe. That
   narrower case is NOT left silently uncovered: the existing per-order
   `decision.py:331` check still catches it the moment any decision reaches
   pricing — but G-01 (zero decisions reaching pricing) is exactly the
   condition under which that backstop is currently silent, so the residual
   risk is real for as long as G-01 holds. This is accepted as a bounded,
   evidence-justified design choice for this item; extending the probe to
   one slug per currently-traded station is named as a small, optional
   strengthening the implementer may choose, not a blocker.
4. **No `src/` constant change** for either (a) or (b) — this item's RED
   tests must be greenable without touching
   `DOCUMENTED_TAKER_FEE_COEFFICIENT` or the `0.01` placeholder.

## 7. Ordered implementation or verification steps

0. **(a) Read-only pre-check — corrected round 3 (resolves the round-2
   mle-reviewer's MATERIAL defect):** query the current
   `offer_tape_<climate_day>.jsonl` file(s) under
   `catalog_root.parent / "decisions"` (via `OfferTape`'s existing read path
   — reused, not reimplemented) for the count of records with
   `decision="refuse"` and a non-null `ask` (i.e., a triggered evaluation
   that priced the market but did not result in a `Take`). **Do NOT query
   `TrialDayLatch`/`StateStore` for this** — confirmed a `Refuse` is never
   written there, so that query is structurally guaranteed to return zero
   regardless of the real population (§2). State the count in
   `MEASURED_SLIPPAGE_2026-09-21.md`'s scope-statement line, alongside the
   §6 item 2 field-by-field table (16 fields / 7 missing, round 4). If
   nonzero (the offer-tape module's own docstring records "7.9 MB / 9612
   rows in ONE hour for ONE station" on its first live day, making a nonzero
   count likely), name it as a follow-up item (no id assigned here) rather
   than silently dropping it.
1. **RED test (a):** `tests/unit/test_measured_slippage_from_fills.py` — a
   fixture with a known `TrialDayRecord.ask` and `FillReport.last_px` pair;
   assert the join computes the expected slippage and flags a
   fill-better-than-ask fixture as suspect rather than silently including it,
   AND asserts the flagged fill is excluded from the aggregate while still
   counted and reported. Fails before the script exists.
2. **Implement** `measured_slippage_from_fills.py` per §6 item 1; run
   read-only against the real ledger; produce §6 item 2's doc including the
   field-by-field table (16 fields / 7 missing).
3. **RED test (b):** `tests/unit/test_fee_drift_probe.py` — fake clock, fake
   wire-fee source returning a value that disagrees with
   `DOCUMENTED_TAKER_FEE_COEFFICIENT`; assert the Actor emits a CRITICAL
   through a stub alert sink AND sets `family_halted`, with NO `src/` change
   required to make it pass. A second fixture proves an AGREEING fee value
   emits nothing and does not halt. A third proves an unreadable/missing wire
   response fails closed (alerts `UNKNOWN`, does not default to "agrees"). A
   fourth asserts the wire-fetch call is made against `gateway_base_url`
   unauthenticated (no `key_id`/`secret_key` in the request), not
   `api_base_url`.
3a. **Set the probe interval**: no coarser than every 2 hours, wired into the
    Actor's `set_timer_ns` call.
4. **Implement** the Actor per §6 item 3, including the single-slug design
   and its cited justification. WP-B0's mechanism has already landed so
   implementation may proceed immediately; **closure** of (b) is gated on
   step 5's live-configuration check.
5. **Live-configuration verification — the SOLE sufficient evidence of
   delivery (round 3, resolves the round-2 prediction-market-reviewer's
   MATERIAL defect):** run `breezy-check-alerts` (the existing WP-B0 CLI)
   against the live node's actual resolved environment. **Exit 0 is the
   sole sufficient evidence that (b)'s alert path is delivered — not
   optional-or with any other signal.** The boot-time
   `log_alert_egress_status` line is retained only as *supporting* evidence
   that the environment variable is non-empty at boot (a fact the
   coordinator's read-only env-file grep in §2/§12 has already substantially
   established) — it never calls `sink.emit()`, has no exit code, and
   structurally cannot prove delivery; it must not be cited, alone or as an
   alternative, to close (b). If `breezy-check-alerts` does not exit 0, (b)
   is NOT closed — see §12's conditional blocker.
6. Full targeted suite:
   `pytest tests/unit/test_measured_slippage_from_fills.py tests/unit/test_fee_drift_probe.py tests/unit/test_weather_common_costs.py tests/unit/test_polymarket_us_fee_schedule_pin.py tests/unit/test_polymarket_us_fee_model.py -q`,
   then the broader suite per the operating contract §8.

## 8. Measurable acceptance criteria and required evidence

- `docs/evidence/MEASURED_SLIPPAGE_2026-09-21.md` exists with all 6 fills'
  computed slippage, the included/flagged breakdown, honest n framing, no
  invented confidence interval, the explicit fills-derived-only scope
  statement, and the field-by-field s8.5-vs-`OfferTapeRecord` comparison
  table (§6 item 2), with its explicit "partially covered, **seven** fields
  missing, named" conclusion (corrected round 4 — was "six," an arithmetic
  error; the table's own 16 rows and s8.5's 16-item field list both support
  seven).
- `docs/evidence/MEASURED_SLIPPAGE_2026-09-21.md` states the §7 step 0 count
  of refused-but-priced station-days, sourced from `offer_tape_<date>.jsonl`
  (not `TrialDayLatch`/`StateStore` — that source is explicitly disallowed
  for this count per §2/§7 step 0).
- The `cli_received_ts` table row's Status cell states why
  `observed_at_ns`/`ts_event` are not treated as equivalents (round 4,
  resolves the round-3 mle-reviewer's MINOR defect).
- RED→GREEN output for both new test files, captured verbatim.
- `DOCUMENTED_TAKER_FEE_COEFFICIENT` and the `0.01` slippage placeholder
  constant are BYTE-UNCHANGED in `src/` (grep-verifiable) unless the doc in
  item 2 above makes an explicit, reasoned recommendation the implementer
  acts on with its own RED test.
- The fee-drift Actor test proves three states (AGREE / DISAGREE / UNKNOWN),
  and proves the probe uses the unauthenticated `gateway_base_url` path
  (`docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/client.py` —
  path corrected round 2).
- The probe's single-representative-slug design cites the 2026-09-17
  uniform-drift evidence (`FEE_SCHEDULE_PIN_2026-09-18.md`) and states the
  residual per-instrument-drift risk explicitly, per §6 item 3 (round 4).
- The probe's timer interval is no coarser than 2 hours, verified against
  the Actor's `set_timer_ns` argument.
- A live-log or paper-run smoke test shows the Actor's timer fires and the
  probe executes read-only, with zero orders placed as a side effect.
- **(Round 3, tightened — the item's actual, sole closing condition for
  (b).)** A `breezy-check-alerts` run against the LIVE node's actual
  resolved environment exits 0 (delivered) — a value-free check (sink class
  name / exit code only, never the webhook URL). This is the SOLE sufficient
  evidence; the boot-time `log_alert_egress_status` line is supporting
  evidence of configuration only and cannot substitute for it, because it
  never attempts a send and has no exit code. Until `breezy-check-alerts`
  exits 0 against the live process, (b) is not closable even if every unit
  test above is green.

## 9. Validation: failure cases, integration behaviour, autonomous operation

- **Failure case (a):** a fill with `last_px < decision_ask` is flagged,
  excluded from the aggregate, and reported separately by count and value —
  the exact L-25 defect signature.
- **Failure case (b):** wire probe returns malformed/missing data — fails
  `UNKNOWN`, alerts, does NOT default to "no drift."
- **Failure case (b), round 4:** a drift confined to a single traded
  instrument other than the probed representative slug is NOT caught by the
  probe itself — named explicitly as the stated residual risk (§6 item 3),
  covered instead by the existing per-order `decision.py:331` check once any
  decision reaches pricing again.
- **Integration behaviour:** the fee-drift Actor runs on the live node
  alongside the existing strategy Actors; its `on_start`/timer registration
  must not interfere with `CurrentRungHoldStrategy`'s own timers or the
  permit-lapse Actor from B1 if both land — named as an integration check in
  step 4.
- **Autonomous operation:** the probe is read-only against the venue (a GET,
  not an order, unauthenticated) and its only side effects are an alert
  emission and a `family_halted` state write, both idempotent primitives
  reused from the existing order-path refusal.

## 10. Deployment, observability, rollback

(a) is a one-shot analysis script; no deployment. (b) deploys as part of the
live node's Actor set — same unit, no new systemd timer, no new process.
Observability: the CRITICAL alert IS the observability artefact, verified
live-delivered per §8's sole closing criterion; the probe additionally logs
its wire-fetch result at INFO on every fire, capped per the repo's existing
diagnostic-capping convention (`_capped_diagnostic`). Rollback: remove the
Actor from the strategy's `on_start` wiring; no state migration,
`family_halted` is the same flag the order-path check already sets and
clears via `CONTINUOUS_FAMILY_HALT_CLEARED_MARKER`, unmodified by this item.

## 11. Relationship to portfolio-level ROI and how it will be evaluated

(a) improves the honesty of every future edge/ROI computation that consumes
`costs.py`'s slippage term — it does not itself change any number unless the
measured data warrants it, and now also gives an honest, field-verified
account of how much of s8.5's broader instrumentation obligation is already
satisfied by `OfferTapeRecord` (7 of 16 fields verbatim, round-4 corrected),
rather than assuming it is entirely unbuilt. (b) protects every future
trading day from a repeat of the exact "halted silently for days" failure
mode already measured twice (θ drift 3 days, permit lapse 11 hours).
Evaluated by: zero future fee-drift halts going undetected for more than one
probe interval **and confirmed by `breezy-check-alerts` exiting 0 against
the live process, not a passing unit test or a boot-log line**, and the
measured-slippage doc (with its field-by-field table) being cited by id in
any future edge computation or s8.5-closure item.

## 12. Assumptions, unresolved questions, blockers

- **Assumption:** the venue exposes a per-slug fee field on a plain
  unauthenticated GET call; if wrong, (b)'s probe mechanism must change and
  is a BLOCKER on (b) specifically, discovered at step 4.
- **Retained from round 2:** WP-B0 is not an upstream-landing dependency — it
  landed `f97c26f` on 2026-09-20. The residual precondition is verification-
  shaped: whether the live node's process environment actually resolves
  `TeeAlertSink`. Coordinator-verified fact (read-only, value never printed):
  the variable is present and non-empty in the env file the supervisor unit
  loads. This makes live misconfiguration unlikely but not yet proven —
  §7 step 5 establishes it, with `breezy-check-alerts` exit 0 as the sole
  sufficient evidence.
- **Blocker on (b), conditional:** IF `breezy-check-alerts` does not exit 0
  when run against the live node, closing (b) requires an operator action
  (setting/confirming `BREEZY_ALERT_WEBHOOK_URL` in the actual running
  process) outside this item's build authority.
- **Retained from round 3, resolved not a blocker:** whether refused-but-
  priced station-days exist that would warrant building s8.5's full record
  is no longer purely unresolved — §6 item 2's field-by-field table
  establishes that `OfferTapeRecord` already covers 7 of 16 s8.5 fields
  verbatim for exactly this population (Take and Refuse alike), narrowing
  the true residual gap to **seven** named fields (round-4 corrected count:
  `cli_received_ts`, `printed_value`, `is_final`, `correction_flag`,
  `revision_seq`, `hours_to_settlement`, raw bucket bounds). Whether to build
  those seven fields into `OfferTapeRecord` is a follow-up item, not
  id-assigned here (backlog authoring is out of this plan's authority).
- **New round 4, resolved not a blocker:** whether the fee-drift probe's
  single-slug design leaves a gap is answered, not left open — §6 item 3
  states the cited justification (uniform 09-17 drift across 3 stations) and
  the residual per-instrument-drift risk explicitly; extending to one slug
  per station is a named, optional strengthening for the implementer, not a
  blocker.
- **No blocker on (a).**

## 13. Review history

**Baseline self-score: 90/100.** (See prior revisions; superseded below.)

**Round 1:**
- mle-reviewer: 87/100. Defects: (1) MATERIAL — (a) mischaracterized as
  fulfilling s8.5 "as written" — **ACCEPTED**, scope narrowed, pre-check
  added. (2) MINOR — flagged-fill disposition unstated — **ACCEPTED**. (3)
  MINOR — probe interval left open — **ACCEPTED**, tightened to 2h.
- prediction-market-reviewer: 80/100. Defects: (1) MATERIAL — WP-B0 framed
  as unresolved dependency when `f97c26f` had landed — **ACCEPTED**,
  corrected. (2) MATERIAL — no acceptance criterion verified live alert-sink
  configuration — **ACCEPTED**, added. (3)/(4) MINOR — unauthenticated path
  and `level0_ask` equivalence left implicit — **ACCEPTED**.

**Revision 2 total: 99/100.**

**Round 2:**
- mle-reviewer: 81/100 (APPROVE WITH WARNINGS). Round-1 dispositions
  independently re-verified as genuinely fixed. Fresh **MATERIAL** defect:
  §7 step 0's new pre-check queries `TrialDayLatch`/`StateStore` for
  refused-but-priced records, but a `Refuse` is never written there by
  construction — the query is guaranteed to report zero regardless of the
  real population, and the durable source that DOES hold this data
  (`OfferTape`/`OfferTapeRecord`) was never checked. **ACCEPTED** — §7 step 0
  is re-pointed at `offer_tape_<date>.jsonl`, and §6 item 2 adds the
  field-by-field s8.5 comparison the reviewer additionally required.
- prediction-market-reviewer: 87/100 (APPROVE WITH WARNINGS). Fresh
  **MATERIAL** defect: §7 step 5/§8's closing criterion offered
  `breezy-check-alerts` exit 0 OR the boot-time `log_alert_egress_status`
  line as interchangeable evidence, but the latter cannot prove delivery.
  **ACCEPTED** — §7 step 5/§8 now state `breezy-check-alerts` exit 0 as the
  SOLE sufficient evidence. Also MINOR: SDK snapshot path typo —
  **ACCEPTED**, corrected.

**Revision 3 total: 90/100.**

**Round 3:**
- mle-reviewer: 85/100 (APPROVE WITH WARNINGS). Round-2 defect dispositions
  independently re-verified as genuinely fixed (`TrialDayLatch` write-path
  trace, `breezy-check-alerts` sole-sufficient-evidence rule). Fresh
  **MATERIAL** defect: the field-by-field count in §6 item 2 is arithmetically
  wrong — s8.5 lists 16 fields (verified directly against
  `bl19_edge_and_cost_decision_2026-09-01.md:694-698`), the table itself has
  16 rows, but the prose summed "7 present + 1 equivalence + 1 partial + six
  missing = 15" and named only six of the seven actually-missing fields.
  **ACCEPTED** — §6 item 2 and §8 corrected throughout to "16 fields"/"seven
  missing," re-summed and verified directly this round. Also MINOR: the
  `cli_received_ts` row's "missing" status did not explain why
  `observed_at_ns`/`ts_event` don't count as equivalents, unlike the
  `hours_to_settlement` row's treatment — **ACCEPTED**, justification clause
  added to the table row.
- prediction-market-reviewer: 99/100 (APPROVE, highest score across both
  items to date). Every claim independently re-derived from source this
  round, all matched. One **MINOR** defect: the single-representative-slug
  fee-drift probe design is reasonable and IS supported by evidence already
  in the repo (2026-09-17 drift uniform across 3 stations,
  `FEE_SCHEDULE_PIN_2026-09-18.md`) but the plan did not cite that evidence
  to justify the design choice, and did not state the residual
  per-instrument-drift risk. **ACCEPTED** — §6 item 3 now cites the
  09-17 evidence explicitly and states the residual risk (round 4).

**Rejected (round 3):** none. Every defect (one MATERIAL, two MINOR) was
independently confirmed this round via direct source reads (`bl19` s8.5's
literal 16-item list re-counted; `cli_received_ts` row's diligence gap; the
09-17 fee-drift evidence's uniformity across stations) and none softened
scope or an acceptance criterion.

**Revision 4 self-score (out of 100), conservative — round-3's own lower
score (85) came from an arithmetic defect in a plan section that had
otherwise been independently verified clean, so this round is graded
against the same standard of re-derivation, not assumed clean (caps
20/20/15/20/15/10):**
- Fidelity to audit gap and completeness: 19/20 — the MATERIAL arithmetic
  defect sat directly in this item's round-3 fidelity gain (the corrected
  residual-scope framing) and is now fixed with a direct re-count against
  source (16 items, listed and verified); the MINOR fee-drift justification
  gap is also closed with an in-repo citation. Held at 19/20 because the
  99/100 prediction-market-reviewer score this round is corrective evidence
  that (b) was already near-complete — the residual point reflects the
  fee-drift probe's stated (not eliminated) per-instrument residual risk,
  which remains real while G-01 holds.
- Technical correctness and evidence grounding: 19/20 — the field count was
  independently re-verified against `bl19_edge_and_cost_decision_2026-09-01.md:694-698`
  directly this round (16 comma-separated items, listed verbatim in §2) and
  the table's own 16 rows and 7/1/1/7 split cross-checked arithmetically;
  the 09-17 uniform-drift citation was independently re-read from
  `FEE_SCHEDULE_PIN_2026-09-18.md`'s description in the round-3 review, not
  re-opened from the primary file this session — held back one point for
  that inherited-not-independently-reread citation, consistent with the
  plan's own past practice of flagging such gaps (see round-3's own
  §13 note on `health.py`).
- Implementation specificity and feasibility: 14/15 — unchanged from round 3
  reasoning; concrete join keys, file locations, extension points, and now a
  concrete justification citation for the single-slug design.
- Acceptance criteria and validation quality: 19/20 — the corrected field
  count now appears consistently in §6 item 2 and §8 ("seven fields
  missing"); the `cli_received_ts` justification clause and the fee-drift
  citation both close named round-3 gaps. Held below 20/20 because the
  field-by-field table itself is still not validated against a live
  `offer_tape` file sample this session (a round-3 self-score note, not yet
  resolved — still deferred to §7 step 0's implementer run).
- Autonomous operation, failure handling, recovery: 15/15 — three-valued
  probe design, unauthenticated-path requirement, idempotent
  `family_halted`/alert side effects, and now an explicit residual-risk
  statement for the single-slug design (§9) are all sound and unchanged in
  substance from round 3's clean 15/15.
- Portfolio alignment, scope, dependencies: 10/10 — dependency framing
  accurate; conditional blocker precise; ROI framing does not invent a
  number and correctly cites the corrected 7-of-16 field coverage.

**Revision 4 total: 96/100.**
**Readiness status: NOT READY — round 4 review pending.**

<!-- COORDINATOR FINAL STATUS — appended after review; everything above this line is the reviewed revision -->

## Coordinator final status (2026-09-21) — authoritative

This block supersedes any score or readiness wording in §13 above, which plan revisers wrote
before review closed.

- **Reviewed revision sha256** (file content above the marker line): `82e708c5e8c050704582b5ac33a1af1b70e92feeaaf63ac462da86cc705f5ffc`
- **Baseline self-score:** 90/100
- **Final score (lowest reviewer, never averaged):** 100/100
  - `mle-reviewer` round 4: 100/100 — `reviews/AUD-12-r4-mle-reviewer.md`
  - `prediction-market-reviewer` round 4: 100/100 — `reviews/AUD-12-r4-prediction-market-reviewer.md`
- **Readiness:** **READY**
- **Unresolved blockers:**
  - None today. Conditional, stated in the plan: if `breezy-check-alerts` does not exit 0 against the live node, closing (b) needs an operator action on the alert webhook environment.
- **Full review history:** 8 records, `reviews/AUD-12-r*-*.md`
- Planning only. Nothing in this plan has been implemented.
