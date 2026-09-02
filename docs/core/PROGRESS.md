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

- **Backtest ROI base:** real-provenance ROI is **-0.054%**, not -5.41%
  (BL-17 closed). `docs/evidence/backtest_roi_measurement_2026-08-31.md`.

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
- **Candidate family #2 (CLI-basis boundary tail): archive gate PASSED, NOT a
  GO.** `P(CLI_final >= R+1)` clears the 0.06285 break-even on LAX/MIA/SFO/MDW
  (16-26%). **NYC is DISCARDED** -- its 56-60% is a station-cadence artifact
  (KNYC hourly; downsampling the dense four reproduces it exactly, L-13). The
  "late-day" framing is dead: `P(R_17==R_23)`=99.4%, so this is the
  UNCONDITIONAL CLI-vs-ASOS basis and entry is headroom-triggered at any hour.
  The binding test is the live OFFER GATE -- whether the venue ever offers that
  tail at <=0.05 in takeable size -- which is what killed the prior three
  families and is unanswerable from any archive.
  `docs/evidence/cli_basis_boundary_study_2026-09-02T044737Z.md`.
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
| CF-1 | OPEN | Non-uniform record counts (28/28/28/30/38); extra MDW/LAX records an unverified inference |
| CF-2 | MED | `never_substitute` in `registry/sites.toml` has no consumer |
| CF-3 | MED | Unbounded whole-catalog reads per lookup (`persistence/catalog.py:693`) |
| CF-4 | MED | `is_record` parsed, never persisted; `tmax_flag` `None` on record days. Not a settlement defect |
| CF-5 | MED | Fail-closed parsing: one bad token blocks a whole site for that poll |
| CF-6 | MED | `tests/live/test_nws_live_ingest.py:86` hardcodes a personal contact; must be a role address |
| CF-7 | MED | `BREEZY_USER_AGENT` required on offline paths (`SharedIngestState.__init__`) |
| CF-8 | MED | Sibling-station products unmarked in the integrity index; wasted fetches |
| CF-11 | LOW | `ruff format --check`: 31 unformatted files; formatting is in no gate |
| CF-13 | UNPROVEN | No CCA/CCB CORRECTION seen live; supersession path fixture-covered only |

### Programme sequence (carried forward from 2026-08-30)

- **P1** — harden then supervise the quote tape; prices are the one
  irreplaceable stream. BL-23 is the remaining P1 work. Still untested end to
  end: the native shutdown joint (`kernel.py:585` + `:613-638`) is confirmed by
  source, not by a live-node run.
- **P2/P3** — forecast probes then ingestion. Breezy ingests **no forecast data
  at all**, so every forecast-strategy ROI is inadmissible. DEPRIORITISED; the
  observation family needs no forecast. See item (5) below.
- **P4** — daily-budget gate and portfolio-wide cap (see operator contract).
  BL-3 is the first increment.
- **P6** — wire boundary-conditional preliminary-revision cost into sizing;
  `min_model_edge=0.04` is plausibly smaller than the revision cost it covers.

### Blocked, with unlock condition

**Venue access is NO LONGER GATED** (operator, 2026-09-01): G-12 (resolve
`MARKET_SLUG_KEY` live), G-13 and G-15 (fee schedule discovery) are plain work
items now. The remaining blockers are technical, not permission:

| ID | Item | Unlock |
|---|---|---|
| G-14 | Continuous capture under systemd | P1 recorder CRITICALs |
| G-16 | ≥14 days of joined tape | calendar: 14 days after G-14 |
| G-17 | Phase 1.5 premise GO/NO-GO | G-16. **NO-GO stops the programme.** |

**The stop gate as written is UNSATISFIABLE by backtest on this venue.** ROI is
a function of fill prices; price history is forward-only, so no amount of weather
or forecast data produces a historical ROI. Both P2 probe reports say it
outright: a forecast archive yields a CALIBRATION dataset, not a backtest.
Measured: total addressable notional at any eventually-winning rung is **$0.574**
(NEGATIVE after fees; refused by `min_liquidity_contracts=25`). Power: sigma/mu
~ 8, so n ~ 300 station-days (~60 clean days at 5 stations) to clear break-even.

**Ordered path to a real-money ROI verdict (revised 2026-09-01):** (1) BL-25
DONE; (2) K1 gates the calibration family BEFORE any forecast build —
`docs/evidence/k1_cheap_open_2026-09-01.md`. Measured n=0; 30 D+1 entries are
captured (09-01) and enter the population once their CLI goes FINAL — missing is
elapsed time, not code. Viable at ask<=0.03 in ~20d / <=0.05 in ~9d; the 0.01
tick needs ~359d, so no plan may wait on it. Re-runs daily, unattended; (3) capture supervised to 2026-10-01 (D+1 book exists only if the recorder
runs before local midnight); (4) execute the EXEC SPINE R-1..R-9
(`docs/plans/EXEC_SPINE_2026-09-01.md`). **R-1/R-2/R-3 LANDED** (2788d11).
R-4 publishes the first AccountState and is what de-inerts every Nautilus cap
(`risk/engine.pyx:682-692` returns True with no account); (5) forecast ingest (`docs/plans/forecast_ingest_2026-09-01.md`)
HELD until K1 reports; (6) accumulate ~300 station-days; (7) settle CAPACITY.
Backtest stays frozen in the REFUTATION + plumbing role: offer survival is a
counterfactual about the venue's reaction to OUR order, recorded nowhere.

**EXEC SPINE follow-ups (R-4 + its 2026-09-02 review):** see
`docs/plans/EXEC_SPINE_2026-09-01.md` §R-4 "review amendments". Most
dangerous: R-9's per-trade return divides by zero for an unpriced forward and
settlement-as-exit bypasses `_submit_order`'s refusal latch — both must be
guarded before R-9 lands.

---

## Pointers

Durable rules `docs/core/LESSONS.md` (L-1..L-13, all binding) · evidence
`docs/evidence/` · live plan `docs/plans/EXEC_SPINE_2026-09-01.md` · runbook
`docs/core/RUNBOOK_NWS_COLLECTION.md` · strategy authoring
`docs/specs/STRATEGY_QUICKSTART.md` · pre-shrink history `docs/core/archive/`
