# Forecast leverage and learning audit — 2026-09-18

Read-only audit, three seams (forecast data path, live decision inputs and learning loops, executed-trade record), each run against the code at `feat/data-capture-and-risk` @ f349ce7, the user systemd units, the user journal, and `~/.local/share/breezy`. Every claim carries its source. Nothing was changed and no service was touched.

## Answer

1. **The bot ingests no forecast data and trades on none.** No NBM, NBS, MOS, TXN, GFS, NWS forecast product, Open-Meteo, or IEM forecast PIL reaches production. The only weather inputs are NWS CLI climate days (observed, settlement truth) and NWS/IEM station observations. The forecast programme is at Stage 0a of a nine-stage plan: two human-run probes are built but unrun, the archive cache exists but is consumed by tests only, and the forecast family `pm_us_crh_fc_v1` has no manifest and no code.
2. **What is being traded is an observation-conditioned climatology bet.** The live family `pm_us_crh_cont` prices the current temperature rung from the running observed maximum and a frozen archive table of hold probabilities keyed by station, season, hour, and rung width. It buys YES (and, since 2026-09-14, NO) with an IOC order of quantity 1 when the bound beats ask plus fee.
3. **The bot does not learn from its trades in the sense of updating any live rule.** Fills are scored nightly against NWS finals into a durable parquet ledger and fed to a pre-registered sequential test whose only output is SURVIVE / KILL / CONTINUE. No probability table, fee coefficient, window, or size is updated from outcomes by code. Every other feedback loop (exit study, resting-bid arm, band screen, calibration upper bound) produced evidence or a ruling that a human then acted on. The champion/challenger learning loop is designed in the Rev 5 plan for Stage 5+ and none of its five components exists in `src/`.
4. **The trade record is seven orders, six fills, three admissible trials, total −0.82 contract-units on the admissible set.** Verdict CONTINUE at n=3, first look at n=10.
5. **Operational finding, outside the question but material:** the trade child process has been a zombie since 2026-09-17 16:50Z and the supervisor self-check has reported `FAIL_NODE_NOT_READY` on 09-15, 09-16, and 09-17. The last successful family tally is 2026-09-16; the 09-17 tally unit failed on a missing `POLYMARKET_US_EXEC_STATE_DB`. No order has been sent since 2026-09-15.

## 1. Forecast data path

| Question | Finding | Evidence |
|---|---|---|
| Forecast symbols in `src/` | `ForecastSource`, `ForecastSnapshot`, three forecast strategies (`forecast_mispricing`, `forecast_revision`, `calibration_mean_reversion`), `ForecastHighEdgeBuyer`, `LadderEvConfig` — none reachable from `app/trade.py`, `runtime`, or the live strategy | `src/breezy/strategy/weather_common/forecast_source.py:103`; `forecast_edge.py:75` (buys from observed `NwsClimateDay.tmax_f`, `:129-130`); `ladder_ev/config.py:163-166` (`mode='full'` raises) |
| Authoritative gap statement | "Breezy ingests NO forecast data … There is no forecast source anywhere in this codebase" | `forecast_source.py:5-9` docstring |
| `ForecastPoint`, `forecast_catalog`, NBM actor | Do not exist | codegraph: symbol not found |
| Forecast scripts | Six probes under `scripts/venue/` (IEM MOS, NOMADS/NBM, AFOS PIL, two Open-Meteo, plus the IEM transport), all headed "EVIDENCE ONLY — NEVER INGEST"; one pure analysis map (`forecast_climate_day_map.py`) | `scripts/venue/iem_mos_reachability_probe.py:2-3`; `nbm_nomads_discovery_probe.py:2-3` |
| Production units | trade-supervisor, nws-ingest, quote-tape, quote-tape-ingest, and nine analysis/tally timers; none named or running a forecast ingest | `~/.config/systemd/user/*.service` ExecStart lines |
| Journal mentions of "forecast" since 09-17 | 0 in all four production units | `journalctl --user -u <unit> --since 2026-09-17` |
| On-disk forecast datasets | None under `~/.local/share/breezy` to depth 6; `archive/` holds only the 335 MB IEM AFOS CLI settlement cache | `find` over the share tree |
| Family manifests | `pm_us_crh_cont` REGISTERED (live), `pm_us_crh_v2` REGISTERED, `pm_us_crh_exit_v4` and `kalshi_crh_v1` DRAFT; no `pm_us_crh_fc_v1` anywhere in `src/`, `scripts/`, `deploy/` | `deploy/families/*.json`; grep 0 hits |
| Plan stage status (Rev 5) | 0a partial (probes built, unrun; cache merged); 0b, 1 (ingest), 2, 3, 4 (arming), 5+ (learning) not started | `docs/plans/FORECAST_EDGE_FAMILY_Rev5_2026-09-18.md`; PROGRESS FC-0a rows |
| Ruling | "Licenses: Stage 0 measurement only. Stage 1+ requires Stage 0b PASS"; arming would displace `pm_us_crh_cont` | `docs/evidence/RULING_forecast_edge_family_2026-09-18.md:11-13` |

