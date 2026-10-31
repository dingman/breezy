# Card A pre-registration (2026-10-31)

YES ask-sum lock (leg 1) and the long-only NO basket (leg 2). Authority: design_r2.md 4.0 (118-149), 4.A (244-287), section 5 row 3 (414). Deltas: design_r2_1_deltas.md 26-33 and 62. Review: review_r2.md J3 (30-34), J5 (42-43), J7 (45). This file is the frozen rule for the one look. The flag is not built here.

## A. Estimands

1. Leg 1, complete YES partition. overround_with_fee = sum over rungs of (ask_i + fee(ask_i)) - 1.
2. Leg 2, long-only NO basket, same frame. bid_excess = sum over rungs of bid_i - 1 - sum over rungs of fee(1 - bid_i). Buying every NO pays 1 - bid per rung and exactly n_rungs - 1 contracts settle at 1.
3. fee(p) is one taker contract: fee_on_ask (decision.py:320-327, alias at 335) quantizes theta * p * (1 - p) to _CENT with ROUND_HALF_EVEN. _CENT is Decimal("0.01") at decision.py:167. theta is 0.0695 (forecast_tape_screen.py:72; fees.py:112). Round each leg, then sum. Do not round a summed unrounded product.
4. The window starts 2026-09-21, after 2026-09-17T17:00:00Z (fees.py:119-120; fee_schedule_bucket at 504-519 returns POST_DRIFT). The 0.06 pin (fees.py:94) is not used.
5. Do not call PolymarketUSFeeModel.get_commission (fees.py:267-289). allow_maker=True pays MAKER_FEE_COEFFICIENT Decimal("-0.0125") (fees.py:83, branch 283-286). The schedule effective 2026-10-19 charges takers theta and makers 0 with no rebate. That maker credit is a known defect and is forbidden. Card A legs are taker legs. Venue rounding for a taker fill is _round_bankers to currency precision, ROUND_HALF_EVEN (fees.py:627-635), the same cent rule fee_on_ask copies (decision.py:79-97).
6. One-tick slippage is 0.01 per leg, so n_rungs * 0.01, applied before the section F comparison. Leg 1 adds it to overround_with_fee. Leg 2 subtracts it from bid_excess.
7. No forecast. No order. No settlement join. sum_ask_row (wp7b_market_as_forecaster.py:537-565) stays as written and is not called: it requires RungEvent (336-353), and p_fc and settled are labels. SumAskRow (505-512) has ask fields only. Leg 2 is not a SumAskRow.

## B. Frame selection

Verbatim from design_r2.md:120-127.

1. One frame per station-day. Target 18:00:00 UTC on D-1. D is the climate date parse_rung reads from the instrument id (h4_preliminary_economic_read.py:209-214).
2. ts_event in [17:30:00, 18:30:00) UTC, else the day is missing.
3. Absolute age from 18:00:00Z at most 60 s, else missing.
4. ts_event at least 60 minutes after the first frame where assert_complete_partition succeeds (wp7b_market_as_forecaster.py:184-224), else missing. Not the first frame. Not nearest with no cap.
5. Non-crossed: every rung has no bid, or bid < ask. A crossed rung drops the frame. A zero-price pad is no bid, not a cross (forecast_cheap_screen_wp7.py:914-918).
6. Leg 2 also needs every bid present, and every bid size at least 1 after section C. A missing bid drops leg 2 only.

## C. Depth10 unit line

1. Before any size comparison the artefact prints the quantity scalar from _fixed_scalars, one raw ask_size_0 integer, and the unit.
2. Definition: forecast_cheap_screen_wp7.py:854-857 returns (float(Price(1.0, 0).raw), float(Quantity(1.0, 0).raw)). The size scalar is the second element. collect unpacks it at wp7b_market_as_forecaster.py:896. read_rung_tape divides the raw sizes by it (forecast_cheap_screen_wp7.py:916-918). Columns are ts_event, ask_price_0, ask_size_0, bid_price_0, bid_size_0 (833-839).
3. The raw integer is one ask_size_0 cell as a little-endian signed int before division (903 and 916). Print both scalars. Only the quantity scalar enters a size comparison. The unit word is contracts as that scalar defines one contract.
4. If that line cannot be printed, every size-dependent outcome is INCONCLUSIVE. Never PASS. Never KILL.

## D. Own-order exclusion

