# Live fill → scored-trial chain — read-only trace at HEAD (2026-09-05 ~00:45 UTC)

**Provenance.** Two independent code-explorer traces (codegraph + direct reads of
the cited lines; no bot run, no network). The first relied partly on a 09-02
plan doc and claimed the exec client "still refuses every order"; the second,
briefed to cite code only, refuted that. Findings below are the merged,
code-cited state. Day-1 live run (09-04) had zero orders, so nothing has been
lost yet; a real fill can occur on any trading day.

## What exists (code-cited)

| Hop | State | Citation |
|---|---|---|
| Strategy `Take` → `_maybe_submit` → `submit_order` | EXISTS | `strategy/current_rung_hold/strategy.py:513-539` |
| `_submit_order` gate chain (permit, `WRITE_CANONICAL_STRING_VERIFIED=True`, BUY-only mapping, `assert_live_order_submission_permitted`, ledger, intent latch) → `write_transport.post_order` → POST `/v1/orders` | EXISTS, SENDS | `exec/client.py:1511-1647`, `write_transport.py:52,179-196`, `submit_chain.py:216-253` |
| Synchronous IOC response → `classify_create_order_outcome` → `KIND_ACCEPT_FILL` → native `generate_order_filled` | EXISTS (fill event fires in-process; no WS/polling) | `submit_chain.py:440-493`, `client.py:1596-1612` |
| `OrderAccepted` | not emitted (synchronous accept-or-fill contract) | no call site in the adapter |
| Durable fill record `record_fill(DurableFillRecord)` → `exec/polymarket_us/fill/{venue_order_id}` | BUILT, **ZERO production callers** | `client.py:1315-1340`, `:328,337`; tests `test_polymarket_us_exec_client.py:950-1509` |
| Strategy `on_order_filled` | ABSENT (native no-op default) | `strategy.py` (no handler) |
| Reconciliation on restart: `generate_order_status_reports`, `generate_fill_reports` | STUBS returning `[]`; by-id `generate_order_status_report` is real but unused at startup | `client.py:987-1013`, `:938-961`, `:859-920` |
| Nautilus `Cache` persistence | memory-only by config | `runtime/node_config.py:217,499,759` (`CacheConfig(database=None)`) |
| Fill reader for scoring | JSONL PLACEHOLDER | `scripts/analysis/score_live_trials.py:255-295` |
| Scoring + store write + v2 sidecars | EXISTS (idle: no input) | `score_live_trials.py:402-525`, `settlement/trial_scorer.py`, `persistence/scored_trial_store.py` |
| Scheduling of the scorer | **NONE** — only the two readers are scheduled (14:30 v1, 15:30 v2) | `deploy/systemd/live-tally-run.sh`, `family-tally-v2-run.sh` |

## Consequence

A real fill today raises `OrderFilled` in the node (position tracked in memory
only) and leaves **no durable record** of `fill_px`, `qty`, `fee`, `filled_at_ns`.
The trial-day latch record (`current_rung_hold/trial/{station}/{climate_day}`,
written at decision time) survives, so the take is known but its fill is not.
Both tallies would report n = 0 forever. This is the blocker-register item
"Live fill → scored-trial chain is UNSCHEDULED" (PROGRESS.md), rated HIGH.

## Plan

`docs/plans/LIVE_FILL_SCORING_CHAIN_2026-09-05.md` (code-architect, peer
review pending): I1 call `record_fill` in the `KIND_ACCEPT_FILL` branch before
`generate_order_filled`; I2 a state-DB fill reader in `score_live_trials.py`
joined to the latch record, idempotent; I3 schedule the scoring step ahead of
both tallies; I4 (deferred unless required) real fill reports for restart
reconciliation.
