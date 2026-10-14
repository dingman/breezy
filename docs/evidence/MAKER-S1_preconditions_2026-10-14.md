# MAKER-S1 preconditions evidence (WP4)

| Field | Value |
|---|---|
| Status | FINAL |
| Run date | 2026-10-14 (census unit `breezy-maker-s1-census` launched 2026-10-14T10:02:06Z, EXIT=0; TQU unit `breezy-maker-s1-tqu`, EXIT=0) |
| Plan | `docs/plans/backlog/MAKER_2026-10-12/S1_preconditions_plan_r3.md` (r3; §2.1, §2.2, WP4) |
| Spec | `docs/strategies/SPEC_pm_us_no_ladder_maker_2026-10-12.md` v0.3 |
| Unit of analysis | station-day (LAX, MDW, MIA, SFO; climate days 2026-08-30..2026-10-13); cluster = climate date |
| Code sha (census) | f2c0f190 (`census_provenance.git_sha`; HEAD at doc time f2c0f190) |
| Declaration sha256 | 38663caad38e455ab1512ca91a049f97d31c2dcfb1477c42db02ceca407abbc6 (matches `docs/evidence/RULING_MAKER-S1_SEARCH_declaration_2026-10-12.md`) |

## 1. Outcome

**no pre-registered STOP fired; S2 proceeds; KILL-LIKELY flag: not set.**

## 2. Provenance

| File (derived dir) | sha256 | Rows / content |
|---|---|---|
| `censused_days.jsonl` | bce597f2bedcf345bceadfcc50030aeac89d64e2754b319378a57d9b4ea91a71 | 180 rows (4 stations x 45 days) |
| `prints.jsonl` | 10de1f8f169b05ca248eab1b163125581457d21d848fafd4402fdad03c526b5f | 253,253 rows (BUYER 127,850; SELLER 125,403; NO_AGGRESSOR 0) |
| `trade_quantity_unit.json` | 6459e9f6384af85af69efca1f70f7a8e8155e343fc18551d85c94d1d9afd4835 | 28 fills, 6 refused |
| `census_run.log` | c513285ea03c45fa373dcfc6c306b2f1e2ff0d9e9205288a5304d3f690cef1d5 | 83 instances (CLEAN 72, CORRUPT 4 unread, EMPTY 6, LIVE 1 counted never read); EXIT=0 |
| `tqu_run.log` | 418a5c17f33c70e99b0cc0a07fce69191489cfedc94164bfa903785777c5bd4b | `EXIT=0` |

Quoted from `census_run.log` (`instances_read` list of 72 ids elided; full line in that file):

```
census_provenance: {"constants": {"CANCEL_LST_HOUR": 9, "COVERAGE_MIN": 0.9, "LONGEST_HOLE_MAX_MIN": 60, "NBP_LAG_UB_H": 2, "RHO_ASSUMED": 0.5, "STALE_H": 8, "TRADE_CAPTURE_START_NS": 1789635600000000000}, "declaration_sha256": "38663caad38e455ab1512ca91a049f97d31c2dcfb1477c42db02ceca407abbc6", "git_sha": "f2c0f19085bf9e2445bb31c6a5e721078af87eb0", "instances": {"CLEAN": 72, "CORRUPT": 4, "EMPTY": 6, "LIVE": 1}, "instances_read": [72 ids elided], "range": ["2026-08-30", "2026-10-13"], "stations": "LAX,MDW,MIA,SFO"}
census_summary: {"C": 0.9895833333333334, "C_030": 0.9895833333333334, "D_cov": 24, "N_cov": 96, "n_eff_ub": 38.4, "prints_skipped_no_aggressor": 0, "prints_written": 253253, "reasons": {"COVERED": 96, "LONG_HOLE": 4, "LOW_COVERAGE": 4, "PRE_TRADE_CAPTURE": 76}, "rho": "0.5 (assumed, not measured)", "rows_discarded_out_of_scope": 117200, "tail_span_only_days": 4}
INFO bidlive: {"C_bidlive": 0.9711538461538461, "D_cov_bidlive": 26, "N_cov_bidlive": 104, "gates_no_stop": true, "n_eff_ub_bidlive": 41.6, "window": "[D-1 16:50Z, D 02:50Z) within the plan window (spec section 3)"}
```

