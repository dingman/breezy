# R-6a — guard semantics correction (design plan) — **Revision 2**, 2026-09-02

Scope: the **uncommitted** R-6a increment (`git diff` on `backtest_order_guard.py`,
`trade_cli.py`, `test_trade_cli.py`, plus untracked `tests/unit/test_runtime_live_order_guard.py`).
Design only; no implementation. Nautilus is exact-pinned (`pyproject.toml:11`,
`nautilus-trader==1.231.0`); every citation is measured against that tree.

## Changelog — Revision 1 → Revision 2

| # | Change | Why |
|---|--------|-----|
| C1 | **Keep** `if event.reconciliation: return`; delete only the tags/prefix branches (was: delete everything) | R1's deletion rested on a grep tripwire that is publisher-shape-dependent; cost asymmetry (one naked short vs. a crash-loop holding a real position) decides for the one-line check |
| C2 | **New decision (§2): the check goes in `on_order_event`, not inside `_refuse_naked_short`** | Reconciliation propagates `post_only=report.post_only` (`live/execution_engine.py:3592`), so a resting post-only order found at the venue would crash the node on restart via `_refuse_post_only` — the same failure D1 exists to prevent |
| C3 | Grep tripwire → **behavioural** test on the existing rig at `tests/contract/test_reconciliation_settlement_price_hazard.py:399-416` | publisher-shape-independent; reuses a harness that exists |
| C4 | Test-deletion criterion narrowed: *pins an exemption keyed on attacker-settable fields* | R1's "asserts a SELL passes" was refuted by R1's own RED-4/RED-5 |
| C5 | Reporter now **prints to stderr at the moment of refusal**, not only latches | `os._exit(1)` beats the CLI exit path; and the `LiveClock` timer path **discards** the exception entirely (coordinator-reproduced) |
| C6 | R-9 remediation text at `:218` is **corrected in this increment** | it omits subtracting working sells; one real shape (working exit 40 + settlement 100 vs. net 100) is refused |
| C7 | `reduce_only` reframed from "R-9's contract" to a **tracked, unremediated bypass of the class this increment just closed** | it is forgeable through the same door; removal of R-4's standing refusal must be gated on its fix |
| C8 | Migration inventory closed (three unlisted artefacts) | D7 |