1. The set is every PM.us instrument id with any own order or intent in the durable store, across all trial prefixes in deploy/families/pm_us_*.json. Six files, each prefix at line 4: pm_us_crh_cont.json, pm_us_crh_exit_v4.json, pm_us_crh_fq_v1.json, pm_us_crh_v2.json, pm_us_crh_v4.json, pm_us_no_maker_sharp_v1.json. That includes taker families from 2026-09-13, pm_us_crh_fq_v1 (d0 2026-10-02), and pm_us_no_maker_sharp_v1 (d0 2026-10-25). Not a shorter subset (design_r2.md:132-137; deltas 26-33).
2. Durable store path the units set: /home/jon/.local/share/breezy/state/exec_polymarket_us.sqlite (deploy/systemd/breezy-score-live-trials.service:69; the file is present). Resolver: resolve_store_path (src/breezy/runtime/exec_state_db_path.py:78-97) from POLYMARKET_US_EXEC_STATE_DB. No default (line 89). Unset, relative, or unreadable: the set cannot be built.
3. Reader found: StoreIntentSource.all_intents (src/breezy/runtime/exec_par_durable_sources.py:812-820), open slots plus HISTORY_KEY_PREFIX "exec/polymarket_us/intent/history/" (line 102). Key scan: SqliteStateStore.keys_with_prefix (src/breezy/runtime/sqlite_store.py:188-198). SubmitIntent holds created_ns and slug, not instrument_id (submit_intent.py:354-368). Fill keys use FILL_KEY_PREFIX "exec/polymarket_us/fill/" (src/breezy/domain/exec_intent.py:31). The instrument-id join is J1. Do not substitute scored-trial rows (scored_trial_dedupe.py:32-33 is the shape J5 rejected).
4. Drop a frame when any rung instrument is in the set and the frame ts_event is at or after that instrument first own order. Not a date cut. Do not shorten the window (design_r2.md:139-140; deltas 33).
5. The artefact lists instrument ids and a count. Never order ids.
6. Cross-checks only: those six manifests, and the node journal (breezy-trade-supervisor.service:177, StandardOutput=journal). A disagreement is not resolved by preferring the manifest (deltas 31). An unread journal is reported. It is not an empty set and it is not a REFUSE (deltas 32).
7. If the set cannot be built, exit 2 before any write.

## E. Window and catalog

1. Climate dates 2026-09-21 through 2026-10-30 inclusive, UTC dates carried in the instrument id. Not the 64 partitions that produced +0.29 (design_r2.md:268).
2. Sample floor: at least 30 partitioned station-days AND at least 7 distinct dates, else INCONCLUSIVE (design_r2.md:270 and 284).
3. Script default catalog: Path.home() / ".local/share/breezy/catalog/quote_tape/polymarket_us" (wp7b_market_as_forecaster.py:830-832). That path is a symlink of /mnt/storage/breezy/catalog/quote_tape/polymarket_us (same directory; harness_entrypoints.md:130-132). Depth10 root: catalog / "data" / "order_book_depths" (forecast_cheap_screen_wp7.py:1002; harness 119). The flag keeps the existing --tape default. It adds no catalog flag.
4. Listing at this writing: 2085 instrument directories, 216 names contain "low", 64 distinct YYYY-MM-DD tokens from 2026-08-30 through 2026-11-02. All 40 climate dates from 2026-09-21 through 2026-10-30 occur in at least one directory name. Directory dates are not ts_event (design_r2.md:436). harness_entrypoints.md:132-133 had 2041 directories ending 2026-11-01; the count above is the later listing.
5. Id grammar: h4_preliminary_economic_read.py:159-167 and parse_rung 209-253. High example: "tc-temp-nychigh-2026-09-06-gte75lt76f.POLYMARKET_US". The pattern requires the literal high, so a low name does not parse. Example: "tc-temp-nyclow-2026-10-19-gte42lt43f.POLYMARKET_US". Unparsed names are skipped, not a failed partition (J2).
6. The census must not call collect (wp7b_market_as_forecaster.py:888), _load_corpus (the call at 893), or decision_instant_ns (forecast_cheap_screen_wp7.py:248-257, which is 09:00 local). It must not apply POOL_CITIES (forecast_cheap_screen_wp7.py:201).

## F. PASS and KILL

Frozen. Not tunable flags. Module constants, asserted at startup before any frame is scored. Each leg is decided alone.

