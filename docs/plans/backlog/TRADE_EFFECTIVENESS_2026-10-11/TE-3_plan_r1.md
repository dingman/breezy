# TE-3 plan r1: NO-side cheap-entry hypothesis (planner, 2026-10-11, read-only; suggested path `docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/TE-3_plan_r1.md`)

## 0. Verdict up front
- TE-3 is **not** a subset of M1-v3. It is a disjoint price band, and the fair-odds prior points the wrong way for it.
- It **is** a subset, in hypothesis space, of NO-1 / PREREG v3a. That test is dead in practice (see §1).
- **Preliminary verdict: INFEASIBLE.** The test cannot reach a powered verdict before the 2027-01-25 backstop.
- The infeasibility is **structural**, so it does not depend on the unmeasured rate.
- The plan therefore delivers the ruling, one cheap outcome-free rate census, and re-open triggers. It builds no shadow collector and freezes no PREREG. A dormant PREREG skeleton (§5) is kept for a lever that changes the arithmetic.
- This plan read no M1-v3 report or output. The only outcome rows it read were the three known NO fills' CLI finals, which are SEARCH data.

## 1. How TE-3 differs from M1-v3, NO-1 and H-NO-SIDE
| | M1-v3 (frozen, read-once ≥ 12-07) | TE-3 (the two wins) |
|---|---|---|
| Entry price | NO ask ≥ 0.90, i.e. YES bid ≤ 0.10 (the NO favourite) | NO ask 0.07–0.12, i.e. YES bid 0.88–0.93 (the NO longshot) |
| Window | first Depth10 row in [12:00,13:00) UTC, about 05–08 LST, pre-peak | 12–16 LST, after the running max has reached the rung |
| Rung | any rung | interior current rung |
| Fair-odds prior | on the favourable side: M1 D_12Z cell −1.4¢, R11 expects NO-EDGE | on the adverse side: M1 YES 0.0–0.1 cells are reliable losers (−1.7 to −2.3¢), a mirror of this region |

- The two ask bands are disjoint, so a TE-3 entry can never be an M1-v3 take. Stage 0 pins this with a test.
- **NO-1 / PREREG v3a** already registers the NO leg for `pm_us_crh_cont`: take NO iff `1 − P_HOLD_UPPER > NO ask + fee`, current rung only, measured on fills with LD-OBF.
  - All 3 live NO fills came from that rule.
  - It is unmeasurable now: the sending family is `fq_v1`, `cont` and `v4` are halted, and no offer-tape file exists after 09-23.
  - The frozen `P_HOLD_UPPER` table is flagged unsafe on the NO side (+0.094 mean on 233 of 240 cells; memory `archive-table-train-serve-skew`).
- **H-NO-SIDE-2026-09** is already ruled `UNDERPOWERED_NOT_REGISTERED` (MDE 0.089 at n=300, 0.04 needs about 1487 station-days).
- **Residual** hypothesis: a model-free, shadow-measured test of "market hold on the current rung at 0.88–0.93 is overpriced". That residual is what this plan finds infeasible.

## 2. Verified premises
- **The wins are real, scored on the instrument day.**
  - Fills are in `~/.local/share/breezy/state/exec_polymarket_us.sqlite`.
  - CGW8DJ23PVB2: MIA 09-15 `gte92lt93^no`, cost 0.09, fee 0. CLI tmax 93, so NO wins, +0.91.
  - CNC3HJD66WP9: MDW 09-22 `gte62lt63^no`, cost 0.12 + fee 0.01. CLI tmax 64, so +0.87.
  - CMRS7Y99WWPE: MIA 09-21 `gte88lt89^no`, 0.12 + 0.01. CLI tmax 88, so the NO loses.
  - Net +1.65, matching the audit.
  - Truth: `~/.local/share/breezy/derived/fq-truth/truth_cli_finals.csv`. Memory `hunt-window-opens-after-repricing` calls this rung the 09-15 winner; the CLI file says 93, so that memory is wrong on this point.
