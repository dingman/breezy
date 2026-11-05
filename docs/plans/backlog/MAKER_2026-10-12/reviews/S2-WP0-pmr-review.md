# S2 WP0 probe -- prediction-market review (blind)
Worktree maker-s2-wp0 @ e1b048c9. Files: scripts/analysis/maker_stage0_probe.py, maker_stage0_probe_core.py.
Authorities: S2 r3 L108-117; r4 delta (b),(e),(g),(i)3; parsing.py:777-779,971,976; maker_tape_census.py.
**VERDICT: REQUEST_CHANGES** (2 HIGH, both small; direction math itself is sound).

## Findings (ranked)
1. [HIGH] Delta and live/gap hours use the S1 maker window, not the process-live window.
   probe.py:315-321 (`span` = `maker_window_ns` = [D-1 12:00Z, ~D 09-10Z)); core.py:201-212.
   Plan: r4 (i)3 "max |offset_ns| in the station-day's process-live window"; r3 L112 and L175 (covered / live = process-live).
   Failure: samples from 12:00-16:50Z and 02:50Z-end, when no bid exists, can push one instance-day over 10 min.
   S-7 then voids the whole run before scoring for a non-result reason. `live_hours`/`gap_overlap_hours` are mislabelled
   and feed the WP5 coverage denominator wrongly.
   Fix: use `core.bidlive_window_ns(climate_day=, window=)` (census.py ~L170, [D-1 16:50Z, D 02:50Z) intersect maker window),
   for deltas AND live/gap hours. Keep the maker-window hours only as a separate labelled column. Add a test with an
   out-of-window 11-min offset that must NOT raise delta.
2. [HIGH] `first_print_instant` is unlicensed. probe.py:296-304 takes min `ts_event` over ALL prints of all CLEAN instances:
   NYC, non-maker stations, post-freeze days, with no `_key`/`admit_print` filter.
   Plan: r4 (b) licence / PMR H-2 (reads beyond licence); r3 WP1 "NYC filtered". A NYC print can set
   `first_replayable_day` for the maker stations; the output depends on firewalled data.
   Fix: filter through `_key` against MAKER_STATIONS (YES leg), over pre-freeze or declared days only (take `days`/`stations`).
   "Global" in r3 L111 means across instances, not across stations. Test: NYC print earlier than all maker prints must not move it.
3. [MEDIUM] Mixed clocks in gap exclusion. probe.py:210 builds `Gap` from `started_ns/ended_ns` and `gap_free_frames`
   (core.py:91-97) compares them with depth `ts_event` (venue transactTime). Gap clock is the recorder's; skew up to
   Delta (<=10 min) can keep a contaminated frame or drop a clean one. Fix: confirm gap clock in tape_records.py/recorder and
   either compare on frame `ts_init` or state the Delta tolerance in the report. Also a print inside a gap sees a pre-gap mid of
   unbounded age; plan is literal ("last gap-free frame"), so keep, but report the age p50/p95 of the mid used (report-only).
4. [MEDIUM] Scratch reuse: probe.py:285-286 `mkdir(exist_ok=True)`. After a SIGKILL the leftover dir is converted into again,
   doubling frames/prints; fails closed (false duplicate_trade_ids) but wastes a run. Fix: refuse a non-empty work_dir.
5. [MEDIUM] Listing instant = `BinaryOption.ts_init` (probe.py:204), host receipt of the definition, not the venue listing.
   Plan: r3 L113 "listing instant". A late recorder boot makes a listed-early market look late: spurious abstain (conservative).
   Fix: confirm S1 `classify`/census uses the same field; if not, align; label the column.
6. [LOW] Tie counts not reported. Add per-side `n_tie` and `agreement_excl_ties` to SideTally.to_dict (report-only, not verdict).
7. [LOW] Positive control (probe.py:381,390) is a subset of the pooled sample, not an independent "10-0x sample"; add
   `control_vs_pooled_agree` flag to the sidecar (report-only). Also add per-station tallies (report-only) so a mis-mapped station
   is not hidden by pooling.