## 3. Headline numbers

| Quantity | Value | Basis |
|---|---|---|
| N_cov | 96 | COVERED station-days |
| D_cov | 24 | distinct covered climate dates (09-18..10-13 less 09-28 and 09-29) |
| n_eff_ub | 38.4 | sum of m_d/(1+(m_d-1)·ρ) = 24 × 4/2.5; **ρ = 0.5 assumed, not measured** |
| C | 0.98958 (95/96) | covered station-days with >= 1 YES BUYER print at p_yes >= 0.20 in the maker window / N_cov |
| C_030 | 0.98958 (95/96) | same at p_yes >= 0.30 (report only) |
| ρ sensitivity | threshold ρ = 0.733 | S-1 would fire only if ρ > 0.733 (n_eff_ub = 96/(1+3ρ)); not measured |

## 4. Window constants and which bound binds

| Constant | Value | Source |
|---|---|---|
| Window start | D-1 12:00Z (listing line) | plan §3.1 |
| Window end | min(D 01:00Z + STALE_H 8 h + NBP_LAG_UB_H 2 h, D CANCEL_LST 09:00 LST) = min(D 11:00Z, cancel) | plan §3.1, provenance |
| CANCEL_LST cut-off (UTC) | MIA 14:00Z, MDW 15:00Z, LAX 17:00Z, SFO 17:00Z | standard offsets |
| Binding end bound | **STALE_DERIVED (D 11:00Z) for all 104 station-days**; CANCEL_LST never binds | earliest cancel (MIA 14Z) is later |
| COVERAGE_MIN / LONGEST_HOLE_MAX_MIN | 0.90 / 60 min | provenance |
| RHO_ASSUMED | 0.5 (assumed, not measured) | provenance |
| TRADE_CAPTURE_START_NS | 1789635600000000000 = 2026-09-17T09:00:00Z | provenance |

## 5. Per-station table (covered station-days)

| Station | N_cov | D_cov | C num | C | C_030 num | C_030 | bid-live C num/N | BUYER prints (in window) | SELLER prints | rungs with qualifying BUYER |
|---|---|---|---|---|---|---|---|---|---|---|
| LAX | 24 | 24 | 24 | 1.0000 | 24 | 1.0000 | 26/26 | 16407 | 23872 | 78 |
| MDW | 24 | 24 | 24 | 1.0000 | 24 | 1.0000 | 25/26 | 9777 | 10880 | 77 |
| MIA | 24 | 24 | 23 | 0.9583 | 23 | 0.9583 | 25/26 | 9489 | 7870 | 70 |
| SFO | 24 | 24 | 24 | 1.0000 | 24 | 1.0000 | 25/26 | 6596 | 11219 | 76 |
| **All** | 96 | 24 | 95 | 0.98958 | 95 | 0.98958 | 101/104 | 42269 | 53841 | 301 |

The one covered station-day without a qualifying print is **MIA 2026-09-18** (5 prints, one BUYER at p_yes < 0.10, coverage 0.997). It is the only C-reducing day.

## 6. BUYER prints by YES-price bucket (covered station-days, maker window)

| Station | [0.00,0.10) | [0.10,0.20) | [0.20,0.30) | [0.30,1.01) | Total |
|---|---|---|---|---|---|
| LAX | 4353 | 3013 | 2713 | 6328 | 16407 |
| MDW | 1765 | 1527 | 1627 | 4858 | 9777 |
| MIA | 2217 | 1946 | 1440 | 3886 | 9489 |
| SFO | 911 | 1527 | 1927 | 2231 | 6596 |
| All | 9246 | 8013 | 7707 | 17303 | 42269 |

## 7. Rows by reason and firewall class

| Reason | LAX | MDW | MIA | SFO | Total | Firewall class |
|---|---|---|---|---|---|---|
| COVERED | 24 | 24 | 24 | 24 | 96 | PRE_FREEZE 32 / SEARCH_DECLARED 64 |
| LONG_HOLE | 1 | 1 | 1 | 1 | 4 | SEARCH_DECLARED 4 |
| LOW_COVERAGE | 1 | 1 | 1 | 1 | 4 | SEARCH_DECLARED 4 |
| PRE_TRADE_CAPTURE | 19 | 19 | 19 | 19 | 76 | PRE_FREEZE 76 (not read) |

