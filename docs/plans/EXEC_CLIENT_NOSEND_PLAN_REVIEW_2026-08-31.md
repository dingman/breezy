# NO-SEND execution-client plan — round 1 merged review

**Reviewed:** `EXEC_CLIENT_NOSEND_PLAN.md` (1150 lines, commit `6ce6691`).
**Lenses:** Nautilus contract fidelity, cage/containment, structure & seam.

## Verdict: BLOCK (3/3), but the SCOPE CUT IS VALIDATED

The structural lens: *"the seam is cut in the right place and the plan is a large
improvement on its predecessor."* NO-SEND is genuinely exercisable standalone —
`_connect` → account → reconcile → deny is a closed loop needing neither the
settlement identity nor the authority algebra. **The L-4 remedy worked.** What
remains are specification defects with named fixes, not a design consuming itself.

## BLOCKING

**B-1 — `_assert_reconciled` is mistimed; goal clause (c) is unreachable.**
NS-5 rule 2 compares reports against the cache inside `generate_mass_status`. The
engine awaits `generate_mass_status` at `live/execution_engine.py:1710-1713` and only
then applies reports via `_reconcile_execution_mass_status` at `:1730`. With NS-3's
`database=None, flush_on_start=False`, the cache holds **zero** positions at that
moment, always. So the rule returns `None` whenever the venue holds a position (the
trader never starts, permanently) and is vacuously true when it holds none. There is
no configuration in which it detects the F-2 hazard it was written for — which fires
*after* the point the fix acts. **RED 11 greens the wrong implementation.**

**B-2 — Goal clause (d) is not well-formed; RED 9 is unimplementable.**
(i) The eight coroutines at `live/execution_client.py:598-636` include
`_connect`/`_disconnect`, which take no command and cannot emit `OrderDenied`. Six
are order-bearing. NS-5 rule 5 says six; clause (d), its falsifier, the walk and RED 9
say eight. (ii) `_cancel_all_orders(CancelAllOrders)` carries **no `client_order_id`**
(`execution/messages.pxd:188-190`), which `generate_order_denied` requires. (iii)
`DENIED` is reachable only from `INITIALIZED`/`RELEASED` (`model/orders/base.pyx:95,107`);
cancels target `ACCEPTED` orders, and `_apply_event_to_order` catches
`InvalidStateTrigger`, **logs a warning and returns True** (`execution/engine.pyx:1587-1594`)
— the denial is emitted and silently discarded. Specify per-coroutine denial
semantics, not a blanket count.

**B-3 — Ledger claim F-17 is FALSE, and it is the predecessor's failure mode again.**
Claimed: `TradingNode` exposes no kernel/engine accessor, evidenced by `dir()` over
the class. But `self.kernel = NautilusKernel(...)` is assigned in `__init__` — a
public *instance* attribute that class-level `dir()` cannot see. `n.kernel.exec_engine.registered_clients`
resolves. Consequences: §5.1's "the factory is the only seam" is unfounded, and the
three-assertion inference chain is both unnecessary AND incapable of detecting
`live/node_builder.py:231-233`, where an unregistered factory name logs an error and
`continue`s — the node builds with **zero** exec clients while all three assertions
pass. **Replace with direct observation:** the pyo3 block is defeated by the same
factory monkeypatch the plan already uses (`test_polymarket_us_factories.py:181-182`),
so `node.build()` opens no socket and composition can be observed.

**B-4 — NS-1 publishes account values. Three findings, one root.**
(i) The recorder NS-1 reuses emits **every scalar verbatim**: `_walk_structure` does
`safe_values[prefix] = str(value)` for every `str|int|float|bool|None`
(`data.py:428-429`), rendered under a literal `"Safe scalar values:"` table
(`polymarket_us_auth_smoke.py:627-635`). Its docstring says "without publishing
**non**scalar payloads" — it suppresses containers and publishes scalars; the plan
paraphrased this as "shape without values", the inverse. Pointed at
`/v1/account/balances` it writes the operator's balance into a committed, hashed
artifact. (ii) The stated fail-closed net does not cover it: `find_secret_leak_offsets`
scans only the credential strings passed as `secrets`, so a balance is not a "secret".
(iii) Dict keys become published path segments (`f"{prefix}.{key}"`, `data.py:435`);
for a positions map keyed by market, the keys **are** the portfolio.
Also: digit/decimal counts and array cardinality are value-derived — scale is
answerable from the SDK snapshot or a public market read without the operator's
numbers.
**Currently-committed evidence is clean** — `_frame_schema` is wired only to the WS
frame handler and the dumps are public order-book levels. The hazard is the proposed
new use, not the existing one.

**B-5 — A second native fail-open the plan never found.**
`_reconcile_position_report_netting` (`live/execution_engine.py:2472-2476`): if the
instrument is not in the cache it logs at **DEBUG** and `return True`. Breezy's
provider loads weather markets only, so any venue position outside that set
reconciles as success, invisibly — which the plan's own falsifier (c) forbids.
Separately, fill reports are applied only inside the loop over `order_reports`
(`:1879-1907`), so a `FillReport` with no matching `OrderStatusReport` is silently
dropped; with `/v1/orders/open` as the only order source, every fill of a closed
order is discarded. LESSONS L-2: the plan named one fail-open and treated it as
the only one.

