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
| BL-10 | LOW | `forecast_mispricing/decision.py:71` pre-signal `quote_tradable` refusal is invisible to BL-8's counter (family KILLED; moot until revived) |
| CF-11 | LOW | `ruff format --check`: 31 unformatted files; not in any gate |
| CF-14 | MED | One bad market aborts the WHOLE discovery cycle; 1 blocked 30 new subs 09-02 (L-17) |
| CF-13 | UNPROVEN | No CCA/CCB CORRECTION seen live; supersession path fixture-covered only |

### Programme sequence

P1–P6 narrative moved to `docs/core/PROGRAMME_PATH.md` (size gate). Active P-work is tracked as backlog IDs above.

### Blocked, with unlock condition

**Venue access is NO LONGER GATED** (operator, 2026-09-01); G-13/G-15 (fee
schedule discovery) are plain work items. Remaining blockers are technical:

| ID | Item | Unlock |
|---|---|---|
| G-16 | ≥14 days of joined tape. K1 09-02: n=30, largest cell 8/96. **Kalshi prior `e97f392`: cheap-D-1 DEAD at ask ≥2c, 2023+, all 5 stations** (`docs/evidence/k1_kalshi_prior_2026-09-02.md`) | calendar |
| G-17 | Phase 1.5 premise GO/NO-GO | G-16. **NO-GO stops the programme.** |

**Programme path and the stop-gate constraint:** see
`docs/core/PROGRAMME_PATH.md` — why the stop gate is unsatisfiable by
backtest on this venue, and the ordered path (K1 → capture → EXEC SPINE →
forecast ingest → ~300 station-days → CAPACITY).

**EXEC SPINE follow-ups:** `docs/plans/EXEC_SPINE_2026-09-01.md` §R-4
"review amendments". Guard before R-9: divides by zero for an unpriced
forward; settlement-as-exit bypasses `_submit_order`'s refusal latch.
**Write path — PLAN CONVERGED (Rev 6, `ab399c3`); R-6.5a `4f76137` + R-6.5P `38f2426` LANDED; PARKED at the operator step** (rest a BUY 1@$0.01, run `polymarket_us_write_signing_probe.py --positive-control`, expect `PREFLIGHT_NOT_EMPTY`).
`docs/plans/EXEC_SPINE_R65_R7_2026-09-02.md`: four blind reviews + two
confirmers. Order: R-6.5a (seam: `private_read` discards `response.status`,
so R-6d's classifier is unreachable; zero barrier changes) → R-6.5P (probe;
OQ-B answered by mechanism — operator rests BUY 1@$0.01, probe must refuse
`PREFLIGHT_NOT_EMPTY`; preview WITHDRAWN, OQ-3 unproven) → R-6.5b (write
transport in a small `write_transport.py`, B4 exemption is a NARROWING) →
R-7 (authorization is the write closure's first positional; caps re-read per
call; ledger releases only on 4xx+Status+no `order.id`; fee floor is an R-8
precondition; native inflight resolution DECLINED — it guesses). The R-4
standing refusal stays until R-7: with no send path, removing it deletes the
only DENIAL. B4 evasions found by that review (`nautilus_pyo3.http_post`,
C1–C5-blind helper) CLOSED `5221da3` (V5 + C6, 13 tests).

**Open from the blind-risk-view audit** (`docs/core/findings/BLIND_RISK_VIEWS_2026-09-02.md`):
T-9 exit policy (Grok: hold to settlement, entry-only halt, cancel working buys
at met lock, never dump into a 0.3-lot bid); T-6 stale node_config docstring;
T-10 reversed-arg `hours_until` in scripts/; `max_simultaneous_positions`
unexercised end-to-end. Nautilus cannot cancel an INITIALIZED order.

**[VERDICT] NO FAMILY HAS A PROVEN EDGE; ONE IS UNDER MEASUREMENT (M_B).**
Forecast family KILLED (`grok_forecast_family_verdict_2026-09-02.md`). Post-lock
observation family REFUTED on execution ×3 (L-9). Cheap-D-1 (K1) DEAD ≥2c on
Kalshi, n=0 here. Grok (`grok_no_edge_verdict_2026-09-02.md`): no long-only
edge; measure once, then stop. **M_A** (`ma_prelock_winner_ask_2026-09-02.md`):
the PRE-lock afternoon window IS offered — 09-01 winner at 0.21×25 (MDW),
0.65×18 (SFO) while R(t) in-rung. **M_B** (`mb_current_rung_edge_2026-09-02.md`,
archive p_hold AUDITED correct; kill amended `grok_mb_kill_amendment_2026-09-02.md`):
realized hold of taken current-rung trials vs ask+fee — kill n≥60, survive
n≥150; today n_taken=1. Clock: ~09-22 / ~10-21 at 3/day. Accrues via
`breezy-mb-daily.timer` (13:30Z) + `breezy-quote-tape-ingest.timer`. **No new
strategy package, BL-24, forecast ingest, or R-6.5b/R-7 until M_B survives.**

---

## Pointers

Durable rules `docs/core/LESSONS.md` (L-1..L-13, all binding) · evidence
`docs/evidence/` · live plan `docs/plans/EXEC_SPINE_2026-09-01.md` · runbook
`docs/core/RUNBOOK_NWS_COLLECTION.md` · strategy authoring
`docs/specs/STRATEGY_QUICKSTART.md` · pre-shrink history `docs/core/archive/`
