# S1 r2 final — prediction-market-reviewer — 2026-10-12
Verdict: READY-WITH-NOTES — every r1 MAJOR is present in the r2 plan body and the rebuttals hold; the only residuals are wording and spec-v0.3 alignment (MINOR).

## Disposition check
| r1 review | # | r2 claims | verified? |
|---|---|---|---|
| architect | 1 MAJOR Depth10 | no Depth10 read at all | YES: §3.1 "Why no Depth10", WP1 converts only BinaryOption/QuoteTapeGap/VenueClockOffset/TradeTick |
| architect | 2 MAJOR gap reader | native convert + load_partitioned_quote_tape_gaps; coverage = alive span - gaps | YES: WP1 `covered_intervals` + script bullet; loader at quote_tape_gaps.py:86-106 and `_cleanup_work_catalog` replay_sufficiency_census.py:758 confirmed |
| architect | 3 MAJOR _load_stream | dedupe on trade_id, TRADE_PARSE_FAILURE, RED tests | YES: WP1 script bullets + tests `..counts_once`, `..parse_failure_refuses..` |
| architect | 4 MAJOR NO-leg rule / F2 | set-size-1, n>=2; F2 deleted; 28-fill pass | YES: WP2 `classify_trade_quantity_unit`; no F2 anywhere in body |
| architect | 5 MAJOR S-1/S-4 | extension named, route to Q1, Pass B required | YES: S-1, S-4, §3.2. Arithmetic re-checked: 8 dates x 1.78 = 14.2; 17 dates for 30; P(X<=2 | n=30,p=.2)=0.0442 |
| architect | 6-12 MINOR | net 58, PRE_TRADE_CAPTURE, PRE_FREEZE_END, first_seen_ns, feeReconciled, sha pin, NYC filter | YES, all in body. 14 listed = 5+4+2+3; 72-14=58; 58/5 = 11.6 d ~ 12 d |
| PM reviewer | 1 MAJOR eligibility flow | BUYER buckets, C, S-5; Depth10 conditions REBUTTED | YES; rebuttal is true in the STOP direction: any-rung C with p_yes >= 0.20 is a superset of what a tail-rung NO bid (b in [0.70,0.80]) can fill, so C < 0.05 is a safe stop. KILL-LIKELY is the only place looseness could mislead; it is labelled |
| PM reviewer | 2 MAJOR bare 25 | derived n_eff_ub >= 30, rho assumed | YES (§2.1) |
| PM reviewer | 3 MAJOR pre-capture | PRE_TRADE_CAPTURE excluded from denominators | YES (WP1 `classify`); window start D-1 12Z < 09-17 09Z gives D <= 09-17, matching spec first replayable day 09-18 |
| PM reviewer | 4 MAJOR resolver tsEvent | GET-/null tradeId/feeReconciled refused; +-5 s | YES (WP2 script). reports.py:1356-1360 is `ts_event=parse_rfc3339_nanos(transactTime)` - TRUE |
| PM reviewer | 5 MAJOR coincident print | unique candidate, size-blind selection; ">= 2 NO-leg" REBUTTED | YES; rebuttal sound: set-size-1 forces NO-leg evidence exactly when the answer is USD, and YES matches validly split CONTRACTS from USD |
| PM reviewer | 6-9 MINOR | SUMMED never counts; bucket + intent note; formula; NYC | YES, all in body (§5.3, WP2, WP1) |

## Spec v0.3 contradictions (plan line -> spec section)
1. Header line 10 says spec v0.2 -> now v0.3. MINOR, relabel.
2. §2.2 S-2 "§6.1 cannot run ... for the spec owner to rule on bracketing (Q5)" vs spec §6.0 / §9.3 ("resolved OR bracketed"; replay runs under both USD hypotheses, conservative governs). Spec has already ruled. S-2 should stop only when CONTRACTS is not excluded or the set is not the two USD hypotheses; a surviving {USD_NOTIONAL_YES, USD_NOTIONAL_TAKER} is a BRACKET, not a stop, and WP3 stays unflipped. MINOR (wording; WP2 already emits the surviving set).
3. §10 Q5 and §12 items 1-7 are now absorbed into v0.3 (§6.1 inversion, §6.0 B-3 sentence, denominator, three hypotheses, `:225-231`). Delete or mark closed. MINOR.
4. Maker window `[D-1 12:00Z, D 09:00 LST)` equals the CANCEL_LST backstop, but spec §3 says STALE_H = 8 usually binds first (about 09-10Z on D), i.e. up to ~8 h earlier than 09:00 LST for LAX/SFO. Effect: C is looser upward (safe for S-5) while coverage/LONG_HOLE gates can drop a day for an interval where no bid would rest (conservative for S-1). Add one sentence stating this; S2 owns the true schedule. MINOR.

## Residual items
- [MINOR] WP1: state explicitly that prints are filtered to MAKER_STATIONS x declared climate days BEFORE any bucketing/count and that NYC and out-of-range slugs are discarded unrecorded. Instances hold all five ladders and the conversion necessarily touches NYC bytes and D+1 slugs; the firewall guard is only specified at `classify`. Add a RED test (`test_nyc_prints_never_reach_a_count`).
- [MINOR] WP2: DurableFillRecord is CUMULATIVE per venue order (client.py:933-957); `tsEvent`/`tradeId` of a multi-clip order reflect the last update. qty-1 IOC makes multi-clip unlikely; state that a multi-print order is routed to SUMMED/not-counted.
- [MINOR] Alive span from VenueClockOffset (one per 200 quote frames) may under-state the span on a quiet overnight feed, dropping days via LOW_COVERAGE. Conservative, but the evidence doc should report how many days failed on tail-span only.
- [MINOR] `TradeTick` through `default_convert` is UNVERIFIED (plan says so, fallback named); the first RED fixture must prove it before the sidecar is built on it.
- No BLOCKER/MAJOR residuals.

## Invariants
- Nautilus immutable / native types only: PASS
- allow_short False, no operator caps assigned, live enablement and BREEZY_ORDERS_ENABLED untouched: PASS
- No frozen PREREG edited, no date moved: PASS
- Stage 0 output exploratory only: PASS
- NO-TRADE ruling in force: PASS
- Zero network, exec sqlite mode=ro, capture root read-only: PASS
- RA-13 B-3: PASS provided WP0 is committed before any post-09-25 read and the pre-count station/day filter is added (MINOR above)
- Simplest path: PASS (separate sidecar justified by verified AUD-09a window/cache/schema facts; no Depth10)
- Exact-set / NO-SEND pins widened never relaxed; stricter unit pin: PASS
