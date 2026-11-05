Commit: e4848c39a979bac5a91b8f6b3887f75c497c1be8

# Create-path fill hardening — the next fill classifies loudly and correctly (2026-09-12) — Rev 1

**L-1.** Three verdicts, all against the INSTALLED tree `.venv/lib/python3.13/site-packages/nautilus_trader/` (1.231.0).
1. **Venue-payload shape-drift capture / key allowlists — GENUINELY-ABSENT.** `grep -rn "key_tree\|unknown key\|unknown_key\|drift_allow\|allowlist"` over the whole install → **0 hits**; `grep -rn "raw_payload\|store_raw_body\|persist_body"` → **0 hits**. Positive control on the same tree: `grep -rn "class FillReport"` → `execution/reports.py:619` and `core/nautilus_pyo3.pyi:4663`. Nautilus defines the *destination* type, never the mapping or its refusal — the adapter owns both. No native facility is bypassed by this plan.
2. **The fill event and its money types — NATIVE-sufficient, already reused.** `FillReport` (`execution/reports.py:619`), `Money`, `LiquiditySide.TAKER`: built by `parse_fill_report` (`reports.py:1078-1101`), published by `generate_order_filled` (`client.py:2838-2853`). Nothing new is built here.
3. **Sub-cent fee representation — NATIVE-insufficient, already extended (GL-2, no new work).** `Money(USD)` cannot carry sub-cents (measured, `reports.py:81-91`), so `_usd_commission` (`reports.py:824-844`) bankers-rounds BEFORE the constructor and `_assert_representable` re-checks; `DurableFillRecord.cumulative_fee` keeps the unrounded `Decimal` (`client.py:524`, L-2 unit note `reports.py:93-98`). Extension, not a patch.

**Constraints.** Nautilus immutable — extend only natively. `allow_short` stays False. No safety/settlement/contract test weakened or deleted. No operator-reserved value assigned (max daily budget, max per position). Live-trading enablement and the NO-SEND execution-egress firewall untouched. PREREG v3 BINDING: this plan changes **no** §3/§5/§9 meaning — a create-path `KIND_ACCEPT_FILL` with `fee_reconciled=True` is already admissible under v3 §5; nothing here re-classifies a resolver fill (L-32 checked: `docs/evidence/codex_prereg_v2_rulings_2026-09-06.md`, `gl1_gl4_order_state_ruling_2026-09-10.md`, `codex_gl3_ambiguous_consume_ruling_2026-09-06.md` — none rules on execution-object drift). `classify_create_order_outcome` stays **byte-unchanged** (L-36). Tests via `scripts/ci/run_tests_no_egress.sh` (addopts already has `-q`; never add `-q`); `lint-imports` + `mypy` after every slice; adapters never import runtime (`pyproject.toml [tool.importlinter]`).

## 1. Goal state (falsifiable)

The next real create-order response carrying an execution leg either (G1) classifies `KIND_ACCEPT_FILL` and books a durable fill row with `"feeReconciled": true` when the venue fee is representable, or (G2) refuses — and the refusal names **every** key the body carried, appears on the AMBIGUOUS diagnostic line, and is **persisted to the exec store** so the drift can be DECLARED from evidence (L-37) before the following fill. **Falsifier:** any create-order response with a non-empty `executions` array that produces neither a fill nor a persisted, name-complete refusal. Today three code paths falsify it (H1–H3 below).

### Happy walk
| # | Hop | file:line |
|---|---|---|
| 1 | POST → classify | `exec/client.py:2748` → `exec/submit_chain.py:772` |
| 2 | select the fill leg | `submit_chain.py:402-426` (`_durable_execution`) |
| 3 | map the leg | `submit_chain.py:633-676` → `reports.py:1015-1101` |
| 4 | strict keys + taker + fee | `reports.py:1037-1039`, `:701-722`, `:979-1012`, `:824-844` |
| 5 | order-level totals | `submit_chain.py:429-446`, `:495-527`, `:583-630` |
| 6 | `KIND_ACCEPT_FILL` | `submit_chain.py:838-851` |
| 7 | durable record FIRST | `client.py:2793-2805` → `record_fill` `client.py:2275-2300` |
| 8 | `feeReconciled` on disk → scoring | `client.py:515-527` |

