# ING-2 S2 — per-run ingest deadline (plan r2, 2026-09-26, planner; round-2 peer review)

r1 (`ING-2_S2_plan_r1.md`) review: python-reviewer HIGH (non-blocking: explicit merge re-sort); architect REQUEST_CHANGES (8 items). r2 addresses all.

## r1→r2 changes
- Poison unit (L-49): per-(instance,type) attempt breadcrumb written before each admitted unit, beside `.converted-*` markers; with a deadline set both passes order instances (poisoned, not-newest, list index) — a poison unit blocks only itself.
- Pass 1 (definitions) gets the same newest-first ordering.
- RunDeadline: sticky expiry; exactly one guaranteed unit per run, consumed by the first gated unit; with a pass-1 selection it is a definitions unit; the loop-top check is a non-consuming peek.
- AC-D10 contradiction resolved: reorder + breadcrumbs ONLY when a deadline is set; `deadline=None` byte-identical; production always has one (AC-D8).
- Unit contract: `OOMScoreAdjust=500` exact; supervisor unit has no OOMScoreAdjust ≥500; +180 s named/justified; no hand-run while active (L-50).
- Honest counts: loop-top deferrals are `deferred_instances=<k>`, separate from `deferred_units=<n>` (r1 R4 removed).
- `_merge_pass_results` explicit precedence + re-sort to original `snap.instance_ids` (python-reviewer).
- 10 new tests; follow-up row ING-2-ALERT (out of scope).

## Code facts (codegraph-verified)
`run()` :1673 → `run_ingest_definitions_first` :1547 (one LivenessSnapshot; pass 1 defs over `_needs_definition_pass`; pass 2 `run_ingest` :1377 over all; `_merge_pass_results` :1512 pass-2 order + p1-failed rule). `run_ingest` → `ingest_instance` :891 (whole-type; convert_fn then `_mark_converted`, ValueError caught per type) or `_ingest_instance_per_file` :1211 (salvage → defs → ticks; per-file markers). Markers: presence-only dotfiles in the instance dir — `_marker_path` :342 `.converted-<class_to_filename>` via `Path.touch()` in `_mark_converted` :390; per-file `.converted-file-<relpath>` :394. Exits: argparse → 2; PreflightError → 2; any `failed` → 3; else 0. `list_instance_ids` (`feather_preflight.py:498`) name-sorted hashes. Unit: 4G/6G/1800, no OOMScoreAdjust anywhere in deploy/systemd, `OnFailure=breezy-study-failed@%n`; `*:0/15` + 6-hourly timers.

## Acceptance criteria
1. AC-D1 After admission closes, no new unit starts (unit = one (instance,type) convert_fn, one salvage, one per-file type, or one instance scan). Skipped in-instance unit → `deferred-deadline`, no marker; loop-top-skipped instance → `deferred-deadline` reason `not evaluated`, no type_results. Exit 0 when deferral is the only non-success.
2. AC-D2 One guaranteed unit per RUN, consumed by the first gated unit; with a pass-1 selection it is a definitions unit (pass-1 salvage runs with definition-only data_types, so it counts as one).
3. AC-D3 A deferred unit converts next run, no duplicate rows; row set equals a no-deadline run with the real StreamingFeatherWriter (L-42).
4. AC-D4 Any pass-1 definitions deferral ⇒ zero tick units (structural via sticky expiry); next run `_needs_definition_pass` reselects it.
5. AC-D5 (deadline set only) Both passes order instances by key (has breadcrumb without its marker, id != `snap.newest_instance_id`, list index). Printed rows stay in original `snap.instance_ids` order. Backlog drains monotonically; no completed unit re-attempted. `deadline=None` → order unchanged.
6. AC-D6 Injectable monotonic `clock_ns` (default `time.monotonic_ns`), independent of wall `now_ns`; dry-run passes `deadline=None`.
7. AC-D7 Every non-dry run that reaches ingest or PreflightError prints exactly one line, even with all counts 0, including exit 3 and PreflightError→2: `breezy-quote-tape-ingest: deadline budget=<B>s elapsed=<E>s deferred_units=<n> deferred_instances=<k> instances=<M>`. No ids, no prices. argparse / bad `--deadline-seconds` exit 2 prints no line (no budget yet); a test pins this.
8. AC-D8 `--deadline-seconds` finite >0 else exit 2; `DEFAULT_DEADLINE_SECONDS = 600` is the argparse default. No disable value — `run()` builds a RunDeadline for every non-dry run.
9. AC-D9 Unit contract: ExecStart `--deadline-seconds` ∈ [600,720] and == module default; ≤ TimeoutStartSec−300; deadline + `STARTUP_AND_TAIL_ALLOWANCE_SECONDS` (180) ≤ 900; 4G / 6G / 1800 unchanged; `OOMScoreAdjust=500` exact; `breezy-trade-supervisor.service` has no OOMScoreAdjust ≥500; `systemd-analyze verify` passes.
10. AC-D10 `deadline=None` byte-identical: no reorder, no breadcrumbs, no gates (49 `run_ingest` callers, S1 tests, ING-1 EXTEND tests, `TestTheMixedCatalogLayoutIsPinned`). Full gate + lint-imports green.

