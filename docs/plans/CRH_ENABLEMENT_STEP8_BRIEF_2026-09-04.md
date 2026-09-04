# CRH build-order step 8 — order-path enablement brief (2026-09-04) — DRAFT, for peer review

Authored by planner against `feat/data-capture-and-risk` @ `f51580a`. Read-only survey; no code
changed. Consumes `EXEC_SPINE_NEXT_2026-09-04.md` §A/§D, `R7_BUILD_BRIEF_2026-09-04.md` (converged
review binding), `CRH_RUNTIME_WIRING_BRIEF_2026-09-04.md` (converged review binding),
`R8_OPERATOR_RUNBOOK.md` §5–§9, LESSONS L-12 and L-22. Operator-reserved caps are named **by role
only** — writing either variable's name into any tracked file turns
`test_operator_control_assignment_scan.py:618` RED (layer B scans file BYTES,
`:347-358`).

## Goal

Make the `current_rung_hold` order path reachable for the FIRST real live-small order — 1 contract,
BUY LIMIT IOC, ask strictly inside (0.05, 0.95), under the two operator caps — through an
**explicit, unforgeable operator enablement path**, without weakening any barrier and without
weakening L-22's refusal of `orders_enabled=True`.

## Null-hypothesis findings (what already exists; file:line)

**The send path is COMPLETE.** R-7 landed (`092695c`, refined `02bfd63`). `exec/client.py:1484-1619`
is the full D1–D9 chain: latched-refusal and account gates (`:1488-1493`), sender presence
(`:1494`), canonical-string predicate read as a bare module attribute at call time (`:1496`), shape
mapping (`:1499`), permit presence + `assert_live_order_submission_permitted` (`:1502-1514`), body
build/encode (`:1515-1516`), **ledger reserve** `authorize_order_cost` (`:1518-1522`), reconcile flag
(`:1525-1527`), latch `arm` (`:1529`), sign + `post_order` (`:1535-1544`), and the four D9 leaves —
`true_up_booking` on `KIND_ACCEPT_FILL` (`:1564`), `true_up_booking(0)` on `KIND_ZERO_FILL`
(`:1592`), `release_booking` on `KIND_REJECT` (`:1606`), AMBIGUOUS default keeping latch OPEN and
booking held (`:1616-1619`). **The ledger call sites are NOT zero** — the brief's premise is stale at
`f51580a`; `authorize_order_cost` / `release_booking` / `true_up_booking`
(`operator_controls.py:299,408,428`) are all wired, caps re-read per call via the two accessors
(`:147,160`). Startup reconciliation is wired (`client.py:679-691`), latch thread-identity asserted
(`:682`), injected by the composition root (`app/trade.py:101-115`).

**Therefore step 8 builds NO execution machinery.** The only missing links are (1) the enablement
capability, (2) the strategy-side gate that consumes it, (3) deployment.

**Nautilus provides, and we reuse unchanged:**
- `Strategy.submit_order` + `OrderFactory.limit(time_in_force=IOC, post_only=False)` —
  already written at `strategy.py:514-522`. No new order construction.
- `RiskEngine` trading state: `TradingState.ACTIVE` default (`risk/engine.pyx:132`),
  `set_trading_state` (`:228`), `HALTED` denies every submit (`:559,1137-1150`). **This is the
  native kill switch; step 8 adds none.**
- `RiskEngineConfig.max_notional_per_order` — **DECLINED, correctly**: it is a per-`InstrumentId`
  dict (`engine.pyx:179,193,675`), so it cannot express a rolling UTC-day AGGREGATE across
  instruments, and weather instrument ids are minted daily so the dict cannot be populated ahead of
  time. It is also a config value, i.e. a value in a file — forbidden for an operator-reserved cap
  (runbook §6). `DailySpendLedger` is not duplication.
- `install_live_order_guard` (`trade_cli.py:373`) already refuses post-only and naked shorts on the
  live path, where `RiskEngine` structurally cannot (cash-account `balance_impact`,
  `backtest_order_guard.py:16-42`). Unchanged.
- `ExecEngine` reconciliation + `generate_order_*` — already used at `client.py:1568-1614`.