- **Entry prices are NO-denominated.**
  - The `^no` instrument price is `1 − YES bid` (`decision.py:455-496`; `no_ask` at `scripts/analysis/market_calibration_scan.py:242`).
  - The venue position capture is NO-denominated (memory `venue-nets-no-holding-as-short-yes`).
- **M1-v3 is a NO-favourite screen.**
  - H1 is NO ask ≥ 0.90: `M1v3-no-longshot-forward-screen_plan.md:10`, with the pinned inclusive selector at `:91`.
  - `docs/evidence/m1v3/PREREG.json` carries `ask_threshold: "0.90"`, `frozen_sha adb1cd8b`, `read_offset_days: 61`, and the expected outcome NO-EDGE or UNDERPOWERED.
  - R11 (`:195`) calls it a forward confirmation of NO-EDGE.
- **The bot's NO rule is the TE-3 region.**
  - `decision.py:487-488` sets `p_miss_lower = 1 − P_HOLD_UPPER`.
  - `decision.py:383-392` and `config.py:234-235` set the executable band to 0.05 < price < 0.95 (strict), so the usable NO ask is about 0.06–0.12.
  - `continuous_no_side.py:106` has `NO_SIDE_SHADOW_ONLY = False`.
  - `continuous_no_side.py:213-296` appends a `side="NO"` offer-tape row on every branch.
- **Offer-tape census** (outcome-free; I counted rows only):
  - Files `…/catalog/quote_tape/decisions/offer_tape_2026-09-{16,20,21,22}.jsonl.gz` hold a total of 9 distinct interior rungs with NO ask ≤ 0.12 over 4 days.
  - Per day: 3, 2, 2, 2. All 9 sit at hour_lst 12–16, and each station-day has exactly one such rung.
  - 7 of the 9 are refused as `observation_ambiguous`; the other 2 reached `taken`.
  - One open-lower tail rung (SFO lt65, 09-20) is also in the count; the interior-only rule excludes it. See the §5 sample-size arithmetic.
  - Coverage caveat: no offer-tape file exists after 09-23, and 09-17/09-19/09-23 are under 7 KB.
- **M1 saw almost none of it.**
  - `docs/evidence/m1/market_calibration_scan_v2.json` tested 35 cells and left 21 untested.
  - The lowest tested NO bin is 0.4–0.5, so NO ask below 0.4 had n < 30 over 26 days at the three fixed windows.
- **Ledger arithmetic is pinned.**
  - `hypothesis_ledger.py:859-870`: `recompute_mde` uses the pinned `VARIANCE_BOUND` (0.25). It is "the ONLY admitted derivation".
  - `:1125`: MDE above the plausibility bound returns `UNDERPOWERED_NOT_REGISTERED`.
  - Constants: `PROGRAMME_ALPHA` 0.05 (`:177`), `MAX_HYPOTHESES` 4 (`:181`), `POWER` 0.80 (`:192`).
  - `RULING_H-NO-SIDE-2026-09_horizon_2026-09-25.md` §3 sets the bound at 0.04 and §4 gives n ≈ 1487.
- **Governance:**
  - The backstop is `RULING_RA-13…` §3 (2027-01-25). It is firm (B-5) and is not extended by capture holes (L-38).
  - The revival routes are R4 and FQ-v2 T1–T3 (`RULING_R3-VIABILITY_NOT_VIABLE_2026-10-08.md` §3.2).
  - **Firewall (`RULING_RA-13…` B-3):** any count on tape after 2026-09-25 permanently spends H-ARCHIVE-RECAL CONFIRM days.
- **Prior art for the sign of the effect:**
  - L-9 amendment (`LESSONS.md:492-505`): the cheap side is mostly a lottery already lost.
  - Operator-ruling memory (09-16): taker-priced shadow rest was an underpowered negative.
  - The three live fills were picked from 34 by outcome. The exact one-sided P(≥ 2 of 3 | p = 0.12) is 0.040, and with that selection it is not evidence.

