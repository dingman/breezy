# S1-WP2 blind review — prediction-market-reviewer — 2026-10-12

Verdict: APPROVE (no CRITICAL, no HIGH; 3 MEDIUM and 3 LOW to fix or record before the run). Domain math only.
Scope: `src/breezy/analysis/trade_quantity_unit.py`, `scripts/analysis/trade_quantity_unit_crosscheck.py`, tests. I read
the code and the plan/spec/declaration. I did not execute the tests (pytest output was not captured here).

## Convention check (item 1)
- Convention used: print `side` = aggressor on the YES instrument, `price` = YES frame. A NO fill at cost c is a taker
  SELL of YES at 1-c (SELL/BUY_SHORT), so the candidate is SELLER at 1-c (`_required_side` / `_target_yes_price`,
  :206-212). A YES fill is BUYER at c. This matches plan §5.2 "Taker-side check".
- No conflict with spec §6.1. §6.1 is the maker side: a resting NO bid fills on a YES BUYER print at p_yes >= 1-b. The
  taker side we were on is the mirror image: we cross the YES bid with a SELLER print. Code follows the plan, which is
  correct for WP2. The spec governs S2. WP2 must not be reused as S2's fill predicate.
- Residual risk: the print `side` field comes from the venue's `taker.side`. If the venue reports it in the NO frame for
  a NO buy, every NO fill reads CONTRADICTED. That fails closed (S-3 STOP), so it is not a wrong verdict.

## Size formulas (item 2)
- `predicted_size` (:236): CONTRACTS = fill_qty; USD_NOTIONAL_YES = print_price_yes * fill_qty (with
  print_price_yes = 1-c on a NO leg); USD_NOTIONAL_TAKER = fill_cost. This equals plan r3 line 257.
- `parsing.py:225-231` and :950 define NO hypotheses. They only pin the constant UNRESOLVED and say "contracts vs
  dollars". The YES/TAKER split exists only in the plan, so the plan is the sole authority. No off-by-side error found.
  A NO fill at 0.12 predicts (1, 0.88, 0.12). A YES fill predicts (1, c, c).
- Consequence (MEDIUM, 1): only 2 of 28 kept fills are NO legs (MIA 09-21, MDW 09-22). Only those can split YES from
  TAKER. If either has no unique print, the likely verdict is BRACKETED_USD, which is the designed conservative
  outcome, not a failure. Say so in the evidence doc so it is not read as inconclusive.

## Tolerances (item 3)
- Price and size use exact Decimal equality. The time window is +-5 s (:69). There is no tick or rounding tolerance.
- Exact price equality is justified for qty=1 fills at 0.01 ticks. It is untested for rounding of the venue's USD size
  (e.g. 0.88 vs 0.8800 compares equal in Decimal, but a venue rounding to cents would not).
- MEDIUM 2, `trade_quantity_unit.py:124`: `unit_cost = cost/qty` is an inexact Decimal division for qty>1 (e.g.
  0.35/3). Such a cumulative multi-clip average never equals a tick price, so the fill silently becomes NO_PRINT. That
  fill is excluded and can never be an anti-candidate. Fix: skip qty>1 fills explicitly with a stated reason, or test
  candidates at tick-quantised prices. Also guard qty<=0 against ZeroDivisionError/InvalidOperation (LOW).
- MEDIUM 3, :69, :214-226: the window is wide and a candidate need only be unique. If our own print is missing (recorder
  gap) or was collapsed by the derived trade-id dedupe, another taker's same-side, same-price print within 5 s counts.
  A small size such as 1 would then register as CONTRACTS. Two such coincidences are needed for a terminal verdict, but a
  quiet 0.03-0.15 rung makes small sizes likely. Fix: emit |ts_print - ts_fill| per candidate in the JSON and add a gate
  that a counted match lies within an unambiguous tight offset (e.g. the smallest |dt| <= 1 s), else it is not counted.

## Verdict logic (item 4)
- `classify_trade_quantity_unit` (:298): needs >= 2 counted matches. The surviving set is the intersection. An empty set
  gives UNRESOLVED (contradiction). A singleton gives that hypothesis. Exactly {YES, TAKER} gives BRACKETED_USD. Any other
  set, including {CONTRACTS, x}, gives UNRESOLVED. This matches plan r3 lines 261-264 and S-2 (script `s2` = UNRESOLVED
  only; BRACKETED_USD is not a stop).
- Counted means candidate_count == 1 and not summed. A single ambiguous print cannot reach a terminal verdict, and a lone
  counted match returns UNRESOLVED with fewer than 2. L-52 holds, apart from the coincidence risk in finding 3.
- SUMMED routing: a single candidate with qty>1 that is inconsistent is routed summed (:253+ `match_fill`), so it never
  counts. A multi-candidate match with no consistent single print is routed summed only when the sum is consistent.
  Otherwise it is an uncounted plain match. Neither can contradict nor confirm. OK.
- S-3: inversion is CONTRADICTED only when there are 0 candidates and >= 1 anti-candidate. LOW 1: an anti-candidate for a
  NO fill is any YES print at the raw cost price (0.12) in the window. An unrelated trader's print at 0.12 plus a missing
  own print triggers a false S-3. This fails closed; just note it in the doc.

## Pinned list (item 5)
- Keep rules in `keep_decision` (:176+) and the 6 excluded rows agree: null tradeId, GET- prefix and 4 pre-capture rows
  each hit a rule. BUY-only is not exercised by the pin (all 28 are BUY), which is fine.
- Station and day come from `bucket_facts_from_instrument_id` (L-56), and an unresolved instrument gives "UNRESOLVED",
  which is out of scope. The pin check compares trade ids only (script), not leg, cost or ts. LOW 2: also compare
  (leg, cost, ts) to the declaration table so a re-keyed fill cannot pass.
- LOW 3: the NO-fill `cumulative_cost` frame is assumed to be the NO price paid (0.12). The memory says price semantics
  are undecidable from preview. If it were the YES wire price, the result would be S-3 or NO_PRINT (fail closed). State
  the assumption in the evidence doc and print the first NO fill's raw record.

## Required before the run
Items 2 and 3 above (MEDIUM 2 and 3); record MEDIUM 1 in the evidence doc. No sizing, fee, PnL or lookahead math is
touched. Fills before 09-25 pass the firewall as PRE_FREEZE and the 25 later fills are covered by the declaration hash.
