# Breezy — Progress and Backlog

**This file tracks OPEN state only.** Closed work, resolution narratives and
evidence summaries do not live here. They live in git history,
`docs/evidence/`, and `docs/core/archive/`.

## Maintenance contract (BINDING, enforced)

- **Hard budget: 250 lines / 12 KB.** A `PostToolUse` hook
  (`.claude/hooks/progress-size-gate.sh`) fails any write that exceeds it.
- **An item leaves this file when it closes.** Do not rewrite it as a
  `[CLOSED]` narrative — delete it and let the commit be the record.
- **Never restate evidence here.** Link `docs/evidence/<file>.md` instead.
- **Never restate a durable rule here.** It belongs in `docs/core/LESSONS.md`.
- **Severity tags mark OPEN items only.** A `[HIGH]` heading over fixed work is
  the exact ambiguity that made the 76 KB predecessor unsafe.

Rationale: L-5 in `docs/core/LESSONS.md`. Pre-shrink copy:
`docs/core/archive/PROGRESS-pre-2026-08-31-backlog-replacement.md`.

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
- **G-01 — Prelim→final revision study: UNDERPOWERED.** N=44 vs floor N≥90/site.
  No PASS claim is valid. `docs/evidence/preliminary_final_revision_2026-08-26.md`.
- **Historical forecasts are NOT proven unavailable.** `CLI_BACKFILL_PLAN.md:46`
  claims otherwise from *repo state*, not availability. Open-Meteo
  `/v1/previous-runs` was deferred, never rejected. Still unverified.
- **Price history genuinely is forward-only.** No public trade tape; expired
  markets return null prices keeping only `settlementPx`.

---

## BACKLOG — selected for execution (opened 2026-08-31)

Source: the three-strategy backtest run of 2026-08-31 (36/36 runs COMPLETED;
report `~/.local/share/breezy/derived/strategy-backtests/weather_strategy_backtests_20260831T135804+0000.json`).

**Binding constraints on every item below.** No item may:
set `allow_short=True`; weaken `BacktestOrderGuard` or any settlement
invariant; relax a safety guard to go green; touch live-trading enablement or
the NO-SEND execution-egress firewall; or invent a value for an
operator-reserved control. Every increment carries an **L-1 null-hypothesis
verdict** citing installed source under
`.venv/lib/python3.13/site-packages/nautilus_trader/` before implementation.

### [HIGH] BL-1 — The stale-quote gate is vacuous

`strategy/weather_common/risk.py:287` passes a hardcoded `0.0` quote age into
`quote_tradable`, so `stale_quote_minutes` can never fire.
`forecast_mispricing` gates real quote age upstream
(`forecast_mispricing/decision.py:70-71`), but `calibration_mean_reversion` and
`forecast_revision` have **no other staleness protection** and can act on
arbitrarily stale quotes. Wire the real age through.

The in-code comment defers this to the operator; the operator control contract
above says otherwise — this is an engineering decision. The direction of effect
is strictly more conservative (it can only block orders that currently pass).

**Acceptance:** RED test proving a quote older than `stale_quote_minutes` is
refused for all three strategies (and one just inside the bound is not); the
"PRESERVED DEFECT" comment (`risk.py:261-286`) removed; the 36-run backtest
re-run with a written before/after fill count per strategy. L-2: state the UNIT
of the threaded age (minutes) and prove it matches `stale_quote_minutes`.
Note `risk.py:268` cites a stale `decision.py:68-70`; the real site is `:70-71`.

### [HIGH] BL-2 — A fully-gagged strategy reports as a clean completion

All 36 runs emitted `SHORTS_DISABLED_REFUSALS`, yet every JSON row carries
`status=COMPLETED, refusal_type=null, refusal_message=null`. Two of three
strategies had their **entire signal set** refused and are indistinguishable in
the report from a strategy that saw no opportunity. `forecast_revision`'s loud
`NakedShortRefusedError` abort has also become this silent path; commit
`4a1280f` is the *suspected* cause but its subject is about the close-only
guard and does not mention `allow_short` — **[INFERENCE, not verified]**, to be
confirmed or dropped by the implementer (L-4: `[V]` belongs on the inference).

**Acceptance:** per-run refusal counts and reasons propagate into report rows; a
run whose signals were all refused is not reported as an unqualified
`COMPLETED`.