Non-covered rows (all on 2026-09-28 and 2026-09-29):

| Station | Day | Reason | Coverage | Longest hole (min) | tail_span_only | CORRUPT unread |
|---|---|---|---|---|---|---|
| LAX | 2026-09-28 | LONG_HOLE | 0.913 | 119 | true | 1 |
| LAX | 2026-09-29 | LOW_COVERAGE | 0.853 | 201 | false | 1 |
| MDW | 2026-09-28 | LONG_HOLE | 0.913 | 119 | true | 1 |
| MDW | 2026-09-29 | LOW_COVERAGE | 0.853 | 201 | false | 1 |
| MIA | 2026-09-28 | LONG_HOLE | 0.913 | 119 | true | 1 |
| MIA | 2026-09-29 | LOW_COVERAGE | 0.853 | 201 | false | 1 |
| SFO | 2026-09-28 | LONG_HOLE | 0.913 | 119 | true | 1 |
| SFO | 2026-09-29 | LOW_COVERAGE | 0.853 | 201 | false | 1 |

Days failed on tail span only: **4** (the four LONG_HOLE rows on 2026-09-28, one per station; flag as emitted by the script).

## 8. first_seen_ns late-listing diagnostic

- 104 station-days carry `first_seen_ns` (96 covered plus 8 non-covered). It is the earliest `BinaryOption.ts_init` the recorder saw, an upper bound on listing time, not a listing timestamp.
- **Late (first_seen after window start D-1 12:00Z): 44**, all between +3.00 h and +3.36 h; none after window end. 60 precede the window start (between -2.25 h and -1.75 h).

## 9. Independent re-derivation from prints.jsonl

- Streamed all 253,253 rows: 0 duplicate `trade_id`, 0 unparsed instrument ids, sides BUYER/SELLER only, 104 station-day keys (26 days x 4).
- Re-derived each station-day bucket vector with the same window and edges: **every covered station-day and every bid-live station-day reproduces exactly**. The 8 non-covered rows carry zero counts in the script output; their 7,450 in-window prints are not counted.

## 10. TRADE_QUANTITY_UNIT (WP2)

- Verdict **CONTRACTS**; surviving set {CONTRACTS}; reason: "25 counted matches leave only CONTRACTS"; counted 25 of 28; `s2_stop` false; `s3_stop` false; `duplicate_prints` 0.
- Summed rows: **none** (0 of 28 marked SUMMED).

Per-fill match table (all 28 kept create-path fills; `counted` = unique candidate in ±5 s window):