**Why `orders_enabled: bool` can never be the unforgeable gate.** `CurrentRungHoldConfig` is
`StrategyConfig, frozen=True` (`config.py:151`) → `NautilusConfig(msgspec.Struct, frozen=True)`
(`common/config.py:241`), whose `.id` is `tokenize_config` → `msgspec.json.encode` (`:238,256`). Two
consequences: (a) every field must be msgspec-encodable, so a sealed capability object cannot be a
field; (b) any bool or string field is exactly reproducible by anyone who can write a config dict
through `ImportableStrategyConfig` + `StrategyFactory.create` (`trading/config.py:104-130`). An HMAC
token field would be replayable verbatim from the encoded config. **A value that can be copied is
not a capability.** L-22's rule — the exclusive mechanism belongs in the primitive's constructor,
never a sibling helper — points at an object, not a flag.

## Design

### D-A. Enablement is a sealed capability, injected; `orders_enabled` stays refused forever

NEW `src/breezy/runtime/order_enablement.py` (~180 lines). `runtime` is below `strategy` in the
`pyproject.toml:75-79` layer list, so `strategy/current_rung_hold` may import it (it already imports
`runtime.submit_intent`), and `runtime` may import `adapters` (`trade_cli.py` does).

```
_SEAL = object()                       # module-private, never exported, never a default

@final
class OrderSubmissionPermit:
    __slots__ = ("expires_at_ns", "operator_id")
    def __init__(self, seal: object, /, *, expires_at_ns: int, operator_id: str) -> None:
        if seal is not _SEAL:
            raise OrderSubmissionNotPermittedError(...)      # L-22 shape, in the constructor
    def __init_subclass__(cls, **kw): raise TypeError(...)   # no subclass forgery
```

`issue_order_submission_permit(*, env, settings, permit, clock) -> OrderSubmissionPermit` is the ONE
construction site. It refuses (raising `OrderSubmissionNotPermittedError`, a `PermissionError`) unless
**all six** hold — absence is always refusal, never a default, and messages name the failed
precondition and never a value:

1. `env.get(ORDERS_ENABLED_VAR) == "1"` exactly — new `BREEZY_ORDERS_ENABLED` (a build-side flag, not
   an operator-reserved cap, so the name may appear in tracked files), parsed with the
   `settings.py:288-293` `== "1"` idiom: no truthiness, no coercion.
2. `isinstance(permit, LiveTradingPermit)` and `clock.timestamp_ns() <= permit.expires_at_ns`
   (`safety.py:714` will re-check at D3; this fails fast at startup instead).
3. `write_transport.WRITE_CANONICAL_STRING_VERIFIED is True` — read as a module attribute at call
   time, the exact D2 idiom already shipped at `client.py:1496`. Today it is `False`
   (`write_transport.py:48`), so step 8 lands **structurally unreachable** until OP-4.
4. Both operator caps present and positive — obtained by CALLING the operator-control module's two
   accessors (`:147,160`), which already raise on absence/blank/malformed/non-positive and never name
   a value. **Never re-read their env vars here; never name them.**
5. `settings.current_rung_hold is True and settings.live_observations is True` — taken from the
   already-loaded `BreezyTradeSettings`, never re-parsed (`settings.py:748-756` owns that rule).
6. The venue credentials are complete (the same `credentials.is_complete()` D3 requires,
   `safety.py:704`) — fails at startup rather than at the first candidate.

`app/trade.py::main` calls it immediately after `issue_live_trading_permit` (`:147`) and passes the
result into `run(...)` → `build_current_rung_hold_strategies(...)` → each
`CurrentRungHoldStrategy(config, trial_day_latch_factory=…, order_submission_permit=…)`. A refusal is
logged at INFO and the permit is `None` — shadow mode, exactly today's behaviour.

`strategy.py:498-508` gate becomes: submit only when `self._order_submission_permit is not None`.
`orders_enabled` is kept, still defaulting `False`, still raising `OrdersEnabledNotPermittedError`
when constructed `True` (`config.py:256-260`) — **its docstring is rewritten**, not weakened: it is no
longer "the increment has no order path", it is "a bool can never be a capability; enablement is the
injected `OrderSubmissionPermit`, and this field exists so no future call site re-introduces a
forgeable flag". `config.py:225-227` and the `__post_init__` clause are byte-unchanged.

`_maybe_submit`'s `# pragma: no cover - unreachable` markers (`:509-522`) come off; the shadow log
line's text is preserved for the runbook's grep (§Shadow mode line 54) with the gate name updated.

