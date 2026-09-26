## Scope
**In scope.** Exactly the three residual sub-items. They come from the FU-1d plan r1.2 "Re-open list" (`docs/plans/backlog/FU-1d_derived_no_marks_plan_r1_2026-09-26.md`, r1.2 section) and the ruling's second re-open trigger (`docs/evidence/RULING_FU-1b_no_leg_marks_2026-09-26.md`, "Re-open triggers").
- **S1, shared `_station_day_exit_counts`.** Decide per-leg vs shared. Record the decision in code and pin it with tests.
- **S2, defense in depth.** Add the NO-leg declaration check to `exec/submit_chain.unmappable_exit_order_reason`.
- **S3, walked VWAP vs realised NO fills.** An offline, read-only measurement script plus a committed evidence doc.

**Out of scope, explicitly.**
- Any manifest byte change: no `deploy/families/*.json` edit and no `no_leg_exit` key anywhere outside test fixtures.
- Any change to `_EXIT_RULE_REGISTERED_FAMILIES` (`src/breezy/persistence/exit_gate.py:55`) or to `MAX_STATION_DAY_EXIT_ORDERS` (`exit_decider.py:107`, Class-C per PREREG v4 line 112).
- `decide_exit` logic, FU-1c netting, any systemd unit, and Nautilus.
- Anything that could let an exit order be constructed or sent. Every change here either adds a refusal or reads data.

**Premise correction (verified read-only against the live exec store, `state` table, keys `exec/polymarket_us/fill/*`).** The store holds 9 fills and **3** of them are NO, not 2:
- `miahigh-2026-09-15-gte92lt93f^no` at 0.09
- `miahigh-2026-09-21-gte88lt89f^no` at 0.12
- `mdwhigh-2026-09-22-gte62lt63f^no` at 0.12

All 9 are `orderSide=BUY` with qty 1, so there are **0 NO exit (SELL) fills**. `docs/evidence/MEASURED_SLIPPAGE_2026-09-24.md` also lists all three `^no` rows.

## L-1 null-hypothesis verdict
- **S1.** Nautilus has only a global submit-rate throttle: `RiskEngineConfig.max_order_submit_rate` (`.venv/.../nautilus_trader/risk/config.py:29,42`). It has no concept of a station-day or a leg. The cap is PREREG v4 §3b ("a per-station-day cap bounds a flapping book", `docs/specs/PREREG_v4_crh_exit_DRAFT_2026-09-16.md:48`), and it already exists at `position_monitor.py:279-281,581-590,618-620`. **Verdict: nothing to build.** The work is a decision plus pins.
- **S2.** The venue-leg declaration is a Breezy manifest concept (`exit_gate.py:73-83`), and Nautilus has no equivalent. **Verdict: reuse the existing Breezy gate.** No new primitive.
- **S3.**
  - Depth frames come from the native `BaseDataCatalog.order_book_depth10` (`.venv/.../nautilus_trader/persistence/catalog/base.py:158-167`), which returns native `OrderBookDepth10` objects.
  - The VWAP is the existing `walk_exit_vwap` (`monitor_evidence.py:162-201`), reused unmodified.
  - Realised fills cannot come from the Nautilus `Cache`, which is memory-only in this deployment (`src/breezy/ingest/product_index.py:228-232`). The durable `DurableFillRecord` store (`exec/client.py:865-...`) is the only realised-fill source.
  - **Verdict: glue only.** Same discipline as `scripts/analysis/exit_window_core.py:20-30`.

## Acceptance Criteria
1. **S1.** `PositionMonitor` keeps one exit counter per `(station, climate_day)`, shared across the YES and NO legs.
   - A test proves that a fired YES exit is visible as `station_day_exit_count == 1` to the next NO-leg decision of the same station-day.
   - A code comment at `position_monitor.py:279-281` states this is deliberate and cites PREREG v4 §3b:48 and L-40.
2. **S1.** With an in-test manifest declaring `no_leg_exit=True`, `decide_exit` for NO evidence with `station_day_exit_count == MAX_STATION_DAY_EXIT_ORDERS` refuses with `station_day_exit_cap`.
3. **S2.** `unmappable_exit_order_reason` returns `"family does not declare a NO-leg exit; refusing"` in this case:
   - the instrument leg is `"no"`, and
   - every existing shape, family and family_id check passed, and
   - `family_declares_no_leg_exit(manifest)` is False.

   In every other case the reasons it returns are byte-unchanged.
