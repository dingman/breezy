# S1-WP1 blind review — prediction-market-reviewer — 2026-10-12

Verdict: REQUEST_CHANGES (1 HIGH, 3 MEDIUM, 3 LOW). Statistics and market logic only. Files:
src/breezy/analysis/maker_tape_census.py (core), scripts/analysis/maker_tape_census.py (I/O).
Checked by running maker_window_ns for all four stations on 10-13: start D-1 12:00Z, end D 11:00Z, binding STALE_DERIVED each.

## Verified correct
- Window arithmetic (core:142-155). The windows are UTC-anchored, so DST cannot enter. The 09:00 LST backstop uses the fixed standard offset
  (14Z MIA, 15Z MDW, 17Z LAX/SFO) and never binds before 11Z on any date in 09-18..10-13.
- n_eff_ub (core:598) is exactly plan 2.1. m=4 gives 4/(1+3*0.5)=1.6. 19 dates give 30.4 and 26 dates give 41.6. Reproduced.
- Dedupe: trade_id is sha256(slug|time|price|size|side) (parsing.py:~980), so it is instrument-specific and the cross-instance dedupe is safe.
- Denominators: summarise() filters reason==COVERED before N_cov, D_cov, n_eff and C (core:594-601). A COVERED day with zero prints is a
  distinct row from every uncovered reason. Open windows fall out through the coverage gate (LOW_COVERAGE / LONG_HOLE).
- STOP wording: S-1 uses n_eff < 30; S-5 uses C < 0.05; the flag is KILL-LIKELY on [0.05, 0.10). The strings are "STOP ... NO-GO pre-screen"
  and "FLAG KILL-LIKELY". "GO" and "NOT-KILLED" are never emitted (script:350-355).
- Item 6: covered_intervals (core:247-264) clips each instance's alive span first and subtracts only that instance's own gaps. An
  unresolved gap runs to window end but cannot cross into a successor's span. A lone-instance LONG_HOLE therefore cannot carry into the
  multi-instance run. The only holes left are the rotation seam (the ~09:00Z gap between one instance's last and the next one's first
  VenueClockOffset) and any instance's trailing hole.

## Findings

1. [HIGH] Census window is silently wider than the window bids can live, and nothing reasons about it.
   core:79-88,142-155; plan r3 WP1 and section 3.1 never mention the permit. Spec section 3 (lines 106-112): under the current schedule
   bids rest only ~16:50Z (D-1) to ~02:50Z (D), about 10 h. The census counts prints, and requires 90% coverage and no hole over 60 min,
   over 23 h. That is 12:00Z-16:50Z (4.8 h, before launch) plus 02:50Z-11:00Z (8.2 h, after the permit lapses): 13 of 23 hours the bot
   cannot have a bid resting.
   Failure, two ways. (a) C overstates the reachable fill ceiling, because it counts D-1 midday and overnight D prints that no bid could
   catch. The overstatement is loose upward, and a loose C is a weaker S-5 STOP, so it errs toward continuing to build S2.
   (b) The coverage gate can reject a day whose real bid-live 10 h was fully recorded, because of a hole in 03:00Z-11:00Z. That makes
   n_eff_ub an understatement, while the name says "ub".
   Fix: in core add BID_LIVE_START_UTC=(D-1,16:50Z) and BID_LIVE_END_UTC=(D,02:50Z) as labelled constants, and make summarise/classify
   emit a second tally (C_bidlive, and coverage on that sub-window) next to the 23 h one. State in the docstring and the report which
   window gates S-1 and which feeds S-5. If the 23 h window is kept as primary, record the reason ("permit TTL is not a knob") in the
   evidence doc.

2. [MEDIUM] Gap and first-seen computation touches rows that never passed admit_print (SEARCH declaration "enters any computation").
   script:134-143 and 120-126: _gaps_by_station_day and _first_seen_by_station_day keep every key for NYC and for LAX/MDW/MIA/SFO on
   days >= 10-14 (D+1 slugs). They extend or compare before the admit_print check at :179.
   Failure: the data are gap and listing metadata, not outcomes, so the leak risk is low. But the declaration's own definition
   (line 34) only exempts "bytes discarded before admit_print".
   Fix: call core.admit_print(key[0], key[1], days, stations) inside both helpers and skip before extend/min. Add a test that gaps for
   an out-of-range day are never materialised.

3. [MEDIUM] Reasons do not separate "not covered" from "never listed" (L-8, L-52).
   script:293 hard-codes corrupt_instances=0, so CORRUPT_ONLY is unreachable. LIVE, CORRUPT and EMPTY instances are never attributed to
   station-days. A day whose only instance was LIVE or CORRUPT (an ambiguous read) lands as NO_CLEAN_INSTANCE, the same as the ~9% of
   station-days the venue never lists.
   Failure: nothing mis-counts N_cov, but the evidence doc cannot say how many dropped days were ambiguous rather than absent. S-1
   UNDERPOWERED could be a recorder-outage artefact and look like a listing artefact.
   Fix: report instance verdict counts per date range alongside the reason histogram. Either wire corrupt_instances from a cheap
   per-instance station-day list, or delete CORRUPT_ONLY from REASONS.

4. [MEDIUM] STOP S-5 fires on a bare point estimate with no sample-size guard (core:605).
   Failure: N_cov=12 with 0 qualifying gives C=0 < 0.05 and "STOP ... NO-GO pre-screen". It would normally also fire S-1, but the
   report does not say which STOP is the load-bearing one.
   Fix: print N_cov and the Clopper-Pearson upper 95% bound on C next to the S-5 line. S-5 fires only if S-1 does not fire, or both
   lines are shown with "S-5 evidence is n=N_cov" in plain words.

5. [LOW] n_eff_ub is not a strict upper bound. If the true rho is below 0.5, n_eff is higher. The code and docs label rho as assumed
   (core:18-21), which is fine. Add a sensitivity line n_eff at rho=0.25 and rho=0.75 to the report so Q1 sees the spread.

6. [LOW] The trade_id hash collapses genuine distinct fills with identical (ms, price, size, side), so counts are slightly low. Harmless
   for the "at least one qualifying buyer" bit that drives C; it matters only for the bucket counts. Note it in the evidence doc.

7. [LOW] parse_failed is OR-ed across instances (script:183). One failed successor instance voids a day whose prints another clean
   instance fully held. This is conservative (S-1 side), so it is not wrong, but report the count of such days. Also: L-31 republished
   instrument definitions are handled correctly by the dict keying, but no test pins it (test_maker_tape_census.py has none). Add one
   with a duplicated BinaryOption.

## Item 4 confirmation
require_firewall_clearance runs for every requested (station, day) in _plan_rows before any tape is opened (script:208-219). NYC is
refused, days above 10-13 are refused, and the sha256 is pinned. TradeTick filtering by admit_print happens before any append
(script:153). Pre-capture days are never admitted (read_days excludes window.start < capture start; classify returns PRE_TRADE_CAPTURE
without a tape). The only scope gap is finding 2.
