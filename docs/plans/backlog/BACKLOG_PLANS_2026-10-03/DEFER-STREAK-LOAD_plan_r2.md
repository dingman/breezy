# DEFER-STREAK-LOAD: plan r2 (2026-10-03)

PROGRESS row (verbatim): "`ingest_deferral_streak.load_state` (:190-195) accepts non-str `first_deferred_utc` from disk unchecked". Severity LOW, from the CF-12 triage on 09-29.
Status: **DRAFT r2, awaiting peer review.** This is a plan only. Nothing is implemented.
Supersedes: `DEFER-STREAK-LOAD_plan_r1.md` (unchanged). r1 merged review: `reviews/DEFER-STREAK-LOAD-r1-merged.md` (score 90; items D1-D5 + four LOWs). Every item is applied below; see **§R2 Disposition** at the end.
Evidence base: codegraph (`projectPath=/home/jon/breezy`) on `src/breezy/runtime/ingest_deferral_streak.py` (whole file), `quote_tape_ingest_core.run` (:2230-2277), `study_failure_notifier.py` (`_cause_text` :190, `_QUOTE_TAPE_INGEST_EXIT_NAMES` :148, `notify_study_failed` :212), `check_alerts_cli.py`. Also read: `src/breezy/runtime/quote_tape_exit_codes.py`, `deploy/systemd/breezy-quote-tape-ingest.service`, `deploy/systemd/README.md` :645-675, `quote_tape_ingest_cli.py` module docstring :220-243, `tests/unit/test_ingest_deferral_streak.py`, `tests/unit/test_quote_tape_ingest_deferral_stall.py` (:274-288), `tests/unit/test_study_failure_alert.py` (:294-315), `tests/unit/test_quote_tape_ingest_unit_contract.py`, `docs/evidence/RULING_backlog_resolution_2026-09-28.md`, `docs/plans/backlog/EDGE_2026-09-27/EDGE-6_ops_reliability_plan_r2_2026-09-27.md`, commit `f97c26f8`, and the live state file (read-only).

---

## §0 Defect and goal state

### 0.1 Code under change
`load_state` (:176-203) checks only that the file is a dict and that `version == 1`. It then builds:

```python
consecutive_runs=int(raw["consecutive_runs"]),       # coerces True->1, 3.9->3, "4"->4; no range check
first_deferred_utc=raw["first_deferred_utc"],         # ANY JSON value: int, list, dict, bool, non-ISO str, naive ISO str
runs_since_alert=int(raw["runs_since_alert"]),       # no range check: -1000 is accepted
```

The `except (JSONDecodeError, KeyError, TypeError, ValueError)` around it only covers values that `int()` rejects. `first_deferred_utc` gets no check at all. Two further gaps (r1 review D2):
- **Load I/O.** `path.read_text()` (and `path.is_file()` for errnos other than ENOENT/ENOTDIR) can raise `OSError` (EACCES, EIO). `OSError` is not in the `except`, so it escapes `run()` and the interpreter exits 1, on every run, until the fault clears.
- **Save I/O.** `save_state` (:206-228) raises `OSError` on ENOSPC/EACCES/EIO, or when a directory sits at the path (`os.replace` → `IsADirectoryError`). `run()` does not catch it (core :2256), so every run crashes with exit 1, and each failed attempt leaves a `<file>.tmp-<pid>` orphan. Worse, if the save keeps failing, every run re-loads the same stale state, so `consecutive_runs` can never advance past `old+1` and **the stall alert can never fire**: silent suppression.

The current WARN also interpolates `exc`, whose text can carry the bad value (`unsupported version 'x'`, `Invalid isoformat string: '...'`).

### 0.2 Every caller of `load_state`
| Caller | Kind |
|---|---|
| `quote_tape_ingest_core.run` :2248, called as `_load_deferral_streak_state(streak_path)` (alias set at :46-48, `__all__` :150) | **Only production caller.** Runs only when `not namespace.dry_run` |
| `quote_tape_ingest_cli` :322 / :444 | Re-export of the alias only; no call |
| `tests/unit/test_ingest_deferral_streak.py` (5 calls), `tests/unit/test_quote_tape_ingest_deferral_stall.py` (7 calls) | Tests |

### 0.3 Who writes the file
`<catalog_root>/.ingest-deferral-streak-v1.json` has exactly one writer: `save_state` (:206), called only from `quote_tape_ingest_core.run` :2256, inside `breezy-quote-tape-ingest.service` (a oneshot started by a timer). Single-writer exclusion comes from systemd, not from code (L-50). `save_state` only ever persists values produced by `step()`, and those are always valid: `INITIAL_STATE` = (0, None, -1), or (≥1, `now.isoformat()` with an aware UTC timestamp, -1..15). So a malformed file can only come from:
- a hand edit,
- disk or filesystem corruption,
- a foreign tool,
- a future code version that writes a different shape under `version: 1`.

That is why the severity is LOW. The live file is currently `{"consecutive_runs": 0, "first_deferred_utc": null, "runs_since_alert": -1, "version": 1}`, which is valid.