Objections raised, not suppressed: C2 (a genuine gap in D1's placement) and the exact spelling of
D4's `try/finally` (§4). Everything else in D1-D7 is adopted as decided.

---

## §0 Measured facts

| # | Fact | Where |
|---|------|-------|
| M1 | Exactly three sites publish an order's init event: `trading/strategy.pyx:856-859`, `:948-951`, `execution/algorithm.pyx:1207-1210`. **None is reconciliation.** | measured |
| M2 | `OrderFactory.market` takes `tags`, `client_order_id`, **and `reduce_only`** as ordinary public params | `common/factories.pyx:236-248` |
| M3 | `MarketOrder.__init__` builds `OrderInitialized` without `reconciliation` → always `False`. Nautilus sets `reconciliation=True` at `live/execution_engine.py:3608`. It is a public ctor kwarg (`model/events/order.pyx:299`, property `:481`), so **the branch is behaviourally testable** | `model/orders/market.pyx:140-165` |
| M4 | Reconciliation propagates the venue report verbatim: `post_only=report.post_only` (`live/execution_engine.py:3592`), `reduce_only=report.reduce_only` (`:3593`), `tags` ∈ `["VENUE"] \| ["RECONCILIATION"] \| None` (`:3559/:3563/:3567`) | measured |
| M5 | `LiveDataEngine._run_data_queue` (`live/data_engine.py:477-493`) → `_handle_queue_exception` (`:347-366`); `graceful_shutdown_on_exception` defaults **`False`** (`live/config.py:60,78,201`) → **`os._exit(1)`**. Same in `LiveExecutionEngine:542`, `LiveRiskEngine:218`. No `set_exception_handler` anywhere in Nautilus (0 hits; positive control passed) | measured |
| M6 | A raising `LiveClock` timer callback has its exception **silently discarded** — no propagation, no `unraisablehook`, no `excepthook`, exit 0 | coordinator-reproduced |
| M7 | `Portfolio._net_position` returns `Decimal(0)`, never `None` (`portfolio/portfolio.pyx:1824-1834`; public `net_position` at `:1735`) | measured |
| M8 | `RiskEngine` gates reduce-only validation on `if command.position_id is not None` (`risk/engine.pyx:424`), and `Strategy.submit_order`'s `position_id` defaults to `None`; `:979-982` exempts `is_reduce_only` from the cash check | measured |
| M9 | Live node has `strategies=[]`, `exec_algorithms=[]` (`node_config.py:699-700`) — by M1, **nothing on this node can publish `OrderInitialized` today** | measured |

M1 proves finding (B) at the source: the `RECONCILIATION`/`VENUE` branches cannot fire. The only
reachable branch is the `tags is None` + `SETTLEMENT-` prefix — finding (A)'s forgeable one.

## §1 Decision 1 — the exemption: **delete the tags/prefix branches, keep one line**

**RECOMMENDATION.** Delete `_is_reconciliation_or_settlement_leg` (`backtest_order_guard.py:258-288`),
`RECONCILIATION_TAG` (`:98`), `VENUE_TAG` (`:110`), `SETTLEMENT_CLIENT_ORDER_ID_PREFIX` (`:128`) and
their `__all__` entries (`:77-79`). Replace the whole predicate with `if event.reconciliation:
return` — placement per §2.

**Reasoning.** By M2 the surviving reachable branch is settable by any strategy that types the right
string: an exemption keyed on attacker-settable fields is not an exemption, it is a documented
bypass. `reconciliation` is the opposite: unforgeable through every public construction path (M3),
and set only by Nautilus itself. It is dead in 1.231.0 (M1) — but the **cost asymmetry** is decisive:
a forged tag costs one naked short, while a false refusal costs a crash-loop **while holding a real
venue position**, on the exact path (restart reconciliation) where the node is least able to
recover. One unforgeable line is the cheap side of that trade.

**Rejected — delete everything (Revision 1's recommendation).** Its backstop was a grep-shaped
tripwire over `msg=order.init_event_c()`, which would not match a future
`publish(topic=…, msg=initialized)` added beside `execution_engine.py:3610`. With the backstop
gone the deletion is no longer safe. R1's supporting claim that "dead code cannot be tested
honestly" is also false (M3): the branch is behaviourally testable.

**Rejected — keep tags but require `reconciliation` as well.** Strictly more code for a branch M1
shows is unreachable, and `reconciliation` alone already carries the whole signal.

## §2 Decision 1b — WHERE the check goes: `on_order_event`, before both rules

**This is a Revision 2 finding, and it is the one place I am deviating from D1's implied shape.**
D1 replaces the predicate that `_refuse_naked_short` called, which would leave `_refuse_post_only`
unguarded. By M4 reconciliation copies `post_only` straight off the venue report
(`execution_engine.py:3592`). A resting **post-only** order found at the venue on restart therefore
arrives with `post_only=True, reconciliation=True` and is refused by `_refuse_post_only` (`:181-194`)
— the crash-loop-holding-a-position failure D1 exists to prevent, reached by the other rule.

**RECOMMENDATION:** in `on_order_event` (`:167-177`), immediately after the
`type(event) is not OrderInitialized` filter, add:

```
if event.reconciliation:
    return
```

Both rules are then uniformly out of jurisdiction for anything Nautilus originated, and the R1
asymmetry question is answered structurally rather than per-rule. Cost: the same one line, one
level up.

### What R-9 must do

R-9's settlement leg needs no exemption: it is sized to the position, so it passes
`pending + quantity > net` (`:205`) on its own merits. **One real shape does not (D5):** a working,
non-reduce-only exit SELL of 40 against a net long of 100, followed by a settlement leg sized to
the full 100 → `40 + 100 > 100` → refused → process death. The guard's own remediation text
(`:218`, "Size every SELL from `self.cache`/`self.portfolio.net_position(...)`") is the only
instruction R-9's author will read and it **omits subtracting working sells**. Correct it in this
increment to name `net_position(...)` **minus unfilled non-reduce-only SELL leaves** — i.e. the
same quantity `_working_sell_quantity` (`:223-244`) computes.

Also record while touching this file: `_net_long`'s `None` branch (`:252-254`) is dead —
`net_position` returns `Decimal(0)`, never `None` (M7). Leave the code (a defensive floor on a
third-party return is cheap); correct the comment so it does not assert a behaviour Nautilus lacks.

## §3 Decision 2 — `reduce_only`: OUT OF SCOPE, TRACKED, and it gates the send path

**After this increment the guard has exactly one remaining unremediated bypass, and it is of the
same class the increment just closed.** Any sentence claiming the guard is sound post-deletion is
wrong and must not appear in the code or the commit message.

Chain (M2, M8): `reduce_only` is a public `OrderFactory` kwarg; `RiskEngine` only validates
reduce-only when `command.position_id is not None` (`risk/engine.pyx:424`) and
`Strategy.submit_order`'s `position_id` defaults to `None`; `:979-982` then exempts reduce-only from
the cash check; and Breezy's own `_working_sell_quantity` (`:237-244`) **excludes** reduce-only
sells from `pending`, so **two reduce-only sells each sized to the net long both pass and are
jointly naked**.

**Do not fix it here** — that grows scope on a safety control mid-correction. Record it as a tracked
hazard, and record the gate: **removal of R-4's standing "refuse every order"
(`adapters/polymarket_us/exec/client.py:1338-1350`) must be gated on the `reduce_only` fix landing**,
not deferred to R-9 — different milestones, and if the send path lands first the bypass goes live
silently. Currently latent: no Breezy code submits reduce-only sells, and `strike_ladder.py:305-311`
is BUY-only by explicit design.

No test may be named `…is_the_only_exemption` or framed as "R-9's contract" (D6b).

## §4 Decision 3 — how a live refusal surfaces: **report at refusal time, then re-raise**

**RECOMMENDATION.** `install_live_order_guard` gains a **required**
`on_refusal: Callable[[ValueError], None]` (both refusal errors subclass `ValueError`; a required
parameter forbids the defaulted-no-op swallow) and subscribes a live-only wrapper that calls
`guard.on_order_event(event)`, catches **only** `PostOnlyRefusedError`/`NakedShortRefusedError`,
invokes the reporter, and re-raises.

`trade_cli._run_node` passes a reporter closing over its `stderr` that (1)
`print(f"breezy-trade: FATAL order-guard refusal: …", file=stderr, flush=True)`, (2)
`record_fatal_exec_fault(component, reason)`, (3) logs at ERROR.

**Why the print, not just the latch.** Latch-then-re-raise is necessary but not sufficient:
- On the engine-queue path, `os._exit(1)` (M5) beats `_exit_code_for_completed_run`, so the
  `breezy-trade: FATAL` line at `trade_cli.py:179-183` never prints — exit 1 with no cause, exactly
  what that function's docstring exists to prevent.
- On the `LiveClock` timer path the exception is **discarded outright** (M6) and the process exits 0.
  A weather strategy submitting from `on_time_event` is a realistic shape, so the latch is the only
  surviving signal there — and it only reaches stderr if the node later stops cleanly.

Writing at refusal time covers both. `sys.stderr` is line-buffered and `flush=True` makes the write
explicit, so it completes before `os._exit`.

**The re-raise is the enforcement.** `Strategy.submit_order` publishes at `strategy.pyx:856-859`
then continues to `cache.add_order`/`SubmitOrder` (`:865-887`); swallowing would submit the naked
short. Only reporting is added.

**Objection to D4's spelling, flagged.** D4 says wrap the reporter `try/finally` with a bare
`raise` in the `finally`. That is subtly wrong: inside a `finally`, a bare `raise` re-raises
`sys.exc_info()`, which — if the reporter itself raised — is the **reporter's** exception, losing
the refusal. Same intent, unambiguous spelling:

```
except (PostOnlyRefusedError, NakedShortRefusedError) as exc:
    try:
        on_refusal(exc)
    except Exception:                      # a broken reporter must not replace the cause
        logger.exception("order-guard refusal reporter failed")
    raise
```

**Rejected:** swallow + `shutdown_system()` (submits the order — disqualifying); publishing
`ShutdownSystem` (redundant on the queue path, unverified re-entrancy inside an in-flight
`msgbus.publish`); `graceful_shutdown_on_exception=True` in `node_config.py` (global behaviour
change in cage-pinned config — its own increment); a third fault module (a third latch an operator
must check). **Injected reporter, not an `exec_fault` import into the guard module:** keeps
`runtime/backtest_order_guard.py` venue-free and mode-agnostic as it claims, and makes the reporter
directly assertable. `install_order_guard` (backtest) is **unchanged** — bare `guard.on_order_event`,
so a refusal still aborts `engine.run()`.

**Barrier check:** no attribute named `post/put/patch/delete/request` is added;
`msgbus.subscribe(...)` stays the spelling. No barrier file is edited. Verify by running the B4
classifier as a gate (§6), not by assumption.

## §5 Decision 4 — the tests

**Deletion criterion (D3), to be used verbatim in the commit message:** *these tests pin an
exemption keyed on attacker-settable fields.* Not "they assert a SELL passes" — RED-4/RED-5 below
also assert a SELL passes, and that criterion would license deleting them next.

**Delete** (all uncommitted; none is a safety, settlement, or contract test):
`test_a_reconciliation_tagged_market_sell_passes_the_live_guard`,
`test_a_claimed_settlement_order_with_tags_none_passes_the_live_guard`,
`test_a_venue_tagged_external_sell_passes_the_live_guard`, and the file docstring's "trap" paragraph.

**Keep:** `test_refuse_naked_short_refuses_and_names_the_instrument`;
`test_an_untagged_unclaimed_market_sell_is_still_refused`;
`test_an_unrecognised_tag_on_a_naked_sell_is_still_refused` → rename
`test_a_tagged_naked_sell_is_still_refused`.

**Amend (D7):** `test_the_live_installer_installs_on_a_live_shaped_msgbus`
(`tests/unit/test_runtime_live_order_guard.py:137-156`) — its `handler == guard.on_order_event`
assertion at `:149` becomes false once the wrapper lands; keep the test, replace that assertion with
the RED-9 form and keep its behavioural drive-an-event half.

| # | RED test | Pins |
|---|----------|------|
| RED-1 | `test_a_reconciliation_tagged_naked_sell_is_refused` (tags only, `reconciliation=False`) | (A) closed |
| RED-2 | `test_a_venue_tagged_naked_sell_is_refused` | (A) closed |
| RED-3 | `test_a_settlement_prefixed_naked_sell_is_refused` | (A) closed — the forgeable branch |
| RED-4 | `test_a_nautilus_reconciliation_event_is_out_of_jurisdiction` — `OrderInitialized(..., reconciliation=True)`, naked SELL → passes | the surviving unforgeable exemption (M3) |
| RED-5 | `test_a_reconciled_post_only_order_is_also_out_of_jurisdiction` — `post_only=True, reconciliation=True` → passes | **§2**; fails if the check is placed inside `_refuse_naked_short` |
| RED-6 | `test_reconciliation_publishes_no_order_initialized_to_the_guard` — drive `_reconcile_position_report_netting` on the rig at `tests/contract/test_reconciliation_settlement_price_hazard.py:399-416` with the guard subscribed; assert its handler receives **no** `OrderInitialized` | M1, behaviourally and publisher-shape-independently (D2) |
| RED-7 | `test_the_order_factory_cannot_set_the_reconciliation_flag` — `pytest.raises(TypeError)` | M2/M3: why the surviving exemption is unforgeable |
| RED-8 | `test_a_settlement_leg_is_refused_when_a_working_exit_sell_is_outstanding` — working 40, settlement 100, net 100 → refused; assert the message names subtracting working sells | D5; pins the corrected remediation text at `:218` |
| RED-9 | `test_the_live_installer_subscribes_the_wrapped_handler_to_the_order_topic` | replaces the now-false identity assertion at `:149` |
| RED-10 | `test_the_backtest_installer_still_subscribes_the_bare_handler` | backtest behaviour explicitly unchanged |
| RED-11 | `test_a_live_refusal_is_reported_before_it_is_raised` — reporter called **and** the original `NakedShortRefusedError` propagates | §4, both halves |
| RED-12 | `test_a_raising_refusal_reporter_does_not_replace_the_cause` | §4's objection; would pass silently under the bare-`raise`-in-`finally` spelling |
| RED-13 | `test_trade_cli_writes_the_refusal_to_stderr_and_latches_it` (`tests/unit/test_trade_cli.py`) — drive a naked short through the handler captured by `_FakeMsgBus`; assert the stderr line is written **at refusal time**, `fatal_exec_fault()` is populated, and `_exit_code_for_completed_run` → `EXIT_RUNTIME_ERROR` | the operator signal, end to end |
| RED-14 | `test_two_reduce_only_sells_within_the_net_long_are_jointly_naked` — **`xfail(strict=True)`**, documenting §3's tracked bypass | records the hazard without weakening a guard or pretending it is fixed |

## §6 Migration and landing order

**Keep:** `install_live_order_guard` + the `trade_cli.py:236` install site; `Node.kernel: Any`
(`trade_cli.py:135`); `_FakeKernel`/`_FakeMsgBus` in `test_trade_cli.py`; the B4
`subscribe`-not-`request` note (trim to ~3 lines — the installer docstring is ~25 lines for a
3-line function).

**Change:** installer gains `on_refusal`; wrapper per §4; `trade_cli` reporter per §4; the
remediation text at `:218` per §2; the `_net_long` `None` comment per §2.

**Delete:** the predicate, its three constants, its `__all__` entries, the three bypass tests.

**Stale prose to update (D7):** `backtest_order_guard.py:46-52` — the module docstring's
reconciliation rationale references the tag/prefix world and goes stale with the constants.
`tests/contract/test_reconciliation_settlement_price_hazard.py:412-415` — a **committed** comment
asserting "R-6's guard exemption cannot key on that tag or every settlement leg is refused"; the
observation is still true but the increment it describes no longer keys on a tag at all. Update the
comment to point at `event.reconciliation`; do not touch the assertion at `:416`.

**Order:** (1) RED-1..RED-3, RED-7 → GREEN by deleting the tags/prefix branches. (2) RED-4, RED-5,
RED-6 → GREEN by the `on_order_event` check (§2). (3) RED-8 → GREEN by the corrected remediation
text. (4) RED-9..RED-12 → GREEN by the wrapper. (5) RED-13 → GREEN by the `trade_cli` wiring.
(6) RED-14 lands `xfail(strict=True)`. (7) Gates: `scripts/ci/run_tests_no_egress.sh` (full suite),
ruff, mypy, `lint-imports`, the B4 classifier on `backtest_order_guard.py`, and
`test_cage_rule_constants_are_pinned.py` — expected unaffected, **verify**.

## §7 Residual risk and where reviewers should still aim

- **[LEAST CONFIDENT] §2's placement.** Moving the check to `on_order_event` widens it from one rule
  to both. That is right for `post_only` (M4), but it means any *future* rule added to
  `on_order_event` inherits the exemption silently. Alternative: call it explicitly at the head of
  each rule. I chose the single point because a rule author who forgets the call gets a crash-loop,
  which is the worse failure — but this is the trade I would most like challenged.
- **Not re-verified by me:** M6 (the `LiveClock` discard) is the coordinator's reproduction, adopted
  as fact; and the "5107 tests currently green" figure.
- **Unverified:** re-entrancy of `msgbus.publish` from inside an in-flight publish dispatch — only
  relevant if the rejected `ShutdownSystem` route is ever revived.
- **Stated, not a defect:** by M9 the guard is **dormant on the live node today**. R-6a's "done
  when: the wired live node reconciles with the guard installed, no crash" proves only that
  installation is harmless. It is the seatbelt for W/R-9; the plan says so rather than implying
  live coverage.