8. [LOW] Delta None (no samples for an instance-day) must be treated by the S-7 pre-pass as UNKNOWN/abort, not 0 (driver note).

## Checks passed
- Direction: strict-before lookback (bisect_left -1, core.py:114) correct; undefined (no frame / one-sided / empty) counted in
  n_undefined, never disagree (core.py:116-117); n_defined>=200 per side (core.py:124); thresholds are module constants, no
  data-dependent parameter; sidecar written before `require_clean` raises (probe.py:124).
- Aggressor label comes from the print's own `aggressor_side` (probe.py:249), mapped from taker.side (parsing.py:976).
  Instruments are filtered to the YES leg (`leg_of == "yes"`, probe.py:170) and prices are YES-quoted, so a BUY_SHORT/NO buy that
  prints as SELL on the YES slug is a YES seller: SELLER <= mid is the right test. If the venue ever stamps such prints at the
  NO price, the seller side drops to INCONCLUSIVE and STOPS -- the correct outcome.
- Census: duplicate trade_id counted within an instance only; cross-instance overlap reported (core.py:158-178), consistent with
  S1 first-wins dedupe on trade_id. Caveat: trade_id = sha256(slug|tradeTime|price|size|side) (parsing.py:981), so two genuinely
  distinct identical-ms fills collapse to one id; S1 already ran with this, so no new risk. Opposite-side twins keyed
  (rung, ts, price, size) over the deduped set; opposite sides carry different ids, so this is the only way to see them. OK.
  NO_AGGRESSOR is counted post-dedupe; direction skips them; census raises on them. OK.
- first_replayable_day (core.py:140-145): print <= X 16:50Z gives X+1, else X+2. Matches r3 L67. Listing abstain after D-1 12:00Z
  (probe.py:325) matches r3 L113.
- Licence/live-instance: `_check_work_root` forbids scratch inside the capture; only CLEAN instances are converted and
  `rmtree` touches only work_root/<instance_id>; the source catalog is opened read-only. Reads inside the scratch copy
  are filtered by `_key`/`admit_print` before any count (core `admit_print` contract). Whole-instance conversion reads
  unlicensed rows into scratch but never records them. Acceptable except finding 2.

## Rulings
- Combination rule: ACCEPT per-side. FIXED = both sides >=0.9; INVERTED = both <=0.1; anything else INCONCLUSIVE; either side
  n_defined<200 INSUFFICIENT; all three non-FIXED outcomes raise StopS2. Pooled agreement would let a heavy side mask the other and
  contradicts "n_defined>=200 per side". INSUFFICIENT as S-2 is fail-closed and consistent with r3 L111 (the plan is silent;
  record this reading in the amendment). Mixed (buyer >=0.9, seller <=0.1) = no information = STOP.
- Tie: keep ties as AGREE (plan literal ">=" / "<="; thresholds frozen pre-data). A print exactly at mid is inside-spread and weakly
  informative, but excluding it changes the frozen statistic. Ties inflate both rates symmetrically, so they cannot manufacture
  INVERTED; they can only soften a borderline FIXED. Mitigation is report-only (finding 6); if tie share exceeds 5% the coordinator
  should decide BEFORE the run whether FIXED additionally requires the tie-excluded rate >=0.9.
- Delta window: use the process-live window [D-1 16:50Z, D 02:50Z) intersect the S1 maker window, i.e. the existing
  `bidlive_window_ns` (not the raw maker window, not the bare nominal window). It equals the nominal permit window clipped to what S1
  already scores, and relaunches (17:10Z-01:00Z) lie inside it. Per instance-day max, station-day max over instances: as implemented.

## S-2 verdict movability after seeing data
None found: no tunable threshold, control and first_print are inputs not selectors. Residual: caller-chosen `days`/`stations`
(driver licence). Finding 2 makes first_replayable_day depend on out-of-licence data and must be closed first.
