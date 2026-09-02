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
- **Lock strategies are DEAD on this venue — see LESSONS L-9.** Three families,
  three refutations, one mechanism: the near-certain rung is never offered. The
  ladder is liquid; only the winning rung is unoffered. Do not design a fourth.
- **Historical forecasts exist but are NON-CONTIGUOUS.**
  `previous-runs-api.open-meteo.com/v1/forecast` yields **2022-01..2023-12 plus
  the present, hole between** (2024-01-01 = 0/168, every model); below 2022 was
  never probed. `docs/evidence/open_meteo_previous_runs_probe_2026-08-31T005848Z/`.
  IEM AFOS forecast PIL is reachable but FAILS its pre-registered bar (parse rate
  0.5125 vs >=0.9; attribution 238/240). **A forecast archive yields a
  CALIBRATION dataset, not a backtest** — a backtest also needs prices, and those
  are forward-only (next line).
- **Candidate #2 (CLI-basis boundary tail): edge REAL but THIN; NOT a GO.**
  Corrected `P(win|setup, h>=17)` = **12.3%** pooled (n=101,590, Wilson lower
  0.1213) -- ~1.9x the 0.06285 break-even; MDW weakest ~1.5x. An earlier 53%
  was inflated 4.4x by pre-peak hours (L-13 corollary) and is retracted. NYC
  DISCARDED (cadence artifact). **The one resolved live event LOST** (LAX
  2026-08-31, offered $0.01, settled 79 vs strike 80). **Adverse selection is
  unsettled and the archive cannot settle it**: separating a true 5% from 12%
  needs ~245 resolved offered trades, plausibly 1.5+ yr. Offer-gate scan runs
  nightly 22:45Z and accumulates unattended; sizing is capped at 250 contracts
  (`RiskLimits`), i.e. $2.50-$12.50/trade -- economics are thin by construction.
  `docs/evidence/cli_basis_setup_win_rate_corrected_2026-09-02T061722Z.md`.
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
  by unit test, NOT by backtest. Live only once shorts are expressible.
- **The `naive`/`realistic` conditions are NOT redundant** (BL-4).
  `forecast_revision` naive refuses nothing; realistic refuses 860
  `shorts_disabled`. Both stay.

---

## BACKLOG — observation-lock strategies (opened 2026-08-31)

Evidence: `docs/evidence/observation_lock_falsification_2026-08-31.md`.

### [HIGH] BL-24 — no intraday observation type exists in-bot

Gate 0 RESOLVED: no live intraday ingest (transport hardcodes CLI, two URL
builders, `_fetch` private at `ingest/http.py:769`), but ~5 yr of 5-min ASOS is
on disk. `R(t)` cannot enter a Nautilus
backtest — no `Data` subclass, no catalog wiring, no client. Plan (unreviewed):
`docs/plans/intraday_observation_ingest_2026-09-01.md` — peer-reviewed
2026-09-01: RESUME WITH AMENDMENTS (re-anchor off the dead lock predicate;
demote I-4; `build_running_max_days` at `pmr_climatology_study.py:351` is an
EXISTING untested fold to PORT, not author).

### [MED] BL-14 — `RefusalAlerter` alerts on `SHORTS_DISABLED` only

`refusals.py:134-151` hardcodes one condition, so a run refused entirely for
`stale_observation` / `observation_limit_unset` never alerts in live.
Generalise `_conditions` over the counted key set.

### [MED] BL-15 — `stale_forecast` fails open on a negative age (BL-9 class)

`risk.py` checks only `>`; a negative age looks infinitely fresh.
`quote_tradable` already guards this (`risk.py:278-279`). Needs its own
`future_signal` reason.

### [MED] BL-16 — `settlement_halt` is dead code; the 1.0h halt never fires