### 0.4 What a malformed value does downstream (current behaviour)
`step()` runs `first_deferred_utc = state.first_deferred_utc or now.isoformat()` and then `datetime.fromisoformat(first_deferred_utc)` (:132-133).

| Malformed value on disk | Next run with `pending=False` | Next run with `pending=True` (the case where the detector matters) |
|---|---|---|
| Truthy non-str (`12345`, `[..]`, `{..}`, `true`) | `step` returns `INITIAL_STATE` and the file is healed silently | **Crash:** `fromisoformat` raises `TypeError`, uncaught in `run()`, so the interpreter exits 1. `save_state` never runs, so the bad file persists and **every 15-minute run crashes until no work is pending**. `OnFailure` fires with `exit=1` (no name). An `EXIT_CONVERSION_FAILED` (3) on that run is masked by the crash. The real stall alert (exit 4) can never fire. Catalog conversion is NOT blocked, because results are computed and printed before the streak block (:2214-2229). |
| Non-ISO str (`"garbage"`) | healed silently | Same crash loop (`ValueError`) |
| Naive ISO str (`"2026-09-27T00:00:00"`) | healed silently | Same crash loop: `now(aware) - naive` raises `TypeError` |
| Falsy non-str (`0`, `false`, `[]`, `{}`, `""`) or `null` while `consecutive_runs > 0` | healed silently | **Silent wrong streak.** The `or` replaces the value with `now`, so the age restarts while `consecutive_runs` is kept. The alert is delayed by up to 60 minutes, with no WARN. |
| `runs_since_alert` far below -1 (e.g. -1000) | healed silently | **Silent suppression.** The value counts up by 1 per run and only re-enters the crossing branch at -1, so a real stall goes unalerted for about \|n\| runs (-1000 is roughly 10 days). This breaks the module's own documented promise of "at most one stall window" (docstring :44-60, README :671-675). |
| `runs_since_alert` ≥ 16, or `consecutive_runs` negative, bool, or float | healed silently | Alert timing is wrong, but the error is bounded |
| Load `OSError` (EACCES/EIO) | **Crash loop** (exit 1) regardless of `pending` | Same |
| Save `OSError` | **Crash loop** (exit 1) regardless of `pending`; tmp orphan per run | Same, and the streak can never advance, so a real stall is suppressed for as long as the fault lasts |

Same failure shape as L-53: one bad input makes a recurring job fail on every run.

### 0.5 Goal state
1. **Invariant G1.** `load_state_checked` returns either `(INITIAL_STATE, reason)` with exactly one WARNING, or `(state, None)` where `step()` can consume `state` without raising and its alert timing is within the documented bound. Every value the sole writer can produce still loads unchanged. No `OSError` from loading or saving the streak escapes `run()`.
2. **G2 (fail-safe for the streak, never stuck).** A malformed or unreadable file resets the streak to a fresh start. The run finishes and (if the disk allows) saves a valid file, so the next run is healthy. The module's documented "fail SAFE, not stuck" choice is kept: no fabricated counts, and never a state of "already alerted".
3. **G3 (the loss is delivered, not only logged; mandatory).** Whenever stall evidence is lost or cannot be persisted **on a run whose `pending` is True** (definition §2.3), the run prints a value-free `DEFERRAL_STREAK_RESET reason=<enum> pending_units=<n>` line and exits non-zero through the existing `OnFailure=` path, with an exit code the notifier names `DEFERRAL_STREAK_RESET`, distinct from `DEFERRAL_STALLED`. Validation and delivery ship together, in one commit; there is no validation-only variant.

---

## §1 Null-hypothesis check (L-1)

| Candidate for reuse | Verdict |
|---|---|
| Nautilus Trader (Cache, persistence, msgspec serialization) | Not applicable. This is a 4-field dotfile that a systemd oneshot uses to alert, outside any `TradingNode`. Nautilus offers no state-file or alert-streak facility for out-of-node processes. Wrapping it in a Nautilus object would be parallel architecture. |
| `msgspec.Struct` strict decode | Rejected. msgspec is a transitive Nautilus dependency, not a declared Breezy dependency; Breezy uses it only for Nautilus config structs (`runtime/node_config.py`). It would mean replacing a frozen dataclass that tests and `step()` use through `dataclasses.replace`. It also cannot express the checks that matter here: aware datetime, ranges, and the cross-field rule. |
| Breezy `_require_str` helpers | There are three **module-private** copies: `runtime/submit_intent.py:167`, `ingest/nws_envelope.py:207`, `ingest/gaps.py:530`. Each raises its own module's exception type. **No shared, validated state-loading helper exists.** Importing a private helper across modules would break encapsulation. Extracting a shared helper for a 4-field loader is speculative abstraction (YAGNI); three call sites with different exception contracts are not one pattern. |
| Existing delivery path | **Reused, not rebuilt.** `OnFailure=breezy-study-failed@%n.service` (AUD-15a) + `study_failure_notifier` + the alert egress fixed on 09-20 (`f97c26f8`, "feat(wp-b0): alert egress -- give detection a destination") + the exit-name map (`_QUOTE_TAPE_INGEST_EXIT_NAMES`, alertcause 2026-09-27). The only extension is one new exit code and one map entry. |
| Pattern to follow | Follow the house *pattern*, not a helper: explicit `isinstance`/`type() is` checks in **module-local** helpers that raise the module's own corruption signal (`ValueError`), which the existing `except` already catches. |