### D-B. Caps arithmetic at the first order
Ask < 0.95 strict, qty 1 → cost ≤ $0.95, rounded up to the cent by `order_cost_usd`
(`operator_controls.py:217`) before the per-position cap compare, **pre-fee** (runbook §6:158). A
per-position cap of exactly $1.00 admits every legal ask in the band; $0.95 admits asks ≤ 0.95 only
after cent-rounding, i.e. it will refuse the top of the band. The daily budget bounds the day at
≤4 orders (one trial per station-day × four stations) → ≤ $3.80 pre-fee. **The build side proposes no
values.**

### D-C. Deployment — CONFLICT, do not resolve inside this increment
`deploy/systemd/` has **no** `breezy-trade` unit. Runbook §7:182-183 states there **must not be
one**, because a unit file would put the enablement value in a file, and §6:160 forbids any of the
operator values in a `.env`, a unit, or a shell rc. The task premise ("values go only into the
untracked runtime env file", "specify the unit mirroring `breezy-quote-tape.service`") contradicts
both. **Recommendation: do not ship a unit in step 8.** Run the first order from the operator's own
shell per runbook §7:177-181 (`.venv/bin/breezy-trade`, `pyproject.toml:251`). If the operator
overrides, the unit must be added *together with* an amendment to runbook §6/§7 in the same commit —
never silently — with `EnvironmentFile=-/home/jon/.config/breezy/<file>` at mode 0600, `UMask=0077`,
`Restart=always`, `RestartSec=30`, `KillSignal=SIGTERM`, `TimeoutStopSec=120`, journald +
`SyslogIdentifier=breezy-trade`, `WantedBy=default.target`, no capture-window field, and a new
distinct timer-hour entry is NOT needed (it is not a timer). See "Unresolved" below.

`breezy-live-tally.timer` is PREPARED, not enabled (runbook §9:221-223): `systemd-analyze --user
verify` then `systemctl --user enable --now breezy-live-tally.timer`. That is operator residue, not
build work; the unit files need no change.

`breezy-clear-submit-intent` has landed (`pyproject.toml:263`,
`runtime/clear_submit_intent_cli.py`) and stays the only exit from an OPEN latch; step 8 adds no
caller and its B9 `named_call_sites` pin (`test_polymarket_us_readonly_guard.py:1652-1659`) must
assert **unchanged**.

## Build order (commit boundaries; each ends gate-green, passed count never drops)

1. **Settings flag.** `settings.py`: `ORDERS_ENABLED_VAR`, `_parse_orders_enabled`, field
   `orders_enabled_requested: bool = False` on `BreezyTradeSettings`. Cross-flag refusal at load:
   the flag on without `BREEZY_CURRENT_RUNG_HOLD=1` is a `SettingsError` naming both. *Null
   hypothesis: none — this is Breezy's own environment contract (`settings.py:695-712`).*
2. **The capability.** `runtime/order_enablement.py` + its six refusals. Zero call sites in this
   commit. *Null hypothesis: `LiveTradingPermit` is the nearest native-shaped precedent and is
   REUSED as input (precondition 2), not re-implemented; Nautilus offers no capability type.*
3. **One-caller pin.** Extend the shipped repo-wide scanner `named_call_sites`
   (`test_polymarket_us_readonly_guard.py:677-692`) with a new B11 row pinning
   `issue_order_submission_permit` → exactly `{("src/breezy/app/trade.py", "main")}`, mirroring B7
   (`:1497-1505`) and B9 (`:1652`). Plus a pin that `OrderSubmissionPermit(` is constructed at
   exactly one site, `order_enablement.py::issue_order_submission_permit`.
4. **Wire it.** `app/trade.py::main` mints and threads it; `composition.build_current_rung_hold_
   strategies` gains `order_submission_permit: OrderSubmissionPermit | None = None`;
   `CurrentRungHoldStrategy.__init__` (`strategy.py:207-217`) gains the same keyword-only argument.
5. **Open the gate.** `strategy.py:498-522`: gate on the permit; drop the `pragma: no cover`s;
   rewrite `OrdersEnabledNotPermittedError`'s docstring. *Null hypothesis: `Strategy.submit_order` +
   `OrderFactory.limit` used as-is.*
6. **Docs.** Runbook §6 corrected (see residue), a new §Enablement row for the flag, journalctl
   strings updated; `EXEC_SPINE_NEXT` §A R-8 row → LANDED-pending-operator; PROGRESS + LESSONS entry
   for the bool-is-not-a-capability finding.

## Tests (RED first, in the commit that makes them green)

- **T1 (barrier, step 3).** `named_call_sites("issue_order_submission_permit") == {("src/breezy/app/
  trade.py","main")}`; non-vacuity BOTH directions through the REAL scanner — remove the call → RED;
  plant a second caller in a `src/` module AND in a `tests/` conftest → each RED.
- **T2 (L-22).** `OrderSubmissionPermit(object(), …)` raises; `OrderSubmissionPermit()` raises;
  subclassing raises; `msgspec.json.decode` cannot produce one (it is not a `Struct`);
  `copy.deepcopy`/`pickle` round-trip of an *existing* permit is not a new grant (assert the type
  refuses `__reduce__`-driven reconstruction, or that `__slots__`-only state cannot be rebuilt
  without `_SEAL`).
- **T3 (config, WIDEN only).** `CurrentRungHoldConfig(orders_enabled=True)` **still** raises; and
  `msgspec.json.decode(b'{"orders_enabled":true,...}', type=CurrentRungHoldConfig)` raises
  (`__post_init__` runs on decode); and `StrategyFactory.create(ImportableStrategyConfig(config={...
  "orders_enabled": True}))` raises. Existing assertions in
  `tests/unit/test_current_rung_hold_config.py` are asserted UNCHANGED (L-12).
- **T4 (refusal matrix).** Parametrised over the six preconditions: for each, all others satisfied
  and that one absent/blank/`"true"`/`"0"`/expired → `OrderSubmissionNotPermittedError`, message
  names the precondition, and **no value appears in the message** (caplog test, precedent
  `test_polymarket_us_secret_exposure.py:141`). Both cap cases parametrised through the accessors,
  never by naming their variables.
- **T5 (end-to-end, fake exec client).** `Take` → `submit_order` → `_submit_order` exactly ONCE per
  station-day: drive two executable quotes for the same station-day, assert one `post_order` call,
  one `arm`, one retire, and that the trial-day latch consumed the day on the first
  (`strategy.py:441`). Assert the ledger round-trip: reserve before the POST, `true_up_booking` on a
  200-with-durable-fill, `release_booking` on the 4xx+`google.rpc.Status`+no-`order.id` leaf, and
  **no** release on AMBIGUOUS. Reaching the POST is only possible via the single shipped monkeypatch
  fixture for `WRITE_CANONICAL_STRING_VERIFIED` (R-7 RED 6's repo-wide "exactly one fixture" scan
  must stay green with the new module).
- **T6 (shadow default).** With the flag absent, `run()` builds strategies with
  `order_submission_permit is None`, the `TAKE recorded, no submit` line still prints, and
  `post_order` is never called.
- **T7 (no barrier weakened).** Assert-as-non-change: B6 (`:1503`-neighbour), B7 exact set, B9
  `post_order`/`clear_submit_intent` sets, `set(BARRED_CALLEES)` (`:1546`),
  `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES` count, `B4_EXEMPT_PATHS` (2 members), cage exemption
  `== 3`, `files_naming_a_control() == {DEFINITION_MODULE}`. Every set-equality barrier touched must
  be WIDENED, never relaxed (L-12); a diff review lists each OLD → NEW.

## Risks / what could bypass a barrier

- **BLOCKER-0 — the live-trading permit expires in 15 minutes.** `PERMIT_TTL_NS = 15*60*1e9`
  (`safety.py:151-157`), minted once at `app/trade.py:147` (B7 pins ONE caller), and D3 refuses at
  `safety.py:714`. The decision window is [12:00,17:00) LST. **Every candidate after minute 15 of the
  process denies.** No code in step 8 changes this. See "Unresolved".
- **Permit budget exhaustion is separate from the caps.** `issue_live_trading_permit` also consumes a
  per-permit session notional and session order count (`safety.py:590-591`, spent down at `:744-755`).
  A session order count below 4 silently caps the day below the daily budget.
- A dynamically computed import string is invisible to the AST pins (accepted residual, same class as
  B5/B8; `EXEC_SPINE_NEXT` records it).
- `sys.modules['breezy.runtime.order_enablement']._SEAL` is reachable by any in-process code. Accepted:
  it is the same trust boundary as `safety._mint_authenticity`'s key, and B11 + the construction-site
  pin make any *shipped* second grant RED.
- Writing either operator cap's variable name into this or any file turns
  `test_operator_control_assignment_scan.py:618` RED. Reviewers: check the diff for it.

## Operator residue after this increment

1. Commit `docs/specs/PREREG_v1_current_rung_hold_2026-09-04.md` as binding (remove the DRAFT line) —
   **before** enablement (runbook §5:148).
2. Run OP-1 → OP-2 → OP-3 → OP-4 (runbook §1–§4).
3. On an OQ-D CLOSED-YES artefact, the build side flips
   `write_transport.py:48 WRITE_CANONICAL_STRING_VERIFIED` to `True` and re-pins its test — that is a
   build commit, not operator residue, and it is the last one.
4. In the launching shell only, export: the live-trading enablement variable; the **maximum daily
   budget**; the **maximum per position**; the per-order notional ceiling, the session notional
   ceiling, the session order count, and the operator identity (all four required by
   `issue_live_trading_permit`, `safety.py:583-592` — **runbook §6 says "three values" and is wrong;
   it is seven**); plus `BREEZY_ORDERS_ENABLED=1`, `BREEZY_CURRENT_RUNG_HOLD=1`,
   `BREEZY_LIVE_OBSERVATIONS=1`, `BREEZY_TRADE_CATALOG_ROOT`, `BREEZY_TRADE_TRADER_ID`.
5. Start `.venv/bin/breezy-trade` from that shell, inside the decision window (BLOCKER-0).
6. `systemd-analyze --user verify` then `systemctl --user enable --now breezy-live-tally.timer`.

## Unresolved — needs a decision this survey cannot make from the code

- **BLOCKER-0 (TTL).** Three options: (a) accept a ≤15-minute trading session, operator starts the
  node inside the window and restarts as needed — zero code change, safe (startup reconciles the
  latch), and sufficient for the FIRST order, which is this increment's stated goal; (b) re-mint
  in-process — REJECTED, it forges the property the TTL protects and the issuer explicitly refuses a
  minter parameter (`safety.py:573-575`); (c) retarget `PERMIT_TTL_NS` to cover one window
  (5 h + startup slack) and re-pin `test_the_permit_ttl_is_pinned_to_fifteen_minutes` at the new
  value with a stated derivation. **Recommend (a) for step 8; route (c) to security-reviewer as its
  own increment.** Arguably (c) is a time BUDGET, i.e. operator-reserved.
- **Systemd unit for `breezy-trade`.** The task asks for one; runbook §7:182-183 forbids one. Not a
  build call to make silently — see D-C.

## Converged peer review (2026-09-04, BINDING — overrides the sections above on conflict)

Reviewers: architect (REVISE), security-reviewer (CONVERGE + R1–R3), prediction-market-reviewer
(REVISE). Merged decisions:

1. **Preconditions live in the constructor (L-22).** `OrderSubmissionPermit` cannot exist
   unvalidated: the five checks run inside its construction path (`@classmethod issue(...)` IS the
   constructor; `__init__` refuses without the internal seal). The module sentinel is an
   accidental-construction guard only. The security claim is **data-unforgeability** (a sealed object
   cannot be a msgspec `StrategyConfig` field, so it is reachable only from code, never from decoded
   config; `common/config.py:241`, `trading/config.py:149-154`) and the **B11 AST one-caller pin +
   one-construction-site pin are the guarantee**. Rewrite the Goal accordingly. Drop the
   `__init_subclass__`/`__reduce__`/deepcopy assertions from T2; keep seal check, no-arg refusal,
   not-a-Struct. A sixth candidate check, venue-credential completeness, is deliberately NOT one
   of the five: `issue` carries no credentials object, so completeness is enforced downstream at
   D3 (`safety.assert_live_order_submission_permitted`), not here (`order_enablement.py:25-32`).
2. **`orders_enabled` stays a refused field** (removing it would delete live RED assertions, L-12);
   docstring rewrite only. The `_maybe_submit` gate keeps the `stale_observation_minutes` `int`
   conjunct alongside the permit.
3. **TTL: option (c).** `PERMIT_TTL_NS` (`safety.py:157`) is retargeted from 15 min to **10 hours** =
   the union of the four decision windows (MIA 12:00 LST = 17:00 UTC … LAX/SFO 17:00 LST = 01:00 UTC
   next day, 8 h) plus 1 h slack each side; re-pin `test_the_permit_ttl_is_pinned_to_fifteen_minutes`
   under a new name with this derivation. The TTL is a build-side constant already in a tracked file,
   not in the reserved inventory. The restart loop (option a) is REJECTED: `DailySpendLedger` is
   process-local (`operator_controls.py:257-281`) and `_PERMIT_BUDGETS` is in-process
   (`safety.py:616-619`), so restarts would reset the daily cap and session budgets; and a restart gap
   changes the "first executable snapshot" selector `P_HOLD_LOWER` was measured on. One process per
   trading day, launched from the operator/automation shell before 17:00 UTC. Documented consequences
   (runbook §6/§8): the daily cap is per-process and re-keys at 00:00 UTC mid-session (the durable
   trial-day latch bounds any day at ≤1 order per station-day = ≤4 orders ≈ $3.80 pre-fee, and is the
   binding cross-restart limit — security R1, with a test); an unplanned restart makes that day's
   selector uptime-conditional (disclosed, not hidden).
4. **No systemd unit, no launcher script.** Nothing under `deploy/` for the trade node. Residual
   exposure of shell/inline exports (`/proc/<pid>/environ` to same-UID processes, shell history outside
   the repo) is named and accepted in runbook §6 (security R3).
5. **Runbook §6 corrected to seven values**, split into the two durable role caps (read on every
   authorization) and the five per-process session values (`safety.py:583-592`): enablement flag
   (exactly `"1"`), per-order notional ceiling (must be ≥ the per-position cap; whole-USD granularity,
   `safety.py:560-566`), session notional (floor: station count × $1), session order count (floor:
   station count — anything lower silently truncates the day), operator identity. Floors are
   functional requirements, not proposed values.
6. **`LiveTradingPermit` value fields get `field(repr=False)`** and a caplog test asserts no permit
   object is ever logged by value (security R2).
7. **Single flag parse.** `runtime/settings.py` parses `BREEZY_ORDERS_ENABLED` once into
   `BreezyTradeSettings.orders_enabled_requested: bool`; refused unless `current_rung_hold` and
   `live_observations` are also set; the permit constructor reads the settings object, never the env.
8. **Build order fix.** Step 3 pins `named_call_sites("issue")` `== frozenset()` (zero call sites);
   step 4 WIDENS it to exactly `{("src/breezy/app/trade.py","main")}` with the non-vacuity test.
9. **Nautilus null-hypothesis, enablement itself:** native `TradingState`/`set_trading_state`
   (`risk/engine.pyx:132,228`) is DECLINED as the enablement — its initial state is node-config data
   (replayable) and there is no operator-only transition path; it stays the kill switch.
10. **T5 additions:** the single `WRITE_CANONICAL_STRING_VERIFIED` monkeypatch fixture must cover BOTH
    reads (issue time and `client.py:1496` D2); a cross-restart test (two engines/strategies over one
    SQLite store) proves the second start cannot take a second trial for a consumed station-day; a
    zero-fill IOC releases the daily reservation via `true_up_booking(0)` (`client.py:1592`) — assert
    it, and note the booking lands in `_trued_up_ids`.
11. **Caps arithmetic accepted** ($1 per-position admits the whole band; ≤4 orders/day is enforced by
    the latch + fixed station list, not the ledger; a fifth distinct station-day is admitted up to the
    daily budget — state this).

Stages: A (parallel, independent files) — A1 settings flag; A2 `safety.py` TTL + repr + caplog;
A3 `runtime/order_enablement.py` + B11 zero-site pin. B (after A) — wiring `app/trade.py` →
composition → strategy ctor, gate opened, B11 widened, T5/T5b, runbook §6/§7/§8. C — independent
review of the diff (code-reviewer, security-reviewer, prediction-market-reviewer). Then OP-2/OP-4 and
the `WRITE_CANONICAL_STRING_VERIFIED` flip are the last gate before the first launch.
