<!-- Codex read-only output, rollout rollout-2026-09-28T17-36-00-01a0e916-7e9d-7b23-ac1b-adc46262204e.jsonl -->

1. **Verified Problem, With Evidence**

`FAILURE-KIND-DURABLE` is open as BUILD: “Persist the last failure kind with the durable ambiguous intent, so the kind survives a restart” ([docs/core/PROGRESS.md](/home/jon/breezy/docs/core/PROGRESS.md:53), [docs/evidence/RULING_backlog_resolution_2026-09-28.md](/home/jon/breezy/docs/evidence/RULING_backlog_resolution_2026-09-28.md:38)). Today `_resolver_last_failure_kind` is initialized as an empty in-memory dict ([client.py](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:1769)). The first stale alert uses that dict, falling back to `"none"` when the id is absent ([client.py](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:2554)). `activities_uninterpretable` is recorded only into that dict after the trade-activity join ([client.py](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:2824), [client.py](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:2830)). The durable resolver context is already per-intent SQLite state, written before the resolver can observe it ([client.py](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:447), [client.py](/home/jon/breezy/src/breezy/adapters/polymarket_us/exec/client.py:5245)).

2. **L-1 Verdict**

NATIVE - insufficient. Nautilus `Cache.add` writes memory and only forwards to a backing database when `_database is not None` ([cache.pyx](/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/cache/cache.pyx:1704)); `Cache.get` reads only `_general` ([cache.pyx](/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/cache/cache.pyx:2853)). Breezy’s trade node config deliberately uses `CacheConfig(database=None, flush_on_start=False)` ([node_config.py](/home/jon/breezy/src/breezy/runtime/node_config.py:846)); Nautilus maps falsy cache DB config to `cache_db = None`, and only Redis is accepted otherwise ([kernel.py](/home/jon/breezy/.venv/lib/python3.13/site-packages/nautilus_trader/system/kernel.py:310)). Existing Breezy SQLite is therefore the correct durable seam: `set()` commits before returning and `get()` reads the same file ([sqlite_store.py](/home/jon/breezy/src/breezy/runtime/sqlite_store.py:168)).

3. **Design: Smallest Correct Change**

Add trailing optional `last_failure_kind: str = "none"` to `AmbiguousResolverContext`; serialize as `lastFailureKind`, default missing legacy rows to `"none"` in `from_bytes`. After decoding context and before the stale check, seed `_resolver_last_failure_kind[intent_id]` from `context.last_failure_kind` when non-`"none"`. Replace every resolver assignment/reset of `_resolver_last_failure_kind[...]` with one helper that updates memory and rewrites the same resolver-context SQLite key. On `_retire`, rewrite the context’s durable kind to `"none"` before clearing alert surfaces. Keep r2/r3 follow-up behavior for post-alert cause changes; it is no longer the restart mechanism.

r2 accepted restart loss because it kept the first CRITICAL immediate and relied on a later in-process follow-up ([FAILURE-KIND-PERSIST_plan_r2](/home/jon/breezy/docs/plans/backlog/EDGE_2026-09-27/FAILURE-KIND-PERSIST_plan_r2_2026-09-28.md:5), [FAILURE-KIND-PERSIST_plan_r2](/home/jon/breezy/docs/plans/backlog/EDGE_2026-09-27/FAILURE-KIND-PERSIST_plan_r2_2026-09-28.md:71)). That no longer holds: the ruling now requires durability, and the target RED requires process B’s stale CRITICAL itself to name the kind.

4. **Exact Files And Functions Touched**

`src/breezy/adapters/polymarket_us/exec/client.py`: `AmbiguousResolverContext.to_bytes`, `AmbiguousResolverContext.from_bytes`, `_resolve_ambiguous_intents`, new `_set_resolver_last_failure_kind(...)`, `_retire`.

`tests/unit/test_current_rung_hold_ambiguous_resolver.py`: new RED tests.

`tests/unit/test_execution_egress_firewall_guard.py`: add a narrow, shape-checked allowance for the new helper’s local resolver-context rewrite only. Do not broadly allow resolver store writes; the guard currently scans resolver callees ([test_execution_egress_firewall_guard.py](/home/jon/breezy/tests/unit/test_execution_egress_firewall_guard.py:2409)).

5. **RED Tests**

`test_resolver_context_last_failure_kind_defaults_legacy_rows_to_none`: decoding a JSON context without `lastFailureKind` exposes `.last_failure_kind == "none"`; fails today because the field does not exist.

`test_activities_uninterpretable_failure_kind_is_written_to_durable_context`: after one pass records `activities_uninterpretable`, rereading the SQLite resolver context shows that kind; fails today because only memory changes.

`test_restart_stale_alert_uses_durable_activities_uninterpretable_kind`: process A records `activities_uninterpretable` and exits; process B over the same store emits first stale alert with `last_failure_kind == "activities_uninterpretable"`; today it is `"none"`.

`test_retire_clears_durable_failure_kind`: a context carrying a non-`none` durable kind is retired; reread context has `"none"`; today no durable field is cleared.

6. **Acceptance Criteria**

1. Existing legacy resolver-context rows decode and resolve unchanged.
2. Process B’s first stale CRITICAL after restart names `activities_uninterpretable`.
3. Retire clears in-memory stale entries and durable `lastFailureKind`.
4. No submit-intent schema version change.
5. No order send/cancel path changes.
6. Firewall guard remains green with a narrow local-store-write exception only.
7. Cage pin remains green.

7. **Risks And Blast Radius**

Main risk is weakening E0-NOSEND by permitting store writes inside resolver code. Mitigation: allow only the named helper and only `RESOLVER_CONTEXT_KEY_PREFIX + context.intent_id`, not general `_store_set`. Do not modify `allow_short`, safety tests, settlement tests, contract tests, or NO-SEND assertions. Durable writes add SQLite I/O on failure-kind transitions only; failures should fail closed by leaving the intent AMBIGUOUS.

8. **Rollout**

Code loads at the next `breezy-trade` node start. Do not kill a live node. The user unit is `breezy-trade-supervisor.service`; there is no trade-node unit itself ([R8_OPERATOR_RUNBOOK.md](/home/jon/breezy/docs/plans/R8_OPERATOR_RUNBOOK.md:192)). The supervisor spawns `.venv/bin/breezy-trade` with forwarded env ([trade_supervisor.py](/home/jon/breezy/src/breezy/runtime/trade_supervisor.py:855)), and `breezy-trade` builds the node config with the exec state DB ([trade_cli.py](/home/jon/breezy/src/breezy/runtime/trade_cli.py:741)).

9. **Open Questions**

Should the r2/r3 follow-up path be removed? Recommended answer: no; leave it for same-process cause changes after the first stale alert.

Should this use the submit-intent singleton instead? Recommended answer: no; `SubmitIntent` has strict schema v1 parsing ([submit_intent.py](/home/jon/breezy/src/breezy/runtime/submit_intent.py:277)), while resolver context already supports trailing optional fields.