# Breezy — Progress and Backlog

**This file tracks OPEN state only.** Closed work, resolution narratives and
evidence summaries do not live here. They live in git history,
`docs/evidence/`, and `docs/core/archive/`.

## Maintenance contract (BINDING, enforced)

Hard budget **250 lines / 12 KB** (`.claude/hooks/progress-size-gate.sh`);
consolidate when it blocks, never raise it. An item LEAVES this file when it
closes — the commit is the record. Never restate evidence (link
`docs/evidence/`) or durable rules (`docs/core/LESSONS.md`). Severity tags mark
OPEN items only. Rationale L-5; pre-shrink copy in `docs/core/archive/`.

---

## Operator control contract (set 2026-08-30) — BINDING

The operator reserves exactly **two** controls; every other engineering
decision is delegated to the build side:

1. **Maximum daily budget.**
2. **Maximum per POSITION** — explicitly *not* per weather market.

**Values are not yet supplied and MUST be obtained before any live enablement.**

Two consequences that are not optional (tracked by P4):

- **The daily-budget control has no home.** `RiskLimits` (`risk.py:47-62`) has
  no time dimension; nothing enforces a daily notional or loss ceiling.
- **The per-position knob silently detunes the rest.** `max_event_notional`
  (1000) / `max_location_notional` (2000) are absolute dollars; only
  `max_equity_fraction` scales. No portfolio-wide `max_total_notional` exists.

---

## Standing verdicts that gate future work

- **Backtest ROI base: BL-17 resolved, not a code bug.** The `...T174940`
  report came from a script inode that no longer exists; all 12 others base on
  $10,000. Real-provenance ROI is **-0.054%**, not -5.41%.
  `docs/evidence/backtest_roi_measurement_2026-08-31.md`.

- **G-02 — ROI feasibility: NO-GO** on committing to the downstream adapter /
  settlement / execution build (~$3–15/day net per 100 contracts per city-day).
  Free falsification and tape capture stay in scope.
  `docs/evidence/roi_feasibility_2026-08-26.md`.
- **G-01 — Prelim→final revision: POWERED, FAIL** (superseded the N=44 run).
  AFOS archive N≈1820/site, same pre-registered rule: LAX/MIA PASS; **MDW 13.96%,
  NYC 11.79%, SFO 4.50% FAIL** Wilson-upper≤0.05. **Interior-bucket strategies
  are dead on MDW/NYC/SFO** (they need exact equality). Open tails unaffected:
  97% of revisions UPWARD, downward rate 0.21%.
  `docs/evidence/observation_lock_falsification_2026-08-31.md`.
- **Historical forecasts are NOT proven unavailable.** `CLI_BACKFILL_PLAN.md:46`
  claims otherwise from *repo state*, not availability. Open-Meteo
  `/v1/previous-runs` was deferred, never rejected. Still unverified.
- **Price history genuinely is forward-only.** No public trade tape; expired
  markets return null prices keeping only `settlementPx`.
- **There is no NO-side instrument, and there cannot be one** (BL-6). NO is a
  side of the SAME book; `parsing.py:_market_sides` refuses any side whose
  `identifier != slug`. **P5 rescoped** to "support `outcomeSide` / price
  inversion on the same instrument".
  `docs/evidence/no_side_instrument_probe_2026-08-31.md`.
- **The stale-quote gate is wired but unreachable for two of three strategies.**
  `evaluate_order` refuses `shorts_disabled` before calling `quote_tradable`
  (`risk.py:296-306`), and two strategies emit only shorts. BL-1's fix is proven
  by unit test, NOT by backtest (fills unchanged 24 -> 24, all
  `forecast_mispricing`). Live only once shorts are expressible.
- **The `naive`/`realistic` conditions are NOT redundant** (BL-4, reversed
  2026-08-31). `forecast_revision` naive refuses nothing; realistic refuses 860
  `shorts_disabled`. "Never signalled" is not "signalled 860 times, all
  refused." Both stay.

---

## BACKLOG — observation-lock strategies (opened 2026-08-31)

Evidence: `docs/evidence/observation_lock_falsification_2026-08-31.md`.

### [HIGH] BL-19 — shipped config refuses `running_extreme_lock`'s whole region

`min_model_edge=0.04` (`risk.py:100`, `config.py:113`, gated `risk.py:411`): at
p_model 0.9968 an ask of 0.970 gives edge 0.0268 < 0.04 -> refused; needs ask
<= ~0.957. `transaction_cost_prob=0.015` (`risk.py:116`) is ~25x the true fee at
p=0.99 (~0.0002; fee is `theta*C*p*(1-p)`, concave, max at p=0.50, so near-
certain contracts are nearly free). Break-even ask at margin 0 is 0.99663.
Decide these deliberately or a null capture reads as a dead market. Tick is
0.01, so 0.995 is not a real price.

### [MED] BL-21 — both tail-locks are outlier strategies; base rate unknown

