# S4 r4 delta (rev 2) — architect review, round 2 — 2026-10-13

Verdict: REQUEST_CHANGES (bounded edits, not re-planning). Recorded by the coordinator verbatim from the reviewer's return (no write tool).

## Round-1 disposition
| # | Finding | Status | Evidence |
|---|---|---|---|
| 1 | Completeness rule | RESOLVED | §5.5 l.128: `parse_open_orders` semantics + empty unknown envelope keys |
| 2 | Unlisted firewall pins | PARTLY | ban untouched (3a); new unlisted rows (H-1); r3 P3 dropped by mistake (H-2) |
| 3 | Inline confirm too wide | RESOLVED | l.65-66: only "AMBIGUOUS WITH a venue_order_id", before `_refuse`/`mark_ambiguous`; NEW only |
| 4 | Crash test / in-flight set | PARTLY | context written first; three gaps (H-3) |
| 5 | Discovery vs existing test | RESOLVED | §7 l.149-151: characterise first, `:653-664` unedited |
| MED | classifier duplicates native | RESOLVED | l.59 |
| MED | confirm helper pin | RESOLVED, list incomplete | N1 l.96 (M-3) |
| MED | native PnL / `settle` | RESOLVED as stated | l.117; durable fee field missed (H-4) |
| MED | `taker_fee_bound` / l.51 / regex | RESOLVED | l.30; l.26, l.124; l.151 |
| LOW | characterisation labels | PARTLY | §6 |