### Failure walks (H1–H3 are the silent ones)
| id | Condition | Today | file:line |
|---|---|---|---|
| F1 | undeclared key on the execution / nested order | LOUD: tree → `fill_parse_error` → log | `reports.py:1037` → `submit_chain.py:660-663` → `:889` → `client.py:2897-2906` |
| **H1** | `_filled_cost_from_execution` returns `None` (absent/malformed `avgPx`+`lastPx`) | **SILENT** `return None`, nothing appended to `errors` | `submit_chain.py:664-666` |
| **H2** | `executions` non-empty but `_durable_execution` selects nothing (drifted `type` enum, absent `lastPx`/`lastShares`/`tradeId`/`order.id`) | **SILENT**: the guard never runs; AMBIGUOUS with `fill_parse_error=None` | `submit_chain.py:823-824` → `:876-890` |
| **H3** | venue adds a field to the `Execution` object itself | whole fill refused; `_EXECUTION_KEYS` has **no** `*_DRIFT_ALLOWED_KEYS` unlike `_ORDER_KEYS`/`_USER_POSITION_KEYS`/`_MARKET_METADATA_KEYS` | `reports.py:283-297` vs `:278-280`, `:332-346`, `:374` |
| F4 | maker fill | LOUD refusal (correct, unchanged) | `reports.py:1006-1012` |

## 2. Spec / evidence vs code

| Piece | Code today (file:line) | Gap |
|---|---|---|
| L-37 (1) "names every field it saw" | `_key_tree` `reports.py:446-468`; `_known_keys_with_full_tree` `:673-698`; `full_payload` = the **selected execution only** (`reports.py:1037-1039`) | H2: no tree at all when no leg is selected; sibling legs and the top-level body never rendered |
| L-37 (2) "surfaces into the AMBIGUOUS diagnostic" | `outcome.fill_parse_error` `submit_chain.py:889` → `client.py:2897-2906` (ba2c5ee) | H1 + H2 produce no `fill_parse_error`, so the line is silent |
| L-37 (3) "declare per surface with captured evidence" | 3 declared allowlists + 2 evidence docs (`BALANCES_SHAPE_DRIFT_2026-09-04.md`; 8d56a26/ba2c5ee log evidence) | H3: the `Execution` surface has none, and **no execution body has ever been captured** (§9 E5) |
| durable capture of a refusal | `AmbiguousResolverContext` written by `_note_ambiguous_open` `client.py:2617-2645`, key `exec/polymarket_us/resolver/<intent_id>`, **never deleted** (only `_store_set` :2644, `_store_get` :1286) | carries no shape evidence; the 09-11 body (`body_len=3481`) is gone forever |
| fee precision on the create path (brief (d)) | `_usd_commission` `reports.py:824-844`; `fee_reconciled` = legs `lastShares` sum == `cumulative_qty` AND (order total absent OR == leg sum OR == bankers-cent(leg sum)) `submit_chain.py:583-630` | **no gap** — present and correct on the create path |
| `_submit_order`→`record_fill`→store→`feeReconciled: true` (brief (e)) | **ALREADY GREEN**: `tests/contract/test_live_fill_scoring_chain_contract.py:282` asserts `record.fee_reconciled is True` (commission `0.03`) | only the **sub-cent** variant lacks the `fee_reconciled` assertion (`tests/unit/test_polymarket_us_submit_order_chain.py:975-998` asserts raw + Decimal, not the flag) |

## 3. Design

**Where.** `submit_chain.fill_generation` (H1), `submit_chain._body_detail` (H2), `client.AmbiguousResolverContext` + `_note_ambiguous_open` + the `_note_ambiguous_open(...)` call site (durable capture), `reports.py` (H3, gated).