Conclusion: no reuse target exists for validation. The fix stays inside `ingest_deferral_streak.py`, plus wiring in `quote_tape_ingest_core.run`, one constant in the stdlib-only `quote_tape_exit_codes.py`, and one entry in the notifier's name map.

---

## §2 Design (one slice; validation and delivery are inseparable)

### 2.1 Strict field validation
Replace the body of the `try` with a private `_parse_state(raw: dict) -> DeferralStreakState`, built from two **module-local** helpers in `ingest_deferral_streak.py` (not shared, not imported from elsewhere):

- `_require_int_in_range(raw: dict, field: str, *, lo: int, hi: int | None) -> int`: raises `_FieldError(field)` unless `type(raw[field]) is int` and `lo <= value` and (`hi is None` or `value < hi`). A missing key raises `KeyError`, which maps to `MISSING_FIELD`.
- `_require_aware_iso_or_none(raw: dict, field: str) -> str | None`: returns `None` for JSON `null`; otherwise raises `_FieldError(field)` unless `type(value) is str`, `datetime.fromisoformat(value)` succeeds, and `.utcoffset()` is not `None`.

`_FieldError` is a private `ValueError` subclass carrying only the field name, so the existing `except` still catches it and the reason maps to `BAD_FIELD`.

| Field | Accept only |
|---|---|
| `consecutive_runs` | `_require_int_in_range(lo=0, hi=None)` |
| `runs_since_alert` | `_require_int_in_range(lo=_NEVER_STALLED, hi=REALERT_EVERY_RUNS)` |
| `first_deferred_utc` | `_require_aware_iso_or_none` |
| cross-field | `(consecutive_runs == 0) == (first_deferred_utc is None)`. Holds for every state `step` emits; closes the silent "null with runs > 0" age-reset path. Violation → `BAD_FIELD` naming `first_deferred_utc` |

**Type rule for falsy values (r1 LOW).** Validation is by exact type, never by truthiness:
- `0` is a valid `consecutive_runs` (an `int`), but invalid as `first_deferred_utc` (`type(0) is not str`).
- `false`/`true` are rejected everywhere: `type(False) is int` is `False` even though `bool` subclasses `int`, so `consecutive_runs: false` and `runs_since_alert: true` both fail.
- `""` is a `str`, so it passes the type test, but `datetime.fromisoformat("")` raises `ValueError` and it is rejected as `BAD_FIELD`. It never reaches `step()`'s `or`.
- `null` is accepted only for `first_deferred_utc`, and only when `consecutive_runs == 0` (cross-field rule).
- Floats with integral value (`1.0`) are rejected (`type(1.0) is not int`).

### 2.2 Reasons and the checked loader
- `StreakResetReason(StrEnum)`, closed: `IO_ERROR`, `UNPARSEABLE`, `UNSUPPORTED_VERSION`, `MISSING_FIELD`, `BAD_FIELD`, `SAVE_FAILED`. The loader can return the first five; `SAVE_FAILED` is used only by `run()` (§2.4). A test pins that `load_state_checked` never returns `SAVE_FAILED`.
- `load_state_checked(path) -> tuple[DeferralStreakState, StreakResetReason | None]`:
  - `path.is_file()` and `path.read_text()` are moved **inside** the `try`. `OSError` → `IO_ERROR`.
  - `json.JSONDecodeError` → `UNPARSEABLE`; non-dict or `version != 1` → `UNSUPPORTED_VERSION`; `KeyError` → `MISSING_FIELD`; `_FieldError` → `BAD_FIELD`.
  - A missing file (`is_file()` False) returns `(INITIAL_STATE, None)` with no WARN, as today.
  - Every reset logs exactly one WARNING: `"%s is corrupt or unreadable (reason=%s field=%s); resetting the ingest deferral-stall streak to a fresh start"`. It keeps the substring "corrupt" (asserted by existing tests) and names the reason and field only, **never the value and never `exc` text**.
- `load_state(path)` becomes `return load_state_checked(path)[0]`. The 12 existing test calls keep their signature.

### 2.3 The one `pending` boolean (D3)
In `run()`, `pending_units = _count_pending_deferral_units(...)` is computed exactly once (as today, core :2238), then:

```
pending: bool = pending_units > 0
```

That **same local** is the only value passed to `_step_deferral_streak(streak_state, pending=pending, now=now_utc)` **and** the only gate for the reset alert. There is no second computation, no re-read, and no alternative predicate (such as "file had `consecutive_runs > 0`"). Definition: `pending` is True iff `_count_pending_deferral_units` (AC-6f-5, marker-aware) returns ≥ 1 for this run. T17 pins the equality with a spy.

