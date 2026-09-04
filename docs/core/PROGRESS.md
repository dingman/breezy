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

### [MEDIUM] BL-24 — live R(t) LANDED: Seam A/A-2 (closed-closed interval fix `85170c0`), Seam B NWS actor `e9492bc` (flag-off, `BREEZY_LIVE_OBSERVATIONS`). Open: trim the 1.9 MB fixture; strategy wiring (step 6).

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
| CF-5b | MED | Route chronic `UNREADABLE` (CF-5, `71ad992`) through `AlertState`, not a bare per-poll WARNING |
| CF-6 | MED | `tests/live/test_nws_live_ingest.py:86` hardcodes a personal contact; use a role address |
| CF-7 | MED | `BREEZY_USER_AGENT` required on offline paths (`SharedIngestState.__init__`) |
| CF-8 | MED | Sibling-station products unmarked in integrity index; wasted fetches |
| BL-10 | LOW | `forecast_mispricing/decision.py:71` pre-signal `quote_tradable` refusal is invisible to BL-8's counter (family KILLED; moot until revived) |
| CF-11 | LOW | `ruff format --check`: 31 unformatted files; not in any gate |
| CF-14b | DEFERRED | Per-market discovery isolation; reopen only when the CF-14a tally (`2aa1e7f`) shows a genuine 1-of-N failure (`docs/plans/CF14_DISCOVERY_ISOLATION_2026-09-02.md`) |
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
**Write path — PLAN CONVERGED (Rev 7, `d1e8e33`); LANDED: R-6.5a `4f76137`, R-6.5P `38f2426`, R-6.5b-0 `43723a1`, ledger `e329667`, latch `5d41eaa`, R-6.5b write transport `757daba` (Grok build, 3 reviews); R-7 brief CONVERGED `docs/plans/R7_BUILD_BRIEF_2026-09-04.md`, Grok build in flight; PARKED at the operator step** (rest a BUY 1@$0.01, run `polymarket_us_write_signing_probe.py --positive-control`, expect `PREFLIGHT_NOT_EMPTY`). Grok builds, Claude verifies.
Ingest defect `252918a`: instrument definitions convert row-wise (re-emitted `ts_init` broke the native disjoint check every run); never identifier-filter `BinaryOption` queries.
R-7 rules still open (`docs/plans/EXEC_SPINE_R65_R7_2026-09-02.md`): authorization is the write closure's first positional; caps re-read per call; ledger releases only on 4xx+Status+no `order.id`; IOC zero-fill is terminal (R-7 brief converged); native inflight resolution DECLINED. The R-4 standing refusal stays until R-7 lands.

**Open from the blind-risk-view audit** (`docs/core/findings/BLIND_RISK_VIEWS_2026-09-02.md`):
T-9 exit policy (Grok: hold to settlement, entry-only halt, cancel working buys
at met lock, never dump into a 0.3-lot bid); T-6 stale node_config docstring;
`max_simultaneous_positions`
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
n≥150; today n_taken=1. **Live family = lags 30/45, NYC excluded, interval rule**
(`grok_live_small_spec_rev2_2026-09-04.md`); clock ~09-27 / ~10-30 at 3/day. Accrues via
`breezy-mb-daily.timer` (13:30Z) + `breezy-quote-tape-ingest.timer`. **The venue skips
~9% of station-days** (`docs/evidence/venue/polymarket_us/MISSING_COHORT_2026-09-02_2026-09-03.md`): add a week to each clock. **09-04 operator override: the M_B gate no longer parks the plumbing** — build the
write path (`docs/plans/EXEC_SPINE_NEXT_2026-09-04.md`, R-6.5b CONVERGED) and live R(t)
(`docs/plans/BL24_LIVE_RT_2026-09-04.md`); only enablement, budgets and the OP-1..OP-4
positive control stay operator-only. M_B's kill rule still binds the family. **current_rung_hold landed 09-04:** table `7babe06`, latch `19ea5fb`, config `15f04f4`, decision+legal-cell `348f9c8`, 6c scorer `43e38ff`, 6d tally `abcc1ad` (timer prepared, not activated), 6e BCa `6ddca6e`; PREREG v1 draft `docs/specs/PREREG_v1_current_rung_hold_2026-09-04.md`. Next: strategy (step 6), R-7.

---

## Pointers

2026-09-03: Kalshi plan `docs/plans/KALSHI_INTEGRATION_PLAN_2026-09-03.md` (plan
only, gated on the Polymarket.us E2E proof; 41 VERIFIED / 20 UNVERIFIED / 10 MISSING).
Polymarket.us docs re-check `docs/evidence/venue/polymarket_us/DOCS_RECHECK_2026-09-03.md`
(no venue max size; no retail idempotency key; fees/tick/min-qty unchanged;
`api.polymarket.us/v1/events` now 401s unauthenticated; public reads use the gateway).

Durable rules `docs/core/LESSONS.md` (L-1..L-13, all binding) · evidence
`docs/evidence/` · live plan `docs/plans/EXEC_SPINE_2026-09-01.md` · runbook
`docs/core/RUNBOOK_NWS_COLLECTION.md` · strategy authoring
`docs/specs/STRATEGY_QUICKSTART.md` · pre-shrink history `docs/core/archive/`
