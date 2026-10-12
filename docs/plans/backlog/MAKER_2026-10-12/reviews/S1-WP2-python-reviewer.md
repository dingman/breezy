# S1-WP2 blind review — python-reviewer — 2026-10-12

Scope: commit 4cb417d1 over 6068a00e in /home/jon/breezy/.claude/worktrees/maker-s1-wp2 (3 files, +1049, nothing else).

## Scores
| # | Axis | Score |
|---|------|-------|
| 1 | Plan compliance | 8 |
| 2 | Test completeness | 7 |
| 3 | Pythonic / types / mypy | 9 |
| 4 | Security | 8 |
| 5 | Performance | 9 |
| 6 | Scope | 10 |

## Verified
- Gate: `run_tests_no_egress.sh` on test_trade_quantity_unit.py + test_polymarket_us_fee_guard.py: 41 passed, `phase1 rc=0 phase2 rc=0`, EXIT=0. The wrapper is already 0755 in the worktree (no chmod needed). Basetemp removed.
- `ruff check` clean; `mypy` on the module and script: no issues.
- `TRADE_CAPTURE_START_NS` (trade_quantity_unit.py:66): datetime(2026,9,17,9,tzinfo=UTC) gives 1789635600 s, so the constant is 1789635600000000000. Correct.
- `git diff --stat`: exactly the 3 files. No stray `ruff format` edits.
- Exec-free purity: the module imports only `breezy.domain.instrument_leg` and stdlib. `test_pure_module_stays_exec_free` runs a subprocess and checks `sys.modules`. The test file does not import exec; only `tests.support.aut2_fixtures` does, and it is allowed.
- Read-only: the script never calls sqlite itself. It goes through `fill_source.read_durable_fills`, which uses `file:{path}?mode=ro` with `uri=True` (fill_source.py:66). `mode=ro` cannot create a missing file. The test spies on `sqlite3.connect`, asserts the URI form, and shows that an INSERT raises OperationalError.
- Keep-rule order matches the plan (NOT_A_BUY, PRE_CAPTURE, NULL, GET-, UNRECONCILED_FEE, STATION, then the firewall last). A test confirms the firewall is not consulted for a fill refused earlier. Station and day come only from `bucket_facts_from_instrument_id`.
- SUMMED routing is implemented (match_fill:271-281) and tested. S-2 and S-3 are covered by test_script_flags_s3.
- Plan's 13 named tests: all 13 are present (one is the script test `test_crosscheck_opens_exec_db_read_only`). Extras: parse strictness, side/price/time never size, the pin mismatch, and the committed 28-id declaration.

## Findings
HIGH-1 (test gap) — the exit-5 failure mode is untested. scripts/analysis/trade_quantity_unit_crosscheck.py:176-181 returns `EXIT_NO_FIREWALL` on ImportError, and WP1's `maker_tape_census` is not in this tree. No test exercises it; the e2e tests all inject `clearance`.
  Fix: add a test that calls `main([...])` with `clearance=None`, with `importlib.import_module` monkeypatched to raise ModuleNotFoundError. Assert rc == 5 and that the stderr message names the module.
  Also check that a non-ImportError failure in WP1, such as an AttributeError on `FirewallRefused`, cannot escape the handler uncaught (lines 122-123 sit inside `firewall_clearance`, which is called in the try, so only ImportError is caught). Either catch `(ImportError, AttributeError)` or add a test that expects the traceback.

HIGH-2 (test gap) — the declaration sha256 / hash-mismatch path has no test. Line 178 hashes the declaration bytes and forwards the hash to WP1. No test asserts that the forwarded value equals sha256 of the file, and nothing exercises a hash-mismatch refusal (`ClearanceRefused` mapped from `FirewallRefused`) through `firewall_clearance()`.
  Fix: build a fake census module (types.ModuleType with `FirewallRefused` and `require_firewall_clearance` that records its args), patch `importlib.import_module`, and assert (a) the recorded hash equals `hashlib.sha256(decl.read_bytes()).hexdigest()` and (b) a raised `FirewallRefused` becomes `FIREWALL_REFUSED` in the `refused` list.

MEDIUM-1 — crosscheck.py:166-221, `main()` is about 55 lines (over the 50-line guideline). Extract `_build_result(...)`.

MEDIUM-2 — trade_quantity_unit.py:279 is an unplanned heuristic: `len(cands)==1 and fill.qty > 1` routes to SUMMED when no hypothesis is consistent. This is conservative (it never counts), but the plan does not say it and no test names it. Add a test or a plan note. Left alone, a single print that contradicts every hypothesis on a qty>1 fill is hidden from the "contradicts every hypothesis" UNRESOLVED reason.

LOW-1 — `Fill.unit_cost` (:125) divides by qty. A qty==0 record raises ZeroDivisionError uncaught in `main`. Add a guard: refuse as `ZERO_QTY` in `keep_decision`, or reject in `load_fills`.

LOW-2 — fill_source.py:66 (pre-existing, reused) interpolates `--db` into the URI without quoting. A path containing `?` or `#` is misparsed; `mode=ro` is appended last, so it likely wins, but it is not guaranteed. Not introduced by this diff. Optionally pass `urllib.parse.quote(path)` in a follow-up.

LOW-3 — tests `_load_script` writes to `sys.modules` and never restores it. Use `monkeypatch.setitem(sys.modules, ...)`.

LOW-4 — crosscheck.py:31 `Any` for the JSON rows; `dict[str, object]` would do. The public dataclasses and functions in trade_quantity_unit.py lack docstrings (`Print`, `match_fill`, `predicted_size`).

## Performance
Each fill is scanned against all prints a few times (match_fill, `_fill_row`). That is O(fills x prints x ~5) with 28 fills, so it is bounded. No concern.

## Verdict: REQUEST_CHANGES
Code is correct, typed, lint-clean and the gate is green. The two HIGH items are test gaps on the failure paths the plan names (firewall-module absence and hash forwarding). Close them and this is APPROVE.
