# S2-WP4 re-check of b2f769cc (over b8193821) -- prediction-market reviewer
Verdict: APPROVE (no CRITICAL/HIGH; 2 MEDIUM, 2 LOW to carry into WP6). Static read; tests not run
(plain pytest trips the egress import guard; use scripts/ci/run_tests_no_egress.sh).

## Per item
1. Truncation: FIXED. fill_pass.py:277-279 refuses only if asks_truncated and (no asks or 100-b >
   deepest displayed ask). level > max(ask) = our level lies beyond the censored tail (right
   direction: truncation drops the deep/high-ask end; a_gt sums p<level, a_eq p==level, both exact
   when level <= deepest). Bid-side-only: not refused; correct, best bid survives so no_ask holds.
2. Release: FIXED. events.py:183-184 DECIDE at shifted release+1 ns; run() applies staged vector only
   after the release-ts group, so the DECIDE sees the new vector; same-ts frames see the old one.
   - No-book skip (pass.py:266): hides a day only when a wanted rung never has ANY frame all day
     (first frame triggers a DEPTH decide). Old code counted it bid_bearing/guard_refused_only (STALE).
     Now it leaves the denominator = optimistic direction. See M1.
   - Repeated stale refusals (one per release/frame in a gap): inflate n_attempts/n_refused and shrink
     truncation_refused_share; guard_refused_only (n_eps==0) and every rung_trials_* rate (unique rungs)
     are unmoved. Old code did the same per frame. No rate moves. LOW (L1: share denominator).
   - Older frame at t0: legitimate. books[rung] is the last frame received at or before now (same-ts
     frames precede DECIDE); no later data. depth_ts_used now honest (old code wrote ts). No max-age
     on a quiet frame (L2), unchanged from before.
3. Stress rows: FIXED. _to_episode takes end/reason/vector from the stress Rest into *_stress fields.
4. rung_trials_attempted = unique rungs over all eps incl. refused-only and stress-only: correct,
   conservative denominator.
5. Cap: OK. slots = max - held - live computed after ends/replaces; rank order; refusals do not
   consume a slot; same in both passes. Cap only removes placements (never adds fills).
   rungs_ever_posted uncapped distinct count: report-only, no fill-rate path. A live lower-rank rung
   is not displaced by a newly higher-ranked one (selector's job).
6. Frames in an open gap now stale (pass.py:217-220), cleared only by a frame outside a gap: correct
   and conservative. Overlapping gaps are ref-counted (old pop-on-first-end ended gaps early).
7. Delta: bound enforced (assert_delta_within_bound). Docstring is honest. Acceptable, but M2.
8. Lower median: sorted[(n-1)//2] in integer cents, correct.

## Q9: does the rewrite credit a fill the old base path did not?
Only one place, and it is a deliberate, justified relaxation: truncated frames with level <= deepest
ask are no longer refused (old: any truncation refused), so those attempts are now placed and can fill.
Their A_gt/A_eq are exact, so no leak. Every other change is equal or stricter: gap-frame staleness,
ref-counted gaps, position cap, no-book skip (removes an attempt, not a fill), release decision uses
the new vector at +1 ns. Print/queue arithmetic (Q0, G, <=t0 guard, BUYER-only, gap block) is
byte-for-byte the old logic. The leak assert now runs with real depth_ts and on the fill path too.

## New findings
M1 (MED) fill_pass.py:266 and fill.py:169: a wanted rung with no frame all day is silently dropped
   (not attempt, not bid_bearing). Fix: count it (e.g. summary field n_no_book_wants / or treat as
   STALE_FRAME refusal without a Rest) so such days stay in the bid-bearing denominator; WP6 must
   report the count.
M2 (MED) fill.py docstring: delaying a release delays forecast-driven cancels (CANCEL_PMIN/STALE),
   so a rest can fill in the extra <=600 s that the real bot would have cancelled: optimistic for
   fills. Fix: WP6 reports delta=0 vs max-delta side by side and treats the delta-sensitive fill
   count as a bound, not a point; or mark fills occurring after an intended cancel.
L1 truncation_refused_share divides by attempts that include per-frame stale refusals; report it
   also per distinct (rung, bid) attempt.
L2 no max frame age on a quiet book (fill_pass.py:274); fine for Stage 0, state in WP6.