**Inputs / outputs.** No new module, no new class, no new dependency. H1 reuses the `errors: list[str]` sink ba2c5ee already threads. H2 reuses `reports._key_tree` (names-only at every depth, `reports.py:446-468`), capped and appended as one `tree={...}` token inside `_body_detail`'s **`executions-present` branch only**. Durable capture reuses the existing resolver-context write: `_submit_order` passes `outcome.detail` (an **attribute access**, not a call) as a new keyword to the already-allowlisted `_note_ambiguous_open`.

**Why not classify.** Every hole could be fixed inside `classify_create_order_outcome`; none is, because L-36 pins it. H1's error reaches `fill_parse_error` through the **existing** `fill_parse_errors[0]` plumbing at `submit_chain.py:889` with no edit; H2 is fixed in `_body_detail` (`:734-769`), a *callee* of classify, so classify's bytes and every `kind` it can return are unchanged.

**Why not a new store key.** `RESOLVER_CONTEXT_KEY_PREFIX` is already written on exactly the path that needs capture (with-id AMBIGUOUS — and a `fill_parse_error` is only reachable when `order_id is not None`, `submit_chain.py:822`), is keyed by a fresh UUID4 so nothing collides or overwrites, and is never deleted. A second key would be a parallel evidence store.

**NOT changed — byte-unchanged pins, by test name.**
| Pinned | Test |
|---|---|
| `classify_create_order_outcome` (`submit_chain.py:772-890`) | `test_an_ambiguous_outcome_keeps_the_latch_open_and_does_not_release_the_booking["200-id-no-exec"]` (`tests/unit/test_polymarket_us_submit_order_chain.py:598-620`, def `:626`) — L-36 |
| `_EXECUTION_KEYS` == snapshot `Execution` | `test_every_key_allowlist_equals_the_snapshot_typed_dict[_EXECUTION_KEYS]` (`tests/unit/test_polymarket_us_exec_snapshot_drift.py:138`) |
| `_submit_order`'s callee set | `test_the_order_coroutine_callee_allowlist_reaches_no_venue` (`tests/unit/test_execution_egress_firewall_guard.py:2770`, set-EQUALITY) — no new callee is introduced |
| `_assert_taker_fill`, `_usd_commission`, `_cumulative_fee_and_reconciliation` | `tests/unit/test_polymarket_us_exec_reports.py:511,534`; `test_i1a_bankers_rounded_total_against_sub_cent_leg_is_reconciled` (`:1655`) |
| every non-`executions-present` `detail` string | `test_every_classified_kind_sets_body_kind_and_body_len` (`:1423`), `test_body_detail_pins_state_and_cum_closed_set_tokens` (`:1545`) |

## 4. Increments

### I1 — H1: a underivable filled cost is never silent (S)
**RED first** — `tests/unit/test_polymarket_us_submit_order_chain.py`:
- `test_fill_generation_records_an_error_when_the_filled_cost_cannot_be_derived` — a leg that MAPS cleanly (passes `parse_fill_report`) but whose `order.avgPx`/`order.cumQuantity` are absent and whose `lastPx` is absent/malformed; assert `result is None`, `len(errors) == 1`, the message names `lastPx`/`avgPx`, and carries no value.
- `test_a_body_whose_filled_cost_is_underivable_stays_ambiguous_with_a_fill_parse_error` — via `_classify_i1a` (`:1161`): assert `outcome.kind == KIND_AMBIGUOUS` and `outcome.fill_parse_error is not None`.

**Minimal change** — `submit_chain.py:664-666` only: append a names-only message to `errors` (when supplied) before `return None`. `classify_create_order_outcome` untouched.
**Observable** — `outcome.fill_parse_error is not None` for a mapped leg with no derivable cost; the AMBIGUOUS log line gains the `fill_parse_error=` suffix (`client.py:2897`).
**Verify** — `scripts/ci/run_tests_no_egress.sh tests/unit/test_polymarket_us_submit_order_chain.py` ; `lint-imports` ; `mypy src/breezy/adapters/polymarket_us`.