## Design
### RunDeadline (new `src/breezy/runtime/ingest_deadline.py`, imports time/typing only)
`RunDeadline(budget_ns, clock_ns)`, deliberately stateful:
- `admit()` consuming. First call of the run → True whatever the time (the guaranteed unit). After that → `clock_ns()-start < budget`. First False is STICKY: every later `admit()`/`can_admit()` → False for the rest of the run.
- `can_admit()` non-consuming peek (loop top).
- `admitted` counter; `elapsed_ns`.
Module also holds `DEFERRED_DEADLINE`, `DEFAULT_DEADLINE_SECONDS=600`, `STARTUP_AND_TAIL_ALLOWANCE_SECONDS=180`, `count_deferred(results) -> (units, instances)`.

### Threading and gates
`run(clock_ns=None)` builds the RunDeadline before the snapshot (None for dry-run). Keyword-only `deadline` threaded through `run_ingest` / `ingest_instance` / `_ingest_instance_per_file` / `run_ingest_definitions_first`.
| Where | Check | On failure |
|---|---|---|
| `run_ingest` loop top | `can_admit()` | one instance-level `deferred-deadline` row, no scan |
| `ingest_instance`, before each un-markered convert_fn | `admit()` | that type `deferred-deadline` |
| `_ingest_instance_per_file`, before salvage / each def type / each tick type | `admit()` | that unit `deferred-deadline` |
Outcome precedence: truncated > dry-run > failed > deferred > converted > live. Row with deferred units → summary prefix `partially ingested (deadline)`; loop-top row → `instance X: deferred (deadline; not evaluated)`.

### Ordering (deadline set only)
`_poison_first_order(ids, snap, catalog_root, subdirectory)`: stable sort by (poisoned, id != newest, index). Pass 1 `replace(snap, instance_ids=_poison_first_order(selected))`; pass 2 `replace(snap, instance_ids=_poison_first_order(snap.instance_ids))`. `replace` keeps the full-list `newest_instance_id` (S1 A6).

### Poison breadcrumbs (L-49)
- `ATTEMPT_PREFIX = ".attempt-"` in the instance dir, beside markers: `.attempt-<class_to_filename>` per (instance,type); `.attempt-salvage` per instance.
- Written (deadline set only) immediately after `admit()` returns True, before the unit starts: empty presence-only file via `Path.touch()` (same mechanism as `_mark_converted`); nothing to tear; a kill before creation means the unit never started.
- Cleared: `_mark_converted` unlinks the type breadcrumb (`missing_ok=True`) AFTER touching the marker (kill between → marker+breadcrumb, which the predicate ignores). A unit that returns normally without a per-type marker (caught ValueError, per-file tick type, salvage return) also unlinks its breadcrumb. So a breadcrumb survives only a MemoryMax/TimeoutStartSec kill or a propagating BaseException.
- Poisoned = any `.attempt-<cls>` without its `.converted-<cls>`, or `.attempt-salvage` present. The poisoned unit still runs when nothing is ahead of it (OnFailure stays visible) but blocks only itself.
- Dotfiles already excluded by `iter_feather_files`; T-poison asserts `_instance_is_fully_converted` unaffected.

### Merge
`_merge_pass_results(pass_one, pass_two, *, order)`: per instance — p1 failed ⇒ failed (existing); else p1 deferred ⇒ failed if p2 failed, otherwise deferred; else p2. Re-sort merged rows by index in the ORIGINAL unreordered `snap.instance_ids` (identity when nothing was reordered).

