# Breezy — Progress and Backlog

**This file tracks OPEN state only.** Closed work, resolution narratives and
evidence summaries do not live here. They live in git history,
`docs/evidence/`, and `docs/core/archive/`.

## Maintenance contract (BINDING, enforced)

- **Hard budget: 250 lines / 12 KB**, enforced by
  `.claude/hooks/progress-size-gate.sh` (`PostToolUse`). Consolidate when it
  blocks; never raise the budget.
- **An item leaves this file when it closes** — delete it, don't rewrite it as
  a `[CLOSED]` narrative. The commit is the record.
- **Never restate evidence** (link `docs/evidence/`) **or a durable rule**
  (that is `docs/core/LESSONS.md`).
- **Severity tags mark OPEN items only.**

Rationale: L-5. Pre-shrink copy in `docs/core/archive/`.

---

## Operator control contract (set 2026-08-30) — BINDING

The operator reserves exactly **two** controls; every other engineering
decision is delegated to the build side:

1. **Maximum daily budget.**
2. **Maximum per POSITION** — explicitly *not* per weather market.

**Values are not yet supplied and MUST be obtained before any live enablement.**

Two consequences that are not optional:

- **The daily-budget control has no home.** `RiskLimits`
  (`strategy/weather_common/risk.py:47-62`) has no time dimension at all.
  Nothing enforces a daily notional or loss ceiling.
- **The per-position knob silently detunes the rest.** `max_event_notional`
  (1000) and `max_location_notional` (2000) are absolute dollars; only
  `max_equity_fraction` scales with equity. No portfolio-wide cap
  (`max_total_notional`) exists.

---

## Standing verdicts that gate future work

- **G-02 — ROI feasibility: NO-GO** on committing to the downstream adapter /
  settlement / execution build (~$3–15/day net per 100 contracts per city-day).
  Free falsification and tape capture stay in scope.
  `docs/evidence/roi_feasibility_2026-08-26.md`.
- **G-01 — Prelim→final revision study: SUPERSEDED 2026-08-31 → POWERED, FAIL.**
  The N=44 UNDERPOWERED run used the live catalog only (`Archive data used: no`).
  Re-run against the held AFOS archive (N≈1820/site) under the SAME pre-registered
  rule: LAX/MIA PASS; **MDW 13.96%, NYC 11.79%, SFO 4.50% FAIL** Wilson-upper≤0.05.
  A stronger constraint, not a release. **Interior-bucket strategies are dead on
  MDW/NYC/SFO** (they need exact equality). Open-tail paths are unaffected: 97% of
  revisions are UPWARD, downward rate 0.21%.
  `docs/evidence/observation_lock_falsification_2026-08-31.md`.
- **Historical forecasts are NOT proven unavailable.** `CLI_BACKFILL_PLAN.md:46`
  claims otherwise from *repo state*, not availability. Open-Meteo
  `/v1/previous-runs` was deferred, never rejected. Still unverified.
- **Price history genuinely is forward-only.** No public trade tape; expired
  markets return null prices keeping only `settlementPx`.
- **There is no NO-side instrument, and there cannot be one** (BL-6, closed
  2026-08-31). NO is a side of the SAME book, not a second market;
  `parsing.py:_market_sides` refuses any side whose `identifier != slug`.
  `docs/evidence/no_side_instrument_probe_2026-08-31.md`.
  **P5 is rescoped** from "add NO-side instrument support" to "support
  `outcomeSide` / price inversion on the same instrument" — smaller, different
  work. Live acceptance of `outcomeSide=NO` stays the operator-gated probe.
- **The stale-quote gate is wired but unreachable for two of three strategies.**
  `evaluate_order` refuses `shorts_disabled` BEFORE it calls `quote_tradable`
  (`risk.py:296-306`). `calibration_mean_reversion` and `forecast_revision`
  emit only shorts, so their orders die at the earlier gate. BL-1's fix is
  therefore proven by unit test, NOT by the backtest: the post-change re-run
  shows zero `stale_quote` refusals and an unchanged fill count (24 -> 24, all
  `forecast_mispricing`). The gate goes live for the other two only once shorts
  are expressible.
