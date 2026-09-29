# CF-12 — mypy burn-down, Rev 2 (2026-09-29)

Status: PEER-REVIEWED (architect ENDORSE-WITH-AMENDMENTS 80; python-reviewer
ENDORSE-WITH-AMENDMENTS 62 on the unmeasured r1). Rev 2 folds in every amendment
and replaces r1's guesses with measured numbers.

## Measured baseline (HEAD 5046132, 2026-09-29 00:59Z)

Command: `.venv/bin/python -m mypy --cache-dir <scratch>` (config lives only in
`pyproject.toml [tool.mypy]`). The run took 17 s wall time and stayed under a 4G
cap, so it is cheap enough to run inside the pytest gate.

**Found 1915 errors in 251 files (checked 919).** r1 used 1891/247 from 645baf5;
the difference is 15 commits of drift.

| By code | n | By package | n |
|---|---|---|---|
| no-untyped-def | 572 | tests/unit | 1471 |
| arg-type | 315 | scripts/analysis | 364 |
| import-not-found | 314 (202 in scripts/analysis) | scripts/venue | 23 |
| unused-ignore | 185 | src/breezy/analysis | 13 |
| attr-defined | 171 | tests/contract | 11 |
| no-any-return | 74 | src/breezy/strategy | 9 |
| type-arg | 72 | scripts/archive | 8 |
| other | 212 | src/breezy/runtime | 7 |
| | | adapters / settlement | **0 / 0** |

- `tests/unit/test_trade_supervisor.py` alone has 466 errors, 24% of the total.
- The next largest file has 69.
- r1's claim that unused-ignore is the largest bucket was **false**: it is 4th.

**Why the backlog built up:** CI's blocking `uv run mypy` step has been red and
ignored, and a collection blocker hid the count until `explicit_package_bases`
(645baf5) removed it. A gate nobody reads is not a gate. That is the reason
for enforcing this inside the local pytest gate.

## Goal state (acceptance)

1. Plain `mypy` exits 0.
2. CI's mypy step is blocking again.
3. The ratchet test is deleted.

## Mechanism: a ratchet test inside the gate (Wave 0)

`tests/unit/test_mypy_ratchet.py` follows the pattern of
`test_strategy_module_gate.py:107` and the count pins in
`test_continuous_rung_hold_backtest_only.py:88`.

- A module-scoped fixture runs ONE full-config `sys.executable -m mypy`. Never run it on a subset of paths, because following imports changes the counts.
- It parses `path:line: error: … [code]` lines, drops `note:` lines, and cross-checks the total against the `Found N errors` line.
- It asserts two things against constants in the test file:
  - `CLEAN`: a tuple of packages/files that must have exactly 0 errors. It only ever grows. A new file under any path must have 0 errors.
  - `CEILINGS`: about 14 per-package maxima. If the actual count drops below a ceiling, the test fails with "lower the ceiling to N", so ceilings cannot go stale.
- The docstring pins the mypy version from `uv.lock`. A mypy version bump re-baselines in its own commit.
- CI: mark the `Mypy` step `continue-on-error: true` with a CF-12 comment until the goal state is reached.
- The ratchet lives in the local gate.

## Behaviour-neutrality is checked mechanically, not by review

Run a close-out checker for each slice from the scratchpad; it is not committed.

- **Comment-only slices** (ignore removal): the per-file `ast.dump(ast.parse(...))` must be equal before and after.
- **Annotation slices:** the AST must be equal after stripping annotations from arguments, returns, and simple `AnnAssign` statements.
- Any AST difference outside those rules goes to the **bug-ticket path**: a separate item with a RED test. It never ships under CF-12.
- Some annotations change runtime behaviour. Editing any of these needs a RED test:
  - msgspec `Struct` fields and Nautilus `*Config` fields (they decode and validate);
  - `@dataclass` fields;
  - `ClassVar` versus a field;
  - TypedDict totality;
  - anything read by `get_type_hints`.
- A Protocol or TypedDict for a Nautilus object that mypy sees as Any must describe attributes that really exist in Nautilus 1.231.0. Cite the source in the commit. Never mark one `@runtime_checkable`, and never use one in an `isinstance` check.

## Waves (ordered by risk and value, measured)