### I2 — H2: the whole body's key tree reaches the diagnostic (M)
**RED first** — same file:
- `test_an_executions_present_body_with_no_selectable_leg_still_reports_the_body_key_tree` — `executions=[{...}]` whose only row has a non-fill `type` (so `_durable_execution` returns `None`); assert `KIND_AMBIGUOUS`, `"tree="` in `outcome.detail`, the drifted key NAME present, its VALUE absent.
- `test_the_body_key_tree_token_is_capped_and_declares_its_truncation` — a body with many keys; assert `len(outcome.detail) <= <cap> + margin` and `"truncated from"` present.
- `test_body_detail_tree_token_appears_only_on_executions_present` — the four other `body_kind` values carry no `tree=` (guards the untouched pins).

**Minimal change** — `submit_chain.py`: import `_key_tree` from `reports` (adapters→adapters, layer-legal); add `_DETAIL_TREE_MAX_CHARS: Final[int]`; in `_body_detail`'s `executions-present` branch only, append ` tree={...}` truncated with an explicit `(truncated from N characters)` marker mirroring `_name_value` (`reports.py:481-494`); update the `_body_detail` docstring — the tree is names-only but an OPEN set, which is exactly what L-37 (1) requires. Update the ONE exact-string pin at `tests/unit/test_polymarket_us_submit_order_chain.py:1470-1471`.
**Observable** — the 09-11 shape (`status=200 body_kind=executions-present … body_len=3481`) now also carries the body's key tree, on **every** kind including `KIND_ACCEPT_FILL` (logged at `client.py:2754-2764`), so a SUCCESSFUL body is captured too.
**Limit (state it, do not fix):** `_key_tree` renders a list as `key[n]: {first element}` — with multiple legs, only leg 0's names appear here; the SELECTED leg's own tree still arrives via `fill_parse_error`. Together they cover the refusal.
**Verify** — as I1, plus `scripts/ci/run_tests_no_egress.sh tests/unit/test_execution_egress_firewall_guard.py`.

### I3 — durable capture, so the declaration can be made from evidence (M)
**RED first** — `tests/unit/test_polymarket_us_exec_client.py`:
- `test_an_ambiguous_create_outcome_persists_the_body_key_tree_in_the_resolver_context` — drive `_submit_order` with an executions-present body that refuses; read `exec/polymarket_us/resolver/<intent_id>` from the real store; assert the decoded context carries the tree and that the tree names the drifted key and no value.
- `test_a_resolver_context_written_before_this_change_still_decodes` — a JSON blob with no `bodyKeyTree`; assert `from_bytes` yields `body_key_tree is None` (no schema bump; trailing-optional precedent `TrialDayRecord.venue_order_id` `trial_day_latch.py:233-240,284-286`).

**Minimal change** — `client.py`: `AmbiguousResolverContext` gains trailing `body_key_tree: str | None = None`, serialized as `"bodyKeyTree"` (`:611-625`) and read via `payload.get(...)` outside the strict `try` (`:637-660`); `_note_ambiguous_open` gains a keyword and stores it (`:2617-2645`); the call site at `:2913-2920` passes `body_key_tree=outcome.detail`. **No new callee in `_submit_order`** — the firewall allowlist (`test_execution_egress_firewall_guard.py:1827-1851`, set-equality pinned at `:2770`) is untouched.
**Observable** — after one refused create, `.venv/bin/python` + sqlite `mode=ro` read of the exec store shows a `resolver/*` row whose `bodyKeyTree` names every key the venue sent. That row is the input to I4.
**Verify** — `scripts/ci/run_tests_no_egress.sh tests/unit/test_polymarket_us_exec_client.py tests/unit/test_execution_egress_firewall_guard.py` ; `lint-imports` ; `mypy src/breezy/adapters/polymarket_us`.

