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

Two reserved controls: **maximum daily budget** and **maximum per POSITION**
(not per market). Values supplied 09-04; the two caps may live ONLY in the
operator's gitignored `operator.env` at the repo root (never committed, never
written by the build side), still present by NAME in the running supervisor/node
env (verified 09-06). Enforced per grant by `DailySpendLedger.authorize_order_cost`
(`operator_controls.py:299-373`). Everything else is build-side.

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

## BACKLOG — selected for execution (opened 2026-09-06): GO-LIVE BLOCKERS

**Binding constraints on EVERY item in this file.** No item may: set
`allow_short=True`; weaken `BacktestOrderGuard` or any settlement invariant;
relax a safety guard to go green; touch live-trading enablement or the NO-SEND
egress firewall; or invent an operator-reserved value. Every increment carries
an **L-1 null-hypothesis verdict** citing installed source under
`.venv/lib/python3.13/site-packages/nautilus_trader/` first.

Merged analysis, evidence and unlock observables: `docs/evidence/GO_LIVE_BLOCKERS_2026-09-06.md`. Owner B = build, O = operator.

| ID | Own | Sev | Blocker (evidence in the doc) | Size |
|---|---|---|---|---|
| GL-1 | B | CRIT | GL-1a shipped (`9ad11ff`): every create-order outcome carries redacted `body_kind`/`body_len`/`state=`/`cum=` tokens and `_submit_order` logs them for every kind (L-30). RULING REQUESTED: amend R-7 item 5 or resolve zero-fills via a GET /v1/order/{id} state read designed with GL-4 (L-32) | M |
| GL-4 | B | HIGH | One AMBIGUOUS burns the rest of the day: latch OPEN until operator (`client.py:1747-1758`), `_has_durable_fill_record` stub (`:730-733`). Auto-retire after a no-order probe | M |
| GL-5 | B | CRIT | WS reconnect storm: 09-05 189/241/281 five-second gaps per station window, 1673 reconnects → every afternoon uncovered under §9 any-overlap (`data.py:1685,1812`, `websocket.py`). 09-06 instance clean so far | L |
| GL-6 | O | MED | Operator action remaining: `systemctl --user daemon-reload && systemctl --user restart breezy-pm-crh-v2-tally.timer`. The 17:15Z tick is inert until that reload runs | S |
| GL-7 | O | SKIP | Operator 09-06: skip. Supervisor 2231261 + node stay in the uncapped `tmux-spawn-d35977dd` scope; SV-1 fix `c84317e` inactive until a relaunch | — |
| GL-8 | B | MED | Instrument set frozen at 16:50 compose (`composition.py:116-150`), discovery reload clamped 21600 s: late-listed HIGH rungs never subscribed | M |
| GL-9 | B | MED | Fill→ScoredTrial chain never run on real data (`record_fill` branch unexecuted, store has no parquet). Synthetic 200+fill body through the live chain in a test, then confirm on first fill | M |
| GL-10 | O/B | DEFER | Operator 09-06: deprioritised. Alerts stay log-only (no `BREEZY_ALERT_WEBHOOK_URL`) | — |
| GL-11 | B | LOW | Recorder OOM 09-04 (14.4 GB) / SIGKILL 09-05 at MemoryHigh predate the deque fix; 09-06 peak 914 MB. Watch | — |
| GL-12 | B | CRIT | Recorder is a zombie since the 09:00Z rotate: `try-restart` lands in the recurrent 02:00 PT empty-climate-listing hole, the initial `initialize()` raise is outside the 09-04 fail-fast wrap (`6fcadae` wraps only `_feed.connect()`), and Nautilus stays RUNNING after the 60 s engine timeout, so systemd never restarts it (13 h / 0 quotes on 09-06; 09-06 afternoons uncovered). Fix ranked: (1) retry empty discovery on initial `_connect` with backoff, (2) widen the fail-fast wrap to all of `_connect` + exit 1, (3) move the rotate tick past ~09:45Z listing; operator restore now: `systemctl --user try-restart breezy-quote-tape.service` | M |

**KILL clock:** D0=09-05, counter 0 (09-05 uncovered; 09-06 uncovered (recorder)); at 4 covered/day with 0 fills the 15th lands ~09-09/09-10 and zero-fill/retired-AMBIGUOUS takes are not trials. GL-2 and GL-3 landed; GL-1 reclassification is under ruling before the first clean covered cluster.

Verified NOT blockers 09-06: exec client connected + reconciled, balances 97.91, permit issued, caps/enablement present, OP-SEQ control CLOSED (GTC only), obs feed live, 24 rungs subscribed, rotation 09:00Z outside every window.

### LADDER_EV (opened 2026-09-07)
- [MED] LADDER_EV whole-ladder EV scanner: design v2 peer-reviewed, `docs/strategies/breezy_strategy_ladder_ev_2026-09-07.md`. DEGRADED-only; shadow while CRH live; census 09-07 train 7/15 covered days ⇒ §12 kill INSUFFICIENT DATA. Stage 1 pure modules landed (42 tests, 2 reviews). Next: stage 2 strategy.py + 6-rung freeze + kill script.