### 2.4 Wiring in `quote_tape_ingest_core.run` (streak block :2230-2277)
1. `streak_state, reset_reason = _load_deferral_streak_state_checked(streak_path)`. This is a new alias that follows the existing alias and `__all__` pattern at core :46-48/:150 and the cli re-export at :322/:444.
2. `new_streak_state, alert_due = _step_deferral_streak(streak_state, pending=pending, now=now_utc)`, unchanged.
3. Save, guarded:
   ```
   save_failed = False
   try: _save_deferral_streak_state(streak_path, new_streak_state)
   except OSError as exc:
       logger.warning("... streak save failed (%s errno=%s); next run will re-read the previous state", type(exc).__name__, exc.errno)
       save_failed = True
   ```
   Only `OSError` is caught. Anything else is a bug and must stay loud.
4. The existing `DEFERRAL_STALLED` print is unchanged.
5. For each of `reset_reason` (if not None) and `SAVE_FAILED` (if `save_failed`), **when `pending` is True**, print one value-free line:
   `breezy-quote-tape-ingest: DEFERRAL_STREAK_RESET reason=<enum value> pending_units=<n>`
   and set `streak_reset_due = True`. When `pending` is False, a reset or save failure is WARN only: nothing in flight was lost, because `step` returns `INITIAL_STATE` on a non-pending run anyway.
6. Exit precedence: **2 > 3 > 4 > 5 > 0**. That is: usage; conversion failure; `alert_due` → `EXIT_DEFERRAL_STALLED`; `streak_reset_due` → `EXIT_DEFERRAL_STREAK_RESET`; OK. Every applicable line has printed before the return, so the journal shows all causes whichever code wins.
   - A load reset and `alert_due` **cannot** coincide: after a reset, `step(INITIAL_STATE, pending=True, now)` yields `consecutive_runs == 1 < STALL_MIN_CONSECUTIVE_RUNS (4)`, so `alert_due` is False.
   - A save failure **can** coincide with `alert_due`. Exit 4 wins, because a real stall is the more specific signal, and both lines print.
7. The saved state after a load reset is the honest fresh streak `(1, now, -1)` (pending) or `INITIAL_STATE` (not pending). Nothing is fabricated, which keeps the anti-suppression rationale. The alert is one-shot: the next run reads a valid file and returns to normal.

### 2.5 New exit code 5 (reverses r1's rejection; forced by D4)
r1 reused exit 4. D4 requires the notifier output to say `DEFERRAL_STREAK_RESET`, so the operator sees "reset" rather than "stalled". The notifier knows only the unit's `ExecMainStatus` (`_cause_text`, :190-209, via `systemctl --user show -p ExecMainStatus -p Result`). It cannot read the journal line, so **on exit 4 it can only ever print `(DEFERRAL_STALLED)`**. Meeting D4 therefore requires a distinct code:
- `quote_tape_exit_codes.py`: `EXIT_DEFERRAL_STREAK_RESET = 5`, with a docstring comment. The module stays a stdlib-only leaf, so the notifier's import isolation (the module docstring's L-52 rationale) is unchanged.
- `study_failure_notifier._QUOTE_TAPE_INGEST_EXIT_NAMES`: add `EXIT_DEFERRAL_STREAK_RESET: "DEFERRAL_STREAK_RESET"`. One import name and one map entry; no logic change.
- Re-export `EXIT_DEFERRAL_STREAK_RESET` from `quote_tape_ingest_cli` beside `EXIT_DEFERRAL_STALLED` (:267, :385).
- The unit needs no directive change. There is no `SuccessExitStatus=`, so any non-zero exit already triggers `OnFailure=` (unit comment). T15 pins that.

**Honest delivery boundary (cited, not assumed).** The off-box webhook payload built by `notify_study_failed` (:268-273) is fixed: `severity=WARN, event=study_unit_failed, site=global, detail=study_unit_reached_failed_state`. It carries **no unit name and no exit name**, by design (a closed `StudyFailedDetail` enum, no free text). So:
- The off-box alert proves that *a study unit failed*. That is the 09-20 delivery fix's guarantee (`f97c26f8`), and it holds for exit 5 exactly as for exits 3 and 4.
- The **name** `DEFERRAL_STREAK_RESET` appears in the notifier's journal WARN line (`breezy study unit failed unit=breezy-quote-tape-ingest.service event=study_unit_failed cause=exit-code exit=5 (DEFERRAL_STREAK_RESET)`). The `reason=` detail appears in the ingest unit's own journal line.

Widening the payload to carry the exit name is a separate change to the notifier's wire contract. It is out of scope here and is filed as a PROGRESS candidate (§8).

---

## §3 RED→GREEN tests

Interpreter: the repo's `.venv/bin/python` **only**. Never `uv run`, `uv sync` or pip (shared venv). In a worktree, export `PYTHONPATH=<worktree>/src` (and put it in the reviewer brief).

