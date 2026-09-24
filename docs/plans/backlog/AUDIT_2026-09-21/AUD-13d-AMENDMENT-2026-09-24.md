# AUD-13d amendment — no ladder detail is reachable; the generic detail stands

Status: PROPOSED — requires independent review.

## Superseded

`AUD-13-native-venue-reconciliation-from-durable-records.md` §7 step 3b (both
tests: `test_engines_that_never_connect_halt_the_boot_with_the_engines_not_
connected_detail`, `test_a_portfolio_that_never_initialises_halts_the_boot_
with_the_portfolio_detail`, and the "discrimination assertion both tests must
carry" naming `BOOT_HALT_ENGINES_NOT_CONNECTED` /
`BOOT_HALT_RECONCILIATION_FAILED` / `BOOT_HALT_PORTFOLIO_NOT_INITIALISED`) and
the matching per-cause `detail` requirement in §8 acceptance criteria. §7 step
3c (the generic-fallback test) is UNCHANGED and now describes every case, not
a fallback for an unattributed remainder.

## Evidence (installed `nautilus_trader==1.231.0`, cited by path:line)

1. **`Component.start()` triggers `START_COMPLETED` unconditionally**
   (`common/component.pyx:1941-1970`): the FSM moves READY→STARTING→RUNNING
   as soon as `.start()` is called, regardless of whether any async work it
   kicks off ever succeeds. A client's `is_running`/`is_stopped`
   (`:1818-1840`, the SAME public properties `trade_cli._trader_reached_
   running` already reads on `trader`) therefore cannot distinguish "this
   client's `.start()` was called" from "this client actually connected."
2. **Connection status is a live, non-latching flag, and no event marks it**
   (`live/data_client.py:224-234`, `LiveExecutionClient.connect()` at
   `:532-539` is the same shape): `_set_connected(True)` runs only as the
   success callback of the `_connect()` task, entirely decoupled from the
   Component FSM transition in (1); no `ComponentStateChanged` or any other
   msgbus event fires when it flips. `test_a_boot_halt_with_no_attributable_
   cause_alerts_with_the_generic_detail`'s own fixture
   (`tests/unit/test_trade_cli.py:991-1013`, `_UnattributedBootHaltNode`) is
   the recorded proof this exact avenue was tried and rejected: a
   `ComponentStateChanged` sample said "reconciliation failed" for a case
   that was actually attribute-less, because the published event cannot
   outlive the moment it fires.
3. **The one live poll of connection state is reset by the kernel's own stop
   path before `_emit_boot_halt_alert` ever runs**: `DataEngine.
   check_connected()` (`data/engine.pyx:324-339`) is `all(client.is_connected
   for client in self._clients.values())`, computed at call time. The
   kernel's `disconnect()` (`system/kernel.py:1290-1291`, called from every
   stop path) runs `_set_connected(False)` (`live/data_client.py:245`)
   before `trade_cli._run_node` reaches the boot-halt check. Reading it
   post-`run()` reports `False` uniformly, whichever of the three early
   returns fired.
4. **The one discriminator that DOES survive stop is binary, not
   three-way**: `kernel.emulator` is public (`system/kernel.py:918-927`) and
   `self._emulator.start()` (`:1033`) is a call/no-call fact gated on
   reconciliation succeeding — not a timing race — so `emulator.is_running`/
   `is_stopped` cleanly separates `{ENGINES_NOT_CONNECTED,
   RECONCILIATION_FAILED}` (never started) from `{PORTFOLIO_NOT_INITIALISED}`
   (started). Nothing installed, public, non-private, and non-polling
   further separates `ENGINES_NOT_CONNECTED` from `RECONCILIATION_FAILED`
   within that first bucket — both return before `:1033` (`:1024`, `:1029`),
   and separating them needs either polling `check_connected()` during
   `start_async` (a timer, forbidden by this item's own invariants) or
   reading the private `_is_connected` flag mid-flight (forbidden).

A partial ladder (attribute the portfolio case correctly, merge the other two
under one label) was considered and rejected: it is exactly the "workaround"
this item's brief prohibits, and a wrong three-way split that occasionally
mislabels `ENGINES_NOT_CONNECTED` as `RECONCILIATION_FAILED` is worse than an
honest, uniform "unattributed."

## Replacement acceptance criteria

1. `BootHaltDetail` keeps its single member, `BOOT_HALT_TRADER_NEVER_STARTED`
   (`trade_cli.py:135-147`) — unchanged.
2. `test_a_false_reconciliation_halts_the_boot_and_emits_a_critical_alert`
   asserts exactly one `CRITICAL` `BOOT_HALT` with that one detail — already
   GREEN, unchanged by this amendment.
3. An operator recovers the actual cause from the kernel's OWN pre-existing
   log lines, which this item does not need to duplicate into the alert:
   `"Timed out ... waiting for engines to connect"` (`system/kernel.py:1310`),
   `"Execution state could not be reconciled"` (`:1345`), `"Timed out ...
   waiting for portfolio to initialize"` (`:1358-1362`) — all three already
   reach the node's own log stream via `logging_bridge.py`, so
   `grep -E "Timed out.*waiting for (engines|portfolio to initialize)|
   Execution state could not be reconciled" <node log>` recovers the cause a
   structured alert field cannot safely carry.