### Clock-speed track (opened 2026-09-04)
- **[HIGH] Kalshi sibling family on NEW stations** — plan `docs/plans/KALSHI_CRH_EXPANSION_PLAN_2026-09-04.md` Rev 3; PREREG draft `docs/specs/PREREG_v1_kalshi_current_rung_hold_DRAFT_2026-09-04.md`. Open: S4 registry (`wip/kalshi-s4-registry`), S5–S7 read path, S8 CLI-final-vs-TWC reconciliation (n≥90), S9 rev2 cells. **Operator-only:** Kalshi account/KYC/funding/API key (S11); fee schedule. Not prioritised until Polymarket.us fills (operator 09-04).
- **PREREG v2 REGISTERED 2026-09-05** (`4975fba`; spec BINDING §13, manifest `pm_us_crh_v2` d0=2026-09-05, v2 tally 15:30Z, n=0). C1–C4 and exclusions ACKNOWLEDGED (`grok_admission_exclusions_ack_2026-09-05.md`). Rejected by ruling: SPRT α=0.05, plug-in-π Z, freeze-π, shadow/paper/archive/Kalshi rows in live n, retroactive scoring, `venue` stratum, qty>1, NYC, pooling venues.
- [LOW] Recorder salvage de-dup relies on per-instance non-overlap (asserted).

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
| CF-12 | MED | `uv run ruff check .` reports 24 errors and `uv run mypy` 313 errors in 31 files on the branch base, none in this session's files |
| CF-14b | DEFERRED | Per-market discovery isolation; reopen on a genuine 1-of-N CF-14a failure (`docs/plans/CF14_DISCOVERY_ISOLATION_2026-09-02.md`) |
| CF-13 | UNPROVEN | No CCA/CCB CORRECTION seen live; supersession path fixture-covered only |
| PF-1 | MED | Perf residue 09-06: book levels parsed 2×/frame (`parsing.py:591`); CRH `is_consumed` SQLite/tick; salvage `collect=True` on 486 MB file |


### Programme sequence

P1–P6 narrative: `docs/core/PROGRAMME_PATH.md`. Active P-work is tracked as backlog IDs above.

### Blocked, with unlock condition

| ID | Item | Unlock |
|---|---|---|
| G-16 | ≥14 days of joined tape. K1 09-02: n=30, largest cell 8/96. Kalshi prior `e97f392`: cheap-D-1 DEAD at ask ≥2c (`docs/evidence/k1_kalshi_prior_2026-09-02.md`) | calendar |
| G-17 | Phase 1.5 premise GO/NO-GO | G-16. **NO-GO stops the programme.** |

EXEC SPINE: write path verified 09-04 (`docs/plans/OP_SEQ_BOT_POSITIVE_CONTROL_2026-09-04.md`); R-7 rules still open (`docs/plans/EXEC_SPINE_R65_R7_2026-09-02.md`): IOC zero-fill is terminal (GL-1 ruling requested; see GL-1 row), ledger releases only on 4xx+Status+no `order.id`. Blind-risk-view audit residue (`docs/core/findings/BLIND_RISK_VIEWS_2026-09-02.md`): T-9 exit policy, T-6 stale docstring, `max_simultaneous_positions` unexercised; Nautilus cannot cancel an INITIALIZED order.

**[VERDICT] NO FAMILY HAS A PROVEN EDGE; ONE IS UNDER LIVE MEASUREMENT.** Forecast family KILLED; lock family REFUTED ×3 (L-9); K1 DEAD ≥2c. M_B (kill n≥60 / survive n≥150): 09-04 n_taken=2, both lost. Live family = lags 30/45, NYC excluded, interval rule (`grok_live_small_spec_rev2_2026-09-04.md`); tallies 13:30Z/14:15Z/14:30Z/15:30Z. Venue skips ~9% of station-days.
**LIVE since 2026-09-04 17:54 UTC** (`BREEZY-L001`; supervisor pid 2231261 since 09-06 01:08Z, launches 16:50Z daily, `docs/plans/R8_OPERATOR_RUNBOOK.md`; [LOW] start line prints twice). Live: 8 listed afternoons, take 1 (SFO 09-05 → AMBIGUOUS, retired), fill 0, n=0.
- Whole-tape paper replay `7e44abd`: 12/12 CLEAN, take **6/14 per arm**, 13 BLOCKED, NO VERDICT; regen feasible since 09-06 (n=1 80 s / 674 MB), run capped in a quiet window, never before 16:50Z.
- [LOW] `BREEZY-NWS` SubscribeData ERROR is cosmetic; recorder `887d2005` CORRUPT (6 truncated).
- Clock: 4 cities × 0.91 listed × take 0.25–0.43 ⇒ 0.9–1.6 trials/day; n=60 KILL 38–66 d. Kalshi S11 is the only station lever and is operator-only.

---

## Pointers

Polymarket.us docs re-check `docs/evidence/venue/polymarket_us/DOCS_RECHECK_2026-09-03.md`.

Durable rules `docs/core/LESSONS.md` (L-1..L-13, all binding) · evidence
`docs/evidence/` · live plan `docs/plans/EXEC_SPINE_2026-09-01.md` · runbook
`docs/core/RUNBOOK_NWS_COLLECTION.md` · strategy authoring
`docs/specs/STRATEGY_QUICKSTART.md` · pre-shrink history `docs/core/archive/`
