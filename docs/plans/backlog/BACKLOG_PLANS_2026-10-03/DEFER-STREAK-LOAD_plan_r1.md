# DEFER-STREAK-LOAD: plan r1 (2026-10-03)

PROGRESS row (verbatim): "`ingest_deferral_streak.load_state` (:190-195) accepts non-str `first_deferred_utc` from disk unchecked". Severity LOW, from the CF-12 triage on 09-29.
Status: **DRAFT r1, awaiting peer review.** This is a plan only. Nothing is implemented.
Evidence base: codegraph (`projectPath=/home/jon/breezy`) on `src/breezy/runtime/ingest_deferral_streak.py` (whole file) and `quote_tape_ingest_core.run` (:2230-2277). Also read: `deploy/systemd/breezy-quote-tape-ingest.service`, `deploy/systemd/README.md` :645-675, `tests/unit/test_ingest_deferral_streak.py`, `tests/unit/test_quote_tape_ingest_deferral_stall.py`, and the live state file (read-only).

---

## §0 Defect and goal state

### 0.1 Code under change
`load_state` (:176-203) checks only that the file is a dict and that `version == 1`. It then builds:

```python
consecutive_runs=int(raw["consecutive_runs"]),       # coerces True->1, 3.9->3, "4"->4; no range check
first_deferred_utc=raw["first_deferred_utc"],         # ANY JSON value: int, list, dict, bool, non-ISO str, naive ISO str
runs_since_alert=int(raw["runs_since_alert"]),       # no range check: -1000 is accepted
```

The `except (JSONDecodeError, KeyError, TypeError, ValueError)` around it only covers values that `int()` rejects. `first_deferred_utc` gets no check at all.

### 0.2 Every caller of `load_state`
| Caller | Kind |
|---|---|
| `quote_tape_ingest_core.run` :2248, called as `_load_deferral_streak_state(streak_path)` (alias set at :47, `__all__` :150) | **Only production caller.** Runs only when `not namespace.dry_run` |
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

Same failure shape as L-53: one bad input makes a recurring job fail on every run.

### 0.5 Goal state
1. **Invariant G1.** `load_state` returns either `INITIAL_STATE` (with one WARNING) or a `DeferralStreakState` that `step()` can consume without raising, and whose alert timing is within the documented bound. Every value the sole writer can produce still loads unchanged.
2. **G2 (fail-safe for the streak, never stuck).** A malformed file resets the streak to a fresh start. The run finishes and saves a valid file, so the next run is healthy. The module's documented "fail SAFE, not stuck" choice is kept: no fabricated counts, and never a state of "already alerted".
3. **G3 (the loss is delivered, not only logged).** When the reset actually discards information, the run exits 4 through the existing `OnFailure=` path, once, and prints a value-free line naming why. A reset discards information when it happens on a run that has pending work, because a streak may have been in progress.

---

## §1 Null-hypothesis check (L-1)

| Candidate for reuse | Verdict |
|---|---|
| Nautilus Trader (Cache, persistence, msgspec serialization) | Not applicable. This is a 4-field dotfile that a systemd oneshot uses to alert, outside any `TradingNode`. Nautilus offers no state-file or alert-streak facility for out-of-node processes. Wrapping it in a Nautilus object would be parallel architecture. |
| `msgspec.Struct` strict decode | Rejected. msgspec is a transitive Nautilus dependency, not a declared Breezy dependency; Breezy uses it only for Nautilus config structs (`runtime/node_config.py`). It would mean replacing a frozen dataclass that tests and `step()` use through `dataclasses.replace`. It also cannot express the checks that matter here: aware datetime, ranges, and the cross-field rule. |
| Breezy `_require_str` helpers | There are three **module-private** copies: `runtime/submit_intent.py:167`, `ingest/nws_envelope.py:207`, `ingest/gaps.py:530`. Each raises its own module's exception type. **No shared, validated state-loading helper exists.** Importing a private helper across modules would break encapsulation. Extracting a shared helper for a 4-field loader is speculative abstraction (YAGNI); three call sites with different exception contracts are not one pattern. |
| Pattern to follow | Follow the house *pattern*, not a helper: explicit `isinstance` checks that raise the module's own corruption signal, which here is `ValueError`. The existing `except` already catches it. This is the smallest correct extension. |

