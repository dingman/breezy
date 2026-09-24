# Autonomous-workflow and portfolio-ROI audit — 2026-09-21

**Status:** read-only audit, complete. Nothing was traded, promoted, reconfigured or
restarted. Five seams ran as independent agents (three Codex, the rest Claude after
Grok 402 and one Codex backend 404); the coordinator spot-checked the key citations
against files and logs. Verdict vocabulary: TRUE (direct evidence supports), FALSE
(direct evidence contradicts), UNVERIFIED (insufficient evidence).

**Backlog derived from this audit:** `docs/plans/backlog/AUDIT_2026-09-21/`.

## Overall verdict

FALSE — the bot does not demonstrably perform the complete workflow (discovery →
backtest → promotion → forecast-based opportunity → execution) autonomously.
Improved portfolio-level ROI is UNVERIFIED: it is not measured at all.

## Requirements table

| Responsibility | Capability | Observed autonomous operation |
|---|---|---|
| 1. Station discovery | FALSE for stations (TRUE for markets inside a fixed set) | FALSE |
| 2. Station backtesting | TRUE | FALSE |
| 3. Promotion to live eligibility | FALSE | FALSE |
| 4. Opportunity identification from forecasts | FALSE | FALSE (non-forecast loop evaluates continuously; nothing qualified since 09-15) |
| 5. Trade execution | TRUE | TRUE for submission/fills; FALSE for venue reconciliation and hands-off operation |

## Numbered gaps (source of truth for the backlog)

Each gap: verdict, evidence, and whether the coordinator verified the citation (V) or
it is agent-reported only (A).

- **G-01 Nothing reaches pricing.** FALSE. `docs/evidence/DECISION_FUNNEL_2026-09-20.md`:
  40,796 decisions (09-20) and 53,624 (09-16); 0 pass "cell legal", 0 reach a price.
  Gates: `observation_ambiguous` (`weather_common/running_extreme.py:286-297`, exact °F
  only on METAR rows) then `illegal_cell`. No order since 2026-09-15T20:12:06Z while the
  node is alive with a valid permit. (V) Related open item: HUNT-1.
- **G-02 No demonstrated edge; no forecast link on the live path.** FALSE. Live family
  `pm_us_crh_v4` (`deploy/families/pm_us_crh_v4.json`, `continuous_rung_hold`) prices from
  frozen `P_HOLD_LOWER/UPPER` tables keyed on observed running max
  (`current_rung_hold/decision.py:44,353,392-402`), not a timestamped forecast.
  `app/trade.py:288-297` refuses `forecast_ladder`: "ForecastLadderStrategy is not
  implemented". `RULING_forecast_edge_programme_closes_2026-09-20.md` closes the forecast
  taker as terminal. PROGRESS: "NO FAMILY HAS A PROVEN EDGE", admissible n = 0. (V)
- **G-03 Portfolio ROI is not measured.** FALSE. No equity curve, balance series,
  capital-flow accounting or baseline. AccountState is logged once per boot
  (`breezy-trade-20260920T165028Z.log:199`); `snapshot_positions=False`. The plan's
  "Portfolio ROI" is `trial_count × mean_realized_edge`, "never annualized"
  (`FORECAST_EDGE_FAMILY_Rev5_2026-09-18.md:182-186`). No realised-P&L figure for the 6
  fills exists in docs or tally output. (V for the plan text; A for the absence claim)
- **G-04 Live family has no working tally.** FALSE. Timers exist only for
  `pm_us_crh_cont` and `pm_us_crh_v2`; `breezy-family-tally@pm_us_crh_cont.service` failed
  2026-09-20 17:20:51Z (V) and, per agent, on both 09-19 runs (A). No unit tallies
  `pm_us_crh_v4` (d0 2026-09-20). Orphan `breezy-pm-crh-{cont,v2}-tally` units are
  `not-found/failed`. (V) Related: R-4.
- **G-05 Station discovery is static.** FALSE. `SUPPORTED_STATIONS = ("LAX","MDW","MIA",
  "SFO")` at `current_rung_hold/config.py:76`. `breezy-quote-tape.service` discovers
  listings unattended (2026-09-20T21:00:42Z: 60 markets / 120 instruments) but nothing
  turns a new station into a backtest candidate. (V)
- **G-06 Backtesting is manual, stale and feeds nothing.** FALSE (autonomy). Harness
  exists (`runtime/backtest_harness.py:663-736`, `scripts/analysis/run_weather_strategy_backtests.py`,
  `current_rung_hold_paper_replay.py`, `whole_tape_paper_replay.py`). No timer runs a
  backtest or replay; last artefacts 09-03 and 09-05. Output is human-read only
  (`FORECAST_LEVERAGE_AUDIT_2026-09-18.md:7`). (A, mtimes not re-checked) Related: SP-4.