## 2. What drives a live decision

The only path that can send an order: `breezy-trade-supervisor` → `app.trade.run` → `phase1_family_permits` (`composition.py:247`) → `ContinuousRungHoldStrategy` (`continuous_strategy.py:376`), with a hard one-sending-family rule (`settings.py:823-833`).

| Input | Source | Cadence / freshness | Registered or default |
|---|---|---|---|
| Station observation temperature (METAR T-group or integer °C) | `nws_observations.py:131-210` → `StationObservation` | NWS API poll; `on_data` accepts only `StationObservation` (`continuous_strategy.py:1101-1103`) | — |
| Running observed max R(t) | `RunningExtremeAccumulator` (`running_extreme.py:225-305`) | per observation | — |
| Stale bound | 50 min (`config.py:85,225`) | — | code default |
| Venue YES ask/size, bid/size | `on_quote_tick` and `on_order_book_depth` top-of-book (`continuous_strategy.py:1136-1159`) | venue websocket | code |
| Hold probability | `P_HOLD_LOWER` / `1 − P_HOLD_UPPER`, key (station, season, hour LST, width, m) | frozen table generated 2026-09-14T14:50Z from the CLI archive corpus (`archive_table.py:13,37`) | frozen artefact, corpus sha pinned |
| Fee | θ·ask·(1−ask), θ=0.06 (`decision.py:308-315`; `config.py:226`) | per decision | venue formula |
| Take rule | bound > price + fee (`decision.py:394-396`); band 0.05–0.95; size ≥ 1; quantity fixed at 1 | per tick | PREREG v3a estimand; qty per Increment 1 |
| Window | 12 ≤ hour LST < 17 (`strategy.py:154-155`) | — | code constant, not in the manifest |
| Admission | Σq ≤ 1 per station-day (`trial_day_latch.py:1413-1480`) | arm time | PREREG v3a §4 |

**Forecast in this path: no.** `ForecastState` has zero symbols in the graph; nothing under `strategy/current_rung_hold/` imports a forecast module; `fit_error_model` (`weather_common/calibration.py:60`) is not a caller of `evaluate_decision`.

Contradiction noted: comments at `continuous_strategy.py:1349,1636` still say NO is shadow-only, but `NO_SIDE_SHADOW_ONLY = False` (`:161`) and `_maybe_submit` is reached on the NO path (`:1895-1937`). The flag and call are the fact; the comments are stale.

## 3. Feedback loops — what "learning" exists