## 3. Stage 0 STOP conditions
Each is a pin test or a checked fact before any work package starts.
1. **STOP if** the M1-v3 PREREG blob differs from `adb1cd8b`/`6fbc4f6b`. Check with `git log -- docs/evidence/m1v3/PREREG.json` and `check_frozen_blob`.
2. **STOP if** any TE-3 code imports `scripts.analysis.no_longshot_pooled_test` or opens a path under `docs/evidence/m1v3/` (other than reading PREREG.json for the band constant). Pin with an AST test.
3. **STOP if** the census reads tape after 2026-09-25. The tool hard-refuses `--until` later than 2026-09-25 (RA-13 B-3).
4. **STOP if** the census joins truth or computes any outcome. It stays outcome-free.
5. **STOP if** any statistic uses the 3 NO fills. They are SEARCH, selected by outcome. Fills and offer-tape counts are premises only.
6. **STOP if** a census row's reference timestamp is not strictly before its climate-day end (`assert_no_lookahead` semantics).
7. **STOP if** the Depth10 catalog or the pre-freeze day list is unavailable. Report the blocker; do not substitute QuoteTick (bid side is structurally non-empty there; memory `weather-market-bid-side-is-empty`).
8. **STOP and re-plan if** the full-tape census shows interior-rung qualifying station-days above 2 per station-day-at-risk. That contradicts §5 and signals a rule-definition bug (L-28).

## 4. Work packages (build route: Grok → Codex → Claude tdd-guide; coordinator runs `scripts/ci/run_tests_no_egress.sh`)
Every brief must carry:
- Nautilus immutable; `allow_short=False`.
- No arming, no live enablement, no operator caps touched.
- Explicit interpreter `/home/jon/breezy/.venv/bin/python`; never `uv` or pip.
- Worktree runs use `PYTHONPATH=<wt>/src`.
- Run `lint-imports` from the tree root and require "0 broken".
- Run `ruff format` on touched files only.
- Never `git stash`.

**WP-1: pre-freeze rate census (outcome-free).**
- File: `docs/evidence/te3/te3_rate_census.py`, following the `docs/evidence/m1v3/*.py` precedent. Reuse `market_calibration_scan` helpers (`classify_directory` via `_index_directories`, `no_ask`, `_levels`) and `RecorderCatalogTape`.
- Rule, bot-available only:
  - interior finite-width rung;
  - hour_lst 12–16, converted with the station registry offsets and scoped by date AND hour;
  - NO ask = `1 − best YES bid (size ≥ 1)` in [0.06, 0.12];
  - first qualifying Depth10 row per (station, climate day).
- Output: per-day counts of qualifying station-days, plus the denominator of station-days with a complete window. Filter `replay_sufficiency` rows by `window_complete == True` for the haircut κ.
- Safety: read-only. Run under `systemd-run --user -p MemoryMax=4G -p LimitNOFILE=524288`, with `--basetemp` under `~/.cache`. Refuse to write under `LIVE_DATA_ROOT`.
- RED tests (`tests/unit/test_te3_rate_census.py`):
  - `test_refuses_until_after_2026_09_25`
  - `test_band_inclusive_006_to_012_and_excludes_013`
  - `test_open_ended_rungs_excluded`
  - `test_bid_side_empty_counted_not_synthesised`
  - `test_one_trial_per_station_day_first_row_wins`
  - `test_hour_window_scoped_by_date_and_hour` (L-34)
  - `test_ref_ts_strictly_before_day_end`
  - `test_never_imports_truth_loader_or_m1v3`
  - `test_refuses_live_data_root_output`
  - `test_open_windows_excluded_from_rate` (`window_complete`)
- Done when: the JSON states λ̂, its exact Poisson 95% interval, κ, n_available, the verdict date, and a census sha256.

