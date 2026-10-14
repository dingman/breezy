# S2 WP1 python review (commit 78906397)

Verdict: REQUEST_CHANGES (2 HIGH, all fixable locally; no CRITICAL)

Gates: mypy 0 errors on 12 changed files; ruff clean; tests: 99 passed (0.87s) + 41 passed,
`[breezy] gate: phase1 rc=0 phase2 rc=0`. Function lengths all < 50 (longest ~36); modules < 400.

## HIGH
1. maker_stage0_inputs.py:237 -- a truncated CSV row is silently DROPPED. csv.DictReader fills
   missing cells with None; `raw["tmax_flag"] != ""` is then True (None != ""), so the row is
   skipped as "non-FINAL". Verified: header + `SFO,2026-09-18` loads with no error. A
   short row in the truth file shrinks the set with no signal. Fix: refuse any row where
   `None in raw.values()` or `None in raw` (extra cells land under key None) with InputRefused
   (row number), before filtering.
2. maker_stage0_inputs.py:240-241,285-290 -- load_truth is not typed at the trust boundary.
   Verified raw escapes: `tmax_f=abc` / `70.0` -> bare ValueError; bad climate_day -> bare
   ValueError; non-UTF8 CSV -> UnicodeDecodeError; missing CSV/parquet -> OSError; parquet
   lacking a column -> pyarrow ArrowInvalid; parquet climate_day of str type would make
   (station, day) keys never match, so the cross-check passes VACUOUSLY (n_overlap 0).
   Fix: wrap int()/fromisoformat/decode/read_table in `except (...) as exc: raise InputRefused(...)
   from exc` with row number; assert parquet `climate_day` is a date (else refuse); consider
   refusing n_overlap == 0 (or at least surfacing it) since the cross-check is the only guard.

## MEDIUM
3. maker_stage0_pins.py:112-118 -- subprocess.run has no `timeout=` (args list, no shell,
   `-C` repo_root pinned: good). Add `timeout=30` and catch subprocess.TimeoutExpired /
   FileNotFoundError (git absent) -> DirtyTree. Both escape untyped today.
4. maker_stage0_ledger.py:149-161 vs 79-105 -- check-then-append is not atomic: two concurrent
   launches both pass ledger_refuses, then both append. flock only serialises the write. Fix:
   append_ledger_entry re-reads entries for the amendment sha under the same lock and raises
   LedgerRefused if the policy now fails (or document single-launcher as WP6's contract).
   Also no os.fsync after flush (the ledger is the one-shot burn record).
5. maker_stage0_inputs.py:158-162 -- UnitHypothesis.name is a free str; any unknown name
   falls through to the TAKER branch. Validate in __post_init__ (name in UNIT_HYPOTHESES) or
   match explicitly with a final raise.
6. maker_stage0_pins.py:376-380, schedule.py:152-154, pins.py:278-283 -- pins.json /
   schedule / catalog manifest written with write_text (non-atomic; a crash leaves a truncated
   file that later hashes as valid). Write to `.tmp` then os.replace. Also these accept any
   path: the "only under run_dir" rule is by caller convention, not enforced.
7. maker_stage0_ledger.py:182-191 -- void_run_dir: rename-then-digest order is right
   (nothing opened pre-rename; episodes.jsonl is stat-only), but a missing run_dir raises bare
   FileNotFoundError, and `p.is_file()` follows symlinks so a symlink named otherwise could
   point at episodes.jsonl and be hashed. Use `p.is_file() and not p.is_symlink()` (refuse
   symlinks) and wrap the rename in LedgerRefused. If tree_digest fails post-rename the dir
   is renamed but unpinned; acceptable, but log the path in the error.
8. maker_stage0_frozen.py:164-168, ledger.py:69-73 -- read_bytes()/decode("utf-8") raise
   OSError/UnicodeDecodeError untyped (frozen sha check runs first so decode failure needs a
   sha-matching bad file: low likelihood; load_addendum same). Wrap -> FrozenSetRefused/LedgerRefused.

## LOW
9. pins.py:258-260 duplicates the sha256_file chunk loop and `_CHUNK` (needed for the
   stat-before/after guard; could hash via sha256_file between the two stats). Raises bare ValueError.
10. pins.py:138-141 package_set_sha256 lower-cases but does not PEP 503-normalise (`-_.`);
    sorted, `name==version`, deterministic on one interpreter. Normalise for cross-host stability.
11. pins.py:383-389 seal_sidecars: `pins["sidecars"]` KeyError and missing sidecar file are untyped.
12. `dict[str, Any]` return types (schedule_to_dict, pin_inputs) -- acceptable for JSON; a
    TypedDict/`JsonValue` alias would remove Any.
13. Ledger tests live in test_maker_stage0_frozen.py (no test_maker_stage0_ledger.py); nodelog is
    tested via test_maker_stage0_schedule.py. Fine, but name the ledger tests' file in the plan.

## Checked and OK
- Node-log regexes: anchored ^...$ with ESCAPED dots, tested on the real discovery_pull fixture
  (1 boot, 1 permit; CRLF-terminated copy also parses -- verified) and near-misses rejected.
- Registry rows in test_runtime_import_isolation.py: 2 one-line additions, same pattern as the
  S1 `maker_tape_census` row. Minimal.
- Fixture generator derives the field set from dataclasses.fields(CensusedDay), raises
  AssertionError on drift, writes only via write_censused_days; a test pins the drift failure.
- Frozen parser: refuses placeholder, duplicate/unknown field, CRLF/absent/duplicate block,
  10-01, > 10-13, NYC, DRAFT, sha mismatch; boundary dates 10-01/10-13 tested (frozen tests :109,:155,:176).
- load_trade_unit/TradeUnit.from_result validate the verdict/surviving consistency; tested.
- pins.py split (389 lines): natural seam is `load_model` + `_parse_doc` + `_assert_fit_window`
  (~100 lines, lines 154-243) -> maker_stage0_model.py. Not required, but any growth in WP6
  will cross 400; do it now if touching pins for item 3/6.
- Test quality: AAA-ish, parametrised refusals for every frozen/ledger/unit/evidence-doc path.
  Gaps (add with the HIGH fixes): truncated CSV row, non-numeric tmax_f, non-date climate_day,
  non-UTF8 CSV, unreadable parquet, git timeout/absent, concurrent ledger append.