| Mechanism | Reads | Can change | Automatic or human-gated | Has it fired |
|---|---|---|---|---|
| Nightly scorer (`score_live_trials`, 14:15Z) | fills + NWS CLI final tmax | writes `scored_trials_<stamp>.parquet` under `derived/scored_trials/<family>` | automatic write, consumed by the tally | yes: 09-16 ok, 09-17 wrote no parquet |
| LD-OBF sequential tally (`family_tally_v2.py`, 17:25Z) | scored trials | verdict SURVIVE / KILL / CONTINUE only (`current_rung_hold_v2.py:461-465`); no call into the halt store | verdict is human-actioned | 09-16 CONTINUE n=3; 09-17 unit FAILED |
| Family halt | duplicate fill / ambiguous exit (`trial_day_latch.py:850-903`) | vetoes all submits | automatic | not fired live |
| Offer tape JSONL | every evaluated snapshot incl. refusals | observability only, never read back by the hunt | human-gated | durable daily files |
| Archive calibration table | CLI archive corpus, not fills | frozen module; regenerating it is a code change | human-gated | last generated 09-14 |
| Exit-window study (15:20Z) | live fills + depth | evidence | human-gated → EXIT-1 built, unarmed | R-DEAD 0/5 fillable |
| Resting-bid Arm A | tape counterfactual | evidence | human-gated → PREREG v5 DRAFT | G-R1/2/4/5 FAIL |
| Band decider 0b screen | tape + IEM + CLI | evidence | human-gated → STOPPED | gate FAIL |
| Drift allowlists | venue JSON keys | code frozensets via capture tests | human-gated | last capture 09-13 |
| Online / bandit / weight update from fills | — | nothing | none exists | — |

Planned (Rev 5 §13, Stage 5+): champion/challenger with a pre-registered update policy; "The loop never touches a live decision inline"; "Online/incremental in-Strategy model update: NONE EXISTS". None of components a–e, the artefact registry, or the promotion engine exists in `src/` today.

## 4. Executed-trade record (since 2026-09-04)

| Date (UTC) | Station / side / rung | Price | Outcome | Settlement | Fee-reconciled | Admissible |
|---|---|---|---|---|---|---|
| 09-05 20:19 | SFO YES [73,74] | 0.28 | AMBIGUOUS, operator-retired, no venue order | — | — | no |
| 09-11 20:20 | SFO YES [70,71] | 0.22 | filled via resolver | CLI final 73 → lost (INFERRED, not scored) | no | no (fee_unverified residual) |
| 09-13 17:03 | MIA YES [91,92] | 0.70 | filled via resolver | won, hold_pnl +0.30 | no | no (residual) |
| 09-15 18:00 | MDW YES [80,81] | 0.11 | filled, create path | lost, pnl −0.12 | yes | yes |
| 09-15 18:12 | MIA NO [92,93] | 0.09 | filled, create path | lost, pnl −0.09 | yes | no (first-NO residual) |
| 09-15 18:23 | MDW YES [82,83] | 0.24 | filled | lost, pnl −0.25 | yes | yes |
| 09-15 20:12 | SFO YES [71,72] | 0.44 | filled | lost, pnl −0.45 | yes | yes |

Totals (quoted, not recomputed): orders 7, fills 6, admissible n 3, admissible PnL −0.82 (`derived/family_tally_v2_pm_us_crh_cont_2026-09-16.md`), exit-study sum_hold_pnl −0.61 including the residual MIA win. Stop rule: PREREG v3 LD-OBF, looks every 10 fills to 160, α 0.025 one-sided, I_max 40, truncation D0+165 or −60 (`docs/specs/PREREG_v3_continuous_rung_hold_DRAFT_2026-09-10.md` §3). PROGRESS still states admissible n=0 as of 09-14 and the 09-18 opportunity audit repeats "n=0"; the 09-16 tally is the current figure.

## 5. Node state at audit time (14:06Z)

- Supervisor RUNNING (pid 995285 since 09-15 15:07Z); trade child pid 2394521 `<defunct>` since 09-17 16:50:20Z.
- Supervisor journal: self-check `FAIL_NODE_NOT_READY` on 09-15, 09-16, 09-17; zero order/fill/permit lines since 09-15; no entries today before the 16:50Z launch window.
- `breezy-pm-crh-cont-tally.service` failed 09-17 17:25Z: `POLYMARKET_US_EXEC_STATE_DB is required`.

Not acted on: the recorder and node were not touched per the audit's read-only scope.

## Gaps and limits

- `systemctl --user show/status/list-units` is refused from the audit sandbox; unit activity was inferred from unit files, journals, and `ps`.
- The 09-11 SFO settlement outcome is inferred from the CLI final (73 ∉ [70,71]); no scorer row exists for it.
- Journal shard/subscription evidence for the recorder is in the separate 09-18 recorder check, not repeated here.

Sources: Grok read-only runs run-mu715vys-mbilom, run-mu7168zy-nndw07, run-mu716j7d-w4vf2s (session scratchpad `audit_*.txt`).