### I4 — H3: declare `_EXECUTION_DRIFT_ALLOWED_KEYS` — **GATED, DO NOT START** (S)
**Gate.** Blocked until a real execution-object key tree is captured (I2+I3 deployed, then one create response with `executions`). **No execution body has ever been captured** (§9 E5) — L-37 (3) forbids declaring an allowlist from guesses, so this increment must not be written speculatively. If the captured tree shows **no** undeclared key on the `Execution` object, this increment is CLOSED-NOT-NEEDED and that fact is recorded.
**RED first, once gated** — `tests/unit/test_polymarket_us_exec_reports.py`: `test_the_execution_drift_fields_observed_live_are_accepted_and_unread` (one test per captured name, parametrized) and `test_a_field_beyond_the_declared_execution_drift_set_is_still_refused`.
**Minimal change** — `reports.py`: add `_EXECUTION_DRIFT_ALLOWED_KEYS` beside `_EXECUTION_KEYS` (`:283-297`) with the observed-at/log-evidence comment block copied in FORM from `_ORDER_DRIFT_ALLOWED_KEYS` (`:258-280`); use it at `reports.py:1037-1039` as `known=_EXECUTION_KEYS | _EXECUTION_DRIFT_ALLOWED_KEYS`. `_EXECUTION_KEYS` itself stays exactly the snapshot set or `test_every_key_allowlist_equals_the_snapshot_typed_dict` goes vacuous. Write `docs/evidence/venue/polymarket_us/EXECUTION_SHAPE_DRIFT_<date>.md` (precedent `BALANCES_SHAPE_DRIFT_2026-09-04.md`). Each declared name must be justified as DECLARED-BUT-UNREAD by pointing at the mapper that does not read it.
**Verify** — `scripts/ci/run_tests_no_egress.sh tests/unit/test_polymarket_us_exec_reports.py tests/unit/test_polymarket_us_exec_snapshot_drift.py`.

### I5 — the sub-cent create path books a RECONCILED fee (S) — characterisation + one new assertion
**L-33: characterisation, not RED.** Brief item (e) **already exists and passes** — `test_live_fill_chain_scores_a_real_taker_fill_end_to_end` (`tests/contract/test_live_fill_scoring_chain_contract.py:282`) drives a schema-shaped 200 body through the real `_submit_order` → `record_fill` → `SqliteStateStore` → scoring and asserts `record.fee_reconciled is True` (commission `0.03`). Brief item (d) is likewise present: `_usd_commission` is on the create path via `fill_generation`→`parse_fill_report`, and `fee_reconciled` requires the two exact `==` identities at `submit_chain.py:605-630`.
**The one real gap** — the SUB-CENT variant asserts `venue_fee_raw` and `cumulative_fee` but never the flag (`tests/unit/test_polymarket_us_submit_order_chain.py:975-998`).
**Change** — extend the GL-9 rig with `test_a_sub_cent_venue_fee_is_reconciled_end_to_end` reusing `_build_accept_fill_rig`/`_accept_fill_body` (`tests/unit/test_polymarket_us_exec_client.py:1966,2074`) at `commission="0.004"`; assert the store row carries `"feeReconciled": true`, `cumulativeFee == "0.004"`, `venueFeeRaw == "0.004"`, and that the scored parquet row's `fee` is the unrounded per-unit Decimal.
**Mutation evidence (L-33)** — flip `submit_chain.py:630` to `return leg_fee, False`; the new assertion must go RED and `test_live_fill_chain_scores_a_real_taker_fill_end_to_end` must go RED with it. Revert; both GREEN.
**Verify** — `scripts/ci/run_tests_no_egress.sh tests/contract/test_live_fill_scoring_chain_contract.py`.

**Order.** I1 → I2 → I3 (independent of each other in code, but I3's test consumes I2's token) → I5 → **I4 only when the gate opens**.

## 5. Acceptance — evidence the executing agent must show

1. RED→GREEN transcripts for I1, I2, I3 (failing assertion text, then the passing run) and the I5 mutation RED→revert→GREEN.
2. Full gate: `scripts/ci/run_tests_no_egress.sh` — no new failure beyond the known clock-dependent `tests/unit/test_app_trade_main_permit_logging.py:115`.
3. `lint-imports` contracts kept (3 kept / 0 broken) and `mypy` clean over `src/breezy/adapters/polymarket_us`.
4. A diff showing `classify_create_order_outcome` byte-identical (`git diff -- src/breezy/adapters/polymarket_us/exec/submit_chain.py` must not touch lines `772-890`) and `_EXECUTION_KEYS` unchanged.
5. Proof the three named pins still pass, by name (§3 table).
6. **Live observable that closes the item (post-deploy, not build-side):** one create-order response with a non-empty `executions` array whose node-log line carries `tree={...}`, and either a `feeReconciled: true` row under `exec/polymarket_us/fill/` **or** a `resolver/<intent_id>` row whose `bodyKeyTree` names every key the venue sent.

