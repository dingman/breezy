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
- **G-01 — Prelim→final revision: POWERED, FAIL** on MDW/NYC/SFO (Wilson-upper≤0.05); interior-bucket strategies dead there; open tails unaffected. `docs/evidence/observation_lock_falsification_2026-08-31.md`.
- **Lock strategies are DEAD on this venue — see LESSONS L-9.** Three families,
  three refutations, one mechanism: the near-certain rung is never offered. The
  ladder is liquid; only the winning rung is unoffered. Do not design a fourth.
- **Historical forecasts: NON-CONTIGUOUS (2022-01..2023-12 + present); a forecast archive is a CALIBRATION set, not a backtest** — prices are forward-only. `docs/evidence/open_meteo_previous_runs_probe_2026-08-31T005848Z/`.
- **Candidate #2 (CLI-basis boundary tail): edge REAL but THIN, NOT a GO** — corrected P(win|setup,h>=17)=12.3% (~1.9x BE); adverse selection unsettled (~245 resolved offered trades needed); offer-gate scan accumulates nightly 22:45Z. `docs/evidence/cli_basis_setup_win_rate_corrected_2026-09-02T061722Z.md`.
- **Venue weather surface (09-04) = 5 cities × daily HIGH only**: 3,743 climate markets, 100% parsed by the repo grammar, no other city or measure; Polymarket.us offers no station lever, Kalshi does. `docs/evidence/venue/polymarket_us/WEATHER_SURFACE_ENUMERATION_20260904T222013Z.md`.
- **Price history genuinely is forward-only.** No public trade tape; expired
  markets return null prices keeping only `settlementPx`.
- **No NO-side instrument exists (BL-6)** — NO is a side of the SAME book; P5 rescoped to `outcomeSide`/price inversion. `docs/evidence/no_side_instrument_probe_2026-08-31.md`.
- **Stale-quote gate wired but unreachable for short-only strategies (BL-1, proven by unit test only); `naive`/`realistic` conditions are NOT redundant (BL-4).**

---

## BACKLOG — selected for execution (opened 2026-08-31)

**Binding constraints on EVERY item in this file.** No item may: set
`allow_short=True`; weaken `BacktestOrderGuard` or any settlement invariant;
relax a safety guard to go green; touch live-trading enablement or the NO-SEND
egress firewall; or invent an operator-reserved value. Every increment carries
an **L-1 null-hypothesis verdict** citing installed source under
`.venv/lib/python3.13/site-packages/nautilus_trader/` first.

---

### Clock-speed track (opened 2026-09-04)
Time-to-verdict = independent station-days × take rate; one city on two venues is ONE weather event (Kalshi settles on The Weather Company, not the NWS CLI). Rulings: `docs/evidence/grok_*_2026-09-04.md`.
- **[HIGH] Kalshi sibling family on NEW stations** — plan `docs/plans/KALSHI_CRH_EXPANSION_PLAN_2026-09-04.md` Rev 3 (converged); PREREG draft `docs/specs/PREREG_v1_kalshi_current_rung_hold_DRAFT_2026-09-04.md`. 18/19 candidates pass temp cadence; KDEN excluded unless live 5-min resumes; KHOU archive hole. Open: S4 registry (in flight), S5–S7 read path, S8 per-station CLI-final-vs-TWC reconciliation (n≥90, Wilson-lower >0.99), S9 rev2 cells + `parse_metar_t_group` 4-digit fix (v1 table untouched). **Operator-only, critical path:** Kalshi account/KYC/eligibility/funding/API key (S11); fee-schedule PDF via a browser or first-fill θ derivation.
- **PREREG v2 REGISTERED 2026-09-05** (`4975fba`; spec BINDING §13, manifest `pm_us_crh_v2` d0=2026-09-05, v2 tally timer 15:30 UTC, n=0). C1–C4 and the admission exclusions ACKNOWLEDGED by the strategy lead (`grok_admission_exclusions_ack_2026-09-05.md`, `0f095b3`); Kalshi sibling stays DRAFT.
- **[LOW] Recorder salvage** de-dup relies on per-instance non-overlap (asserted). [LOW] commission `0.0111` exceeds price precision → `parse_fill_report` refuses → AMBIGUOUS (pre-existing; contract fixture adjusted).
- Rejected by ruling: SPRT α=0.05, plug-in-π Z, freeze-π, shadow/paper/archive/Kalshi rows in live n, retroactive scoring, `venue` column/stratum, qty>1, NYC, pooling venues.

## Carried forward — open, not selected for this batch