Conclusion: no reuse target exists. The fix stays inside `ingest_deferral_streak.py`, plus a small amount of wiring in `quote_tape_ingest_core.run`.

---

## §2 Design

### S1: strict field validation (required; fixes the PROGRESS item by itself)
Replace the body of the `try` with a private `_parse_state(raw: dict) -> DeferralStreakState`. It raises `ValueError` on any violation, which the existing `except` already turns into one WARNING plus `INITIAL_STATE`. Rules:

| Field | Accept only |
|---|---|
| `consecutive_runs` | `type(x) is int` (rejects bool, float, str) and `x >= 0` |
| `runs_since_alert` | `type(x) is int` and `_NEVER_STALLED <= x < REALERT_EVERY_RUNS` |
| `first_deferred_utc` | `None`, or a `str` where `datetime.fromisoformat` succeeds **and** `tzinfo`/`utcoffset()` is not None |
| cross-field | `(consecutive_runs == 0) == (first_deferred_utc is None)`. This holds for every state `step` emits, and it closes the silent "null with runs > 0" age-reset path |

The WARN text keeps the substring "corrupt", which the existing tests assert on. The message names the failing *field* (`bad field 'first_deferred_utc'`) and never the value.

S1 alone removes every crash-loop and silent-suppression row in §0.4. A malformed file then behaves exactly as the module documents: a reset, one WARN, and a delay of at most one stall window.

### S2: deliver the reset when it can hide a stall (recommended; separable)
- Add `StreakResetReason(StrEnum)`, a closed enum: `UNPARSEABLE`, `UNSUPPORTED_VERSION`, `MISSING_FIELD`, `BAD_FIELD`.
- Add `load_state_checked(path) -> tuple[DeferralStreakState, StreakResetReason | None]`. `load_state(path)` becomes `return load_state_checked(path)[0]`. The signature used by the 12 test calls does not change. A missing file returns `(INITIAL_STATE, None)`, as today.
- `quote_tape_ingest_core.run` :2248 switches to the checked loader, through a new alias `_load_deferral_streak_state_checked` that follows the existing alias and `__all__` re-export pattern at core :46-53/:150 and cli :322/:444. After `save_state`, if `reset_reason is not None and pending_units > 0`, it prints a value-free line:
  `breezy-quote-tape-ingest: DEFERRAL_STREAK_RESET reason=<enum> pending_units=<n>`
  and sets `alert_due = True`.
- The exit precedence is unchanged (2 > 3 > 4 > 0). A run that also hit a conversion failure still exits 3, and the RESET line has already printed.
- No new exit code. The alert means "pending deferral whose stall status cannot be vouched for", which fits `EXIT_DEFERRAL_STALLED`. The notifier's `DEFERRAL_STALLED` label stays truthful enough, and the journal line tells the two cases apart. A new exit 5 is rejected because it would touch `quote_tape_exit_codes.py`, the notifier name map, the unit contract test and the README for no extra signal.
- A reset with nothing pending: WARN only, no alert. Nothing is lost, because `step` would have returned `INITIAL_STATE` anyway.
- The saved state is the honest fresh streak from `step(INITIAL_STATE, pending=True, now)`: (1, now, -1). Nothing is fabricated, which keeps the module's anti-suppression rationale. The alert fires once. The next run reads a valid file and returns to normal behaviour.

**Why S2 is fail-closed for the monitor without being stuck:** the streak state fails safe (reset). The *monitoring* fails closed: a loss of stall evidence while work is pending is surfaced on the existing delivered alert path instead of only a journal WARN that reaches no one. The module's earlier rationale (at most one window of delay) still holds, but "bounded and silent" is weaker than "bounded and announced". The cost is one possible extra alert per corruption event.

---

## §3 RED→GREEN tests

Interpreter: the repo's `.venv/bin/python` **only**. Never `uv run`, `uv sync` or pip (shared venv). In a worktree, export `PYTHONPATH=<worktree>/src`.