- **The `naive`/`realistic` conditions are NOT redundant** (BL-4, reversed
  2026-08-31). Making refusals visible falsified the byte-identical claim:
  `forecast_revision` naive refuses nothing; realistic refuses 860
  `shorts_disabled`. "Never signalled" is not "signalled 860 times, all
  refused." Both conditions stay; the collapse was withdrawn.

---

## BACKLOG — observation-lock strategies (opened 2026-08-31)

Evidence: `docs/evidence/observation_lock_falsification_2026-08-31.md`.
Landed this batch: shared-risk `SignalFreshness` contract (observation-kind
orders gate on `RiskLimits.stale_observation_hours`, unset ⇒ refuse);
`SharedExposureMixin` + harness guard closing the silent private-exposure-view
gap; `running_extreme_lock` v1 (open-tail only, margin-conditioned model_p).

### [HIGH] BL-11 — `stale_observation_hours` has no shipped value

Derived recommendation is **12.665h** (max-over-sites P99 issuance gap, MIA
12.3167h, + live receipt P99 0.3488h). NOT the pooled P99 (12.52h): MIA's own P99
exceeds the pooled figure, so a pooled bound spuriously refuses MIA's slowest ~1%
of legitimate days. No shipped config declares it (a test pins that). Observed MAX
gap is 18.80h, so any P99 bound fires on rare legitimate days — decide whether
that is acceptable before live enablement.

### [HIGH] BL-12 — observation strategies cannot be backtested

`scripts/analysis/run_weather_strategy_backtests.py` is forecast-plumbing
end-to-end (`ForecastSource` injection, `published_at`-offset sweep). An
observation-only strategy has nothing of that shape to plug into, and faking a
forecast is forbidden. `running_extreme_lock` is therefore unit-tested but has
NO backtest run. Needs an observation-shaped harness path.

### [MED] BL-13 — `cli_settlement_print_lock` not implemented

Both pre-registered gates PASS on archive data (p_stable 99.989% N=9106;
halt-window 98.66% N=9164). Blocked only on BL-12 for economic confirmation.
`lagged_anomaly_tail` stays build-order 3, unstarted.

### [MED] BL-14 — `RefusalAlerter` alerts on `SHORTS_DISABLED` only

`refusals.py:134-151` hardcodes one condition, so a run refused entirely for
`stale_observation` / `observation_limit_unset` counts but never alerts in live.
Mitigated for now by the construction-time raise in `running_extreme_lock`;
generalise `_conditions` over the counted key set.

### [MED] BL-15 — `stale_forecast` fails open on a negative age (BL-9 class)

`risk.py` checks only `>`. A negative age makes a signal look infinitely fresh.
`quote_tradable` already has the `future_quote` guard for exactly this
(`risk.py:278-279`). Deliberately deferred from the freshness change because it
is a behavior change on the forecast path; needs its own `future_signal` reason.

---

## BACKLOG — selected for execution (opened 2026-08-31)

Source: the three-strategy backtest run of 2026-08-31, 36/36 COMPLETED. Reports:
`~/.local/share/breezy/derived/strategy-backtests/` (newest = `...20260831T151235+0000.json`, post-BL-1/2/3/5).

**Binding constraints on every item below.** No item may:
set `allow_short=True`; weaken `BacktestOrderGuard` or any settlement
invariant; relax a safety guard to go green; touch live-trading enablement or
the NO-SEND execution-egress firewall; or invent a value for an
operator-reserved control. Every increment carries an **L-1 null-hypothesis
verdict** citing installed source under
`.venv/lib/python3.13/site-packages/nautilus_trader/` before implementation.

### [MEDIUM] BL-10 — One strategy refuses quotes before the counter can see it

