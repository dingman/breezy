# ING-2 S2 — per-run ingest deadline (plan r1, 2026-09-26, planner; UNDER PEER REVIEW)

Scope: S2 only (deadline + deferred-count line + unit contract). No memory change (S3). Preserves S1 definitions-first.

Code facts: `quote_tape_ingest_cli.py` `run()` :1673 → `run_ingest_definitions_first` :1547 (one LivenessSnapshot; pass 1 defs over `_needs_definition_pass`, pass 2 `run_ingest` :1377 over all). `run_ingest` dispatches `ingest_instance` :891 (whole-type) or `_ingest_instance_per_file` :1211 (salvage → defs → ticks). `list_instance_ids` (`feather_preflight.py:498`) is name-sorted (hash ids → arbitrary). Unit: MemoryHigh 4G / MemoryMax 6G / TimeoutStartSec 1800, no OOMScoreAdjust; `*:0/15` frequent timer + 6-hourly timer.

## Acceptance criteria
1. AC-D1 `run_ingest_definitions_first(..., deadline=RunDeadline)` starts no new unit (one (instance,type) conversion, one salvage step, or one instance preflight scan) after expiry; each skipped unit reported `deferred-deadline`, no marker; exit 0 when deferral is the only non-success.
2. AC-D2 ≥1 unit admitted per RUN (not per pass).
3. AC-D3 deferred unit converts next run, no duplicate rows; row-set equality vs no-deadline run with real StreamingFeatherWriter (L-42).
4. AC-D4 any pass-1 definitions deferral ⇒ zero tick units that run; next run `_needs_definition_pass` reselects it.
5. AC-D5 pass 2 processes `snap.newest_instance_id` first, then list order; printed results stay list order; backlog drains monotonically, no completed unit re-attempted.
6. AC-D6 injectable monotonic `clock_ns` (default `time.monotonic_ns`), independent of wall `now_ns`; dry-run ignores deadline.
7. AC-D7 non-dry run prints exactly one `breezy-quote-tape-ingest: deadline budget=<B>s elapsed=<E>s deferred=<N> unit(s) instances=<M>` line, even N=0; no ids/prices.
8. AC-D8 `--deadline-seconds` finite >0 else exit 2; `DEFAULT_DEADLINE_SECONDS = 600`.
9. AC-D9 unit contract: ExecStart `--deadline-seconds` ∈ [600,720]; ≤ TimeoutStartSec−300; +180 ≤ 900; MemoryHigh 4G / MemoryMax 6G unchanged; OOMScoreAdjust int 1..1000; `systemd-analyze verify` passes.
10. AC-D10 `deadline=None` callers byte-identical behaviour (49 `run_ingest` callers, S1 tests, ING-1 EXTEND tests, `TestTheMixedCatalogLayoutIsPinned`); full gate + lint-imports green.

## Design
`run(clock_ns)` builds `RunDeadline(budget_ns, clock_ns)` before the snapshot (None when dry_run) → pass 1 `run_ingest(defs, snapshot=replace(snap, instance_ids=selected), deadline)`; pass 2 `run_ingest(all, snapshot=replace(snap, instance_ids=_freshness_first(snap)), deadline)` (replace keeps full-list `newest_instance_id`, S1 A6); `_merge_pass_results` returns rows in `snap.instance_ids` order. Gates via `deadline.admit()`: run_ingest loop top (`expired()` — skip scan/open, report deferred for each un-markered requested type; overcount accepted, documented "not evaluated"), `ingest_instance` before each `convert_fn`, `_ingest_instance_per_file` before salvage / each def type / each tick type. Outcome precedence: truncated > dry-run > failed > deferred > converted > live; `summary_line` prefix `partially ingested (deadline)`. `RunDeadline` = small, deliberately stateful shared counter (admit/expired/admitted/elapsed_ns) in new module `src/breezy/runtime/ingest_deadline.py` (imports time/typing only), plus `DEFERRED_DEADLINE`, `DEFAULT_DEADLINE_SECONDS=600`, `count_deferred_units`.

## Files
- NEW `src/breezy/runtime/ingest_deadline.py`
- MOD `src/breezy/runtime/quote_tape_ingest_cli.py` (kw-only `deadline` threaded through run_ingest / ingest_instance / _ingest_instance_per_file / run_ingest_definitions_first; gates; `_freshness_first`; merge order; `--deadline-seconds`; `run(clock_ns=None)`; deadline line; docstring)
- MOD `deploy/systemd/breezy-quote-tape-ingest.service`: `--deadline-seconds 600`, `OOMScoreAdjust=500` (+comments); 4G/6G/1800 unchanged
- NEW `tests/unit/test_quote_tape_ingest_deadline.py`, `tests/unit/test_quote_tape_ingest_unit_contract.py`
- MOD `tests/unit/test_quote_tape_ingest_cli.py` only if an outcome vocabulary is enumerated (+1 reviewed row)

## Tests (FakeClock advanced inside convert_fn spy)
T6a defer+exit 0; T6b next-run convert, no duplicates (real feathers); T7a expired-at-start ⇒ exactly one convert; T7b per-run not per-pass (mutation check); T-defs deferral in pass 1 blocks all ticks; T-defs-next; T-fresh newest first + list-order print (characterisation); T-drain monotone drain; T-exit deferred-only 0 / deferred+failed 3; T-log line even N=0, dry-run no line; T-cli bad deadline exit 2; T-clock injected monotonic; T-perfile between types + salvage gated; T9 unit contract (band, ≤Timeout−300, +180≤900, 4G/6G, OOMScoreAdjust, ExecStart==module default).

## Risks
R1 HIGH residual: one native unit (whole-feather read, F2; e.g. OrderBookDepth10) can overrun; >900s skips a tick, >1800s TimeoutStartSec kill → no marker → same unit retried every run blocking backlog behind it (newest still first; OnFailure alert). Fix is S3. R2 deadline bounds wall not memory. R3 sustained deferral invisible → always-printed count line; follow-up alert N>0 for K runs. R4 loop-top overcount. R5 outcome-word parsers — grep scripts/ deploy/ first. R6 order-sensitive tests — reorder only in wrapper. R7 kill mid native write (pre-existing). Deploy: copy unit + daemon-reload; no node restart.

## Trade-offs
Gate granularity between units (binding) not per-file (S3 option) nor inside native (Nautilus immutable). 600 over 720 for 300 s overrun margin. Newest-first + stable order over persisted round-robin cursor (markers already guarantee drain) or poison-unit back-off (S3/R1). Shared RunDeadline over threaded return counts / per-pass budgets.

Confidence: HIGH on semantics; MEDIUM on 600 s throughput under 4G throttle (per-unit durations unmeasured — U1). Unknowns U1 largest unit wall; U2 outcome parsers; U3 user-manager default OOMScoreAdjust.
