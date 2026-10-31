# Card A pre-registration r1 (2026-10-31)

YES ask-sum lock (leg 1) and the long-only NO basket (leg 2). Authority: design_r2.md 4.0 (118-149), 4.A (244-287), section 5 row 3 (414). Deltas: design_r2_1_deltas.md 26-33 and 62. Binding review: review_card_a_r0.md. This file is the frozen rule for the one look. The flag is not built here. Nautilus Trader is immutable. allow_short stays False (wp7b_market_as_forecaster.py:239).

## A. Estimands

1. Leg 1, complete YES partition. overround_with_fee = sum over rungs of (ask_i + fee_1(ask_i)) - 1. The q=1 gate uses fee_1 only.
2. Leg 2, long-only NO basket, same frame. bid_excess = sum over rungs of bid_i - 1 - sum over rungs of fee_1(1 - bid_i). Buying every NO pays 1 - bid per rung and exactly n_rungs - 1 contracts settle at 1.
3. fee_1(p) is one taker contract. _fee at src/breezy/strategy/current_rung_hold/decision.py:320-327 quantizes theta * p * (1 - p) to _CENT with ROUND_HALF_EVEN. fee_on_ask is that function (decision.py:335). _CENT is Decimal("0.01") at decision.py:167. theta on this gate is 0.0695 (forecast_tape_screen.py:72). Round each leg, then sum. Do not round a summed unrounded product. At this theta the one-contract fee is 0.00 for p below about 0.078 or above about 0.922, because the product is under half a cent before the quantize at decision.py:327.
4. The window starts 2026-09-21, after 2026-09-17T17:00:00Z (fees.py:119-123; fee_schedule_bucket at fees.py:504-519 returns POST_DRIFT at 519). The 0.06 pin (fees.py:94) is not used.
5. Do not call PolymarketUSFeeModel.get_commission (fees.py:267-289). allow_maker=True takes the maker branch (fees.py:283-286) and pays MAKER_FEE_COEFFICIENT Decimal("-0.0125") (fees.py:83). Makers are 0 with no rebate on the live schedule. That maker credit is a known defect and is forbidden. Card A legs are taker legs. prize(q) does not call get_commission. For q in {5, 10, 25}, prize uses one rounded fee per q-fill per leg: polymarket_us_fee (fees.py:314-315) computes theta * C * p * (1 - p) once (fees.py:352) and _round_bankers quantizes with ROUND_HALF_EVEN (fees.py:627-635). It is not q times fee_1(p). The q=1 gate stays fee_1.
6. Theta is per instrument, from instrument.info. The key is "fee_coefficient" (parsing.py:304), the stored venue feeCoefficient (parsing.py:29), read at fees.py:471 (class text fees.py:160-163 and 169). Missing, or not equal to Decimal("0.0695"): that row is INCONCLUSIVE. Do not fill the gap with the module constant. An INCONCLUSIVE row supports neither PASS nor KILL.
7. One-tick slippage is 0.01 per rung, so n_rungs * 0.01, applied before the section F comparison. Leg 1 adds it to overround_with_fee. Leg 2 subtracts it from bid_excess.
8. No forecast. No order. No settlement join. No budget, no per-position cap, and no order quantity is read or set. sum_ask_row (wp7b_market_as_forecaster.py:537-565) stays as written and is not called: it requires RungEvent (336-353), and p_fc and settled are labels. SumAskRow (505-512) has ask fields only. Leg 2 is not a SumAskRow.

## B. Frame selection

Depth rows are per instrument (forecast_cheap_screen_wp7.py:895-923). Do not use _first_row (market_calibration_scan.py:354-359) or first_liftable_at_or_after (wp7b_market_as_forecaster.py:232-248, called at 943-947). design_r2.md:124 forbids the unbounded nearest and the first frame.

1. One frame per station-day. Target 18:00:00 UTC on D-1. D is the climate date parse_rung reads from the instrument id (h4_preliminary_economic_read.py:209-214).
2. A qualifying row has ts_event inside [17:30:00, 18:30:00) UTC and absolute age from 18:00:00Z at most 60 s. Both bounds. Selection is time-only.
3. Per rung, choose the qualifying row with the smallest distance from 18:00:00Z. A tie goes to the earlier ts_event.
4. Frame time = the latest per-rung time. Any rung without a qualifying row makes the day MISSING.
5. First complete partition = latest of the rungs first ts_event. assert_complete_partition (wp7b_market_as_forecaster.py:184-224) checks ids only. The 60 minute rule applies to the frame time, which must be at least 60 minutes after that first-complete time, else MISSING. Ids that fail the partition check make the day MISSING.
6. Crossed is defined only when both sides exist (ask is not None and bid is not None) and bid is greater than or equal to ask. A zero pad is not a side: ask is None at forecast_cheap_screen_wp7.py:915 and bid is None at 917. A pad is not a cross. A crossed rung drops the frame.
7. Leg 1 requires every ask present and scaled ask_size_0 at least 1. A missing ask drops leg 1 only. Size uses L0 only (section C).
8. Leg 2 needs every bid present and every bid_size_0 at least 1 after section C. A missing bid drops leg 2 only.
9. Floor denominator = station-days with a selected valid frame (every rung qualifying, ids accepted, frame time legal, not crossed, no INCONCLUSIVE fee row). Under 30 is INCONCLUSIVE, never KILL.

