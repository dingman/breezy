# ING-2 S2 — r2→r3 amendment (planner, 2026-09-26; round-3 peer review)

Amends `ING-2_S2_plan_r2.md`; anything not replaced here stays r2. Line refs codegraph-verified against on-disk `quote_tape_ingest_cli.py`. No scope change.

## Changes
N1 breadcrumb written only after `admit()`→True, cleared only on a terminal outcome; no-op returns never write or clear. N2 every gate after marker checks and no-op returns, where convert work starts; tick types gated lazily at the first convertible file; a no-op never calls admit(), writes nothing, is never deferred. N3 `can_admit()` defined while the guarantee is unused; scan tail bounded to one scan. N4 `InstanceIngestResult.salvage_deferred`. N5 single precedence ladder in the merge; `count_deferred` on RAW pass results. N6–N9 residuals (N6 resolved by marked-skip unlink).

## RunDeadline (replaces r2)
State: `_guarantee_used`, `_closed` (sticky), `scans_started`, `admitted`, `deferred_units`, `deferred_instances`.
- `admit()` consuming: `_closed` → False. Guarantee unused → set used, True regardless of time. Else True iff elapsed < budget; first False sets `_closed`.
- `can_admit()` loop-top peek: `_closed` → False. elapsed < budget → True. Expired → True only if guarantee unused AND `scans_started == 0`; otherwise set `_closed`, False.
- `note_scan()` immediately before `scan_instance` :1465; increments `scans_started`; never consumes the guarantee.
- Rationale: tail bounded to one scan. `run()` builds the deadline before the snapshot, so expired-with-guarantee-unused means the budget went on no-work scans; deferring the rest is right. Residual R11.
- With the N2 gates a skip never reaches admit(), so the newest live instance cannot burn the guarantee on a skip (T-newest-skip).
- AC-D2 restated: the guarantee goes to the first gated unit that starts real work; it is unavailable after expiry once a scan has run without using it.

## Gates (replaces r2 table; `deadline=None` ⇒ no gate code runs, AC-D10)
kw-only `deadline` also threaded into `_convert_one_definition_type` and `_convert_one_tick_type_per_file`.
| Where | Inserted | On False |
|---|---|---|
| `run_ingest` loop top, after :1421 | `can_admit()` | instance row `deferred-deadline`, reason `not evaluated`, no scan |
| `run_ingest` before `scan_instance` :1465 | `note_scan()` | — |
| `ingest_instance` between marker `continue` :922 and `try` :923 | `admit()` then `_write_attempt` | type `deferred-deadline`; continue |
| `_ingest_instance_per_file` inside `if not dry_run and truncated_to_salvage:` :1255, before `salvage_truncated_instance` | `admit()` then `.attempt-salvage` | skip salvage; `salvage_deferred=True` |
| `_convert_one_definition_type` after no-op returns :1050-1053 and dry-run return :1054-1055, before `try` :1056 | `admit()` then `_write_attempt` | return `(TypeConversionResult(cls, DEFERRED_DEADLINE), False, False)` |
| `_convert_one_tick_type_per_file` in the loop after dry-run `continue` :1131-1133, before `_read_feather_file` :1134, only while `not admitted` | `admit()` then `_write_attempt`; `admitted=True` | `deferred=True`; break; result DEFERRED_DEADLINE |
Lazy tick gate: reaching :1134 means the file passed the marked/unreported/unreadable/truncated/empty/unclosed filters (:1096-1130) — that is the convertible-closed-file signal (DRY). Open/unclosed-only types, `skipped-definitions-pending` (:1293) and marked types (:1270, :1290) never reach a gate; empty-file marking (:1117-1122) stays ungated.
Ladder truncated > dry-run > failed > deferred > converted > live: `_ingest_instance_per_file` (:1310-1333) adds `elif any_deferred:` after `any_failure`; `ingest_instance` (:936-945) failed > deferred > converted. `summary_line` (:874): deferred with type_results → `partially ingested (deadline)`; deferred without → `instance X: deferred (deadline; not evaluated)`; skipped-truncated + salvage_deferred → append `; salvage deferred (deadline)`.
N4: `InstanceIngestResult` (:866-872) gains `salvage_deferred: bool = False` (kw default; 49 callers unaffected).

## Poison breadcrumbs (replaces r2)
`ATTEMPT_PREFIX=".attempt-"`; `.attempt-<class_to_filename>`, `.attempt-salvage`; empty `Path.touch()` written only after admit()→True.
Cleared ONLY on terminal outcome: (a) `_mark_converted` (:390-391) unlinks `missing_ok=True` after the marker touch; (b) caught ValueError (`ingest_instance` :925-933, `_convert_one_definition_type` :1058-1062); (c) per-file tick type admitted, not deferred, loop completed normally — every ADMITTED file ends marked (:1168, :1185) or caught-failed (:1135-1160, :1171-1197); (d) salvage returns normally. (c) considers only admitted files: open/unclosed/truncated closed files are not this unit's work, and requiring them would keep the live newest instance poisoned forever (breaks T-fresh).
No-ops never clear (N1): skipped-open, helper no-op skipped-already-converted, skipped-definitions-pending, tick loop with nothing admitted.
N6: with a deadline set, marked-skip paths (:918-922, :1270-1272, :1290-1292, and a tick type whose closed files are all marked) unlink a stale breadcrumb.
Poisoned predicate unchanged from r2; a breadcrumb only reorders, never blocks.