4. **S2.** A YES-leg exit ignores the new check. An in-test manifest with `exit_rule` and `no_leg_exit=True` still maps a NO exit with the complemented wire price, 0.09 → 0.91, both at the `submit_chain` layer and at the exec-client boundary.
5. **S2.** At the exec-client boundary, a tagged NO exit under `ARMED_EXIT_MANIFEST` (exit_rule set, no `no_leg_exit`) produces exactly one `OrderDenied` carrying the new reason and `sender.calls == []`.
6. **S3.** `scripts/analysis/no_leg_mark_fidelity.py` reads the exec store with `mode=ro` (reusing `fill_time_count._open_readonly`, `fill_time_count.py:84-98`) and the quote-tape catalog. For every durable fill it emits one row:
   - `venue_order_id`, `instrument_id`, `leg`, `order_side`, `fill_px = cumulative_cost/cumulative_qty`, `qty`
   - `frame_ts_init`, `frame_age_ns`
   - `derived_entry_px`, `residual = fill_px − derived_entry_px`
   - `derived_exit_mark` (the monitor's own mark at that frame)
   - `status` ∈ {`measured`, `no_frame`, `stale_frame`, `one_sided`, `not_a_buy`}
   - `flagged`
7. **S3.** For a BUY fill, `derived_entry_px = 1 − walk_exit_vwap(depth, opposite(leg), qty)[0]`:
   - For a NO buy this walks the YES **bids**, so it is `1 − yes_bid_vwap`.
   - For a YES buy it walks the YES **asks**, since `walk_exit_vwap(...,"NO")` returns `1 − ask_vwap`.

   `derived_exit_mark = walk_exit_vwap(depth, leg, qty)[0]`. There is no hand-written price formula.
8. **S3.** Frame selection:
   - Use the latest sibling-YES frame with `frame.ts_init < fill.ts_event`. It must be strictly earlier, and the code asserts `frame_ts < fill_ts`.
   - `frame_age_ns > _BOOK_STALE_NS` (`monitor_decision.py:157`, imported) → `stale_frame`.
   - `flagged` means `fill_px < derived_entry_px`: the L-25 signature of a fill better than displayed.
   - `stale_frame`, `flagged`, `no_frame` and `one_sided` rows are excluded from the aggregate but still listed.
9. **S3.** The output is a **measurement, not a gate.**
   - Exit 0 whenever the sources are readable, whatever the residuals are. Exit 2 when a source is unreadable.
   - The Markdown evidence doc gives n per leg, a count of exact / ≤1 tick / >1 tick residuals, and the flagged rows.
   - The doc states that n(NO exit fills) = 0, so the ruling's re-open trigger ("walked-ask VWAP diverges from realized NO **exit** fills") is **not evaluable yet**.
   - No verdict and no CI gate is derived from it.
10. Gates stay green, each run with PYTHONPATH set to the worktree:
    - `scripts/ci/run_tests_no_egress.sh`, the full pytest suite, `lint-imports`, ruff and mypy
    - `test_execution_egress_firewall_guard.py`, with **no pin edits**

## Edge Cases & NFRs
| Case | Behaviour |
|---|---|
| S2: NO exit, family not registered | The family-gate reason still fires first, so the reason is unchanged (existing tests :344/:358 unedited) |
| S2: NO exit, family_id mismatch | The mismatch reason still fires first (existing test :378 unedited) |
| S2: `authorization.leg`≠instrument leg | The shape check (`submit_chain.py:446-448`) already refuses. The new check keys off `leg_of(instrument.id)`, the leg that actually reaches the wire |
| S1: two NO rungs, same station-day | Shared cap. Consistent with L-40: the trial unit is the station-day |
| S3: NO fill with qty 1 | `walk_exit_vwap` degenerates to top of book. The doc must say that depth-walk beyond level 0 is **not** exercised by any of the 9 fills |
| S3: resolver (`GET-…`) fill | `ts_event` is only an upper bound (`client.py` `trade_id` docstring). Row tagged `ts_provenance=resolver` and kept, but not in the NO aggregate. The one such fill is YES (09-13) |
| S3: legacy record (`tradeId=None`, 09-11 SFO) | Measured normally. `order_qty=None` is never inferred (S-M1); `cumulative_qty` is used |
| S3: frame gap (ING-1 stranding) | `no_frame`. The catalog is never guessed and the staged tape is not read. Verified: parquet intervals cover all three NO fill instants (18:12Z 09-15, 19:18Z 09-21, 18:00Z 09-22) |
| S3: a SELL record | `not_a_buy`, listed only. None exist today |
| NFR memory | 9 fills × 1 instrument-day of Depth10 each. Query per instrument with `start`/`end` = fill ± 1 day. Never load the whole catalog |
| NFR safety | Read-only URI, no flock, no writes to the store or catalog. Output goes only to `--out` and the committed doc |

## Design & Data Flow
**S1.** Options considered:
- (a) Keep the shared key, and make it explicit and pinned. **Chosen.**
- (b) Key by `(station, climate_day, leg)`. **Rejected:** it doubles the possible exits per station-day, which loosens a Class-C constant's meaning. PREREG v4:112 says "changing one is a registered amendment". The PREREG literally says "per-station-day" (:48).
- (c) Defer again. **Rejected:** the backlog row asks for closure, and (a) is a no-behaviour-change decision.

The change is a comment plus two tests. It is a characterisation item, so it has no RED; L-33 demands mutation evidence instead. The mutation is to key the dict with `monitored.leg`, and the S1 test must then fail.

**S2.** Options considered:
- (a) Add the check in `unmappable_exit_order_reason` after the family_id check (`submit_chain.py:485-486`). **Chosen:** every existing reason stays first, and it is the one place both the exec client (`client.py:4618-4620`) and the tests reach.
- (b) Add it in `_unmappable_exit_shape_reason`. **Rejected:** that function has no manifest (`submit_chain.py:400-405`).
- (c) Add it in `client._submit_order`. **Rejected:** that coroutine is E0-NOSEND-scanned (`client.py:689-697`), and a new callee would need a cage-pin widening.

The adapters→persistence import already exists (`submit_chain.py:44`), so no layer changes. The new reason string contains none of `BANNED_EXEC_DIRECTION_TOKENS` (`test_execution_egress_firewall_guard.py:257`).

**S3.** Data flow:
1. The durable fill records (read-only sqlite) give `DurableFillRecord.from_bytes`.
2. `sibling_instrument_id` (the involution at `symbology.py:318-325`) gives the YES catalog id.
3. `ParquetDataCatalog.order_book_depth10([yes_id], start, end)` gives the frames.
4. The pure core selects the frame, then applies `walk_exit_vwap` on opposite(leg) and on leg.
5. The rows go to `render_markdown` and the evidence doc.

Options considered:
- (a) A new, small, pure-core script. **Chosen.**
- (b) Extend `measured_slippage_from_fills.py`. **Rejected:** that script answers `fill − decision_ask` from `TrialDayRecord` (AUD-12a, already 0.00 for all 3 NO fills). This item is an independent reconstruction from the Depth10 tape through the monitor's own function. Mixing the two would blur two estimands.
- (c) Extend `exit_window_core`. **Rejected:** its scope is the post-fill window and it filters out frames at the fill instant (`exit_window_core.py:208-...`).

**The two findings the doc must state:**
- The NO rows validate the complement and sibling-routing mechanism on the **bid** side, which is how NO entries execute.
- The YES rows (n=6) are the **ask-side control**: a NO exit buys YES through the asks, the same book side as a YES entry. Neither measures a realised NO **exit**.

## File-by-File Plan
| Path | New/Mod | Exact change |
|---|---|---|
| /home/jon/breezy/src/breezy/strategy/current_rung_hold/position_monitor.py | mod | Comment-only at :279-281: "shared across YES and NO legs deliberately; PREREG v4 §3b:48 per-station-day cap; L-40; per-leg keying is a Class-C amendment". No code change |
| /home/jon/breezy/src/breezy/strategy/current_rung_hold/exit_decider.py | mod | Docstring-only at the `MAX_STATION_DAY_EXIT_ORDERS` block (:102-107): the count is shared across legs |
| /home/jon/breezy/src/breezy/adapters/polymarket_us/exec/submit_chain.py | mod | :44 also import `family_declares_no_leg_exit`. After :485-486 add `if leg_of(getattr(instrument, "id")) == "no" and not family_declares_no_leg_exit(manifest): return "family does not declare a NO-leg exit; refusing"` (keep the `# noqa: B009` idiom). Update the :470-474 docstring |
| /home/jon/breezy/src/breezy/persistence/exit_gate.py | mod | Docstring of `family_declares_no_leg_exit` (:73-82): name both consumers (decider and adapter seam) |
| /home/jon/breezy/tests/unit/test_current_rung_hold_position_monitor.py | mod | Add the S1 tests (below). No existing test edited |
| /home/jon/breezy/tests/unit/test_current_rung_hold_exit_decider.py | mod | Add the AC2 test |
| /home/jon/breezy/tests/unit/test_polymarket_us_exit_submit_chain_2026_09_16.py | mod | `_manifest(...)` gains `no_leg_exit: bool = False`. Add `_registered_no_leg_manifest()`. The :219 NO test switches to it, with **all assertions kept**. Add the S2 tests |
| /home/jon/breezy/tests/unit/test_polymarket_us_exec_client.py | mod | `_family_manifest` (:191) gains `no_leg_exit=False`. Add `ARMED_NO_LEG_EXIT_MANIFEST` next to :224. The NO-exit tests at :3226, :3524 and :3578 switch to it, assertions unchanged. The implementer greps `_no_leg_instrument()` × `limit_exit_sell` for any others. Add the AC5 test |
| /home/jon/breezy/scripts/analysis/no_leg_mark_fidelity.py | new | Pure core: `select_frame`, `measure_fill` → frozen `FillMarkComparison`, `summarise`, `render_markdown`. CLI: `--exec-state-db`, `--catalog-root`, `--run-date`, `--out`. Under 300 lines |
| /home/jon/breezy/tests/unit/test_no_leg_mark_fidelity.py | new | S3 tests |
| /home/jon/breezy/docs/evidence/NO_LEG_MARK_FIDELITY_<run-date>.md | new | Generated evidence doc (Deploy step 1) |
| /home/jon/breezy/docs/core/PROGRESS.md | mod | Close FU-1d-reopen with SHAs. Carry forward "ruling trigger (ii) not evaluable: n(NO exit fills)=0" |

## Test Strategy
**test_current_rung_hold_position_monitor.py**
- `test_station_day_exit_count_is_shared_across_yes_and_no_legs_of_one_station_day`
  - Setup: `_build_position_monitor_via_callables` with `sibling_for` set, a **stub** `exit_decider` that records `(evidence.leg, station_day_exit_count)` and returns a real `ExitProposal`, `submit_exit=list.append`, and both legs held.
  - Drive a YES THREATENED/DEAD evaluation, then the NO one.
  - Assert NO received count 1.
  - No RED (L-33): mutation evidence is to key the dict with `monitored.leg`, which gives NO count 0 and fails the test. Attach the mutation diff and its output.
  - The failure path is that a NO leg evaluates before YES; also assert the symmetric order.

**test_current_rung_hold_exit_decider.py**
- `test_no_leg_evidence_honours_the_station_day_cap_when_no_leg_exit_is_declared`
  - In-fixture manifest with `exit_rule` and `no_leg_exit=True`, NO DEAD evidence, count = MAX → `station_day_exit_cap`.
  - No RED (characterisation). Mutation: skip the cap check for NO → the test fails.

**test_polymarket_us_exit_submit_chain_2026_09_16.py**
- `test_a_no_exit_refuses_when_the_family_does_not_declare_no_leg_exit`. **RED:** returns `None` today.
- `test_a_yes_exit_is_unaffected_by_the_no_leg_declaration`. Pin: it passes before and after.
- `test_the_no_leg_refusal_follows_the_family_and_family_id_checks`. Order pin: a NO exit on an unregistered family still returns the family-gate reason.
- The existing :219 test must stay GREEN on the new fixture. Running it on the old fixture is the RED proof of the need.

**test_polymarket_us_exec_client.py**
- `test_a_tagged_no_exit_is_denied_when_the_armed_manifest_does_not_declare_no_leg_exit`. **RED:** `sender.calls` has 1 entry today.
- The retargeted :3226/:3524/:3578 must stay GREEN.
- **Reviewer sign-off:** these are fixture tightenings, not weakenings. Every assert is kept.

**test_no_leg_mark_fidelity.py**
- Fixtures go through the real writer paths (L-42):
  - `DurableFillRecord(...).to_bytes()` inserted into a tmp sqlite `state` table.
  - Depth10 written with `ParquetDataCatalog(tmp).write_data([...])`.
  - Expected values are computed with `walk_exit_vwap` inside the test, never hand-written.
- Tests, all **RED** because the module does not exist:
  - `test_no_buy_derived_entry_is_one_minus_walked_yes_bid`. Decoy asks.
  - `test_yes_buy_derived_entry_is_walked_yes_ask`. Decoy bids.
  - `test_derived_exit_mark_equals_monitor_walk_exit_vwap_for_the_leg`
  - `test_frame_selection_is_strictly_before_the_fill`. A frame at `ts == fill.ts_event` and one after are both ignored (leak guard).
  - `test_stale_frame_is_reported_and_excluded_from_aggregate`
  - `test_fill_better_than_displayed_is_flagged_not_aggregated`
  - `test_no_frame_and_one_sided_statuses`
  - `test_unreadable_store_exits_2_without_writing`
  - `test_sell_record_is_not_a_buy`
  - `test_report_states_no_leg_exit_fills_n_zero_and_no_verdict`
  - `test_store_opened_read_only`. Assert no WAL/journal is created and the mtime is unchanged.

**Re-run:**
- `test_execution_egress_firewall_guard.py` and `test_cage_rule_constants_are_pinned.py`, expecting zero pin changes
- `test_persistence_exit_gate.py` and `test_family_manifest.py`
- `test_measured_slippage_from_fills.py`
- full no-egress gate and `lint-imports`

## Deploy / Host Steps
1. After merge, from the primary tree, in a quiet window (one heavy job at a time):

   `PYTHONPATH=src .venv/bin/python scripts/analysis/no_leg_mark_fidelity.py --exec-state-db "$POLYMARKET_US_EXEC_STATE_DB" --catalog-root /home/jon/.local/share/breezy/catalog/quote_tape/polymarket_us --run-date <date> --out docs/evidence/NO_LEG_MARK_FIDELITY_<date>.md`

   Then commit the doc.
2. No node restart. No unit or timer. The runtime behaviour change (S2) sits behind a gate that is False for every committed manifest, so it is inert until the next node respawn and after it.

## Risk Register
- [MED] **Exec-client fixture retargets.** They could be misread as weakening a test. Mitigation: every assert is kept, the new RED test proves the gate, and the change is named in the review brief (L-12 spirit: tighten, never relax).
- [MED] **S3 may be over-read as validating the exit mark.**
  - n=3 NO rows, all qty 1, all entries.
  - Mitigation: the doc header states that it validates the complement and routing mechanism on the bid side plus an ask-side control, that the walk beyond level 0 is untested, and that the exit trigger is not evaluable. No verdict (memory: "check what data a blocker actually used").
- [LOW] **Fill `ts_event` vs frame `ts_init` clock skew.** Mitigation: report `frame_age_ns`; the `custom_venue_clock_offset` data exists but is not applied (YAGNI), which the doc notes.
- [LOW] **S1 comment drift.** Mitigation: the mutation-backed test is the real pin.
- [LOW] **Wording of the new refusal reason.** Mitigation: no banned X3 token, and it follows the inline-literal convention of its siblings.

## LESSONS Compliance
| Lesson | How the plan complies |
|---|---|
| L-1, L-11 | Native `order_book_depth10` and the existing `walk_exit_vwap`, `sibling_instrument_id` and `_open_readonly` are reused. Nothing new is authored where a native exists |
| L-2 | Every price is in the leg's own unit. The complement is derived only via `walk_exit_vwap` |
| L-12, L-14 | S2 only adds a refusal. Firewall pins are unchanged. The new refusal is derived from "what would refuse a NO exit" |
| L-22 | S2 inherits the code-registered frozenset through `family_declares_exit_rule` |
| L-24, L-42 | S3 fixtures go through the real writers. The S1 test drives the real `PositionMonitor` |
| L-25 | "Fill better than displayed" is flagged, not averaged |
| L-33 | S1 and AC2 are characterisation tests, backed by mutation evidence rather than a fabricated RED |
| L-40 | The shared station-day cap matches the station-day trial unit |
| L-43, L-51 | The full gate runs after merge. PYTHONPATH is set per worktree. No `uv sync` and no `git stash` |
| L-44 | Each leg's refusal and mapping path is tested separately |
| memory "implausible result is a leak" | Strict `frame_ts < fill_ts` assertion |

## Confidence
**HIGH (~88%)** for S1 and S2: small, additive, and every cited line was read.

**MEDIUM-HIGH (~80%)** for S3. Unknowns:
- (1) Whether `DurableFillRecord.ts_event` for create-path fills is venue transact time or local receipt time. This affects frame age, not the frame's side.
- (2) Whether the catalog's Depth10 for the 09-15 MIA rung carries the ING-1 truncation (`custom_depth_truncation` exists).
- (3) Whether any other exec-client test sends a NO exit under `ARMED_EXIT_MANIFEST`. The implementer must grep before GREEN.

**Coordinator note:** the brief's "2 NO" is wrong. The store holds 3.