### 3.1 Streak module (`tests/unit/test_ingest_deferral_streak.py`, new class `TestLoadStateRejectsMalformedFields`)
| # | Test | RED today because |
|---|---|---|
| T1 | Parametrized `first_deferred_utc` ∈ {`12345`, `["x"]`, `{"a":1}`, `true`, `false`, `0`, `""`, `"not-a-date"`, `"2026-09-27T00:00:00"` (naive)} with `consecutive_runs=5, runs_since_alert=-1`: `load_state_checked` → `(INITIAL_STATE, BAD_FIELD)`, the WARN contains "corrupt" and `field=first_deferred_utc`, and the WARN **does not contain** the repr of the bad value | the raw value is passed through |
| T2 | Parametrized `consecutive_runs` ∈ {`true`, `false`, `3.5`, `1.0`, `"4"`, `-1`, `null`}: `(INITIAL_STATE, BAD_FIELD)` | `int()` coerces |
| T3 | Parametrized `runs_since_alert` ∈ {`-1000`, `-2`, `16`, `true`, `-1.0`}: `(INITIAL_STATE, BAD_FIELD)` | not range-checked |
| T4 | Cross-field: (5, `null`) and (0, valid aware ISO): `(INITIAL_STATE, BAD_FIELD)` | accepted |
| T5 | Crash invariant: for every T1-T4 fixture, `step(load_state(p), pending=True, now=_T0 + 2h)` does not raise and returns `alert_due=False` | `TypeError`/`ValueError` on the truthy and naive cases |
| T6 | Positive control / writer compatibility: walk the existing stall sequence (`_advance(0..40)`, pending throughout, then one non-pending run), `save_state`→`load_state_checked` after every step; each load equals the saved state with reason `None` and no WARN | must stay green; guards against over-strict rules |
| T12 | Reason mapping: `"{not json"` → `UNPARSEABLE`; `[]` and `{"version": 2, ...}` → `UNSUPPORTED_VERSION`; valid v1 missing `runs_since_alert` → `MISSING_FIELD`; `Path.read_text` monkeypatched to raise `OSError(errno.EIO, ...)` → `IO_ERROR`, no raise; missing file → `(INITIAL_STATE, None)`, no WARN. Across all of them, the reason is never `SAVE_FAILED` | `OSError` escapes; no reason API |
| T13 | `save_state` with `os.replace` monkeypatched to raise `OSError`: re-raises `OSError`, and **no `*.tmp-*` sibling remains** | the tmp orphan is left behind |

### 3.2 CLI (`tests/unit/test_quote_tape_ingest_deferral_stall.py`; reuse `_run_cli`, `_touch`, `_tiny_deadline_argv`, `_TickingClock`, `_seed_failing_instance`)
| # | Test | Expectation |
|---|---|---|
| T7 | Streak file `first_deferred_utc=12345, consecutive_runs=5`, pending work present | RED today: `TypeError` escapes `_run_cli`. GREEN: exit `EXIT_DEFERRAL_STREAK_RESET` (5); `DEFERRAL_STREAK_RESET reason=bad_field pending_units=` in `out`; no `12345` anywhere in out, err or caplog; file rewritten valid as `(1, <aware>, -1)` |
| T8 | Same malformed file, nothing pending | exit 0, no RESET line, WARN logged, file `== INITIAL_STATE` |
| T9 | Malformed file + pending + `_seed_failing_instance` | exit `EXIT_CONVERSION_FAILED` (3), and the RESET line still printed |
| T10 (amendment, justified in §R2 D5) | Existing `test_corrupt_streak_file_resets_and_warns` (:274-288) asserts `code == EXIT_OK` for `"{not json"` + pending | **Amended** to `code == EXIT_DEFERRAL_STREAK_RESET` plus `reason=unparseable` in `out`. Every existing assert is kept (WARN contains "corrupt"; `consecutive_runs == 1`). Strictly stronger |
| T11 | Second consecutive run after T7 (same pending work, clock +2 s) | exit 0, no RESET line, `consecutive_runs == 2`, `first_deferred_utc` **unchanged** from T7's saved value, **`runs_since_alert == -1` unchanged**: proves the alert is one-shot and the reset left no armed or suppressed alert counter |
| T14 | `Path.read_text` raising `OSError(EACCES)` on the streak path: (a) pending → exit 5, `reason=io_error`, no traceback; (b) nothing pending → exit 0, WARN only | RED today: `OSError` escapes |
| T16 | `quote_tape_ingest_core._save_deferral_streak_state` monkeypatched to raise `OSError(ENOSPC)`: (a) pending → exit 5, `reason=save_failed`, no raise; (b) nothing pending → exit 0, WARN; (c) on the stall-crossing run (4th pending run, ≥60 min) → exit 4, with **both** the `DEFERRAL_STALLED` and `DEFERRAL_STREAK_RESET reason=save_failed` lines | RED today: `OSError` escapes |
| T17 (D3) | Corrupt file; parametrize nothing-pending vs pending; spy-wrap `_step_deferral_streak` and record its `pending` kwarg. Assert that the RESET line is present **iff** the recorded `pending` is True, and that the spy was called exactly once | pins the single-boolean contract |