## C. Depth10 unit line

1. Before any size comparison the artefact prints the quantity scalar from _fixed_scalars, one raw ask_size_0 integer, and the unit. The size test uses L0 only.
2. _fixed_scalars is forecast_cheap_screen_wp7.py:854-857 and returns (float(Price(1.0, 0).raw), float(Quantity(1.0, 0).raw)). The size scalar is the second element. collect unpacks it at wp7b_market_as_forecaster.py:896. ask_size_0 is divided at forecast_cheap_screen_wp7.py:916. bid_size_0 is divided at 918.
3. Columns are ts_event, ask_price_0, ask_size_0, bid_price_0, bid_size_0 (forecast_cheap_screen_wp7.py:833-839). The ask price raw is a little-endian signed int at 903. The ask size raw is the same decoding of ask_size_0 inside the division at 916. Print both scalars. Only the quantity scalar enters a size comparison. The unit word is contracts as that scalar defines one contract. Nautilus Price and Quantity are read only (855).
4. If that line cannot be printed, every size-dependent outcome is INCONCLUSIVE. Never PASS. Never KILL.

## D. Own-order exclusion

1. The set is every PM.us instrument id with any own order or intent in the durable store, across all trial prefixes in deploy/families/pm_us_*.json. Six files, each prefix at line 4: pm_us_crh_cont.json, pm_us_crh_exit_v4.json, pm_us_crh_fq_v1.json, pm_us_crh_v2.json, pm_us_crh_v4.json, pm_us_no_maker_sharp_v1.json. That includes taker families from 2026-09-13, pm_us_crh_fq_v1 (d0 2026-10-02, line 5), and pm_us_no_maker_sharp_v1 (d0 2026-10-25, line 5). Not a shorter subset (design_r2.md:132-137; deltas 26-33).
2. Store path: /home/jon/.local/share/breezy/state/exec_polymarket_us.sqlite (deploy/systemd/breezy-score-live-trials.service:69). Resolver: resolve_store_path (src/breezy/runtime/exec_state_db_path.py:78-97) from POLYMARKET_US_EXEC_STATE_DB. No default (line 89). Unset, relative, or unreadable: the set cannot be built.
3. Reader: mode=ro as read_durable_fills does (src/breezy/analysis/labeling/fill_source.py:66), plus PRAGMA query_only=ON (line 68). Do not construct SqliteStateStore (src/breezy/runtime/sqlite_store.py:117-126): that init creates directories, sets WAL, creates a table, and commits. Dry-run has zero store side effects.
4. Join on the base slug (src/breezy/adapters/polymarket_us/exec/client.py:7749), the slug arm_slot stores (client.py:7867-7870). The NO leg is the base slug plus "^no" (src/breezy/domain/instrument_leg.py:40, built at 73). An order on either leg excludes the market. First own order = minimum created_ns per base slug.
5. slug is optional on older K=1 records (src/breezy/runtime/submit_intent.py:357-367). If slug is absent, resolve fill_by_fingerprint/<UTC day>:<fp> (src/breezy/domain/exec_intent.py:34; get at src/breezy/runtime/exec_par_durable_sources.py:365) to the fill bytes (369-373) and read DurableFillRecord.instrument_id (src/breezy/adapters/polymarket_us/exec/client.py:1079, decoded at 1157). Unresolvable: exit 2 before any write.
6. Open-slot source: CURRENT_INTENT_KEY (submit_intent.py:88), injected as open_intents (exec_par_durable_sources.py:804) and merged by all_intents (812-820) with HISTORY_KEY_PREFIX (line 102). A row that does not decode means the set cannot be built.
7. Drop a frame when any rung shares a base slug with the set and the frame time is at or after the first own order of that slug. Not a date cut. Do not shorten the window (design_r2.md:139-140; deltas 33).
8. The artefact lists instrument ids and a count. Never order ids.
9. Cross-checks only: those six manifests, and the node journal (breezy-trade-supervisor.service:177, StandardOutput=journal). No node-log reader exists, so this cross-check is reported as not performed. It is not an empty set and it is not a REFUSE (deltas 32). Non-blocking (J4).
10. If the set cannot be built, exit 2 before any write.

## E. Window and catalog