### S1 tests (`tests/unit/test_ingest_deferral_streak.py`, new class `TestLoadStateRejectsMalformedFields`)
| # | Test | RED today because |
|---|---|---|
| T1 | Parametrized `first_deferred_utc` ∈ {`12345`, `["x"]`, `{"a":1}`, `true`, `0`, `""`, `"not-a-date"`, `"2026-09-27T00:00:00"` (naive)} with `consecutive_runs=5, runs_since_alert=-1`: result `== INITIAL_STATE` and the WARN contains "corrupt" | the raw value is passed through |
| T2 | Parametrized `consecutive_runs` ∈ {`true`, `3.5`, `"4"`, `-1`}: result `INITIAL_STATE` | `int()` coerces |
| T3 | Parametrized `runs_since_alert` ∈ {`-1000`, `-2`, `16`, `true`}: result `INITIAL_STATE` | not range-checked |
| T4 | Cross-field: (5, `null`) and (0, valid ISO): result `INITIAL_STATE` | accepted |
| T5 | Crash invariant: for every T1-T4 fixture, `step(load_state(p), pending=True, now=_T0 + 2h)` does not raise and returns `alert_due=False` | `TypeError`/`ValueError` on the truthy and naive cases |
| T6 | Positive control / writer compatibility: walk the existing stall sequence (`_advance(0..40)`, pending throughout, then one non-pending run) and `save_state`→`load_state` after every step; each load equals the saved state with no WARN | must stay green; guards against over-strict rules |

### S1/S2 CLI tests (`tests/unit/test_quote_tape_ingest_deferral_stall.py`; reuse `_run_cli`, `_touch`, `_tiny_deadline_argv`, `_TickingClock`, `_seed_failing_instance`)
| # | Test | Expectation |
|---|---|---|
| T7 | Streak file `first_deferred_utc=12345, consecutive_runs=5`, pending work present | RED today: `TypeError` escapes `_run_cli`. GREEN under S1: no raise, file rewritten valid with `consecutive_runs == 1`. Under S2 also: exit `EXIT_DEFERRAL_STALLED` and `DEFERRAL_STREAK_RESET reason=bad_field pending_units=` in `out`, with no `12345` anywhere in out or err |
| T8 | Same malformed file, nothing pending | exit 0, no RESET line, WARN logged, file `== INITIAL_STATE` |
| T9 | Malformed file + pending + `_seed_failing_instance` | exit `EXIT_CONVERSION_FAILED` (3) and the RESET line still printed (S2) |
| T10 (S2 amendment) | Existing `test_corrupt_streak_file_resets_and_warns` currently asserts `code == EXIT_OK` for "{not json" + pending | **Deliberately amended** to `EXIT_DEFERRAL_STALLED` + `reason=unparseable`. This makes the test strictly stronger, not weaker: the reset, WARN and `consecutive_runs == 1` asserts all stay. It is a contract change and is called out for peer review. |
| T11 | Second consecutive run after T7 | normal behaviour (no RESET line; exit 0, below threshold), proving the alert is one-shot |

Existing `test_dry_run_never_touches_streak_file` and the notifier tests (`test_study_failure_alert.py`, exit-4 naming) must stay green without changes.

Record RED output for T1-T5 and T7 (S1), and for T7/T9/T10 (S2), before any production edit. Then GREEN.

---

## §4 Minimal change set
| File | Change | Slice |
|---|---|---|
| `src/breezy/runtime/ingest_deferral_streak.py` | `_parse_state` + the rules in §2; WARN names the field | S1 |
| same | `StreakResetReason`, `load_state_checked`, `load_state` as a thin wrapper; extend the docstring's "fail SAFE" section by one paragraph about delivery | S2 |
| `src/breezy/runtime/quote_tape_ingest_core.py` :46-53, :150, :2248-2265 | checked alias; RESET line; `alert_due` OR-in | S2 |
| `src/breezy/runtime/quote_tape_ingest_cli.py` :322/:444 | re-export the new alias (mirrors the existing pattern) | S2 |
| `deploy/systemd/README.md` :671-675 | one sentence: a reset while pending exits 4 with `DEFERRAL_STREAK_RESET` | S2 |
| `deploy/systemd/breezy-quote-tape-ingest.service` exit-code comment | one clause: exit 4 also covers the streak reset (comment only) | S2 |
| tests per §3 | | S1/S2 |