### 3.3 Delivery path (D4)
| # | File | Test |
|---|---|---|
| T18 | `tests/unit/test_study_failure_alert.py` | Mirror of the existing `test_cause_lookup_names_the_exit_code_for_the_quote_tape_ingest_unit` (:294-315): the fake `cause_reader` returns `ExecMainStatus={EXIT_DEFERRAL_STREAK_RESET}\nResult=exit-code\n` for `_QUOTE_TAPE_INGEST_UNIT`. Assert: the notifier returns 0; exactly one payload; a WARN record contains `exit=5 (DEFERRAL_STREAK_RESET)` and **not** `DEFERRAL_STALLED`; `payload.detail == StudyFailedDetail.STUDY_UNIT_REACHED_FAILED_STATE.value` (the wire stays closed-enum). The existing exit-4 test stays unmodified and keeps proving that exit 4 still names `DEFERRAL_STALLED` |
| T15 | `tests/unit/test_quote_tape_ingest_unit_contract.py` | (a) the unit has the active line `OnFailure=breezy-study-failed@%n.service`; (b) no uncommented `SuccessExitStatus=` directive (it is checked on non-`#` lines, because the comment "NO SuccessExitStatus" exists); (c) the exit-contract comment mentions `DEFERRAL_STREAK_RESET`. Together with T18, this proves exit 5 → `OnFailure=` → `breezy-study-failed@%n` → a named notifier line → an alert payload |

The delivery chain is unit-test-proven end to end except the systemd hop itself, which is pinned by configuration (T15) and by `systemd-analyze verify` (the existing `test_systemd_analyze_verify_passes_when_available`). The off-box webhook leg is covered by the 09-20 loopback-HTTPS tests from `f97c26f8`; this plan does not touch it.

Unchanged and must stay green with no edits: `test_dry_run_never_touches_streak_file`, `test_run_exits_zero_when_every_non_success_is_a_deferral` (AC-6f-3; it has no streak file, so the missing-file path gives reason `None` and no alert), the existing exit-4 notifier test, and `test_write_is_atomic_no_tmp_file_left_behind`.

Record RED output for T1-T5, T7, T10 (amended), T12-T14, T16 and T18 before any production edit. Then GREEN. T6, T8, T11, T15(a/b) and T17 may be green or red at RED time; record whichever it is.

---

## §4 Minimal change set (one commit)
| File | Change |
|---|---|
| `src/breezy/runtime/ingest_deferral_streak.py` | `_FieldError`, `_require_int_in_range`, `_require_aware_iso_or_none`, `_parse_state`, `StreakResetReason`, `load_state_checked`; `load_state` becomes a thin wrapper; value-free WARN; `save_state` unlinks its own tmp file on failure and re-raises (the persisted shape and write order are unchanged); the docstring's "fail SAFE" section gains one paragraph on delivery (exit 5 when pending) |
| `src/breezy/runtime/quote_tape_exit_codes.py` | `EXIT_DEFERRAL_STREAK_RESET = 5` + comment |
| `src/breezy/runtime/study_failure_notifier.py` | import + one map entry `DEFERRAL_STREAK_RESET` (:87, :148-152) |
| `src/breezy/runtime/quote_tape_ingest_core.py` :43-60, :150, :2230-2277 | checked alias; import of exit 5; single `pending` local; guarded save; RESET lines; precedence 2 > 3 > 4 > 5 > 0; precedence comment |
| `src/breezy/runtime/quote_tape_ingest_cli.py` :220-243 (docstring exit table + precedence), :267/:385, :322/:444 | exit-table row for 5; re-export the constant and the alias |
| `deploy/systemd/README.md` :671-675 | replace "resets ... with one WARNING" with: a reset or save failure while work is pending prints `DEFERRAL_STREAK_RESET reason=…` and exits 5; otherwise WARN only |
| `deploy/systemd/breezy-quote-tape-ingest.service` exit-code comment | one clause for exit 5 (comment only) |
| tests per §3 | T1-T18 |

Not touched: `step`, `STATE_VERSION`, the on-disk shape (v1, no migration), the notifier's payload/`StudyFailedDetail`, `health.py`, the alert egress.

## §5 Gate (read the EXIT code before any push)
1. Focused: `.venv/bin/python -m pytest tests/unit/test_ingest_deferral_streak.py tests/unit/test_quote_tape_ingest_deferral_stall.py tests/unit/test_study_failure_alert.py tests/unit/test_quote_tape_ingest_unit_contract.py`. Check the exit code, not the `-q` summary.
2. `ruff check` / `ruff format --check` / `mypy` on the touched files.
3. `lint-imports` console script, run from the tree root; demand the "N kept, 0 broken" line. No new import edges: the streak module still imports nothing from the ingest CLI, and `quote_tape_exit_codes` stays stdlib-only (the notifier imports nothing new beyond it).
4. Full: `scripts/ci/run_tests_no_egress.sh` (about 23-25 min). EXIT must be 0.