| Wave | Scope | Size | Rule |
|---|---|---|---|
| 0 | Ratchet test + CI `continue-on-error` | — | RED→GREEN on the ratchet test itself (fake output fixture) |
| 1 | **Money path, 16 errors**: `runtime/trade_supervisor.py` (6, `_send_permit_alert` receives Optional), `strategy/current_rung_hold/trial_day_latch.py` (8, halt-state StateStore key Optional, and `object` not callable), `fee_drift_probe.py:210` (empty-body), `runtime/quote_tape_ingest_cli.py:2413` | 16 | **Triage first.** Each site is either UNREACHABLE (narrowing fix) or REACHABLE (bug ticket with a RED test). Gated on the 09-29 reachability triage. |
| 2 | unused-ignore removal | 185 | comment-only; per-file AST equality |
| 3 | `import-not-found` strategy for scripts/analysis bare sibling imports | 314 | **Decision step first**: make them real package imports, or add a mypy path entry. Never remove `files` entries (pinned by `test_polymarket_us_taxonomy.py:156-216`). |
| 4 | Remaining `src/` (analysis 13) | 13 | annotation slices |
| 5 | `tests/unit/test_trade_supervisor.py`, as its **own slice** | 466 | Stripped-AST equality. The supervisor is the permit engine. |
| 6 | Rest of tests/ and scripts/. `scripts/venue` and `scripts/archive` come first. | ~900 | Stripped-AST equality. Mandatory for the NO-SEND conftest, contract, permit, settlement, exit_guard, and ambiguous-resolver tests. |
| 7 | Goal state: CI blocking, ratchet deleted | — | — |

Each wave's exit:
- the slice reaches 0;
- lower the matching CEILING or add the slice to CLEAN;
- run the full gate `scripts/ci/run_tests_no_egress.sh` and **read its EXIT before chaining any other step**;
- `lint-imports` passes;
- python-reviewer signs off. For runtime/strategy slices, trading-bot-architect also signs off.

## Wave 1 triage result (2026-09-29, two silent-failure-hunter passes, high confidence)

All 16 sites are **UNREACHABLE (type-only)**. None of them is a bug ticket.

- `trade_supervisor.py:2140-2142`, `:2273-2275`: `PermitAlertDecision` is built only by `decide_permit_alert` (`trade_supervisor_core.py:1669-1719`). Both of its ALERT branches fill `event`, `severity` and `detail`, and each call site is guarded by `action is ALERT`.
- `quote_tape_ingest_cli.py:2413`: `step()` returns `alert_due=True` only with `first_deferred_utc = state… or now.isoformat()` (`ingest_deferral_streak.py:132`).
- `trial_day_latch.py` sites 1050/1141/1179/1188/1190/1270/1296: `_require_family_id()` runs first in every method, and `_family_halt_key` is assigned once (`:691`). **A set halt cannot read back as unset.** `SqliteStateStore.get/set` raise `TypeError` on a non-str key, so this code fails closed.
- `trial_day_latch.py:364`: `connect: object = sqlite3.connect`. Retype it as a `Callable`.
- `fee_drift_probe.py:210`: `_PublicReadClient` is a structural stub that is never instantiated. Make it a `Protocol`.

**Narrowing forms allowed in Wave 1.** These are exceptions to the AST-equality rule, allowed only because the triage proved each site unreachable:
- `assert x is not None` placed directly after the proven guard;
- a private `_require_family_halt_key() -> str` helper that wraps `_require_family_id()` and returns the halt key;
- retyping `connect` as `Callable[..., sqlite3.Connection]`;
- `_PublicReadClient(Protocol)`.

A tagged-union refactor of `PermitAlertDecision` is out of scope (YAGNI).

Separate follow-up, not CF-12: `ingest_deferral_streak.load_state` (`:190-195`) accepts a non-string `first_deferred_utc` from disk without a type check.

## Carve-outs and don'ts

- **`strategy/current_rung_hold/archive_table.py` is FROZEN**: regeneration tests pin its bytes (5046132). It has 0 errors now, so it stays in CLEAN. If mypy ever reports errors there, allow a single-module override pinned by a test. Never edit the file's bytes.
- `adapters/polymarket_us/exec/client.py` already has 0 errors. Nothing to fix there.
- Forbidden:
  - bare or blanket `# type: ignore`;
  - `ignore_errors`;
  - dropping `strict`;
  - new `disable_error_code`;
  - removing `files` entries;
  - using Any or `cast` to silence an error;
  - stubs placed inside `.venv`. Nautilus is IMMUTABLE. A Breezy-side `stubs/` is allowed only if 50 or more same-shaped errors come from one Nautilus symbol.
  - runtime edits under CF-12.
- Worktree briefs must say:
  - `PYTHONPATH=<wt>/src`;
  - run mypy exactly as `/home/jon/breezy/.venv/bin/python -m mypy`, with a per-worktree `--cache-dir`;
  - **never `uv run`, `uv sync`, or `pip`** (the shared venv is production; CI's `uv run` does not apply locally);
  - never `git stash`.