1. Leg 1 PASS: at least one frame with overround_with_fee + n_rungs * 0.01 <= -0.01 * n_rungs, and minimum ask size at least 1 after the unit line.
2. Leg 2 PASS: at least one frame with bid_excess - n_rungs * 0.01 >= 0.01 * n_rungs, every bid present, and every bid size at least 1 after the unit line.
3. KILL of a leg: zero frames clear that leg, among at least 30 partitioned station-days and at least 7 distinct dates. Below either floor, or a missing unit line: INCONCLUSIVE, not a zero (design_r2.md:282-284; section C).
4. P(PASS under H0) is approximately 0 on both legs. Published minimum sum-ask minus 1 is +0.05, fees are non-negative after rounding, and crossed and stale frames are excluded, not counted (design_r2.md:278-281).
5. The slippage addend is design_r2.md:129-130. The hurdle on the right-hand side is design_r2.md:274-276. F1 and F2 freeze both, applied in that order. r1 margin of -0.02 sits inside one tick times 6 to 10 legs and is not a PASS (design_r2.md:129-130).

## G. Extensions

Same artefact, separate sections, never a gate. These produce no PASS and no KILL.

1. BUYER print counts per instrument. TradeTick.aggressor_side.name is read at maker_stage0_catalog_read.py:262-270. The name to count is BUYER (maker_stage0_fill_events.py:21). Count prints. Do not sum size (design_r2.md:145).
2. Inventory of HIGH and LOW pairs whose combined asks make the pair impossible. Inventory only (design_r2.md:247-250 and 264-266).

## H. One look

1. Entry, once the flag exists: python -m scripts.analysis.wp7b_market_as_forecaster --census-only. Absent the flag, main stays as written (wp7b_market_as_forecaster.py:1287-1323, which calls collect). With the flag, main must not call collect or _load_corpus and must not build a RungEvent (design_r2.md:255-262). One flag on the existing script. Not a new harness, evaluator, runner, or unit (review_r2.md J3, 30-34, applied to this card by the task).
2. Writes only docs/evidence/STRAT_DESIGN_2026-10-31/card_a_census.md and card_a_census.parquet. Temp file in that directory, then atomic replace. The markdown header records the prereg sha256.
3. The process asserts that --prereg-sha equals the sha256 of this file. Mismatch refuses.
4. It refuses to run while docs/evidence/STRAT_DESIGN_2026-10-31/FREEZE_card_a.txt is absent or its status is PENDING (review J7 at review_r2.md:45; deltas 3 and 59; prereg_r2_1.md:68 and 80). Model record: FREEZE_card_e.txt:1-6 (prereg path, prereg_sha256, frozen_at_commit, looks_allowed 1). This card also requires a status field.
5. A second invocation with the same prereg sha refuses, unless --force-new-look is passed, and the artefact records that a new look was forced.
6. --dry-run performs zero writes and zero network connects, including while it refuses. Local catalog and store reads on a non-refused dry-run are not network. A refused run writes nothing.

## I. Decides

1. Leg KILL: that leg is retired permanently (design_r2.md:286-287 and 414). The other leg is not retired by that kill.
2. Leg PASS: hand prize(q) as a table over q in {1, 5, 10, 25} contracts, times the count of frames that passed that leg, per month. Compute the margin only after fees and after the slippage in F. Never pick q. No budget and no per-position size are read or set.
3. No engine run. No feed into P4 (design_r2.md:406). A PASS stops on the size question for that leg (design_r2.md:421-422).

## J. Open items

Reviewers settle these before status leaves PENDING. Each is a point the code did not close.

1. Instrument ids are not on SubmitIntent (submit_intent.py:361-368). all_intents returns those records (exec_par_durable_sources.py:812-820). intent_fingerprint hashes instrument_id and does not store it (domain/exec_intent.py:38-48). No reader was found that lists order rows as instrument ids, and no field was verified as the first-own-order timestamp other than created_ns on the intent. Fill prefix: domain/exec_intent.py:31.
2. Low directories fail parse_rung because the id pattern requires high (h4_preliminary_economic_read.py:159-162). Confirm they are skipped and do not refuse a high station-day. Card LOW is a later row (design_r2.md:289).
3. No code selects an 18:00:00Z frame. design_r2.md:120-124 gives the hour cap and the 60 s cap and forbids unbounded nearest. It does not say which timestamp wins when two frames sit inside the 60 s cap, nor how an equal-age tie breaks. decision_instant_ns (forecast_cheap_screen_wp7.py:248-257) is a different instant and must not be reused.
4. No function reads node logs. The only surface found is StandardOutput=journal at breezy-trade-supervisor.service:177. Reviewers name the unit and the field that carries an instrument id. Until then the cross-check is reported as not performed (section D6).

## K. Freeze line

Frozen when docs/evidence/STRAT_DESIGN_2026-10-31/FREEZE_card_a.txt records prereg_sha256 of this file, frozen_at_commit, looks_allowed 1, and status FROZEN; until then status PENDING.