## Merge (replaces r2)
`_merge_pass_results(pass_one, pass_two, *, order)` (:1512): per instance the merged outcome is the higher ladder rung of p1/p2 (p2 alone if no p1 row); a winning p1 `failed` keeps the reason prefix `definitions pass failed;`; type_results p2 else p1 (existing); `salvage_deferred = p1 or p2`; re-sort to original `snap.instance_ids`.
Counts from RAW results: `run_ingest_definitions_first` calls `deadline.record(count_deferred(pass_one + pass_two))` before merging; `run()` reads `deadline.deferred_units`/`deferred_instances` for the line; public signature unchanged. Units = every DEFERRED_DEADLINE type result + 1 per salvage_deferred row. Instances = distinct ids with a `not evaluated` row in either pass. Raw keeps p1 in-instance deferrals visible under a p2 `not evaluated`; sticky closure means no unit is deferred in both passes (no double count).

## Tests (additions)
T-n1-survive (BaseException in tick T's first file → `.attempt-T`; next run T skipped-definitions-pending → survives; later run converts → gone). T-n1-noop (stale breadcrumb survives a definitions skipped-open and an all-unclosed tick return). T-n2-marked (expired run over fully marked def types → skipped-already-converted, admitted==0, no `.attempt-*`, deferred_units==0). T-n2-lazy (open/unclosed-only tick type never calls admit(); first convertible file third → exactly one admit; convertible file after expiry → deferred, first two files not re-read). T-newest-skip (newest live instance with nothing convertible leaves the guarantee unused; the next instance consumes it). T7a-tail (starts expired, N≥3 no-work instances ahead of the one with work → scans_started==1, zero converts, deferred_instances==N, exit 0; original T7a still converts once). T-scan-noconsume. T-n4-salvage (skipped-truncated + salvage_deferred + deferred_units≥1 + `salvage deferred (deadline)` in the line). T-merge ladder pairs (truncated+failed⇒truncated; failed+deferred⇒failed; deferred+converted⇒deferred; converted+live⇒converted), salvage_deferred OR, raw-count pin (p1 in-instance deferred + p2 not-evaluated ⇒ units=1, instances=1), order. T-n6 (marker then kill before unlink; next run with deadline removes it; deadline=None leaves it). T9 exit comment contains "deadline deferral".

## Files (delta)
MOD `deploy/systemd/breezy-quote-tape-ingest.service:85-90`: "deadline deferral ⇒ 0 (deferred units retry next run; see the `deadline` count line)" (N9).

## Risks (additions)
R9 (N6) closed by marked-skip unlink; with deadline=None a stale breadcrumb is inert (no reorder). R10 a type that never becomes convertible keeps its instance demoted — reorder only, accepted. R11 run expired with guarantee unused after one scan defers everything; visible as elapsed ≥ budget in the line; ING-2-ALERT covers repeats. R12 cross-pass truncated masks a p2 failed (same within a pass; both passes scan identical files). N7 backup restore brings back `.attempt-*` (reorder only). N8 hand-relaunched node inherits the user-manager OOMScoreAdjust (U3 open).
Confidence HIGH on gate placement and N1; MEDIUM on R11 acceptability.

## r3.1 coordinator addendum (architect round-3 conditions — CONVERGED)
Round-3 architect: every other round-2 fix holds against the code. Two conditions, both taken verbatim from the reviewer:
- **S1 (blocking, fixed here).** The salvage gate applies only if `any(not _is_salvage_marked(instance_dir, r.path) for r in truncated_to_salvage)`. Otherwise skip the gate and the `.attempt-salvage` breadcrumb, and leave `salvage_deferred` unset. New test **T-n4-noop**: an already-salvaged instance on an expired run yields admitted==0, no salvage_deferred, and no `.attempt-salvage`.
- **S2 (condition, taken as a residual).** R11 now reads: if the no-work scans ahead of a backlog instance cost at least the budget, that instance can be starved every run. **U5** is the measured rescan cost of the currently truncated instances. The post-deploy check reads `elapsed=` and `deferred_instances=` from the count lines across ≥4 consecutive runs. If `deferred_instances>0` persists with `deferred_units==0`, the one-scan-tail rule is replaced so that scanning continues into the 180 s allowance until the guarantee is used. ING-2-ALERT is filed as a backlog row.
- Non-blocking items to apply:
  - "no-op never calls admit()" is scoped to the per-file path. On the whole-type path, a zero-file type admits once and is then marked.
  - N6 requires "non-empty AND all marked".
  - AC-D1 notes that marking empty files after closure is allowed.