**B-6 — NS-4 has no `lint-imports` container.** `exec/reports.py` imports the Nautilus
report types; the forbidden-import contract needs a per-module `ignore_imports` entry
(`pyproject.toml:88-142`) and CI runs `uv run lint-imports` (`.github/workflows/tests.yml:37`).
NS-4 has no Files section, no `pyproject.toml` in scope, and no `lint-imports` RED.

**B-7 — NS-1 has an undeclared forward dependency on NS-4.** §3 says NS-1 depends on
"nothing in this plan"; its own Barriers paragraph needs the exact-path V2 allowance
NS-4 introduces. `scripts/venue/` is venue-touching by C2 and V2 fires on any
`/v\d+/orders?\b` literal. As ordered, NS-1 creates a **second** V2-allowlisted path,
falsifying goal clause (e), and puts an order path in the one file holding live
credentials. Reorder NS-1 after NS-4, or drop `/v1/orders/open` from it.

## HIGH

- **Orphaned SEND-half constraints.** Six findings from the abandoned document belong
  to the deferred half and are recorded nowhere a successor would look: the `TradeId`
  36-char cap; `marketData.stats.settlementPx` in `/book` (not `stats.settlementPx`)
  plus the `bbo_*` same-named-field exclusion; correction → silent drop or phantom
  short; the unspecified fill side/qty/`venue_position_id`/emission precondition; the
  free fourth gate conjunct (`settlementSetTime` at/after expiration); and the known
  issuer `== 1` / probe-script collision. §9.1 discarded the *corrections* along with
  the stale text. **Add a carry-forward table.**
- **Speculative building for the deferred half.** NS-2 D-1 and D-3 fix `safety.py`
  code with no production callers, unreachable under this plan's own `== 0` pin; D-3
  *designs new authority state* (a process ledger keyed by `operator_id`) inside a
  plan whose seam defers the authority model. Move D-1/D-3 to the SEND plan; keep D-2.
  Also: D-3's ledger key is read from operator-controlled env, so changing one
  variable mints a fresh budget — pin at first issuance and refuse a different value.
- **B-17 overstated** — the alert sink is also constructed at `ingest/nws_actor.py:2070`,
  `strategy/weather_common/refusals.py:123`, and referenced as a default argument at
  `composition.py:279`. The load-bearing half survives, but `refusals.py:123` is the
  established `sink=None → resolve_alert_sink()` injection pattern NS-5 should mirror.
- **`open_only` is silently ignored** — `generate_mass_status` issues
  `GenerateOrderStatusReports(open_only=False)` (`live/execution_client.py:474-481`)
  while NS-4 binds it to `/v1/orders/open` alone. State it as a venue limitation.
- **NS-0's "attested AND substantiated" is untested** — RED 3 covers only the
  unattested case; a lying `BREEZY_TEST_OS_EGRESS_BLOCK=1` passes. Call the canary at
  sessionstart or drop "substantiated".
- **NS-2 counter 2 is vacuous for `exec/*`** (passes on the string prefix alone) and
  **false today for `settings.py`** (classifies `False`), so it cannot land as written.

## MEDIUM / LOW

- `is_built` is a **method**, not a property (`live/node.py:185`) — NS-3 RED 3 asserts
  on a bound method and is permanently wrong.
- `build_exec_clients` fails open on a name mismatch (`node_builder.py:231-233`); it
  also applies `name.partition("-")[0]` at `:220`. Pin the client name.
- "Refuses to start the trader" ≠ refuses to start: `start_async` returns
  (`system/kernel.py:1026-1028`), `run_async` then logs RUNNING and starts all queue
  tasks. The process daemonises with no trader, exit 0. `emit_alert` is the only
  signal — and `_disconnect`, which closes the webhook sink, never runs on that path.
- **F-9 signature wrong**: `generate_order_denied(..., reason, ts_event)` — five
  params (`execution/client.pyx:370-406`).
- **B-15 overstated**: `QUOTA_KEY_PORTFOLIO` has three live callers in
  `scripts/venue/polymarket_us_auth_smoke.py:1018,1062,1122` — the very file NS-1
  extends.
- `calculate_commission` undecided; the base returns `None` (`execution/client.pyx:193`).
- NS-4's "round-trip the shapes recorded by NS-1" versus never-ingest: say fixtures
  are hand-transcribed.
- D-2's "one-entry allowlist declared and empty" is self-contradictory; pin `== 0`
  with no allowlist structure.
- The `None`-from-`generate_mass_status` handoff constraint (right for NO-SEND, WRONG
  for SEND) exists only as a parenthetical — needs a §8 row and a pinned code comment.
- Cite drift: `pyproject.toml:78` not `:79`; `live/config.py:195` not `:188`;
  kernel gate `:1026-1028`.

## Verified sound

F-1..F-16 (excluding F-9's signature), B-1..B-14, B-16, B-18..B-26 all check out at
the cited lines. Corrections C-1..C-5 are all genuine, including the Redis reversal
(no connectivity probe exists in `system/kernel.py`) and the seven-not-eight FILLED
transition count. Goal clause (b) is achievable at the claimed lifecycle point, and
the explicit `cache.account(...) is not None` assertion correctly distrusts the
native warn-and-return. NS-0's ordering, the exact-path/prefix asymmetry, the per-site
value table, and behavioural-purity-over-AST-blacklist are all improvements on the
abandoned document.
