# S2-WP3 PMR review (prediction-market domain math)
Date: 2026-10-14. Commit 44562c03, worktree maker-s2-wp3. Spec v0.3 s3 (:69-136), plan r3 WP3, r4 delta (e).
Scope: scripts/analysis/maker_stage0_rule.py, tests/unit/test_maker_stage0_rule.py.
## Verdict: REQUEST_CHANGES (1 HIGH, cheap fix; remainder MED/LOW)

## HIGH
H1. NaN p_yes passes P_MIN and is eligible (more permissive than spec :125-127).
  File: maker_stage0_rule.py:135 (`1.0 - p < P_MIN - _EPS` is False for NaN, so no `continue`); :129 argmax over NaN is
  order-dependent, so the modal/adjacency exclusion is also unreliable. Unlike decide_bid (:81), select_rungs never
  calls _validate_p_no. No test covers it.
  Failure: a NaN or out-of-range model cell yields a selected rung; decide_bid would later raise, or the selection
  consumes a MAX_RUNGS slot and displaces a valid rung.
  Fix: validate every p_yes with _validate_p_no (raise) at the top of select_rungs, and add NaN/-0.1/1.1 tests.

## MED
M1. Fee theta is not validated (:56-67). theta<0 or NaN: negative theta raises b_max above spec (fee credit); NaN yields
  None (safe). Fix: require finite theta >= 0 in b_max/decide_bid and test it. The theta source is the caller
  (EVIDENCED_FEE_THETA=0.0695, hypothesis_ledger.py:204); no duplicate pin here, good. Spec treats the fee as the
  continuous theta*b*(1-b) (:138-140), and the code does the same; only b is quantised.
M2. forecast_gate (:108-114) accepts a negative age_ns (vector available_at in the future = lookahead) as fresh.
  The spec age = now - available_at assumes >= 0. Strict `>` at STALE_H matches :80 (test :100 pins the boundary).
  Fix: return "forecast_not_yet_available" for age_ns < 0, or document that the caller's value_at guarantees it.
M3. Ladder order is an unchecked precondition (:122, :133). Adjacency uses list position. The docstring states it and
  the tests use an ascending ladder, but nothing sorts or asserts it. A gap (unlisted rung) only shrinks distance,
  which is conservative; a descending or arbitrary dict silently mis-defines adjacency (permissive).
  Fix: take explicit ordered keys (or lower-edge values) and assert monotonicity; add a test that a shuffled mapping raises.
M4. P_MIN tolerance is inconsistent. select_rungs admits p_no >= 0.94-1e-9 (:135) but decide_bid refuses p_no < 0.94
  strictly (:82). A rung can be selected and then refused at the same instant (harmless: the bid is None), but the
  1e-9 slack is permissive vs the spec. Fix: compare in the same domain (round p_no to 1e-9 once, or use one helper).
M5. K1 determinism is not enforced by the module (:142-144). k1_rung is a pure selected[0]. The "first-ranked at the
  first attempt instant, held for the day" rule lives entirely in the WP4/5 caller. Ties break by ladder index
  (ascending), which is deterministic. Action: confirm a WP4/5 test pins the frozen K1 rung (not re-ranked per event).
  Also note selection filters on bid >= B_FLOOR at the attempt instant, so K1 may pick a rung other than the pure
  lowest-p_YES rung (spec-consistent: "both bids >= B_FLOOR").

## LOW / verified-correct
L1. Rounding: bid is computed in integer cents, so it is on-tick and rounded DOWN (largest cent under b_max): conservative.
  Inputs use round() (banker's) at :48; an off-grid book price could round up (a 0.755 best bid +1 gives 0.77). Tape
  prices are 1 cent, so this is theoretical; assert on-grid inputs if cheap.
L2. obs_cancel (:167-173): `>=` at the boundary and +1.8 F widening match :98-99. A lower_edge of -inf (lowest open
  rung) always cancels: conservative, costs bids on that rung only. Doc it, or skip the cancel when the edge is -inf.
L3. hard_cancel_ns (:151-154): 09:00 LST as UTC ns; std_offset_hours is signed east-positive (-5 gives 14:00Z, tested
  :171-172). The sign convention is undocumented in the docstring; add it. Integer-hour offsets only (fine for US stations).
L4. Verified OK: constants :21-27 equal spec :72-73; b_max largest cent satisfying b+fee <= p_no-E_MIN, capped at 0.80,
  None below 0.70; bid = min(b_max, best+1c, ask-1c); empty NO bid side drops the best+1c term (:88-89 matches :88);
  empty YES bid side drops the ask clamp; marketable-ask abstention is realised by the ask-1c clamp, then the floor.
  Own-order exclusion is a caller contract (docstring :76); the plan says the tape cannot contain it. STALE_H `>`;
  listed_in_time `<=` D-1 12:00Z (:123), UTC, None abstains; GTD min(...) incl. end of UTC booking day (:163, tested
  at exact midnight); MAX_RUNGS=2 slice; modal = argmax (first on tie).
L5. Not in module by design: permit_window_for_day / permit expiry arrive as args (no duplication); permit-binds-first
  is therefore a caller concern (WP4/5 must feed the 02:50Z-class expiry).

## Discrepancy table
| Item | Spec | Code | Class |
| NaN p_yes eligibility | n/a (must fail closed) | eligible | HIGH |
| theta<0 | theta>=0 implied | accepted | MED |
| age<0 | age>=0 implied | fresh | MED |
| P_MIN compare | strict < | eps in select only | MED |
| ladder order | position (implicit) | unchecked | MED |
| -inf lower edge | n/a | always cancels | LOW (conservative) |