`risk.py:395-398` checks halt before `min_hours_to_settlement` (2.0h); a
decreasing clock always crosses 2.0 first. Decide if the two knobs are one.

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
| CF-1 | OPEN | Non-uniform record counts (28/28/28/30/38); extra MDW/LAX an unverified inference |
| CF-2 | MED | `never_substitute` in `registry/sites.toml` has no consumer |
| CF-3 | MED | Unbounded whole-catalog reads per lookup (`persistence/catalog.py:693`) |
| CF-4 | MED | `is_record` parsed, never persisted; `tmax_flag` `None` on record days. Not a settlement defect |
| CF-5 | MED | Fail-closed parsing: one bad token blocks a whole site for that poll |
| CF-6 | MED | `tests/live/test_nws_live_ingest.py:86` hardcodes a personal contact; use a role address |
| CF-7 | MED | `BREEZY_USER_AGENT` required on offline paths (`SharedIngestState.__init__`) |
| CF-8 | MED | Sibling-station products unmarked in integrity index; wasted fetches |
| CF-11 | LOW | `ruff format --check`: 31 unformatted files; not in any gate |
| CF-14 | MED | One bad market aborts the WHOLE discovery cycle; 1 blocked 30 new subs 09-02 (L-17) |
| CF-13 | UNPROVEN | No CCA/CCB CORRECTION seen live; supersession path fixture-covered only |

### Programme sequence (carried forward from 2026-08-30)

- **P1** — harden then supervise the quote tape; prices are the one
  irreplaceable stream. BL-23 is the remaining P1 work. Still untested end to
  end: the native shutdown joint (`kernel.py:585` + `:613-638`) is confirmed by
  source, not by a live-node run.
- **P2/P3** — forecast probes then ingestion. Breezy ingests **no forecast data
  at all**, so every forecast-strategy ROI is inadmissible. DEPRIORITISED; the
  observation family needs none. See (5).
- **P4** — daily-budget gate and portfolio-wide cap (see operator contract).
  BL-3 is the first increment.
- **P6** — wire boundary-conditional preliminary-revision cost into sizing;
  `min_model_edge=0.04` is plausibly smaller than the revision cost it covers.

### Blocked, with unlock condition

**Venue access is NO LONGER GATED** (operator, 2026-09-01); G-13/G-15 (fee
schedule discovery) are plain work items. Remaining blockers are technical:

| ID | Item | Unlock |
|---|---|---|
| G-16 | ≥14 days of joined tape | calendar |
| G-17 | Phase 1.5 premise GO/NO-GO | G-16. **NO-GO stops the programme.** |

**Programme path and the stop-gate constraint:** see
`docs/core/PROGRAMME_PATH.md` — why the stop gate is unsatisfiable by
backtest on this venue, and the ordered path (K1 → capture → EXEC SPINE →
forecast ingest → ~300 station-days → CAPACITY).

**EXEC SPINE follow-ups:** `docs/plans/EXEC_SPINE_2026-09-01.md` §R-4
"review amendments". Guard before R-9: divides by zero for an unpriced
forward; settlement-as-exit bypasses `_submit_order`'s refusal latch.
**R-4 gate: conditions MET, removal NOT taken.** The guard's three known
bypasses are closed — forged tags (70d68e8), `reduce_only` (e83b8e0), and both
cache-visibility holes (d7c6063, c5818cc). Removing the standing refusal
(`exec/client.py:1338-1350`) enables order sends and is a SEPARATE decision
needing its own review; the guard is also still DORMANT (`strategies=[]`).

**[HIGH, TRACKED] T-1 — the same blindness at the STRATEGY layer.**
`weather_common/risk.py:198-204` documents two independent covers for the
jointly-naked case; both call `cache.orders_open`, which is one query with a
hole. 14 call sites / 6 modules: 8 skip-gates, and 5 feeding
`_signed_open_order_qty`, so the risk snapshot's own in-flight view is blind
too. Correct that docstring in the same change.

---

## Pointers

Durable rules `docs/core/LESSONS.md` (L-1..L-13, all binding) · evidence
`docs/evidence/` · live plan `docs/plans/EXEC_SPINE_2026-09-01.md` · runbook
`docs/core/RUNBOOK_NWS_COLLECTION.md` · strategy authoring
`docs/specs/STRATEGY_QUICKSTART.md` · pre-shrink history `docs/core/archive/`