1. Climate dates 2026-09-21 through 2026-10-30 inclusive, UTC dates carried in the instrument id. Not the 64 partitions that produced +0.29 (design_r2.md:268). The window is 40 dates. The prize table uses 30 (section I).
2. Sample floor: at least 30 denominator station-days AND at least 7 distinct dates, else INCONCLUSIVE (design_r2.md:270 and 284; section B9). Under 30 is never KILL.
3. Catalog constant: Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us" (wp7b_market_as_forecaster.py:830-832). That path is a symlink of /mnt/storage/breezy/catalog/quote_tape/polymarket_us (harness_entrypoints.md:130-132). Depth10 root: catalog / "data" / "order_book_depths" (forecast_cheap_screen_wp7.py:1002). Census mode refuses --tape. No catalog flag is added.
4. Listing at this writing: 2085 instrument directories, 216 names contain "low", 64 distinct YYYY-MM-DD tokens from 2026-08-30 through 2026-11-02. All 40 climate dates from 2026-09-21 through 2026-10-30 occur in at least one directory name. Directory dates are not ts_event (design_r2.md:436).
5. Id grammar: h4_preliminary_economic_read.py:159-167 and parse_rung 209-253. High example: "tc-temp-nychigh-2026-09-06-gte75lt76f.POLYMARKET_US". _INSTRUMENT_RE requires the literal high (159-162). A low name does not parse. Low directories are skipped and noted (forecast_cheap_screen_wp7.py:1011-1015) and do not refuse a high station-day. Closed (J2).
6. The census must not call collect (wp7b_market_as_forecaster.py:888), _load_corpus (the call at 893), or decision_instant_ns (forecast_cheap_screen_wp7.py:248-257). It must not apply POOL_CITIES (forecast_cheap_screen_wp7.py:201).

## F. PASS, KILL, and constants

Frozen. Not tunable flags. Each leg is decided alone. Compare in integer cents after the cent rounding in section A. Not a float inequality. sum_ask_row uses math.fsum (wp7b_market_as_forecaster.py:559-562) and is not the comparator.

1. Module constants, asserted at startup before any frame is scored: window 2026-09-21 through 2026-10-30; target 18:00:00Z; offsets [17:30:00, 18:30:00) UTC; age cap 60 s; partition lag 60 minutes; fee coefficient 0.0695, the fee_coefficient argument of venue_fee (forecast_tape_screen.py:156-157) and of sum_ask_row (wp7b_market_as_forecaster.py:538); tick 0.01; hurdle per rung 0.01; floors 30 and 7. A mismatch refuses. Census mode refuses --tape (E3).
2. Leg 1 PASS: at least one frame with overround_with_fee + n_rungs * 0.01 <= -0.01 * n_rungs, in integer cents, every ask present, and minimum L0 ask size at least 1 after the unit line.
3. Leg 2 PASS: at least one frame with bid_excess - n_rungs * 0.01 >= 0.01 * n_rungs, in integer cents, every bid present, and every L0 bid size at least 1 after the unit line.
4. Slippage of 1 tick (design_r2.md:129) plus the hurdle of -0.01 per rung (design_r2.md:274) is 2 ticks per rung, and that sum is intentional. A KILL means no lock with 2 ticks per rung of margin. A margin of -0.02 sits inside one tick times 6 to 10 legs and is not a PASS (design_r2.md:129-130).
5. KILL of a leg: zero frames clear that leg, among at least 30 denominator station-days and at least 7 distinct dates. Below either floor, or a missing unit line: INCONCLUSIVE, not a zero (design_r2.md:282-284; sections B9 and C).
6. P(PASS under H0) is approximately 0 on both legs only given the frame rule (B) and the every-ask-present rule (B7). The figure +0.05 is the empirical minimum of sum-ask minus 1 from the earlier 64-partition run, not a theorem. Fees are non-negative after rounding. Crossed frames and MISSING days are excluded, not counted (design_r2.md:278-281).

## G. Extensions

Same artefact, separate sections, never a gate. These produce no PASS and no KILL.

1. BUYER print counts per instrument. G1 imports the reader in maker_stage0_catalog_read. TradeTick.aggressor_side.name is read at maker_stage0_catalog_read.py:262-270. The name to count is BUYER (maker_stage0_fill_events.py:21). Count prints. Do not sum size (design_r2.md:145). Not a new runner.
2. Inventory of HIGH and LOW pairs whose combined asks make the pair impossible. Inventory only (design_r2.md:247-250 and 264-266).

## H. One look

