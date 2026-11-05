# RULING_MAKER_sharp_v1_live_small_2026-10-21

Status: **DRAFT** (becomes FINAL in the ARM commit; PMR + security review before then). Family `pm_us_no_maker_sharp_v1`.

## Authority
The operator, 2026-10-21 ≈17:10Z, verbatim: "You are the expert. Proceed with what you need to, to arm the trading bot to begin trading." Earlier the same day: "strictly prioritize designing and backtesting strategies until observing a winning strategy. Once that is observed, promote it and set the bot live." Decision owner per the operator's standing pre-authorization; the two operator caps are reused unchanged and never assigned by the build.

## Decision
Arm a NEW family, live-small, quantity 1: resting BUY NO, GTD limit, non-post-only, far rungs, HIGH ladders only, stations LAX/MDW/MIA/SFO. Decision rule = the Stage 0 maker rule ported unchanged (`src/breezy/strategy/no_ladder_maker/`, equivalence- and parity-tested) under the frozen `sharp` parameters: P_MIN 0.97, E_MIN 0.04, B_FLOOR 0.75, B_CAP 0.89, MAX_RUNGS 2, no listing abstention. Live fills are the out-of-sample test. No taker family is armed (every taker variant lost or could not fill in replay).

## Evidence and its limits (disclosures)
- Design tape (maker stations ≤ 2026-10-13, 10-01 excluded): 17 fills, 17 wins, mean per-fill X +0.115, n_eff 13.5, lower bound +0.099. Verdict UNDERPOWERED by the pre-stated floor (n_eff < 30). This is NOT a demonstrated edge.
- `sharp` was chosen after six arms on the same 92 station-days (selection artefact).
- 17/17: one-sided 95% lower bound on the win rate 0.84 < w* ≈ 0.875 — zero edge is NOT excluded.
- 9 of 17 fills were on late-listed station-days (abstention departure from the spec).
- False-stop probability of the harm stop ≈ 32% over 40 fills at a true win rate of 0.95.
- Robustness: Δ ±600 s reruns 18/18, Jaccard 0.84, no new loss; MAX_RUNGS 1 gives 5/17 → MAX_RUNGS 2 shipped.
- Leakage audit: `docs/evidence/MAKER_sharp_v1_leakage_audit_2026-10-21.md` sha256 f8519d87d14da392bddf119ed199db1f981ebc8a94e1aae835b776e984fcb776 — no look-ahead found.
- Design-time departures: Δ=0 latency, maker fee assumed = taker θ, census listing instant.
- R10 erratum: the D 09:00 LST hard cancel falls after the posting window and never binds (plan_r3_delta R10-ERRATUM).