### [MEDIUM] BL-4 — The `naive`/`realistic` backtest conditions are a no-op

All 18 pairs are byte-identical. `forecast_mispricing`'s "realistic" override
sets `allow_short=False`, already the default; the other two never reach a
timing gate because `SHORTS_DISABLED` fires first. The runner spends 18 extra
runs and claims two conditions while measuring one.

**Decision (pre-committed, not a disjunction):** COLLAPSE. Making the two
conditions differ behaviourally at current defaults would require flipping
`allow_short=True` (`:746`) or bypassing `SHORTS_DISABLED` — both forbidden by
the header. So the runner collapses to ONE condition and the two-condition
claim is deleted from the docstring.

**Acceptance:** one condition remains; run count drops 36 → 18; the surviving
run's per-row results are byte-identical to today's `naive` rows (proving the
collapse removed only duplication, not signal); no config default edited.

### [MEDIUM] BL-5 — Runner docstring states a default that does not exist

`scripts/analysis/run_weather_strategy_backtests.py:124` claims `allow_short`
"is left at its config default (`True`)" for `forecast_revision`. All three
configs default `False` (`*/config.py:99,115,112`).

**Acceptance:** docstring matches verified defaults and records that the
naked-short abort path is unreachable at defaults.

### [BLOCKER] BL-6 — Does a NO-side instrument exist in the captured tape?

Two of three strategies cannot execute because SHORT_YES has no legal
expression on this venue. Before any NO-side support is designed, answer
empirically and **offline**: do the 60 captured instruments contain the
complementary NO-side market for any of the 5 tradable YES buckets?

**Scope limit:** read-only against the existing capture. No live venue access,
no credentials, no network — the live probe is operator-gated and out of scope.

**Acceptance:** a written yes/no with instrument ids and evidence.

---

## Carried forward — open, not selected for this batch

| ID | Sev | Item |
|---|---|---|
| CF-1 | OPEN | Non-uniform record counts across sites (28/28/28/30/38) — extra MDW/LAX records are an unverified inference |
| CF-2 | MED | `never_substitute` declared in `registry/sites.toml` but no consumer reads it |
| CF-3 | MED | Unbounded whole-catalog reads per lookup (`persistence/catalog.py:693`); full scan per poll per site |
| CF-4 | MED | `is_record` parsed but not persisted; `tmax_flag` is `None` even on record days. Not a settlement defect |
| CF-5 | MED | Fail-closed parsing: one bad token blocks a whole site for that poll |
| CF-6 | MED | `tests/live/test_nws_live_ingest.py:86` hardcodes a personal contact address; must be a role address |
| CF-7 | MED | `BREEZY_USER_AGENT` required on offline construction paths (`SharedIngestState.__init__` builds `HttpTransport` unconditionally) |
| CF-8 | MED | Sibling-station products never marked in the integrity index; wasted body fetches on list change |
| CF-9 | LOW | `_store_validators` can pair a fresh ETag with a stale `Last-Modified` |
| CF-10 | LOW | `respx` intercepts below httpx header validation — no mocked test can catch a malformed UA |
| CF-11 | LOW | `ruff format --check` reports 31 unformatted files; formatting is in no gate |
| CF-12 | LOW | Gate log line `state=BLOCKED reason=successful_poll` is cosmetically misleading |
| CF-13 | UNPROVEN | No CCA/CCB CORRECTION product ever appeared live; supersession write path is fixture-covered only |

### Programme sequence (carried forward from 2026-08-30)

- **P1** — harden then supervise the quote tape (watchdog exiting non-zero on
  degradation, conversion-time integrity check, convert-and-prune retention,
  attended smoke run, then a systemd unit). Prices are the one irreplaceable
  stream. Three CRITICALs remain open: reconnect gives up and then runs forever
  doing nothing; an unclean shutdown silently voids an entire daily feather
  file; the `websocket.py`/`factories.py` pool rewrite is uncommitted.
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

- Durable rules: `docs/core/LESSONS.md` (L-1..L-5 — all binding)
- Evidence: `docs/evidence/` (32 files)
- Plans: `docs/plans/`
- Runbook: `docs/core/RUNBOOK_NWS_COLLECTION.md`
- Strategy authoring: `docs/specs/STRATEGY_QUICKSTART.md`
- Full pre-shrink history: `docs/core/archive/PROGRESS-pre-2026-08-31-backlog-replacement.md`