## Files
- NEW `src/breezy/runtime/ingest_deadline.py`
- MOD `src/breezy/runtime/quote_tape_ingest_cli.py`: deadline kw; gates; `_poison_first_order`; `ATTEMPT_PREFIX`, `_write_attempt`/`_clear_attempt`; `_mark_converted` clears the breadcrumb; merge precedence + re-sort; `--deadline-seconds`; `run(clock_ns=None)`; count line on 0 / 3 / PreflightError; docstring
- MOD `deploy/systemd/breezy-quote-tape-ingest.service`: `--deadline-seconds 600`, `OOMScoreAdjust=500` (commented); comment "never hand-run while `systemctl --user is-active` reports active — two writers race markers/catalog (L-50)"; 4G/6G/1800 unchanged
- NEW `tests/unit/test_quote_tape_ingest_deadline.py`, `tests/unit/test_quote_tape_ingest_unit_contract.py`
- MOD `tests/unit/test_quote_tape_ingest_cli.py` only if it enumerates an outcome vocabulary (+1 reviewed row)

## Tests (FakeClock advances inside the convert_fn spy AND a fake scan_instance)
Kept from r1: T6a defer/exit 0; T6b next-run convert, no duplicates (real feathers); T7a expired-at-start ⇒ exactly one convert; T7b per-run not per-pass (mutation check); T-defs; T-defs-next; T-fresh newest first + list-order print; T-drain; T-exit (0 / 3); T-log line even N=0, dry-run no line; T-cli bad deadline ⇒ 2 and no line; T-clock; T-perfile gates between types + salvage gated; T9 unit contract (band, ≤Timeout−300, +180≤900, 4G/6G/1800, OOMScoreAdjust==500, supervisor none ≥500, ExecStart == module default).
New in r2:
- T-sticky: hypothesis property over random clock sequences — after the first False, all later admit()/can_admit() False; `admitted` never grows after expiry.
- T-expired-p1: expired at start with a pass-1 selection ⇒ exactly one definitions convert, zero ticks.
- T-partial-whole: whole-type mid-instance deferral ⇒ markers only for converted types; next run converts only the deferred types, no duplicates, real writer.
- T-merge: failed+deferred ⇒ failed; deferred+deferred ⇒ deferred; p1-failed unchanged; output order = original ids after reorder.
- T-scan-clock: clock advanced inside fake scan_instance closes admission ⇒ next instance deferred at loop top.
- T-poison: BaseException from convert_fn on A ⇒ no marker + breadcrumb on A; next run converts B, C before A, A still runs last; marker write clears A's breadcrumb.
- T-p1-order: pass 1 attempts the newest selected instance first.
- T-line-paths: deadline line on exit 3 and PreflightError→2.
- T-none-identical: `deadline=None` ⇒ no `.attempt-*` files, list order unchanged.
- T-sdv: `systemd-analyze verify` when present; else `pytest.skip("systemd-analyze not on PATH")` (reported, never a silent pass).

## Risks
- R1 HIGH residual: one native unit (whole-feather read, F2) can overrun. >900 s skips a tick; >1800 s TimeoutStartSec kill, no marker → breadcrumb demotes it so it blocks only itself; OnFailure fires each time. Fix = S3.
- R2 bounds wall time, not memory. R3 sustained deferral visible only via the count line → follow-up ING-2-ALERT. R4 withdrawn. R5 outcome-word parsers — grep scripts/ deploy/ first (python-reviewer found none as of 09-26). R6 reorder only in the wrapper, only with a deadline. R7 kill mid native write (pre-existing). R8 a normal-return clear hides a slow-but-surviving unit — accepted.
- Deploy: copy unit + `daemon-reload`; no node restart; no manual run while is-active (L-50).

## Trade-offs
Gate between units (binding), not per file (S3 option), not inside native (Nautilus immutable). 600 over 720 s (300 s overrun margin). 180 s is a budget, not a measurement (U4): ~45 s import under Nice=10 + 4G throttle, ~15 s listing/snapshot/output, 120 s margin; 600+180=780 ≤ 900. Breadcrumb demotion over a persisted cursor/back-off counter (reuses the marker mechanism). One shared sticky RunDeadline over threaded counts / per-pass budgets.

## Follow-up (out of S2 scope)
ING-2-ALERT: alert when `deferred_units+deferred_instances > 0` for K consecutive runs, via the alerts.env egress convention.

Confidence HIGH on semantics; MEDIUM on 600 s throughput under 4G throttle. Unknowns U1 largest unit wall; U2 parsers; U3 user-manager default OOMScoreAdjust; U4 startup wall under Nice=10.
