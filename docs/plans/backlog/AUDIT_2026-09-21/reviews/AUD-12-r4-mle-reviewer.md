# AUD-12 — round 4 review (mle-reviewer)

Plan file: docs/plans/backlog/AUDIT_2026-09-21/AUD-12-cost-model-slippage-and-fee-drift.md
SHA256: 82e708c5e8c050704582b5ac33a1af1b70e92feeaaf63ac462da86cc705f5ffc
Round: 4
Reviewer: mle-reviewer (independent, blind to other reviewers)

## Round-3 defect disposition — verified fixed against source, not §13

**s8.5 field-count arithmetic (round-3 MATERIAL, mle-reviewer).** Directly
re-counted `docs/evidence/bl19_edge_and_cost_decision_2026-09-01.md:694-698`
myself this round:

    station, climate_day, cli_received_ts, printed_value, is_final,
    correction_flag, revision_seq, mapped_instrument_id, bucket bounds,
    hours_to_settlement, level0_ask, ask_size, vwap_ask_at_intended_size,
    fee_coefficient, computed edge at slippage_prob in {0.000, 0.010},
    and the FIRST gate that stopped it

= 16 comma-separated items, confirmed. §6 item 2's table has 16 rows and its
prose now reads "7 present + 1 equivalence + 1 partial + 7 missing = 16,"
correctly re-summed and consistent with the table (7 verbatim: `station`,
`climate_day`, `mapped_instrument_id`→`instrument_id`, `level0_ask`→`ask`,
`ask_size`→`size`, `fee_coefficient`, "first gate"→`reason`; 1 equivalence:
`vwap_ask_at_intended_size`; 1 partial: computed edge→`p_bound`/`break_even`;
7 missing: `cli_received_ts`, `printed_value`, `is_final`, `correction_flag`,
`revision_seq`, `hours_to_settlement`, bucket bounds). Cross-checked every
row against `OfferTapeRecord.to_dict()`
(`src/breezy/strategy/current_rung_hold/offer_tape.py:183-248`, re-read in
full): `station`, `climate_day`, `instrument_id`, `ask`, `size`, `reason`,
`fee_coefficient` present verbatim; `observed_at_ns`/`ts_event` present but
correctly NOT treated as `cli_received_ts` equivalents (neither is the
NWS-CLI-retrieval clock); `width_code`/`m_code` present but correctly not
treated as raw bucket bounds; `minutes_since_window_open` present but
correctly not treated as `hours_to_settlement`; `p_bound`/`break_even`
present as edge proxies, correctly marked partial not equivalent; no
`printed_value`/`is_final`/`correction_flag`/`revision_seq` field exists at
all. **Every cell of the table is accurate. CONFIRMED FIXED**, count is now
consistent throughout §2/§6/§8/§12.

## Fresh, whole-plan review this round

- `order_quantity` pinned to exactly 1 with a raising `__post_init__` check
  (`src/breezy/strategy/current_rung_hold/config.py:230,253-255`, re-read) —
  the `vwap_ask_at_intended_size`≡`level0_ask` equivalence claim (§2, §6 item
  2) holds as stated.
- Unauthenticated `gateway_base_url` GET path re-verified directly against
  `docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/client.py:79-133`:
  `get()` defaults `authenticated=False`; `_request` routes
  `authenticated=False` → `self.gateway_base_url`, no auth headers attached;
  `authenticated=True` requires `key_id`/`secret_key` and routes to
  `api_base_url`. Matches the plan's claim exactly.
- `feeCoefficient` parsed per-market (`src/breezy/adapters/polymarket_us/parsing.py:639-645`,
  re-read: `raw = market.get("feeCoefficient")` inside the per-market
  parse path) — supports the plan's stated residual per-instrument-drift
  risk for the single-slug probe design.
