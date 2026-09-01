# Native-reuse audit — does Breezy rebuild what Nautilus Trader already provides?

**Date:** 2026-09-01 · **Nautilus:** 1.231.0 (installed, `.venv/lib/python3.13/site-packages`)
**Question (operator):** *"I thought Nautilus would have most of the functionality that we've
built, check again that we absolutely need this functionality."*

Five blind auditors, one seam each. Every load-bearing claim below was re-verified by the
coordinator against installed source. Verdicts use three values:

- **GENUINE GAP** — no native, or the native computes a different quantity / is unreachable.
- **NATIVE DECLINED** — a native exists and we chose not to use it, for a stated reason.
- **DUPLICATION** — we rebuilt something reachable.

> **Method note, and it nearly invalidated the whole audit.** The Grep tool's *directory
> recursion* under `.venv/` is silently blind: ripgrep honours `.gitignore`, whose first line is
> `.venv/`, so a recursive search there returns **0 matches with no error** — indistinguishable
> from a true negative. Measured: `rg -l 'Nautech Systems'` under `nautilus_trader/live/` → 0
> files; `--no-ignore` → 15. File-scoped Grep works normally. **Every negative in this document
> was re-run with shell `grep -r` alongside a positive control proving the search descended.**
> A bare "0 matches" does not close a null hypothesis in this repo.

---

## 1. Headline answer

**Mostly not duplication.** Breezy reuses the native `BinaryOption`, `LiveExecutionClient`,
`LiveMarketDataClient`, `InstrumentProvider`, `nautilus_pyo3.HttpClient`, `MessageBus`,
`Strategy`, `BacktestEngine`, `ParquetDataCatalog`, `StreamingConfig`, and the `FeeModel`
extension point. Three real findings came out of it, and the most valuable is the inverse of
the question asked: **a native we should be using and are not.**

---

## 2. GENUINE GAPS — verified, keep what we built

| Surface | Closest native | Why it is not a substitution |
|---|---|---|
| Naked-short refusal (`runtime/backtest_order_guard.py`) | `RiskEngine._check_orders_risk_for_account` (`risk/engine.pyx:703-740`) | The native gate is **structurally unable to fire on a cash account**: `CashAccount.balance_impact` returns **+notional** for a SELL (`accounting/accounts/cash.pyx:482-495`), so `(free + impact) < 0` at `engine.pyx:949` is unreachable; `TradingState.REDUCING` denies a sell only when already net short (`:1160`), so a sell from flat passes. No native post-only concept at all. |
| Pre-trade cost in probability units (`strategy/weather_common/costs.py`) | `FeeModel.get_commission` (`backtest/models/fee.pyx:38-64`) | Native requires an `Order` plus a **filled** `Quantity` and `Price` and returns `Money`. It prices a fill that already happened; it cannot answer "what if I paid 0.03?". That is the only unit a binary edge gate can compare against. |
| Live settlement exit (R-9) | `check_instrument_expiration` | Exists at `backtest/engine.pyx:3680,5919,5934` and **nowhere else**. `expiration_ns` occurs **0 times** across `live/`, `execution/`, `portfolio/`, `risk/`, `trading/` — against a positive control of **63** in `model/instruments/` and **261** occurrences of `instrument` in `live/execution_engine.py`. Backtest-only. |
| Exit status on a lost feed (`adapters/polymarket_us/feed_fault.py`) | `Component.fault()` / `shutdown_system` | Native `FAULTED` is per-component and in-memory. `TradingNode.run()` returns `None` and the kernel retains no stop reason, so a dead feed is byte-identical to SIGTERM. Breezy reuses the native shutdown and adds only the exit code. |
| `[0,1]` price bounds | `BinaryOption.__init__` | Hardcodes `max_price=None, min_price=None` (`model/instruments/binary_option.pyx:144-145`) with **no parameter to set them** — not merely unset, unsettable. `RiskEngine._check_price` (`engine.pyx:1036-1048`) checks precision and `> 0` only; no native ever compares a price to 1.0. |
| Cross-instrument notional caps (`risk.py:460-470`) | `max_notional_per_order` (`engine.pyx:179,675-679`) | Native is per-order, per-`InstrumentId`. Breezy's aggregate across instruments grouped by climate day and station. No native grouping exists. |
| Position sizing (`forecast_mispricing/decision.py:166-172`) | `FixedRiskSizer` (`risk/sizing.pyx:94-211`) | Native **does** exist, but sizes off stop-loss distance in ticks (`:181-189`). A binary settling to 0/1 has no stop loss; its risk is the premium paid. Wrong model, not a missing one. |