## 6. Non-goals

`classify_create_order_outcome` semantics or bytes; the GET-based AMBIGUOUS resolver; Nautilus reconciliation and `generate_fill_reports`/`generate_order_status_reports` (separate plan, audit S9 #1); PREREG v3 text and the residual/fee-unreconciled rule; `record_venue_order_id` wiring (audit S9 #2); `_has_durable_fill_record` (audit S1b #3); the alert sink (audit B4); relaxing ANY guard to make a body pass; declaring `_EXECUTION_DRIFT_ALLOWED_KEYS` from an uncaptured or inferred shape; persisting a raw venue body anywhere (names-only, always).

## 7. Risks, blast radius, rollback

| Risk | Mitigation |
|---|---|
| `fill_generation` blast radius (codegraph impact): `classify_create_order_outcome` + 17 tests in `test_polymarket_us_submit_order_chain.py` + `client._submit_order` | I1 adds a branch-local append only; existing callers that pass no `errors` sink are unchanged by construction (`errors is not None` guard already present at `:661`) |
| `_body_detail` feeds every classified log line and the `detail` pins | Token added in ONE branch; exactly one exact-string pin changes (`:1470-1471`); three new tests pin the other four `body_kind` values as token-free |
| Log/key bloat or an adversarial key set | `_DETAIL_TREE_MAX_CHARS` cap + explicit truncation marker; `_key_tree` renders **no** value at any depth (`reports.py:446-468`) |
| Store growth: resolver rows are never deleted | One extra string per AMBIGUOUS create; volume is ~2 orders in 8 days. Capped by the same truncation |
| Adding a callee to `_submit_order` would break the set-equality firewall pin | Design avoids it: only an attribute is passed to the already-allowlisted `_note_ambiguous_open` |
| Old resolver rows failing to decode | Trailing-optional read via `payload.get`, outside the strict `try`; pinned by its own RED test |
| I4 declared from a guess | Hard gate; I4 must not be started before the capture exists |
| **Rollback** | Each increment is one commit touching ≤2 source files; revert restores prior behaviour exactly (no schema version, no migration, no data rewrite) |

## 8. Rulings / operator items

| id | Item | Who | Options | Evidence needed |
|---|---|---|---|---|
| R1 | **Evidence sufficiency for declaring `_EXECUTION_DRIFT_ALLOWED_KEYS`** (gates I4) | strategy lead | (a) **Adopt repo precedent**: ONE observed key tree from ONE live body suffices, declared-but-unread, with a dated evidence doc — this is what `_USER_BALANCE_DRIFT_ALLOWED_KEYS` (one probe, `BALANCES_SHAPE_DRIFT_2026-09-04.md`), `_ORDER_DRIFT_ALLOWED_KEYS` (one GET body, 8d56a26) and `_MARKET_METADATA_DRIFT_ALLOWED_KEYS` (one observation, **explicitly extended by same-schema inference to a second unobserved surface**, `reports.py:353-374`) all did. (b) Require a second independent observation before declaring — costs one extra locked-out fill cycle at ~1 order/8 days. (c) Require a `scripts/venue/` re-probe of `GET /v1/order/{id}` corroborating the same names | the captured `bodyKeyTree` row from I3 + this table of three precedents. **Recommended: (a)** — it is the standing repo practice and (b) trades a real lockout for no new information |
| R2 | Persisting a names-only key tree onto the exec money store | build-side by my read (L-37 mandates names-only; the same string is already logged, pinned value-free by `test_..._stays_ambiguous_with_the_key_tree` at `:1172-1198`). Raised only so a reviewer can object | — | — |

No operator item. No budget, enablement, or PREREG amendment is implied by any increment.

## 9. Citations — verified against the working tree today (2026-09-12, HEAD e4848c3)

VERIFIED: `reports.py:283-297` (`_EXECUTION_KEYS`, no drift set), `:278-280`, `:332-346`, `:374` (the three sets that DO have one), `:221-230`, `:353-374`, `:446-468`, `:481-494`, `:673-698`, `:701-722`, `:824-844`, `:979-1012`, `:1015-1101`, `:1037-1039`. `submit_chain.py:169` (`fill_parse_error` field), `:402-426`, `:429-446`, `:456-469`, `:495-527`, `:583-630`, `:633-676` (narrow catch `:660-663`, **silent branch `:664-666`**), `:734-769`, `:772-890` (classify; `KIND_ACCEPT_FILL` `:838-851`, `fill_parse_error` `:889`). `client.py:345-378` (key prefixes), `:515-527`, `:590-660`, `:2275-2300`, `:2617-2645`, `:2647-2920` (AMBIGUOUS diag `:2889-2906`, `_note_ambiguous_open` call `:2913-2920`). Tests: `test_polymarket_us_submit_order_chain.py:598-620,626,902-998,1161-1198,1201-1227,1423,1470-1471,1545,1655`; `test_polymarket_us_exec_snapshot_drift.py:119-152,199-204`; `test_live_fill_scoring_chain_contract.py:282-306`; `test_execution_egress_firewall_guard.py:1827-1851,2770`. LESSONS: L-36 `docs/core/LESSONS.md:1318-1330`, L-37 `:1332-1344`. Commits 8d56a26, ba2c5ee read in full.

**E5 — NO captured create-order execution body exists (the finding that gates I4).** `grep -rln '"executions"' docs/evidence/` → **zero files**. `docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/` holds portfolio/book/balances probes only — no create body. The single executions-present create response ever observed is node log `breezy-trade-20260911T165022Z.log:886`: `status=200 body_kind=executions-present rpc_code=none body_len=3481 state=absent cum=absent` — the 3,481 bytes were never persisted, and `grep -c "key tree"` and `grep -c "fill_parse_error"` return **0** across **every** file in `~/.local/share/breezy/logs/` (that log predates ba2c5ee; no fill has occurred since). Schema anchor for the surface: `docs/evidence/venue/polymarket_us/docs_snapshots/api-reference_orders_create-order_2026-08-25.md` `CreateOrderResponse` = `{id, executions[]}` (L-36).

**UNVERIFIED / corrections to the brief and to L-36:**
- **Stale line numbers.** The brief and L-36 (`LESSONS.md:1327`) both cite `classify_create_order_outcome` as `submit_chain.py:818-855` and the strict ZERO_FILL predicate as `:818-825`. At HEAD the function spans **`772-890`** and the predicate is **`855-860`**; `:818-855` now points inside branch bodies. Cite the symbol, not those lines.
- **Stale citation.** The brief cites `_assert_representable` at `reports.py:414-419`; at HEAD that range is `_FILL_EXECUTION_TYPES`. `_assert_representable` is imported from `parsing.py` and applied at `reports.py:530-532` and `:841-843`.
- **"Byte-unchanged" is narrower than it reads.** ba2c5ee already added the `errors`/`fill_parse_error` plumbing INSIDE `classify_create_order_outcome` (`:821,831,889`), so the function is not literally byte-identical to the L-36 ruling text. This plan takes the strict reading and leaves it byte-unchanged anyway (I1/I2 are confined to its callees) — no increment relies on the looser reading.
- **UNVERIFIED:** whether the 09-11 `Execution` object itself carried undeclared keys. 8d56a26 attributes that refusal to the nested **order** drift; the execution object's own key set was never rendered. I4 exists precisely because this is unknown.
- **UNVERIFIED:** post-change `lint-imports`, `mypy` and gate results — no test was run for this plan (planning-only session).
- **UNVERIFIED:** `submit_chain` importing `reports._key_tree` is layer-legal by inspection (adapters→adapters, `submit_chain.py:27` already imports `parse_fill_report` from the same module) but `lint-imports` was not executed.