## HARM STOP (pre-declared; verbatim from plan r2 §D5; fixed before the first fill)
> HARM STOP, family pm_us_no_maker_sharp_v1. Settled fill = a filled qty-1 BUY NO resolved by venue settlement, cross-checked against the CLI final; a fill with unresolved, missing or mismatched settlement counts as a LOSS until resolved (fail closed). cost_i = posted bid + max(venue-reported fee, taker θ=0.0695 round-half-even cent fee), slip 0. W wins, L losses (two NO legs on one ladder-day lose at most once; losses count distinct station-days), n = W+L, w* = mean(cost_i). Evaluated after every settlement batch and daily after truth-fetch. FAIL (entries vetoed, resting orders cancelled, family halted) if ANY: (T1) L ≥ 3; (T2) n ≥ 3 and the one-sided 95% Clopper–Pearson upper bound on W/n < w*; (T3) n ≥ 4 and cumulative realised net PnL after fees ≤ −w*. PASS otherwise; PASS with zero fills; absent or stale (> 26 h) `latest.json` vetoes entries (fail closed). Restart needs a new dated ruling citing the loss evidence. A FAIL is not evidence of no edge; a PASS at n < 30 is not evidence of edge.
Implementation addendum (B6/D1 reviews): the harm stop HOLDs (never PASS) while any family fill is resolver-booked (`GET-` trade id) or any family intent is AMBIGUOUS; it never filters on `fee_reconciled`.
Disclosed amendments (D1 PMR review, 2026-10-22), each more conservative than or clarifying the quote above:
- Counting unit: W, L and n are all counted in distinct station-days. A station-day is W only if every fill on it won; a day with any non-WIN fill is an L day. w* and cumulative PnL remain per fill. The T3 gate n ≥ 4 is on station-days, so T3 can arm one fill later on two-leg days.
- Fee floor: the modelled taker fee in cost_i is floored at 0.01 (from the same delta's fee-booking line, r2 l.27); it binds at bids ≥ 0.93.
- Staleness: a `latest.json` older than 26 h vetoes entries unconditionally for this family (the probe's strict mode; the FQ alert-delivered grace does not apply).
- Settlement timing (clarification of "unresolved ... counts as a LOSS until resolved"): a fill whose station-day D has not passed its settlement deadline (48 h after the end of local day D) is PENDING and is excluded from W, L, n, w* and PnL. After the deadline, an unresolved, missing or mismatched settlement counts as a LOSS (fail closed). Without this, three same-day fills would trip the sticky FAIL before any market could settle.
- Cadence: the producer runs on its own daily timer after the truth fetch; it is not triggered after every settlement batch.

## Safety floors (unchanged, binding)
`allow_short = False`; operator caps enforced per order by `DailySpendLedger`; permit gate (TTL 10 h); NO-SEND firewall; every safety, settlement and contract test; manual or foreign open orders refuse arming (own-order rule exempts only ledger-bound rests with registered exposure and no unconfirmed cancel); GTD backstop ≤ permit expiry; venue-verified flags flip only on B2 positive-control evidence.

## Preconditions to the ARM commit (checked, cited by sha/log in the FINAL version)
1. S2 evidence commit landed; A0′ pin-retire ruling FINAL; C7 byte pin re-baselined in one reviewed commit immediately before the B-chain merge.
2. B-chain (B1–B7 + review fixes) merged `--no-ff`; full gate EXIT=0 read before push.
3. B2 positive control evidence committed; `GTD_EXPIRY_VERIFIED`, `SLUG_SCOPED_CANCEL_ALL_VERIFIED`, `MAKER_COMMISSION_SIGN_VERIFIED` flipped only as the evidence supports.
4. C2 wiring + C3 parity + D1 producer merged; harm-stop `latest.json` PASS exists and is fresh.
5. Supervisor restarted after the WP2 enum (`ACCEPTED_RESTING`, `BOOT_SWEEP_RESTING_NO_FILL` admitted).
6. Slot table empty; no unbound open orders on the account (unfiltered GET); no study depends on FQ shadow capture.
7. A venue-settlement source writes `maker_venue_settlement/v1` for every family slug (final markets only, fetch time stamped), cross-checked against the CLI final; without it every fill is a LOSS and the sticky FAIL trips at the third station-day.
8. The manifest's `d0_climate_day` is set to the first legitimately tradable ladder day in the ARM commit (the build placeholder 2026-10-28 refused by test).
9. One offline replay of a full, valued activities page through `parse_position_resolutions` reports `unreadable == 0` (B2 captures match every required path and enum, but record no values).
10. Shadow day passed (zero `post_order` calls; would-be GTD orders logged; fee drift AGREE; Depth10 coverage = ladder count).

## Rollback
Family halt + cancel while armed → unfiltered GET shows none of our slugs → `git revert` of the ARM commit + restore the orders-off drop-in → daemon-reload + supervisor restart. Max orphan lifetime if the node dies uncleanly = GTD ≤ permit expiry.

## Evidence (filled at FINAL)
ARM commit <ARM_SHA>; gate log <GATE_LOG> EXIT=<GATE_EXIT>; B2 evidence docs/evidence/b2/maker_positive_control_20261022T075159Z.json (PASS S-1/S-2/S-6, 2026-10-22 07:52Z) sha <B2_SHA>; harm-stop latest.json sha <HS_SHA>; S2 evidence commit <S2_SHA>.