**Persistence is a thin wrapper, not a rebuild.** Breezy never writes or reads parquet itself:
`persistence/catalog.py:485` calls native `write_data`, `:930` calls `custom_data`,
`quote_tape_gaps.py:111` calls `query`, and capture runs on native `StreamingConfig`. Nothing
reimplements consolidation. The added flock / read-back / mountinfo layer has no native
counterpart.

---

## 3. NATIVE DECLINED — with the reason now stated correctly

**Durable order and position state.** Nautilus DOES persist this natively when a cache database
is configured: `cache/cache.pyx:393-394` restores orders and `:1366-1368` rebuilds
`_index_venue_order_ids[venue_order_id] → client_order_id`; `cache/database.pyx:709-755`
`load_position` replays stored `OrderFilled` events and reconstructs the `Position`, so
`avg_px_open` is **derived from the fills** and survives byte-exact.

**Redis is the only backend** — `system/kernel.py:312` accepts `"redis"` and `:324-329` raises
`ValueError` for anything else; `cache/database.pyx:162-166` constructs
`nautilus_pyo3.RedisCacheDatabase` unconditionally. (`cache/postgres/` and `infrastructure/`
do **not** exist in 1.231.0, contrary to an earlier assumption.) We decline the dependency: an
external server as a hard runtime requirement of the trading process is a new failure mode, a
new operational surface, and a second network egress the N2 firewall does not model.

> **The rule this produced.** `EXEC_SPINE` Revision 1 justified building the store with *"a
> restart orphans the position"*, stated as a property of Nautilus. It is a property of our
> **configuration**. **Claiming a gap where a native exists is the same failure as claiming a
> native where none exists — the same error with the sign flipped**, and it is harder to catch
> because the resulting code works. Both are now barred by the same standing rule: every
> null-hypothesis verdict cites a `file:line` that was actually opened.

Same shape for `Actor.on_save`/`on_load` (`common/actor.pyx:208,226`): declined at
`runtime/sqlite_store.py:16-44`, and the decline is *stronger* than the repo argues —
`Cache.update_actor` (`cache/cache.pyx:2742-2757`) writes only `if self._database is not None`
and, unlike `Cache.add`, keeps **no in-memory copy**, so with `database=None` actor state is
discarded outright.

---

## 4. DUPLICATION — real, ranked

1. **The fee formula is written four times.** `θ·C·p·(1−p)` at
   `adapters/polymarket_us/fees.py:186`, `strategy/weather_common/costs.py:168`,
   `scripts/analysis/price_conditional_settlement_analysis.py:135-139` — and byte-identically
   in shipped Nautilus at `adapters/polymarket/common/parsing.py:394`. The **model class** is
   justified: the native reads a flat `instrument.taker_fee` and **fails open to `Money(0)`**
   when the rate is ≤0 (`adapters/polymarket/fee_model.py:294-295`) and credits negative maker
   rebates (`:301-315`), both of which Breezy deliberately refuses. The **arithmetic** is
   quadruplicated. *Deferred deliberately:* R-9 bans the modelled fee from the live realized
   path in favour of the venue's measured commission, so that work will touch this code anyway;
   consolidating now would mean touching money code twice.
2. **The `[0,1]` price-bound check appears five times** inside Breezy (`parsing.py:412,535,803`;
   `fees.py:178-184`; `costs.py:157-162`). One helper.
3. **Config builders vs `live/__main__.py`.** `nautilus_trader/live/__main__.py:24-46` is a
   complete config loader and runner (`msgspec.json.decode(raw, type=TradingNodeConfig)`), and
   two of Breezy's three builders emit pure data that could be JSON. **Keeping ours** — the
   swap loses `validated_trader_id` (`node_config.py:141-161`, which guards a Rust SIGABRT) and
   the `recorder_instance_id` pinning (`:456-458`), and the third builder cannot be replaced at
   all because `ActorFactory.create` ends at `actor_cls(config)` with one JSON-round-tripped
   positional argument (`common/config.py:610-614`) while `NwsIngestActor` needs live shared
   state. There is no native TOML or env loader.

---

## 5. THE INVERSE FINDING — a native we should use and do not

**Breezy configures no native risk caps at all.** No `RiskEngineConfig` and no
`max_notional_per_order` anywhere in `src/breezy`. Combined with the separately-pinned fail-open
(`risk/engine.pyx:684-689` allows everything while `account_for_venue(...)` is `None`), the
native risk engine is currently both **inert and unset**. `instrument.max_quantity` is likewise
left unset at `parsing.py:1244` while `min_quantity` is set.