**WP-2: ruling (docs only, planner plus peer review).**
- File: `docs/evidence/RULING_TE-3_NO_CHEAP_LONGSHOT_INFEASIBLE_<date>.md`.
- Contents: §0 verdict, §1 delta, WP-1 numbers, the structural bound, the levers table, the re-open triggers, and the declaration that no post-09-25 tape was touched.
- Verdict wording: `INFEASIBLE_NOT_REGISTERED`. Closed-form arithmetic only; no outcome statistic.
- Optional: register a zero-look `UNDERPOWERED_NOT_REGISTERED` record through the existing `_UNDERPOWERED_REGISTRATIONS` pattern in `scripts/analysis/hypothesis_register.py`. It consumes no alpha and no slot. Skip unless peers want it (YAGNI); the ruling is the record.

**WP-3: bookkeeping.**
- Update the TE-3 row in `docs/core/PROGRESS.md` to `RULED INFEASIBLE <ruling>` with the WP-1 numbers.
- Write the convergence record `reviews/TE-3-final.md`.
- Record the lesson that fill-picked anecdotes cannot power a hypothesis (dedup against the LESSONS "implausible result" entries first).

**WP-4 (CONTINGENT, DORMANT): PREREG freeze and shadow collector.**
- Builds only if a §6 lever fires. It would be an offline Lane-E tool in the `no_longshot_pooled_test.py` pattern, using `check_frozen_blob` and a freeze-introduction check.
- It would not use the CRH strategy shadow path, which is dormant and sits next to the arming path.
- Its tests would mirror the M1-v3 list: forward-day filter from git, no verdict before the read date, read-once, lookahead gives INVALID, and decision ts < outcome ts.

## 5. PREREG skeleton (DORMANT; never frozen on PM.us per §6)
- **Id / lane:** `H-NO-CHEAP-CURRENT-RUNG` / Lane E (execution-structure screen), outside the AUT-S K ledger as M1-v3 is. A WINNER nominates only an admissibility filter on a weather-sourced NO decision, never a family.
- **H1:** buying NO at the Depth10 ask on an interior current rung, with NO ask in [0.06, 0.12], at the first qualifying row in 12–16 LST, has positive mean net EV per take after cost.
- **Net EV:** `hit − (ask + max(venue_fee(ask), THETA·ask·(1−ask)) + s)`, s = 0.01, THETA from `EVIDENCED_FEE_THETA`. Hit = settled high outside the closed rung interval.
- **Entry features (decision time only):** Depth10 YES bid size ≥ 1, rung geometry from the instrument id, LST hour. No model, no archive table, no running max.
- **Unit and cluster:** one trial per station-day; calendar-day cluster bootstrap with zero-take days kept.
- **Statistic and α:** K = 1, one-sided; primary α = 0.05 (a ledger-registered variant would use α′ = 0.0125, see §6); lower bound from the day-block bootstrap plus BCa, both > 0.
- **Looks:** single look, no interim verdict. Before the read date the report holds counts only (the M1V3-R21 rule).
- **n_min / power:** break-even p0 = 0.12 (ask 0.10 + fee 0.01 + s 0.01); n = ((z_α√(p0q0) + z_β√(p1q1)) / δ)² at 80% power. Exact numbers are in §6.
- **Floors:** n_takes ≥ n_min, n_days ≥ 40, loss_days ≥ 5 as a degeneracy guard only.
- **KILL:** the verdict date is later than 2027-01-25 (ruled INFEASIBLE), or the read date arrives with any floor unmet (UNDERPOWERED).
- **Window:** first_forward_day = UTC committer date of the freeze commit + 1 day, derived from git. last_forward_day = backstop − 8 days.
- **Prior disclosure:** the band was chosen after seeing 3 fills and 9 offer-tape rungs, which is SEARCH. The adverse fair-odds prior and the archive-table skew make P(WINNER) close to α.
- **Pins:** SEARCH/CONFIRM split at the freeze commit; the three live fills and all pre-09-26 tape are SEARCH.