## §6 Live activation
- `breezy-quote-tape-ingest.service` and `breezy-study-failed@.service` are both `Type=oneshot`. Each fire is a fresh interpreter importing the editable install from the primary tree. **No service, supervisor or node restart is needed.** The code goes live at the next timer fire after the merge lands on the primary tree's checked-out branch.
- The unit-file comment changes. The unit is symlinked into the repo, so run `systemctl --user daemon-reload` right after the merge. That only clears the "changed on disk" warning; behaviour is identical. It is safe even mid-run, and it does not touch the trade node.
- Post-activation verification: from `journalctl --user -u breezy-quote-tape-ingest.service`, the next fire shows the usual summary lines, no traceback, the expected exit, and no `DEFERRAL_STREAK_RESET` line (the live file is valid). The streak file still parses. **Do not** hand-edit the production streak file as a positive control, and **do not** hand-run the unit (L-50 hand-run ban). T7-T18 are the positive control.

## §7 Rollback
`git revert` the single commit, then `daemon-reload` (the unit comment reverts) and wait for the next timer fire. The v1 on-disk shape is unchanged in both directions, so rolling back or forward never invalidates a valid file. **There is no partial rollback.** Validation without delivery would convert today's loud crash into a quiet WARN, which is the silent-detector shape the 09-20 fix exists to prevent. If delivery must go, the whole change goes.

## §8 Risks
| Risk | Likelihood / impact | Mitigation |
|---|---|---|
| A rule is stricter than the writer, so a genuine streak gets reset | Low / one delayed alert + one spurious exit 5 | Every rule is derived from `step`'s outputs; the T6 round-trip sweep pins writer compatibility |
| A code rollback across a future `STATE_VERSION` bump fires one exit 5 | Low / one alert | Accepted; this is the correct signal |
| The off-box payload is identical for exits 3/4/5 | Certain / the operator must open the journal to tell them apart | Unchanged from today for 3/4. The notifier journal line names the exit (T18). Payload widening filed below |
| Persistent save failure (disk full) | Low / one exit 5 per pending run (≤ 4/h) | Intentional: the detector is blind for as long as it lasts, and that must be loud. It stops when the disk recovers or when nothing is pending |
| Concurrent agents in the shared tree | Medium / false test failures | Tests use `tmp_path` only; work in an isolated worktree with `PYTHONPATH` set; never stash; commit by explicit path |

**PROGRESS row candidates.** These are filed here only; this plan does not edit PROGRESS.
1. **DEFER-STREAK-FUTURE-TS (LOW).** A future-dated but aware, valid `first_deferred_utc` makes `age` negative, so the 60-minute threshold is suppressed until wall time passes it. Only a hand edit can produce this. Rejecting it needs a clock in `load_state`, and small backward clock jumps would then reset genuine streaks. Candidate fix: in `step`, clamp with `age = max(age, 0)` and reject in `run()` only when the value is more than one stall window ahead of `now`. Reopen if ever observed.
2. **STUDY-ALERT-EXIT-NAME (LOW).** The study-failure webhook payload carries neither the unit nor the exit name (`StudyFailedDetail` has one member). Candidate: a closed-enum `detail` per named exit. This is a wire-contract change and needs its own security review.

## §9 Invariants honoured
Nautilus is untouched. No trading path, permit, `allow_short`, operator cap, live enablement or NO-SEND egress is touched. No safety or contract test is weakened: T10 keeps every assert and adds two, and AC-6f-3's pinned test is unmodified. No new dependency. No change to the on-disk format or the alert wire payload.

## §10 Open points for peer review
1. Exit 5 versus reusing exit 4 (§2.5): the choice is forced by D4's "notifier says DEFERRAL_STREAK_RESET" and evidenced by `_cause_text`'s inputs. Reviewers should confirm or name a cheaper way to meet D4.
2. Whether a save failure on a non-pending run should also alert. r2 says no, under the single `pending` gate (D3). The cost is that a persistently unwritable file only alerts once work is pending, which is exactly when it matters.

---

## §R2 Disposition