## The seven UNVERIFIED items, checked now
1. Exec client reading `InstrumentStatus`: VERIFIED — data engine caches it (`data/engine.pyx:2820-2822`), readable via `self._cache.instrument_status(id)` (`cache/cache.pyx:3373`); using it in `_cancel_order` needs a P1 row; better drop the annotation (YAGNI).
2. Venue order-id charset: UNVERIFIED, but `endpoints.order_by_id_path` (`endpoints.py:123-140`) already refuses empty ids, `/?#\`, whitespace. T3 builds `cancel_order_path` on it (DRY), adds `%` and `..`; frozen-from-WP0 regex = build-time check.
3. Static-scan reader list: answerable now — 17 `src/` files read `.commission`/`.cumulative_fee` incl. `runtime/exec_par_settled_pnl.py:175` (settled P&L), `exec_par_counter_ingest.py`, `settlement/exit_guard.py`, `continuous_strategy.py`, `trial_day_latch.py`, labeling scorers. A scan worded "no module reads `FillReport.commission`" is red on day one (H-4).
4. `manage_gtd_expiry`: VERIFIED — `strategy.pyx:888-889` sets the GTD timer; `_expire_gtd_order` (`:1734-1748`) calls `cancel_order` (→ M-1).
5. With-id resolver skipping in-flight intents: VERIFIED it does NOT — only the no-id path skips (`client.py:4299`); with-id reads context and GETs (`:3045-3300`). "Add the skip if absent" must be a definite step with a RED test.
6. `resting` field needing a schema version per L-47: REFUTED — L-47 is about citing evidence; `AmbiguousResolverContext` uses trailing-optional `.get` decoding (`client.py:1248-1286`); absent `resting` decodes to False. Strike premise row l.22.
7. `liquidity_side`: VERIFIED conflict — resolver fill path hardcodes TAKER, `commission=Money(0, USD)`, `fee_reconciled=False` (`client.py:4037-4038`, `:3879-3880`); `calculate_commission` latches `_refuse` on any MAKER reconciliation fill (`:6600-6606`); `fees.py:275,449` raise on a sideless fill (H-5).

## Pin rows
- 3a. `:3374-3381` ban needs no edit (banned words read/send/post/request; none of the new names contains one).
- Correct: FW-1..4 WIDEN, P1a-c WIDEN, P4a-c WIDEN, N1-N5 NEW, T1 companion NEW, P13/P16 WIDEN, P11/P23 characterisation, W1 additive.
- FW-1/FW-2: `ORDER_SENDER_REFERENCE_PERMITTED_SCOPES` is a union expression (`:4374-4376`); add a named `| frozenset({...})` term.
- T2 mislabelled: it is a WIDEN of an exact set plus a forced edit of a safety test (`:355` asserts `== {"url","headers","keys"}`, `:348` calls without `slugs`). Own commit + plant (bodiless call must fail).

## New findings
HIGH
- H-1 Unlisted exact-set rows (L-12, L-46): (a) `_submit_order` → `_bind_resting_order` has no P1 row; (b) resolver branch → `resting_echo_matches` has no `EXEC_RESOLVER_PERMITTED_CALLEES` (r3 P6) row; (c) the T3 literal `"/v1/order/{order_id}/cancel"` trips the V2 order-path rule wherever it lives (in `write_transport.py` widens `test_b4_raw_content_is_exactly_the_three_expected_violations` `:533-540`, 4→5; in `endpoints.py` widens `V2_ORDER_READ_PATH_ALLOWLIST`, `readonly_guard:2512`). Splicing the path is prohibited (L-46). One named row each, each with a plant.
- H-2 P3 "DROPPED" conflates two things: r3 P3 was the `_query_order` override (`EXEC_DECLARED_UNIMPLEMENTED_COROUTINES` → `frozenset()`, scanned GET-only `EXEC_QUERY_PERMITTED_CALLEES`). Rev 2 still has the override (§8 l.161, WP5 poll). Drop only `_read_market_state`; restore r3 P3.
- H-3 HOLD path (l.66-67): (a) leaving the id in the in-flight set forever = K=1 never freed (L-48 deadlock) → remove in a `finally` around POST+confirm; durability from the context. (b) post-`_refuse` `_note_ambiguous_open` overwrites the context; must pass `resting=True`. (c) HOLD sets a global `AMBIGUOUS_REASON` refusal + alert (`:7516`); the resolver bind must clear it as `_resolve_accept_fill`'s A3 block does (`:4050-4060`), with a test.
- H-4 Fee gate targets the wrong field: readers consume `DurableFillRecord.cumulative_fee` (e.g. `exec_par_settled_pnl.py:175`), not `FillReport.commission`. Set `cumulative_fee = recognised_commission(raw)` while unverified; raw only in `commission_raw`; scope the scan to `commission_raw` readers; list the 17 readers now.
- H-5 Resting fills meet taker-only paths (l.77 vs l.68, §6 l.137): (a) a HOLD-resolved fill goes through `_resolve_accept_fill` with TAKER + zero commission — pick "resolver paths unchanged (report with taker fills, fee unreconciled)" or raw booking, not both; (b) `calculate_commission` refuses on MAKER — state whether mass-status/reconciliation can surface a bound rest; if so a reviewed carve-out for bound `resting:` ids.

MED
- M-1 no §6 row for a cancel during HOLD (GTD expiry / strategy stop on an unbound SUBMITTED order): cancel by id via `_cancel_resting_order` from the with-id context, or `generate_order_cancel_rejected` and let `goodTillTime` expire it.
- M-2 nothing names what drives RETRY-WHEN-OPEN (`create_task` banned in order coroutines; if `_query_order` drives retries a send enters a GET-only set). Name the driver and its pin row.
- M-3 N1–N3 omit callees: N2/N3 need `self._write_signer.sign_headers` + path builder (`_submit_order` signs at `:7176`); N1 needs `asyncio.sleep`, `UUID4`, `self._clock.timestamp_ns`.
- M-4 P1b plant "used by `_cancel_order` only" conflicts with N4 and r3 4d `_cancel_all_orders`; restate; add `self._cancel_order` to P1 if `_cancel_all_orders` loops over it.
- M-5 "complete pin-row list" must say r3 P2, P6, P7, P9, P10, P12, P14, P15, P18–P22 stand; P5, P17, P24 superseded by FW-3/4, T2, N4.

LOW: `RETRY_WHEN_OPEN_MAX_AGE_S` per order cannot be a RulePin constant (pin grace + floor); 25 GETs per rest at 0.2 s spends `QUOTA_KEY_PORTFOLIO` (consider 0.5 s); `_cancel_slug_orders` ledger check needs key enumeration not `_store_get`; NO-leg echo compares via the leg mapping (venue shows a NO buy as SELL/BUY_SHORT); N5 overlaps the B4 exemption list — pin the probe in both.

## RED / characterisation (L-33)
Characterisation + mutation evidence: `test_banned_word_ban_unedited_and_new_helper_names_pass_it`, `test_sweep_missing_eof_counts_complete`, `test_sync_response_echo_never_accepts`. RED to add: `test_with_id_resolver_skips_in_flight_intent`, `test_hold_context_rewrite_keeps_resting_true`, `test_resolver_bind_clears_ambiguous_refusal`, `test_cancel_during_hold_by_with_id_context`, `test_maker_reconciliation_commission_does_not_refuse_bound_rest` (or characterisation that it still refuses).

## §11.1
Leave the unbound order and refuse arming; never cancel unbound orders (may be the operator's manual order). The sanctioned claim path is the no-id resolver's ADOPT path → with-id ledger id → cancellable.

## Buildability
WP0 done (provisional); WP1 buildable (step 0 now; T3 location H-1c); WP2 buildable; WP3 blocked (H-1a/b, H-3, H-5a); WP4 blocked (H-1c, H-2, M-1..M-4); WP5 blocked (H-2, H-4, H-5); WP6 after WP3–5.