| ID | Sev | Item |
|---|---|---|
| CF-1 | OPEN | Non-uniform record counts (28/28/28/30/38); extra MDW/LAX an unverified inference |
| CF-2 | MED | `never_substitute` in `registry/sites.toml` has no consumer |
| CF-4 | MED | `is_record` parsed, never persisted; `tmax_flag` `None` on record days. Not a settlement defect |
| CF-5b | MED | Route chronic `UNREADABLE` (CF-5, `71ad992`) through `AlertState`, not a bare per-poll WARNING |
| CF-6 | MED | `tests/live/test_nws_live_ingest.py:86` hardcodes a personal contact; use a role address |
| CF-7 | MED | `BREEZY_USER_AGENT` required on offline paths (`SharedIngestState.__init__`) |
| CF-8 | MED | Sibling products never `observe()`d (`nws_actor.py:1161`); refetched every poll |
| BL-10 | LOW | `forecast_mispricing/decision.py:71` pre-signal `quote_tradable` refusal is invisible to BL-8's counter (family KILLED; moot until revived) |
| CF-11 | LOW | `ruff format --check`: 31 unformatted files; not in any gate |
| CF-14b | DEFERRED | Per-market discovery isolation; reopen on a genuine 1-of-N CF-14a failure (`docs/plans/CF14_DISCOVERY_ISOLATION_2026-09-02.md`) |
| CF-13 | UNPROVEN | No CCA/CCB CORRECTION seen live; supersession path fixture-covered only |
| PF-1 | MED | Perf residue 09-06: book levels parsed 2×/frame (`parsing.py:591`); CRH `is_consumed` SQLite/tick; salvage `collect=True` on 486 MB file |
| SV-1 | HIGH | 17:05Z self-check false NO_PERMIT: permit marker un-latched in drained log delta (`trade_supervisor.py:930`); fix pending restart |

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
**Write path VERIFIED 09-04** (R-6.5a..R-7 landed `4f76137..02bfd63`; OP-SEQ live positive control `CLOSED_YES_BOTH_VERBS`, `docs/plans/OP_SEQ_BOT_POSITIVE_CONTROL_2026-09-04.md`; `WRITE_CANONICAL_STRING_VERIFIED=True`; blocking controls: sealed order permit, 10h live-trading permit, caps, exact-`"1"` enablement). Grok builds, Claude verifies.
R-7 rules still open (`docs/plans/EXEC_SPINE_R65_R7_2026-09-02.md`): authorization is the write closure's first positional; caps re-read per call; ledger releases only on 4xx+Status+no `order.id`; IOC zero-fill is terminal (R-7 brief converged); native inflight resolution DECLINED. The R-4 standing refusal stays until R-7 lands.

**Open from the blind-risk-view audit** (`docs/core/findings/BLIND_RISK_VIEWS_2026-09-02.md`):
T-9 exit policy (Grok: hold to settlement, entry-only halt, cancel working buys
at met lock, never dump into a 0.3-lot bid); T-6 stale node_config docstring;
`max_simultaneous_positions`
unexercised end-to-end. Nautilus cannot cancel an INITIALIZED order.

**[VERDICT] NO FAMILY HAS A PROVEN EDGE; ONE IS UNDER LIVE MEASUREMENT.**
Forecast family KILLED; post-lock lock family REFUTED ×3 (L-9); K1 DEAD ≥2c (`docs/evidence/grok_*_2026-09-02.md`). **M_A**: the pre-lock afternoon window IS offered. **M_B** (kill n≥60 / survive n≥150, `grok_mb_kill_amendment_2026-09-02.md`): 09-04 run n_taken=2 (both 09-01, both lost); 09-02 VENUE-NEVER-LISTED, 09-03 lost to the recorder outage. **Live family** = lags 30/45, NYC excluded, interval rule (`grok_live_small_spec_rev2_2026-09-04.md`); accrues via `breezy-mb-daily.timer` 13:30Z + `breezy-live-tally.timer` 14:30Z (09-04 tally n=0). The venue skips ~9% of station-days (`MISSING_COHORT_2026-09-02_2026-09-03.md`). M_B's kill rule binds the family; the plumbing is no longer parked (operator 09-04).
**LIVE since 2026-09-04 17:54 UTC** (`BREEZY-L001`; supervisor pid 2231261 since 09-06 01:08Z on the fixed self-check code, launches 16:50Z daily, `docs/plans/R8_OPERATOR_RUNBOOK.md`; [LOW] its start line prints twice — stdout and file logger share the log). Permit audit visible since `f85a452`. OPEN:
- **First live order 09-05 20:19Z (SFO IOC @0.28) → AMBIGUOUS; venue shows no order/fill/position** (`docs/evidence/venue/polymarket_us/AMBIGUOUS_ORDER_2026-09-05_SFO/`). Intent RETIRED 01:08Z (OPERATOR_CLEARED, `no-order-exists`). n=0. Ruled 09-06 (`docs/evidence/codex_prereg_v2_rulings_2026-09-06.md`): zero-fill IOC and retired-AMBIGUOUS takes are takes, not trials (no n/k/S/I effect); `unresolved_takes.jsonl` never feeds the tally.
- **[HIGH] Structural-dead KILL automated `c21f9bf`**. Ruled 09-06: "covered" = recorder capture only (PREREG v2 §9); adding node liveness/permit/intent state is a §12 screen and is forbidden. Consequence: node-down or intent-blocked afternoons count toward the 15 — node uptime every listed afternoon is now a KILL-avoidance requirement. 09-06 14:15Z read: all four 09-05 station-days NOT covered (resolved QuoteTapeGap).
- Whole-tape paper replay `7e44abd` (`~/.local/share/breezy/derived/paper_replay/`): 12/12 CLEAN, 14 station-days, take **6/14 per arm**, 13 BLOCKED, NO VERDICT. Report still pooled `12/14`; regen feasible since 09-06 (n=1 80 s / 674 MB); run capped in a quiet window, never before 16:50Z.
- [LOW] `BREEZY-NWS` SubscribeData ERROR is cosmetic; recorder `887d2005` CORRUPT (6 truncated).
- Clock: 4 cities × 0.91 listed × take 0.25–0.43 ⇒ 0.9–1.6 trials/day; n=60 KILL 38–66 d. Kalshi S11 (KYC/funding/key) remains the only station lever and is operator-only.

---

## Pointers

Polymarket.us docs re-check `docs/evidence/venue/polymarket_us/DOCS_RECHECK_2026-09-03.md`.

Durable rules `docs/core/LESSONS.md` (L-1..L-13, all binding) · evidence
`docs/evidence/` · live plan `docs/plans/EXEC_SPINE_2026-09-01.md` · runbook
`docs/core/RUNBOOK_NWS_COLLECTION.md` · strategy authoring
`docs/specs/STRATEGY_QUICKSTART.md` · pre-shrink history `docs/core/archive/`