| Item | Disposition | Where |
|---|---|---|
| **D1 [HIGH]** delivered alert mandatory, same change; drop "S1 can stay"; alert on any reset with work pending | **Applied.** S1/S2 merged into one slice and one commit (§2 header, §4). §7 now forbids a partial rollback and says why. G3 makes delivery mandatory. The alert fires for **every** reset reason (IO_ERROR, UNPARSEABLE, UNSUPPORTED_VERSION, MISSING_FIELD, BAD_FIELD) and for SAVE_FAILED whenever `pending` is True (§2.4 step 5) | §0.5, §2, §4, §7 |
| **D2 [MED]** `IO_ERROR` on load `OSError`; handle `save_state` failure; no crash-loop; tests | **Applied.** `is_file`/`read_text` moved inside the `try`, `OSError` → `IO_ERROR`. Save is guarded in `run()` (only `OSError`), with reason `SAVE_FAILED`; `save_state` cleans its own tmp. Tests T12, T13, T14, T16. §0.1/§0.4 document both crash loops | §0.1, §0.4, §2.2, §2.4, §3 |
| **D3 [MED]** tie the alert to the same `pending` passed to `step`; define it exactly | **Applied.** §2.3: a single local `pending = pending_units > 0`, computed once from `_count_pending_deferral_units` (AC-6f-5), passed to `step` and used as the only reset gate. T17 spy pins it | §2.3, T17 |
| **D4 [MED]** notifier-mapping test: exit reaches `breezy-study-failed@%n`, notifier output contains `DEFERRAL_STREAK_RESET`; cite the 09-20 fix | **Applied, with one evidence-driven deviation.** The notifier names the exit from `ExecMainStatus` alone (`_cause_text` :190-209), so on exit 4 it can only print `DEFERRAL_STALLED`. "Exit 4" and "output contains `DEFERRAL_STREAK_RESET`" cannot both hold. r2 introduces `EXIT_DEFERRAL_STREAK_RESET = 5` and a map entry (§2.5). T18 is the mapping test; T15 pins `OnFailure=` and the absence of `SuccessExitStatus=`. The 09-20 fix is cited: `f97c26f8` (2026-09-20) "feat(wp-b0): alert egress -- give detection a destination". The boundary is stated honestly: the webhook payload does not carry the exit name, so it is filed as a PROGRESS candidate | §1, §2.5, §3.3, §8 |
| **D5 [python]** quote the EDGE-6 6f ruling; justify the T10 amendment | **Applied.** See below | here |
| LOW: type rule for `0`, `""`, `false` | **Applied** | §2.1 "Type rule" |
| LOW: name the local `_require_*` helpers | **Applied:** `_require_int_in_range`, `_require_aware_iso_or_none` (+ `_FieldError`), module-local | §2.1 |
| LOW: T11 asserts `runs_since_alert` unchanged | **Applied** (`== -1`, plus `first_deferred_utc` unchanged) | T11 |
| LOW: future-dated timestamp as a PROGRESS row candidate in §8; do not edit PROGRESS | **Applied** (DEFER-STREAK-FUTURE-TS) | §8 |

### D5: the EDGE-6 6f ruling, quoted, and the T10 justification
**Search result.** `docs/evidence/` holds exactly one ruling line on EDGE-6, at `docs/evidence/RULING_backlog_resolution_2026-09-28.md:70`:

> `| EDGE-6 | CLOSE | 6b/6d/6f live; 6c K1 retired in 833bada. The only residue was ING-2-AMEND, now ING-2-AMEND2. |`

(`RULING_k1_daily_disposition_2026-09-27.md` mentions EDGE-6 only for 6c/6d.) The ruling closes 6f as *live*; it says nothing about corrupt-file behaviour. The 6f acceptance criteria live in the plan the ruling closed, `docs/plans/backlog/EDGE_2026-09-27/EDGE-6_ops_reliability_plan_r2_2026-09-27.md`:

> **AC-6f-1** Pending work deferred on ≥ 4 consecutive runs **and** ≥ 60 min makes the run exit **4** (`EXIT_DEFERRAL_STALLED`) on the crossing run. `OnFailure=` then delivers `study_unit_failed` via `breezy-study-failed@`. (:114)
>
> **AC-6f-3** Below threshold → exit 0. `test_run_exits_zero_when_every_non_success_is_a_deferral` stays green, unmodified. (:116)

The only corrupt-file artefact in that plan is a test *name* in the 6f test list (:353): `test_corrupt_streak_file_resets_and_warns`. **No AC and no ruling specifies an exit code for a corrupt file.** The `assert code == EXIT_OK` in that test (:284) is an implementation choice, mirrored in the module docstring ("fail SAFE, not stuck") and README :671-675.

**Why amending T10 from 0 to 5 is a strengthening, not a weakening:**
1. **No ruled contract changes.** AC-6f-1 (exit 4 on a crossing) and AC-6f-3 (below threshold → exit 0, with its pinned test unmodified) still hold exactly. A corrupt file with pending work is neither "crossed" nor "below threshold"; the streak is **unknown**. AC-6f-1's own phrasing makes delivery via `OnFailure=` the 6f control, and r2 extends that control to the unknown case.
2. **Every existing assert is kept** ("corrupt" WARN; `consecutive_runs == 1`, i.e. reset rather than poisoned). Two are added: the exit code and `reason=unparseable`. The amended test fails on strictly more wrong implementations than the original.
3. **The "fail SAFE, not stuck" rationale is kept and completed.** Its argument is that a reset delays an alert by at most one window and never suppresses one. That bound holds only for well-formed values. §0.4 shows that malformed values break it (an approximately 10-day suppression, crash loops). Once the bound can fail, a silent WARN is the detector-without-delivery shape that `f97c26f8` was written to end ("every alert this system has ever emitted went to a log file nobody reads").
4. **Nothing is fabricated.** The saved state is still the fresh `(1, now, -1)`, and exit 5 is a distinct code, so the 6f stall semantics and the `DEFERRAL_STALLED` name stay exclusively for real stalls.

---

Self-score: 94/100. Deductions:
- (−3) Exit 5 adds surface (exit table, notifier map, unit comment) that r1 avoided. It is forced by D4, but peers must confirm it.
- (−2) The off-box payload still cannot distinguish exits 3/4/5 (filed, not fixed).
- (−1) The future-timestamp path is still open by design (filed).