H1 fired 0/4 and H2 0/4 on the first in-window capture; the venue lists one
`gte<N>f` and one `ltXf` per city-day, positioned outside the day's actual, so
the day lands in the interiors. The margin table was built by sweeping floors
in `[H-5,H]` the venue never lists. Pre-registered kill: trigger rate < 0.20
over captured station-days. Any ask/break-even comparison MUST gate on the
trigger first — an unfired tail shows pennies that read as free certainty.
`first_in_window_capture_2026-09-01.md`, `h2_lower_tail_rejected_2026-09-01.md`.

### [LOW] BL-22 — 60 spurious `cache.instrument is None` ERRORs per cycle

Cosmetic, data is sound: the check runs with no `await` after publishing
(`data.py:720-721`) so the engine has not processed yet; the authoritative gate
at `:724` passes, and WS frames resolve via `_instrument_provider.find()` first
(`:1020-1022`). Fix before an unattended run or it buries real errors.

### [HIGH] BL-13 — build `cli_settlement_print_lock` (NOW THE LEAD STRATEGY)

Both tail-locks are outlier strategies against the measured ladder: a six-rung
ladder centred on the forecast is a WINDOW around the expected max, so the
interiors catch the mode and both open tails are the outlier rungs. Measured
2026-08-31: H1 (upper) fired 0/4, H2 (lower) fired 0/4.
`docs/evidence/h2_lower_tail_rejected_2026-09-01.md`.

Print-lock triggers on the FINAL CLI print and buys YES on the unique bucket
CONTAINING the printed value — usually an interior, so it is designed to fire on
most station-days. This does NOT contradict G-01: interiors are dead AFTER THE
PRELIMINARY (revision breaks exact equality) but sound AFTER THE FINAL (the
revision already happened). p_stable 99.989% (9105/9106), halt-window 98.66%
(9041/9164). Long-only, taker, no forecast, exclusive-bucket logic already in
`RiskManager`.

**Its capture window is 05:00-13:00Z, NOT the evening.** Evening tape only
measures tail reachability; morning tape tests the strategy that can fire.

### [MED] BL-14 — `RefusalAlerter` alerts on `SHORTS_DISABLED` only

`refusals.py:134-151` hardcodes one condition, so a run refused entirely for
`stale_observation` / `observation_limit_unset` never alerts in live.
Generalise `_conditions` over the counted key set.

### [MED] BL-15 — `stale_forecast` fails open on a negative age (BL-9 class)

`risk.py` checks only `>`; a negative age looks infinitely fresh.
`quote_tradable` already guards this (`risk.py:278-279`). Needs its own
`future_signal` reason.

### [MED] BL-16 — `settlement_halt` is dead code; the 1.0h halt never fires

`risk.py:395-398` checks halt (1.0h) before `min_hours_to_settlement` (2.0h); a
decreasing clock always crosses 2.0 first. Decide if the two knobs are one.

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
market conditions (BL-8 drew that line at "the strategy formed an order"), then
either count it under the same bounded key set or document why not.

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

- **P1** — harden then supervise the quote tape; prices are the one
  irreplaceable stream. CONFIRMED open: reconnect exhaustion sets `_degraded`
  and RETURNS (`websocket.py:678-684`), so the supervisor ends and the node runs
  forever doing nothing — must exit non-zero for systemd. UNVERIFIED: whether
  unclean shutdown voids a daily feather file (read the writer close path).
- **P2/P3** — forecast probes (Open-Meteo `/v1/previous-runs`; IEM AFOS forecast
  PIL) then forecast ingestion. Breezy ingests **no forecast data at all**, so
  every forecast-strategy ROI is inadmissible until P3 lands. DEPRIORITISED:
  the observation family needs no forecast and is the route to the stop gate.
- **P4** — daily-budget gate and portfolio-wide cap (see operator contract).
  BL-3 is the first increment.
- **P6** — wire boundary-conditional preliminary-revision cost into sizing;
  `min_model_edge=0.04` is plausibly smaller than the revision cost it covers.

### Blocked, with unlock condition

**Venue access is NO LONGER GATED** (operator, 2026-09-01). G-12/G-13/G-15 are
released; the remaining blockers are technical, not permission.

G-12 (resolve `MARKET_SLUG_KEY` live) and G-15 (fee schedule discovery) are now
plain work items, no longer blocked. Still blocked:

| ID | Item | Unlock |
|---|---|---|
| G-14 | Continuous capture under systemd | P1 recorder CRITICALs |
| G-16 | ≥14 days of joined tape | calendar: 14 days after G-14 |
| G-17 | Phase 1.5 premise GO/NO-GO | G-16. **NO-GO stops the programme.** |

**Immediate path to the ROI stop gate** (`docs/specs/CAPTURE_SPEC_OBSERVATION_GATE0.md`):
BL-18 parser fix -> Gate 0A screening capture (3 station-days, 19:00-01:00Z,
five UPPER-tail slugs, pre-registered kill at median ask >= 0.99663) -> P1
recorder hardening -> Gate 0B (>=14 station-days) -> observation backtest.

---

## Pointers

Durable rules `docs/core/LESSONS.md` (L-1..L-5, all binding) · evidence
`docs/evidence/` · plans `docs/plans/` · runbook
`docs/core/RUNBOOK_NWS_COLLECTION.md` · strategy authoring
`docs/specs/STRATEGY_QUICKSTART.md` · pre-shrink history `docs/core/archive/`