- **G-07 Promotion is a human commit and cannot change stations.** FALSE. Unit-file
  commits `7938032` (09-12), `23fe848` (09-19), `bcb82d6` (09-20) (V). REG-1
  (`PROGRESS.md:49`): `manifest.stations` validated but not consumed. Written criteria
  (`FORECAST_EDGE_PEER_REVIEW_2026-09-18.md:121-152`) are not enforced by code (A).
- **G-08 Look-ahead in backtests.** FALSE for one runner, UNVERIFIED elsewhere.
  `run_weather_strategy_backtests.py:~56-64` re-stamps observations retrieved after the
  tape window to before it (V). `whole_tape_paper_replay.py:589` carries
  `LOOK_AHEAD_CAVEAT` (V). Guards exist at `backtest_harness.py:573`,
  `runtime/paper_replay.py:228` (A). Other study paths not checked.
- **G-09 Costs incomplete.** UNVERIFIED. Fee model wired (`backtest_harness.py:736`,
  `adapters/polymarket_us/fees.py:123`); slippage is an "UNMEASURED" 0.01 placeholder
  (`weather_common/costs.py:59`) (V). Fee θ drifted 0.06→0.0695 on 09-17
  (`docs/evidence/venue/polymarket_us/FEE_SCHEDULE_PIN_2026-09-18.md:47`) (V); v4 pins
  0.0695 but there is no automated current-fee verification (A).
- **G-10 Venue reconciliation is stubbed.** FALSE. `generate_order_status_reports` /
  `generate_fill_reports` return `[]` (`adapters/polymarket_us/exec/client.py:2500-2548`)
  (V). Order 2's fill (09-11) surfaced only after a relaunch on 09-12 (A). Related:
  SP-3 B1/B2, R-1, R-2.
- **G-11 Sizing is fixed; no allocation logic.** FALSE (alignment). `order_quantity=1`;
  MP-B blocked on R-11 (`PROGRESS.md:53`) (V). `weather_common/equity.py`
  `max_equity_fraction` is unused by the live family (A).
- **G-12 Exit seam unarmed.** FALSE (alignment). EXIT-1 (`PROGRESS.md:52`): built
  c96c7f4, `pm_us_crh_exit_v4` DRAFT, live family never sells (V).
- **G-13 Operation is not hands-off.** FALSE. 11/11 automatic daily launches, but 7
  supervisor Stopped→Started cycles in 11 days with no preceding crash line, self-check
  `FAIL_NODE_NOT_READY` 09-12..09-17 and `FAIL_CHILD_EXITED` 09-18 (A). Motive for the
  restarts is unrecorded (UNVERIFIED).
- **G-14 Scheduled studies are failing.** FALSE. `breezy-mb-daily.service` timeout
  2026-09-20 14:30:27Z; `breezy-offer-gate-daily.service` timeout 02:35:47Z (A for cause;
  V that both are in failed state).
- **G-15 Evidence hygiene gaps.** UNVERIFIED items: (a) `PROGRESS.md:32,82` live counts
  stale (3 orders/2 fills vs 7/6 in logs + sqlite ledger) (V for staleness); (b) family id
  is never logged at runtime (A); (c) order 1 (09-05) has no `OrderSubmitted` line, ledger
  only (A); (d) the funnel doc says no decision "ever" reached pricing although four
  orders filled 09-15 — presumed tape-start effect, unconfirmed; (e) look-ahead status of
  remaining study paths (see G-08).
- **G-16 Caps on the v4 composition are not proven by test.** UNVERIFIED. Caps are
  enforced in `_submit_order` (`exec/client.py:3489-3531`) and at permit mint
  (`order_enablement.py:215-221`) (A); no test was identified that exercises them through
  the `pm_us_crh_v4` live composition.
- **G-17 "Why no trades" is not answerable from the node log.** FALSE (observability).
  The 5.2-day order drought shows no refusal line in the node log; the cause was only
  recoverable from the offline funnel study (A + V via G-01).

## Live execution record (agent-reported; 09-15 lines verified)

7 orders / 6 venue-confirmed fills / 1 zero-fill, 2026-09-05 → 2026-09-15; none since.
Logs `~/.local/share/breezy/logs/breezy-trade-*.log`; ledger
`~/.local/share/breezy/state/exec_polymarket_us.sqlite`.

## Corrections made to agent output

- An agent ruled execution capability FALSE because `CurrentRungHoldConfig.orders_enabled`
  is pinned False. Rejected: `current_rung_hold/strategy.py:20` states that flag is not the
  gate; the permit is, and six live fills prove the path.
- The ROI agent's "3 orders, 2 fills" and "live family pm_us_crh_cont" came from a stale
  PROGRESS line; the unit runs `pm_us_crh_v4` since `bcb82d6`.