## 6. Feasibility method and numbers
**Inputs, all assumptions flagged:**
- λ̂ = 9 rungs / 4 days = 2.25 per day. Exact Poisson 95% interval [1.03, 4.27]. This is preliminary: 9 events, 4 days, and offer-tape coverage is not random. WP-1 replaces it.
- κ = 0.8 coverage haircut (about 8% of M1 windows lacked Depth10, plus about 9% of station-days never listed). WP-1 sets it from the `window_complete` census.
- T = 84 days: first_forward_day assumed 2026-10-26, backstop 2027-01-25 less an 8-day truth lag (M1-v3 R7 precedent).

**Available takes:**
| Case | λ | n_avail (λ·κ·T) |
|---|---|---|
| Central | 2.25 | 151 |
| Low | 1.03 | 69 |
| High | 4.27 | 287 |

**Structural ceiling:** PM.us has 5 cities, so at most 5 station-days per day. 5 × 84 = 420 even if every station-day qualified, which it does not.

**Required n (binomial, p0 = 0.12, 80% power):**
| α | δ = 0.04 | δ = 0.05 | δ = 0.06 | δ = 0.08 |
|---|---|---|---|---|
| 0.05 | 445 | 290 | 205 | 119 |
| 0.025 | 559 | 364 | 257 | 149 |
| 0.0125 | 672 | 437 | 308 | 178 |

**Ledger path (the only route to a revival under R4):**
- Pinned variance 0.25 gives n = 1485 station-days for MDE 0.04.
- MDE at 420 station-days is 0.075, which is above the 0.04 bound.
- **Mechanical result: `UNDERPOWERED_NOT_REGISTERED` at any rate.**

**Verdict:**
- At δ* = 0.04 and α = 0.05, n_min = 445. That exceeds the structural ceiling (420), the upper-bound n_avail (287), and the central n_avail (151).
- Central MDE at n = 151 is about 0.077, hit rate about 20% against 12% implied. That contradicts the 0.04 plausibility bound and the adverse fair-odds prior.
- **Verdict dates at rate:**
  - Central: 445 / (2.25 × 0.8) = 247 days after first_forward_day, about 2027-07-09 with truth lag.
  - High (4.27): about 2027-03-13.
  - Low (1.03): about 2028-04.
  - Every case is past 2027-01-25.
  - The ledger n = 1485 lands about 2029-01 (central) and 2028-01 (high).

**Levers and why each fails on PM.us:**
| Lever | Effect | Disposition |
|---|---|---|
| Widen the ask band to ≤ 0.30 | about 3× rate, but p0 = 0.30 needs n of about 1000+ | Rejected: worse |
| All hours | tail rungs are untradable (ask ≤ 0.05) | Rejected |
| Relax δ to 0.08 | n = 119 (α = 0.05) | Rejected: above the 0.04 bound, and the prior says no |
| Kalshi, 24 cities | about 6× station-days | Only live lever; own ledger, TWC settlement, no PM.us pooling (RA-13 B-2); K-2a desk plan, build gated on KILL |

**Re-open triggers (ruling text):**
1. PM.us lists at least 15 daily-high stations.
2. A K-2b Kalshi ledger exists, and TE-3 enters its hypothesis list.
3. A ruling raises the plausibility bound with outcome-free evidence.
4. FQ-v2 T1–T3 fire and request it.

## 7. Dependencies
- WP-1 needs the Depth10 catalog and `replay_sufficiency.jsonl` for `window_complete`. It does not need truth.
- WP-2 needs WP-1 and a prediction-market-reviewer pass.
- The M1-v3 read (≥ 12-07, read-once) is untouched. TE-3 never waits on it and never peeks.
- Kalshi lever: K-2a/K-2b (`docs/plans/backlog/K-2a_2026-10-08/`); no action now.
- Review protocol (README): parallel prediction-market-reviewer (domain math), trading-bot-architect, python-reviewer, and a Codex adversarial pass, until READY with no BLOCKER/HIGH.