Not touched: `quote_tape_exit_codes.py`, `study_failure_notifier.py`, `save_state`, `step`, `STATE_VERSION`. The on-disk shape stays v1, so no migration is needed.

## §5 Gate (per slice, read the EXIT code before any push)
1. Focused: `.venv/bin/python -m pytest tests/unit/test_ingest_deferral_streak.py tests/unit/test_quote_tape_ingest_deferral_stall.py tests/unit/test_study_failure_alert.py tests/unit/test_quote_tape_ingest_unit_contract.py`. Check the exit code, not the `-q` summary.
2. `ruff check` / `ruff format --check` / `mypy` on the touched files.
3. `lint-imports` console script, run from the tree root; demand the "N kept, 0 broken" line. No new import edges: the streak module still imports nothing from the ingest CLI.
4. Full: `scripts/ci/run_tests_no_egress.sh` (about 23-25 min). EXIT must be 0.

## §6 Live activation
- `breezy-quote-tape-ingest.service` is `Type=oneshot` and is fired by `breezy-quote-tape-ingest.timer` (`*:0/15`, plus `-frequent.timer`). Every fire is a fresh interpreter importing the editable install from the primary tree. **No service, supervisor or node restart is needed.** The code goes live at the next timer fire after the merge lands on the primary tree's checked-out branch.
- S2 edits a comment in the unit file. The unit is symlinked into the repo (`~/.config/systemd/user/breezy-quote-tape-ingest.service`), so run `systemctl --user daemon-reload` right after the merge. That only clears the "changed on disk" warning; behaviour is identical. It is safe even mid-run, and it does not touch the trade node.
- Post-activation verification: from `journalctl --user -u breezy-quote-tape-ingest.service`, the next fire shows the usual summary lines, no traceback, and the expected exit. The streak file still parses. **Do not** hand-edit the production streak file as a positive control, and **do not** hand-run the unit (L-50 hand-run ban). The CLI tests T7-T11 are the positive control.

## §7 Rollback
`git revert` the slice commit(s), then wait for the next timer fire (and run `daemon-reload` if S2's unit comment is reverted). The v1 on-disk shape is unchanged in both directions, so rolling back or forward never invalidates a valid file. S1 can stay if only S2 is reverted.

## §8 Risks
| Risk | Likelihood / impact | Mitigation |
|---|---|---|
| A rule is stricter than the writer, so a genuine streak gets reset | Low / one delayed alert + (S2) one spurious exit 4 | Every rule is derived from `step`'s outputs; the T6 round-trip sweep pins writer compatibility |
| S2: a code rollback across a future `STATE_VERSION` bump fires one exit 4 | Low / one alert | Accepted; this is the correct signal |
| S2 reuses the exit-4 notifier label `DEFERRAL_STALLED` for a reset | Cosmetic | The journal line names `DEFERRAL_STREAK_RESET reason=`; a new exit code was rejected (§2) |
| A future-dated `first_deferred_utc` (aware, valid) suppresses the age threshold | Very low (hand edit only) | **Out of scope.** Rejecting it needs a clock in `load_state`, and small backward clock jumps would then reset genuine streaks. Noted for a later item if it is ever observed |
| Concurrent agents in the shared tree | Medium / false test failures | Tests use `tmp_path` only; work in an isolated worktree with `PYTHONPATH` set; never stash; commit by explicit path |

## §9 Invariants honoured
Nautilus is untouched. No trading path, permit, `allow_short`, operator cap, live enablement or NO-SEND egress is touched. No safety or contract test is weakened (T10 only gets stronger). No new dependency. No change to the on-disk format.

## §10 Open points for peer review
1. Whether to accept S2 (a contract amendment to the EDGE-6 6f "corrupt resets with WARN, exit 0" behaviour) or ship S1 alone. S1 by itself fully closes the PROGRESS row.
2. Whether the cross-field rule is too strict. It holds for every `step` output, per T6.

Self-score: 88/100. Deductions: S2 changes an existing contract test's expected exit code; the future-timestamp suppression path is left open by design.