- The single-representative-slug justification's cited evidence
  (`docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md`) was
  independently re-read from the primary file this round (not inherited from
  a prior round's review, closing the round-4 self-score's own admitted
  gap): confirms exactly 6 offer-tape rows, all `fee_coefficient="0.0695"`,
  spanning 3 distinct stations (MIA, MDW, SFO) on 2026-09-17. The plan's
  characterisation ("SAME drifted value ... across 3 different stations ...
  and 6 different instrument rows on the same day") is accurate.
- `resolve_alert_sink`, `WebhookAlertSink`, `TeeAlertSink`,
  `alert_egress_configured`, `log_alert_egress_status` all confirmed present
  in `src/breezy/runtime/health.py`; `breezy-check-alerts` confirmed wired as
  a console-script entry point (`pyproject.toml:302` →
  `breezy.runtime.check_alerts_cli:main`) and the module exists.
- `_default_offer_tape_path` (`composition.py:473-485`) confirmed to produce
  `catalog_root.parent / "decisions" / f"offer_tape_{day.isoformat()}.jsonl"`
  exactly as §7 step 0 cites, supporting the corrected pre-check source.
- Referenced test files for §7 step 6
  (`tests/unit/test_weather_common_costs.py`,
  `tests/unit/test_polymarket_us_fee_schedule_pin.py`,
  `tests/unit/test_polymarket_us_fee_model.py`) all exist.
- No LESSONS.md violation, no `DOCUMENTED_TAKER_FEE_COEFFICIENT`/`0.01`
  constant edit proposed, no operator-cap value assigned, no PREREG
  semantics change, `allow_short`/NO-SEND untouched, WP-B0 correctly framed
  as landed (not a dependency) with a verification-shaped residual precondition.

## Defects

None found. Every load-bearing citation in this revision was checked
directly against source this round and confirmed accurate, including the one
citation the plan's own round-4 self-score flagged as "inherited, not
independently reread" — I reread it directly and it holds. The round-3
MATERIAL arithmetic defect is genuinely fixed and consistent everywhere it
appears (§2, §6 item 2's table and conclusion, §8, §12). No new defect was
introduced by the round-4 changes.

## Per-criterion points (caps 20/20/15/20/15/10)

- Fidelity to audit gap and completeness: 20/20 — (a)'s narrowed,
  fills-derived scope is honest and explicit; (b)'s fail-closed,
  delivery-proven closing criterion is complete; the residual s8.5 gap is
  now correctly characterised as partially-covered with a named 7-field list
  rather than assumed unbuilt.
- Technical correctness and evidence grounding: 20/20 — field count,
  `OfferTapeRecord` schema, SDK auth routing, `feeCoefficient` per-market
  parsing, and the 09-17 uniform-drift evidence all independently
  re-verified against source this round.
- Implementation specificity and feasibility: 15/15 — concrete join keys,
  file paths, extension points (`Actor.set_timer_ns`), and a cited
  justification for the single-slug design.
- Acceptance criteria and validation quality: 20/20 — three-valued
  AGREE/DISAGREE/UNKNOWN probe test, unauthenticated-path assertion,
  byte-unchanged-constant grep check, and `breezy-check-alerts` exit 0 as the
  sole sufficient closing evidence for (b), explicitly not interchangeable
  with the boot-time log line.
- Autonomous operation, failure handling, recovery: 15/15 — fail-closed
  UNKNOWN state, idempotent `family_halted`/alert side effects, explicit
  residual per-instrument-drift risk named rather than silently accepted.
- Portfolio objective alignment, scope, dependencies: 10/10 — no invented
  ROI number; (a) explicitly framed as honesty-improving, not
  edge-establishing; dependency on WP-B0 correctly framed as landed with a
  verification-shaped residual.

**Total: 100/100.**

## Blockers

None owed to this review. The plan itself correctly names one conditional,
operator-shaped blocker for closing (b) (§12: if `breezy-check-alerts` does
not exit 0 against the live node, closing (b) requires an operator action to
set/confirm `BREEZY_ALERT_WEBHOOK_URL` in the live process environment) —
that is the plan's own honest disclosure of a real dependency outside build
authority, not a defect in the plan.