`forecast_mispricing/decision.py:71` calls `risk.quote_tradable(...)` as a
pre-check BEFORE forming a signal, discards the reason into `_why`, and returns
`None`. That refusal never reaches `evaluate_order`, so BL-8's counting cannot
see it: for this one strategy a stale or wide-spread quote is still silently
unrecorded. Predates BL-8; found while fixing it.

**Acceptance:** decide whether a pre-signal quote refusal is a gag or ordinary
market conditions (BL-8 drew that line at "the strategy formed an order" — say
whether this sits on the same side), then either count it under the same
bounded key set or document why it must not be counted.

---

## Carried forward — open, not selected for this batch

| ID | Sev | Item |
|---|---|---|
| CF-1 | OPEN | Non-uniform record counts (28/28/28/30/38); extra MDW/LAX records an unverified inference |
| CF-2 | MED | `never_substitute` in `registry/sites.toml` has no consumer |
| CF-3 | MED | Unbounded whole-catalog reads per lookup (`persistence/catalog.py:693`) |
| CF-4 | MED | `is_record` parsed, never persisted; `tmax_flag` `None` on record days. Not a settlement defect |
| CF-5 | MED | Fail-closed parsing: one bad token blocks a whole site for that poll |
| CF-6 | MED | `tests/live/test_nws_live_ingest.py:86` hardcodes a personal contact; must be a role address |
| CF-7 | MED | `BREEZY_USER_AGENT` required on offline paths (`SharedIngestState.__init__`) |
| CF-8 | MED | Sibling-station products unmarked in the integrity index; wasted fetches |
| CF-9 | LOW | `_store_validators` can pair a fresh ETag with a stale `Last-Modified` |
| CF-10 | LOW | `respx` intercepts below httpx header validation; no mocked test catches a bad UA |
| CF-11 | LOW | `ruff format --check`: 31 unformatted files; formatting is in no gate |
| CF-12 | LOW | Gate log `state=BLOCKED reason=successful_poll` is cosmetically misleading |
| CF-13 | UNPROVEN | No CCA/CCB CORRECTION seen live; supersession path fixture-covered only |

### Programme sequence (carried forward from 2026-08-30)

- **P1** — harden then supervise the quote tape (watchdog exiting non-zero on
  degradation, conversion-time integrity check, convert-and-prune retention,
  attended smoke run, then a systemd unit). Prices are the one irreplaceable
  stream. Three CRITICALs open: reconnect gives up then runs forever doing
  nothing; unclean shutdown silently voids a whole daily feather file; the
  `websocket.py`/`factories.py` pool rewrite is uncommitted.
- **P2** — two read-only probes: Open-Meteo `/v1/previous-runs`
  availability/depth, and whether IEM AFOS serves a forecast PIL.
- **P3** — forecast ingestion, scoped by whichever P2 branch wins. Breezy
  currently ingests **no forecast data at all**; every backtest forecast is
  synthetic.
- **P4** — daily-budget gate and portfolio-wide cap (see operator contract).
  BL-3 is the first increment.
- **P6** — wire boundary-conditional preliminary-revision cost into sizing;
  `min_model_edge=0.04` is plausibly smaller than the revision cost it covers.

### Blocked, with unlock condition

| ID | Item | Unlock |
|---|---|---|
| G-12 | Resolve `MARKET_SLUG_KEY` against the live venue | operator-gated venue access |
| G-13 | Gating live run of the recorder | operator-gated venue access |
| G-14 | Start continuous capture under systemd | G-13 |
| G-15 | Fee schedule discovery | operator-gated venue access |
| G-16 | Accumulate ≥14 days of joined tape | calendar: 14 days after G-14 |
| G-17 | Phase 1.5 premise falsification GO/NO-GO | G-16. **NO-GO stops the programme.** |

---

## Pointers

Durable rules `docs/core/LESSONS.md` (L-1..L-5, all binding) · evidence
`docs/evidence/` · plans `docs/plans/` · runbook
`docs/core/RUNBOOK_NWS_COLLECTION.md` · strategy authoring
`docs/specs/STRATEGY_QUICKSTART.md` · pre-shrink history `docs/core/archive/`