1. Entry, once the flag exists: python -m scripts.analysis.wp7b_market_as_forecaster --census-only. The flag branches in main before collect (wp7b_market_as_forecaster.py:1318). Absent the flag, main stays as written (1287-1323). With the flag, main must not call collect or _load_corpus and must not build a RungEvent (design_r2.md:255-262).
2. Second-runner guard. Reuse only read_rung_tape (forecast_cheap_screen_wp7.py:860-923), _fixed_scalars (854-857), assert_complete_partition (wp7b_market_as_forecaster.py:184-224), fee_on_ask (src/breezy/strategy/current_rung_hold/decision.py:335), SumAskRow (wp7b_market_as_forecaster.py:505-512), and load_sites as imported at forecast_cheap_screen_wp7.py:995 (defined at settlement_alignment_study.py:668). G1 imports the maker_stage0_catalog_read reader. Allowed new code: the frame selector, the own-order set, the sha and freeze guard, and the atomic writer. Nothing else. Not a new harness, evaluator, runner, or unit.
3. Writes only docs/evidence/STRAT_DESIGN_2026-10-31/card_a_census.md and card_a_census.parquet. Temp file in that directory, then atomic replace. The markdown header records the prereg sha256.
4. The process asserts that --prereg-sha equals the sha256 of this file. Mismatch refuses.
5. It refuses to run while docs/evidence/STRAT_DESIGN_2026-10-31/FREEZE_card_a.txt is absent or its status is PENDING (review_r2.md:45; deltas 3 and 59; prereg_r2_1.md:68 and 80). Model record: FREEZE_card_e.txt:1-6. This card also requires a status field.
6. A second look needs a new prereg sha. A prior look is detected when card_a_census.md already exists and its header carries this sha. The run refuses. No override flag.
7. --dry-run performs zero writes, zero store side effects (D3), and zero network connects, including while it refuses. A local catalog read and a mode=ro store read on a non-refused dry-run are not network and are not writes.

## I. Decides

1. Leg KILL: that leg is retired permanently (design_r2.md:286-287 and 414). The other leg is not retired by that kill.
2. Leg PASS: print prize(q) for q in {1, 5, 10, 25} as a report index, never as an order quantity. Never pick q. No budget and no per-position size are read or set. The q=1 column uses fee_1. Each q in {5, 10, 25} uses one rounded fee per q-fill per leg (A5). Normalize to 30 days: the window is 40 dates (E1), so scale the counted frames by 30/40. Count a frame for q only if the minimum L0 size on that leg is at least q.
3. Print these assumptions with the table: full-size simultaneous taker fills; no leg risk; the two legs are never both executed; voids are out of scope; the executable NO price may differ from 1 minus the YES bid under the SELL or BUY_SHORT representation.
4. Compute the margin only after fees and after the slippage in F. No engine run. No feed into P4 (design_r2.md:406). A PASS stops on the size question for that leg (design_r2.md:421-422).

## J. Open items

1. Closed. The join is D4 through D6. SubmitIntent has no instrument_id field (submit_intent.py:361-368). intent_fingerprint hashes instrument_id and does not store it (src/breezy/domain/exec_intent.py:38-48). Fill prefix: exec_intent.py:31.
2. Closed. _INSTRUMENT_RE requires high (h4_preliminary_economic_read.py:159-162). Low directories are skipped and noted (forecast_cheap_screen_wp7.py:1011-1015) and do not refuse a high station-day. Card LOW is a later row (design_r2.md:289).
3. Closed. The frame rule is section B. decision_instant_ns (forecast_cheap_screen_wp7.py:248-257) is not reused.
4. Open and non-blocking. No function reads node logs. The only surface found is StandardOutput=journal at breezy-trade-supervisor.service:177. The cross-check stays "not performed" (D9). It does not refuse the run and it does not hold the freeze.

## L. Reviewer corrections

1. K2: a zero pad sets ask to None at forecast_cheap_screen_wp7.py:915, not at 918. Line 917 sets bid to None. Line 918 is bid_size.
2. K3: _fee quantizes at src/breezy/strategy/current_rung_hold/decision.py:327. Lines 319-326 end on the unrounded product (326). fee_on_ask is the alias at 335.
3. K5: instrument_leg.py:63-65 strips the suffix (base_symbol_of). The suffix is line 40 and the NO symbol is built at 73. all_intents is exec_par_durable_sources.py:812; line 804 is the open_intents parameter. instrument_id is DurableFillRecord at client.py:1079. FillRecordLike (exec_par_durable_sources.py:148-158) does not declare it. Lines 365-373 only resolve the fingerprint to fill bytes.
4. S2: the info key is "fee_coefficient" (parsing.py:304), read at fees.py:471. fees.py:160-163 is the class docstring. feeCoefficient is the payload name (parsing.py:29), not the info key.
5. S7: ask size is divided at forecast_cheap_screen_wp7.py:916 and bid size at 918. Line 903 is the ask price raw, not the size. Line 917 sets bid to None.

## K. Freeze line

Frozen when docs/evidence/STRAT_DESIGN_2026-10-31/FREEZE_card_a.txt records prereg_sha256 of this file, frozen_at_commit, looks_allowed 1, and status FROZEN; until then status PENDING.