| # | Station | Climate day | Leg | Cost | Qty | Cands | Anti | Counted | Inversion | Consistent | Venue trade id |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | MIA | 2026-09-21 | NO | 0.1200 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CMRYWHC1AW1E |
| 2 | SFO | 2026-09-21 | YES | 0.3500 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CMSVQ19VGW1E |
| 3 | MDW | 2026-09-22 | NO | 0.1200 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CNCE55N1WW1E |
| 4 | LAX | 2026-10-02 | YES | 0.2300 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CV44TMZW4YHR |
| 5 | LAX | 2026-10-02 | YES | 0.0800 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CV44TXW6JYHR |
| 6 | MDW | 2026-10-02 | YES | 0.0300 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CV44V8DE2YHR |
| 7 | MDW | 2026-10-02 | YES | 0.0700 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CV44VJNC8YHR |
| 8 | MDW | 2026-10-02 | YES | 0.2300 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CV56FW6R4YHR |
| 9 | MIA | 2026-10-03 | YES | 0.4100 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CVSE930Y2YHR |
| 10 | LAX | 2026-10-03 | YES | 0.0500 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CVSE937HRYHR |
| 11 | LAX | 2026-10-03 | YES | 0.1500 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CVWEANWH8YHR |
| 12 | SFO | 2026-10-03 | YES | 0.0500 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CVX115N56YHR |
| 13 | SFO | 2026-10-03 | YES | 0.1500 | 1 | 1 | 1 | yes | HOLDS | CONTRACTS | CW0GJ0J0YYHR |
| 14 | MIA | 2026-10-03 | YES | 0.1100 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CW1EK169WYHR |
| 15 | LAX | 2026-10-04 | YES | 0.1500 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CWE1N7CA2YHR |
| 16 | MDW | 2026-10-04 | YES | 0.2000 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CWE25PN3EYHR |
| 17 | SFO | 2026-10-04 | YES | 0.0900 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CWE3HZTJ2YHR |
| 18 | LAX | 2026-10-04 | YES | 0.1500 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CWF9AGYQCYHR |
| 19 | MIA | 2026-10-05 | YES | 0.4800 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CX2MG6YM2YHR |
| 20 | MDW | 2026-10-05 | YES | 0.0700 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CX2MJZBNPYHR |
| 21 | MDW | 2026-10-05 | YES | 0.0300 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CX2MKE7R4YHR |
| 22 | LAX | 2026-10-05 | YES | 0.6400 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CX2MTHFKGYHR |
| 23 | MIA | 2026-10-05 | YES | 0.1100 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CX5MPF3JEYHR |
| 24 | SFO | 2026-10-06 | YES | 0.1000 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CXQ7T822YYHR |
| 25 | MDW | 2026-10-06 | YES | 0.0300 | 1 | 2 | 0 | no | HOLDS | n/a (candidate_count 2) | CXQ7WGS7GYHR |
| 26 | MDW | 2026-10-06 | YES | 0.0700 | 1 | 2 | 0 | no | HOLDS | n/a (candidate_count 2) | CXQ7ZD7NYYHR |
| 27 | LAX | 2026-10-06 | YES | 0.1400 | 1 | 2 | 0 | no | HOLDS | n/a (candidate_count 2) | CXQ801VGYYHR |
| 28 | SFO | 2026-10-06 | YES | 0.1500 | 1 | 1 | 0 | yes | HOLDS | CONTRACTS | CXSH6TQ0AYHR |

Refused (6, plan §6 WP2 list; all carry reason `PRE_CAPTURE`, all with ts_event before 2026-09-17T09:00Z):

| # | ts_event (UTC) | Venue order | trade_id | Reason |
|---|---|---|---|---|
| 1 | 2026-09-12T02:23Z | CEBPX0EVTTMX | None | PRE_CAPTURE |
| 2 | 2026-09-13T17:03Z | CFJ485874TMM | GET-CFJ485874TMM | PRE_CAPTURE |
| 3 | 2026-09-15T18:00Z | CGW2XWZQRVBA | CGW7YF5SEVAY | PRE_CAPTURE |
| 4 | 2026-09-15T18:12Z | CGW8DJ23PVB2 | CGWDJA68EVAY | PRE_CAPTURE |
| 5 | 2026-09-15T18:23Z | CGWDCNJGEVB5 | CGWJPXEMPVAY | PRE_CAPTURE |
| 6 | 2026-09-15T20:12Z | CGY02FK3PVB7 | CGY4D3D4JVAY | PRE_CAPTURE |

## 11. YES→NO inversion (spec §5.2 / §6.1)

- HOLDS 28/28; CONTRADICTED 0; NO_PRINT 0. S-3 not triggered. One fill has an anti-candidate (SFO 2026-10-03 YES 0.15) and still HOLDS because its candidate count is 1.

## 12. Net forfeiture (post-freeze station-days read)

- Station-days read post-freeze (firewall class SEARCH_DECLARED): **72** = 18 days (09-26..10-13) x 4 stations (64 COVERED + 8 non-covered).
- Already SEARCH per plan §3.2 / WP0 §3: **14** (LAX 10-02..10-06 x5; MDW 10-02, 10-04, 10-05, 10-06; MIA 10-03, 10-05; SFO 10-03, 10-04, 10-06). All 14 lie inside the 72.
- **Requested arithmetic: 72 - 14 = 58 net station-days.**
- **Open discrepancy:** WP0 §3 declares the net cost as **72**, crediting none of the 14, because the exit-window study read of their Depth10 is not evidenced (they appear as `excluded fill` entries). The 58 figure is therefore conditional on a later audit that proves the 14 were read. This doc does not verify the exit-window files and does not credit them.