## 8. Risks
- **The 9 events are 4 days of data.**
  - The verdict does not depend on λ̂: the ceiling is 420 and n_min is 445.
  - The verdict date does depend on it. WP-1 hardens it, and the ruling quotes the interval.
- **Confusing the sides.** TE-3 is the NO longshot, not the NO favourite. The two are on opposite sides of the fair-odds prior; the delta table prevents a lift of M1-v3's optimism.
- **Firewall cost.** A forward shadow collector would count post-09-25 tape and spend CONFIRM days. Declaring INFEASIBLE touches none.
- **Anecdote pressure.** 2 of 3 wins will tempt a build. The ruling quotes P = 0.040 and the selection from 34 fills.
- **Venue skew.** Observation-ambiguity refuses 7 of 9 candidates, so the bot's own NO rule would rarely have fired. The model-free rule avoids that, but real-money fillability is unmeasured.
- **Leak hazard for any future outcome join.** If WP-4 is ever built, enforce the sanity check "ask ≤ 0.12 with hit rate > 0.35 is a bug signature" and the date-and-hour scoping (memory `implausible-result-is-a-leak`).

## 9. Non-goals
- No live order, arming, halt change, permit, or operator cap.
- No change to M1-v3 files or PREREG; no M1-v3 outcome read.
- No new strategy family and no `ContinuousRungHoldStrategy` shadow re-enable.
- No resting-bid design (rest_v5 stays as is).
- No post-09-25 tape count.
- No Kalshi build.
- No hit-rate or EV statistic on the SEARCH corpus.

## 10. Goal-state map
| Goal item | Where met |
|---|---|
| Documented ruling that the hypothesis is covered or infeasible | WP-2 (INFEASIBLE_NOT_REGISTERED), with §1 for the part covered by NO-1 / v3a |
| Feasibility number | §6: 2.25/day (preliminary, CI [1.03, 4.27]); WP-1 firms it |
| Verdict date at that rate | §6: about 2027-07-09 central, past the backstop in every case |
| INFEASIBLE with the number when n_min is unreachable | §6: n_min 445 (α = 0.05, δ = 0.04) or 1485 (ledger) against a ceiling of 420 |
| Shadow measurement path | Not built, by the infeasibility rule. WP-4 and §5 hold the dormant design |
| Arming and live sending | Out of scope |

Relevant files, all absolute:
- `/home/jon/breezy/docs/plans/backlog/TRADE_EFFECTIVENESS_2026-10-11/README.md`
- `/home/jon/breezy/docs/plans/backlog/FQ_LOSS_RESPONSE_2026-10-04/M1v3-no-longshot-forward-screen_plan.md`
- `/home/jon/breezy/docs/evidence/m1v3/PREREG.json`
- `/home/jon/breezy/docs/evidence/PREREG_v3_AMENDMENT_NO_SIDE_2026-09-14.md`
- `/home/jon/breezy/docs/evidence/RULING_H-NO-SIDE-2026-09_horizon_2026-09-25.md`
- `/home/jon/breezy/docs/evidence/RULING_RA-13_programme_kill_2026-09-27.md`
- `/home/jon/breezy/docs/evidence/RULING_R3-VIABILITY_NOT_VIABLE_2026-10-08.md`
- `/home/jon/breezy/docs/evidence/m1/market_calibration_scan_v2.json`
- `/home/jon/breezy/src/breezy/strategy/current_rung_hold/decision.py`
- `/home/jon/breezy/src/breezy/strategy/current_rung_hold/continuous_no_side.py`
- `/home/jon/breezy/src/breezy/analysis/hypothesis_ledger.py`
- `/home/jon/breezy/scripts/analysis/market_calibration_scan.py`