This is free protection sitting on the floor, and it is the opposite of the failure the operator
suspected: not rebuilding a native, but ignoring one. **Being remediated.**

---

## 6. STRUCTURAL CAUSE — why this drift is systemic

`pyproject.toml:83-104` declares a contract named *"Breezy never imports the Nautilus Polymarket
.com adapter"* whose `forbidden_modules` is `["nautilus_trader"]` — the **entire framework** —
unblocked only by a hand-maintained ~30-entry `ignore_imports` allow-list. Adopting any new
native therefore costs a `pyproject.toml` edit, which biases the codebase toward rebuilding.

The friction is already documented in the repo: the `breezy.strategy.**` entry carries a comment
that a per-module rule *"made 'write a strategy' a pyproject edit that nothing in pytest
catches"*. **Being narrowed** to `nautilus_trader.adapters.polymarket`, preserving the real ban.

---

## 7. The `.com` adapter question, settled

Nautilus ships a complete `adapters/polymarket/`. It targets a **different venue**:

| | shipped `polymarket` | Breezy `polymarket_us` |
|---|---|---|
| HTTP | `https://clob.polymarket.com` (`factories.py:91`) | `https://api.polymarket.us` (`config.py:96`) |
| auth | Polygon EVM key + EIP-712 / HMAC `POLY_*`, via `py_clob_client_v2` | Ed25519 over `timestamp+METHOD+path`, `X-PM-*`, ±30s (`signing.py:91-93,128-134`) |
| identity | `{condition_id}-{token_id}` | market slug (`symbology.py:5`) |
| custody | pUSD / CTF on Polygon chain 137 | fiat USD, CFTC-regulated DCO |

It is **not importable in this environment at all** — `py_clob_client_v2` is not installed, so
`import nautilus_trader.adapters.polymarket` raises `ModuleNotFoundError`. Breezy's signer is
byte-identical to the official Polymarket.us SDK's (`sdk_snapshot/.../auth.py:26-43`). The
decision was already recorded before this audit, in
`docs/plans/POLYMARKET_US_CONNECTOR_DECISION.md:7` with a 27-row evidence table, and it holds up.

**It remains valuable as a reference implementation** — proof that `BinaryOption`,
`LiveExecutionClient` and `LiveMarketDataClient` are the right native base classes — and as a
**hazard**: it imports `RetryManagerPool` (`execution.py:104`, constructed `:221`) and runs order
submission through it. On a venue with no client-order-id that auto-resubmits and doubles a
position, which is why barrier B8 bans it by name.

---

## 8. Corrections to claims previously recorded in this repo

| Where | Claimed | Actually |
|---|---|---|
| `runtime/backtest_order_guard.py:20-22` | 1.231.0 "exempts position-reducing sells outright" | Exempts **conditionally**: `order.is_reduce_only or pending_sell_qty <= available_long_qty` (`engine.pyx:979-982`). Conclusion survives; reasoning does not. |
| `ingest/product_index.py:223-226` | The Actor backs state with "the same `Cache.add` / `Cache.get` pair" | It uses `SqliteStateStore`; `Cache` was explicitly declined (`sqlite_store.py:16-44`). |
| `strategy/weather_common/costs.py:22-31` | The import-linter contract blocks the native `PolymarketFeeModel` | **False** — `fees.py -> nautilus_trader` is explicitly allow-listed. The real objections (fail-open to `Money(0)`, maker rebates) stand; the architectural one does not. |
| `EXEC_SPINE` Rev 1, R-4 | "A restart orphans the position" | True of our config, not of Nautilus. See §3. |
| `EXEC_SPINE` Rev 1, R-9 | "A mapping increment, not a research one" | No live mechanism exists. See §2. |

---

## 9. What changed as a result

- `EXEC_SPINE` R-4's justification rewritten from "gap" to "declined native, and here is what we
  decline and why".
- R-9 rewritten from a mapping increment to a Breezy-owned increment with a real
  null-hypothesis verdict — and in the process found that R-4 would otherwise **arm a silent
  zero**: `generate_missing_orders` defaults `True` (`live/config.py:183`) and the native flatten
  path books the close at the *open* price when it has no `avg_px_open`
  (`execution_engine.py:2866-2880`), yielding `realized_pnl == 0` for every settled trade.
- Native risk caps being wired; import contract being narrowed; the three false comments in §8
  being corrected.
- New standing constraint in `EXEC_SPINE`: a negative about installed Nautilus is evidence only
  if the search could have found a positive.