## 13. STOP and flag evaluation

| Rule | Threshold | Observed | Result |
|---|---|---|---|
| S-1 UNDERPOWERED | n_eff_ub < 30 | 38.4 | not fired |
| S-2 unit | only UNRESOLVED stops | CONTRACTS | not fired |
| S-3 premise break | CONTRADICTED inversion | 0 | not fired |
| S-4 firewall | WP0 declaration sha pinned and matched | 38663caa... matched | not fired |
| S-5 fillability ceiling | C < 0.05 | 0.98958 | not fired |
| KILL-LIKELY flag | 0.05 <= C < 0.10 | 0.98958 | not set |

## 14. §6.9 power line (plan §2.1, reported, not gated by S1)

At p_YES <= 0.06 per bid, 10 expected losses need >= 167 fills, above any pre-freeze plus declared sample, so Stage 0 can likely emit only the two non-PASS verdict labels (elided here by the binding wording rule), never PASS (§7 g9). Not computed by this census.

## 15. Bid-live vs plan-window comparison

| Quantity | Plan window | Bid-live window (REPORT-ONLY, handed to S2) |
|---|---|---|
| Window | [D-1 12:00Z, D 11:00Z) (23 h) | [D-1 16:50Z, D 02:50Z) (10 h) |
| N_cov / D_cov | 96 / 24 | 104 / 26 |
| C | 95/96 = 0.98958 | 101/104 = 0.97115 |
| n_eff_ub | 38.4 | 41.6 (ρ = 0.5 assumed) |
| Covered 09-28 and 09-29 | no (holes) | yes (8 station-days) |

## 16. NO_AGGRESSOR skip count

`prints_skipped_no_aggressor` = 0 (summary); `prints.jsonl` contains no NO_AGGRESSOR side. Seller prints in covered station-days: 53,841.

## 17. Caveats

- **instances_corrupt_unread lower bound:** 4 CORRUPT instances were not read. N_cov, D_cov and n_eff_ub are therefore lower bounds on what the tape could support. The unread-corrupt tally (8 station-days) falls only on 09-28 and 09-29, the two non-covered days, so their failure is not established as tape absence. C has no known bound direction. The tally of 8 is per station-day, not an instance count.
- **Unique-candidate matching** (3 uncounted fills have two candidate prints: MDW 10-06 x2, LAX 10-06): a fill matches only prints with the same side, price and time (±5 s), never size. A match counts only when exactly one candidate exists, which is a window-local uniqueness test, not a global one. A true print outside the window would be missed; a wrong unique print would be counted. All 25 counted matches are qty 1 with print size 1.00, so the test excludes USD hypotheses on size but cannot test fractional or multi-contract sizes.
- **ρ = 0.5 is assumed, not measured.** n_eff_ub is sensitive to it (threshold 0.733, §3).
- **Refusal labels:** all six refusals carry `PRE_CAPTURE`, which precedes the null-tradeId and `GET-` checks. Those two are also pre-capture, so the label hides nothing material, but the precedence is not evident in the JSON.

## 18. Open items for the coordinator

1. Net forfeiture: 72 (WP0 declared) vs 58 (requested arithmetic). Resolve by audit of the exit-window Depth10 read; do not credit until evidenced.
2. ρ is assumed; a measured within-date ρ above 0.733 would flip S-1 to UNDERPOWERED. Measure before any claim beyond the assumption.
3. The 4 CORRUPT instances should be re-checked for 09-28 and 09-29 before any day-count claim.
4. first_seen_ns is recorder-observed; a listing time needs another source.

## 19. WP3 consequence

WP3 records TRADE_QUANTITY_UNIT = CONTRACTS in src/breezy/adapters/polymarket_us/parsing.py (WP3 commits 77f278a6 + 999c2d8e, merged into feat/data-capture-and-risk); effective at the next scheduled 09:00Z recorder rotation; S2 runs under the single hypothesis CONTRACTS.

