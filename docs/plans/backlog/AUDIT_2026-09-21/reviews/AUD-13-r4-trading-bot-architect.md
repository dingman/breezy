# AUD-13 round-4 review — trading-bot-architect

Plan: AUD-13-native-venue-reconciliation-from-durable-records.md
SHA256: d5cbd9a06f4b460bee5fc946694868796dbd0c19c59a89ba819f01b443907d06
Round: 4 (FINAL)
Reviewer: trading-bot-architect

## Claims verified against source (this session, read-only)

| Claim | Verdict |
|---|---|
| `kernel.start(self)` (`:989`) has no early return; body runs `_emulator.start()` (`:999`), `_initialize_portfolio()` (`:1000`), `_trader.start()` (`:1001`) unconditionally | CONFIRMED (`.venv/.../nautilus_trader/system/kernel.py:989,999-1001`) |
| `start_async(self)` (`:1003`) — `_await_engines_connected` false → `return` at `:1025`; `if self.exec_engine.reconciliation:` at `:1027`, `_await_execution_reconciliation` false → `return` at `:1029`; else WARN at `:1031`; `_emulator.start()` `:1033`, `_initialize_portfolio()` `:1034`; `_await_portfolio_initialization` false → `return` at `:1037`; `_trader.start()` at `:1039` | CONFIRMED line-for-line, read directly (`kernel.py:1020-1039`) |
| `TradingNode.run()` (`live/node.py:283`) awaits `kernel.start_async()` at `:349` | CONFIRMED |
| `reconcile_execution_state` with zero clients returns `True` trivially (`execution_engine.py:1698-1701`, `if not self._clients: ... return True`) — load-bearing for the 3b-fixtures "portfolio never initialises" test design, which keeps zero exec clients so reconciliation passes and `:1033` runs | CONFIRMED — the plan's fixture premise is technically sound |
| `TradingNodeConfig.timeout_connection` default `60.0` (`:127`), `timeout_portfolio` default `10.0` (`:129`), both `PositiveFloat` | CONFIRMED |
| `_SilentDataClient`/`_SilentDataClientFactory` at `tests/contract/test_trade_node_lifecycle_contract.py:80,96`, registered via `add_data_client_factory` at `:153` | CONFIRMED (plan's `:79-110`/`:153` is accurate within a line) |
| `Cache.add_order` is `cpdef void add_order(` at `cache.pyx:2155` | CONFIRMED |
| `Portfolio.initialize_orders` is `cpdef void initialize_orders(self):` at `portfolio.pyx:236`; `instrument is None` branch sets `initialized = False`; stored at `self.initialized = initialized` (`:300`) | CONFIRMED |
| `OrderEmulator(Actor)` at `emulator.pyx:81`; `Actor(Component)` at `actor.pyx:128`; `COMPONENT_STATE_TOPIC = "events.system.*"` at `component_health_watch.py:95` | CONFIRMED |
| `node_config.py:882` `LiveExecEngineConfig(inflight_check_interval_ms=0)` | CONFIRMED |
| `trade_cli.py`: `install_component_degraded_alert` at `:421`, `node.run()` at `:438` | CONFIRMED |
| `app/trade.py:399-407` alert-emission shape (`emit_alert(resolve_alert_sink(), AlertPayload(severity=..., event=..., site=..., detail=...))`) | CONFIRMED (`:397-407`) |
| `exec/client.py`: `_has_durable_fill_record` at `:1436`, `generate_order_status_reports` at `:2500`, `generate_fill_reports` at `:2530` | CONFIRMED |

Every load-bearing citation in this revision — including the two the round-3 reviewers required (`start()`/`start_async()` method-name split, `:1038`→`:1039`) — is now correct against installed source. I read the kernel file directly rather than trusting the plan's transcription, and it matches exactly, including the arithmetic ("ten lines" between `:1029` and `:1039`).

## Defects

None MATERIAL. None MINOR found this round. This is a from-scratch re-derivation, not a re-reading of the plan's own quotes — I grepped/read the kernel, node, cache, portfolio, emulator, actor and execution-engine source directly before comparing to the plan text, per this backlog's standing caution about self-confirming citations.

One point worth recording, not a defect: the "engines never connect" 3b fixture description says `_check_engines_connected` polls "in under a second" at `timeout_connection=0.5` — I did not execute the test to confirm the poll interval keeps this under the harness's own test timeout, but the mechanism (a `PositiveFloat` config field plus a never-set `asyncio.Event`) is sound and needs no patch of Nautilus. That is an execution-time detail, not a specification gap.

## Reconciliation (coordinator-requested, this revision)

The prior version of this record withheld 1/10 on "Portfolio objective alignment, scope and dependencies" for a P2 rating on 13b/13c that is "an argued priority call, not one derived from a measured cost." Re-applying the brief's rule: **every point withheld must be tied to a named defect AND a required change; a shortfall no change to the plan could fix is a BLOCKER or note, not a deduction.**

Checked on the merits: the plan cannot derive a measured cost for 13b/13c's priority because the bot has not placed an order since 2026-09-15T20:12:06Z — there is no trading activity to measure a cost against. No change to this plan's text produces that measurement; it does not exist to be cited. That is exactly the "unavailable evidence" case the rule carves out, not a defect in the plan's reasoning. The plan is explicit and honest about this (§4: "Rationale, stated honestly…"), states the P1/P2 split's actual justification (13d is valuable today against today's `return []` behaviour; 13b/13c are correctness debt gated on rulings, not an ROI path), and never invents a figure to paper over the gap — §11 states "Demonstrated: none… Claiming an ROI benefit here would be invention" in so many words. That is the criterion being *met*, not merely excused: "scope and dependencies" alignment is fully argued and internally consistent; the only thing absent is a number that cannot exist yet.

Per the brief, this is option (b): the criterion is met as far as it applies, the point is awarded, and the absence of a measured-cost figure is recorded as a note (not a blocker — nothing here gates acceptance; it is a standing fact about the trading account's current inactivity, not a missing plan deliverable).

**Note (not a blocker):** no dollar or priority-magnitude figure can be attached to 13b/13c's P2 rating until the bot resumes trading and a real cost of delayed reconciliation-correctness becomes measurable. This is a fact about the portfolio's current state, not a gap in AUD-13's text, and no revision of this plan can close it.

## Per-criterion scoring

| Criterion | Cap | Points | Rationale |
|---|---|---|---|
| Fidelity to the audit gap and completeness | 20 | 20 | G-10 fully covered; the boot-halt path (F5) the gap implies but does not name is closed with its own P1 increment and does not wait on the ruling-blocked generators. |
| Technical correctness and evidence grounding | 20 | 20 | Every kernel, cache, portfolio, emulator and Breezy anchor re-verified from source this round and all are correct, including the two citations that survived three prior rounds broken. |
| Implementation specificity and feasibility | 15 | 15 | The detail ladder is literal to the probe; the 3b fixture shape is fully specified (config field, subclass, cache call) with a positive control named; step 0's citation-re-derivation gate has a stop condition (`SYMBOL GONE`). |
| Acceptance criteria and validation quality | 20 | 20 | Twelve falsifiable items including the cross-assertion pair that makes the emulator latch load-bearing rather than decorative, and the 09-11 incident replay. |
| Autonomous operation, failure handling and recovery | 15 | 15 | F5 (the only failure mode that silently stops the node trading) gets a delivered CRITICAL with cause attribution; F1-F4/F6 fall closed to today's already-running behaviour with a latched reason; no self-healing is added, correctly, and it is named as a scope exclusion rather than an omission. |
| Portfolio objective alignment, scope and dependencies | 10 | 10 | Reconciled this revision (see above): the criterion is met as far as it applies — the P1/P2 split is fully argued, honest about zero demonstrated ROI, and invents no figure. The absent measured-cost number is unavailable evidence, not a plan defect, and is recorded as a note rather than a deduction. |
| **Total** | **100** | **100** | |

## Required changes

None. No MATERIAL or MINOR defect was found in this plan this round, and the one prior deduction is reconciled above as unearned — it named no defect and no change to the plan's text could have recovered it.

## Blockers

R-1 (fee unit on a reconciled `FillReport`) and R-2 (may a reconciled `OrderFilled` reach `on_order_filled`) remain strategy-lead rulings, gating 13b/13c only. Not waivable by review. 13d (the boot-halt alert) carries no blocker and is independently actionable.
