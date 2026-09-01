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
- **`cli_settlement_print_lock` is REFUTED on real data (2026-09-01).** Two
  independent nulls on the same window: no legal window, and no ask. On all five
  stations the bucket containing the printed value carried **0 asks across 3332
  depth rows**. The settlement-truth edge is measured-certain and
  unexecutable. `docs/evidence/print_lock_refuted_2026-09-01.md`; rule L-7.
- **The book reprices on PHYSICAL determination, not on the print.** The NYC
  winner had no ask at 03:30Z -- 3 h BEFORE its final printed, ~10 h after its
  climate day ended. The ladder itself is liquid (2026-08-31: 18653/21985 rows
  carry an ask, 84.8%; 2026-09-01: 100424/100431, 100.0%); only the winning rung
  is unoffered. Any trigger anchored to a publication event arrives late by the
  publication lag. L-7 amendment.

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

### [HIGH] BL-24 — H3's Gate 0: does Breezy hold ANY intraday observation?

H3 needs `R(t)`, the running observed max, updated intraday and available with
no look-ahead. `running_extreme_lock` reads `observation.tmax_f`, which comes
from CLI PRELIMINARY/FINAL products -- end-of-period summaries, not intraday.
If no hourly/METAR/ASOS path exists, `R(t)` does not exist inside the bot and H3
is unimplementable until it does. Two look-ahead traps to settle in the same
pass: for FINALS `ts_event` is climate-day END, not the observed high's
measurement time; and `BacktestEngine` orders by `ts_init`, so a running max
built from measurement timestamps and stamped available afterwards LEAKS.

**Acceptance:** a cited YES/NO on intraday ingest; per-class `ts_event`/`ts_init`
provenance; and, if NO, the smallest native-first extension named against an
existing actor/data-client pattern. Observations are backfillable from the NWS
archive, so this gates H3's labelling, not today's capture.

### [MED] BL-21 — both tail-locks are outlier strategies; base rate unknown

H1 fired 0/4 and H2 0/4 on the first in-window capture; the venue lists one
`gte<N>f` and one `ltXf` per city-day, positioned outside the day's actual, so
the day lands in the interiors. The margin table was built by sweeping floors
in `[H-5,H]` the venue never lists. Pre-registered kill: trigger rate < 0.20
over captured station-days. Any ask/break-even comparison MUST gate on the
trigger first — an unfired tail shows pennies that read as free certainty.
`first_in_window_capture_2026-09-01.md`, `h2_lower_tail_rejected_2026-09-01.md`.

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

**Binding constraints on EVERY item in this file.** No item may: set
`allow_short=True`; weaken `BacktestOrderGuard` or any settlement invariant;
relax a safety guard to go green; touch live-trading enablement or the NO-SEND
egress firewall; or invent an operator-reserved value. Every increment carries
an **L-1 null-hypothesis verdict** citing installed source under
`.venv/lib/python3.13/site-packages/nautilus_trader/` first.

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
  irreplaceable stream. Exit-status and fail-closed supervision LANDED
  (79b9b44); the feather question is ANSWERED — see BL-23, which is the
  remaining P1 work. Still untested end-to-end: the native shutdown joint
  (`kernel.py:585` + `:613-638`) is confirmed by source, not by a live-node run.
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

**Immediate path to the ROI stop gate.** The observation family's
settlement-truth branch is closed (print-lock refuted). The live hypothesis is
**H3** (`docs/strategies/H3_intraday_running_max_lock.md`): buy the bucket
holding the running observed max `R(t)` after the diurnal peak, while the book
still offers it. Its Gate 0 is a DATA prerequisite, not a modelling one --
Breezy's ingest is CLI-product-driven and may hold no intraday observation at
all, in which case `R(t)` does not exist inside the bot. Sequence: settle Gate 0
-> keep the recorder alive through 2026-09-02 13:00Z so the 09-01 peak window
and its finals are both on tape -> label the 09-01 tape by `R(t)` -> H3 kill
criteria 1-4.

---

## Pointers

Durable rules `docs/core/LESSONS.md` (L-1..L-5, all binding) · evidence
`docs/evidence/` · plans `docs/plans/` · runbook
`docs/core/RUNBOOK_NWS_COLLECTION.md` · strategy authoring
`docs/specs/STRATEGY_QUICKSTART.md` · pre-shrink history `docs/core/archive/`
