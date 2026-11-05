# GATE-RACE r2 — both shipped-tree writers move under tmp_path, plus a tree-wide AST guard

## Trade-off and decision (read at HEAD 8995a147)
- Writer A: `test_the_environ_mutation_scan_is_not_vacuous` (tests/unit/test_polymarket_us_permit_issuance.py:1700-1721) writes `REPO_ROOT/src/breezy/__environ_probe__.py` (L1703), scans, unlinks (L1719).
- Writer B1: `test_scan_sees_a_planted_reference` (tests/unit/test_polymarket_us_cancel_transport.py:280-288) writes `REPO_ROOT/scripts/venue/_b1_planted_reference.py` (L283), unlinks (L287); takes `tmp_path`, never uses it.
- Reader: `test_fetch_is_single_cache_writer` (tests/unit/test_iem_cli_fetch.py:263-295) rglobs `scripts` and `src` then read_text → FileNotFoundError on unlink between glob and read. Any real-tree rglob reader has the same exposure; r1's "~130 readers" withdrawn (unmeasured).
- False claim: scripts/ci/gate_reviewed.json L139 (cancel_transport) and L143 (permit_issuance) in a parallel-safe group claiming nothing written to a shared location; neither in `serial_tail`. Becomes true after this fix.
- Option (a) extended to B1: each scanner gets keyword-only `repo_root`; each probe/plant writes under `tmp_path`. `find_environ_mutations` has 2 callers (permit L1695, L1717). `_scan` (cancel_transport L249-258) has 4 callers, all in-file (L268, 276, 285, 292); only L285 changes. Serial-tail fallback not needed. Option (b) stays rejected (L-81; SIGKILL leaves a stray file).
- AC5 = tree-wide AST guard: deterministic pure parse of tests/**/*.py; no I/O race; no test-calls-test; closes the class. `tests.support.real_tree_write_guard` (runtime) considered and rejected: only sees writes by tests running under it.
- Full-tree sweep (regex Grep; codegraph indexes symbols not call sites): 433 test files, 3145 write-method calls; filtered to expressions rooted at REPO_ROOT/_REPO_ROOT/ROOT/_ROOT/.parents[k] joined with "src"/"scripts" → ~47 sites; all read-only except A and B1. Benign: test_execution_egress_firewall_guard.py:605 (path built then `del`), test_us_source_ingest_egress_guard.py:503 (read via import_closure), test_autonomy_pins.py:600 (read), test_autonomy_pins.py:608 and autonomy/test_f7b_core_contracts.py:190 (copies under tmp_path; f7b is the precedent). No shutil/os.replace targets the tree. Residual blind spot: writes via computed `REPO_ROOT / rel` strings or cross-module helpers → R7.

## Acceptance Criteria
AC1 No test writes/unlinks under REPO_ROOT/src or REPO_ROOT/scripts. A writes only `tmp_path/src/breezy/__environ_probe__.py`; B1 only `tmp_path/scripts/venue/_b1_planted_reference.py`.
AC2 `find_environ_mutations(repo_root=tmp_path)` == exactly, in order (6 of the scan's rules; pop/popitem/clear/unsetenv not exercised):
```
["src/breezy/__environ_probe__.py:2: imports load_dotenv",
 "src/breezy/__environ_probe__.py:6: assigns os.environ[...]",
 "src/breezy/__environ_probe__.py:7: os.environ.setdefault()",
 "src/breezy/__environ_probe__.py:8: os.environ.update()",
 "src/breezy/__environ_probe__.py:9: os.putenv()",
 "src/breezy/__environ_probe__.py:10: load_dotenv()"]
```
Order: `ast.walk` is breadth-first (ImportFrom depth 1, Assign depth 2, four Calls depth 3 in source order). No `"__environ_probe__"` filter needed. Exact strings prove `rel` from `repo_root`.
AC2b `_scan(_CANCEL_ALL_TOKENS, frozenset({_OWNER, _LEGACY_PROBE}), repo_root=tmp_path)` == `[("scripts/venue/_b1_planted_reference.py", "_signed_post_cancel_all")]` (other two tokens not substrings of the planted text).
AC3 Real-tree scans keep defaults: `test_no_shipped_code_can_set_the_operator_trading_gate` still `find_environ_mutations()` → `[]`; cancel_transport L268/276/292 default `_scan`; `_scan` real-tree non-vacuity already pinned by L277 `{path for path,_ in unexempted} == {_B2_CONTROL}`.
AC4 Behavioural non-vacuity: `test_the_real_tree_environ_scan_reads_the_gate_module(monkeypatch)` — delegating spy on `Path.read_text` records unresolved `self`; `find_environ_mutations()` must record `REPO_ROOT / "src/breezy/adapters/polymarket_us/safety.py"`. No inspect.signature.
AC5 New file tests/unit/test_no_test_writes_into_the_shipped_tree.py: on today's code `find_shipped_tree_writes()` == exactly `{"tests/unit/test_polymarket_us_permit_issuance.py::test_the_environ_mutation_scan_is_not_vacuous", "tests/unit/test_polymarket_us_cancel_transport.py::test_scan_sees_a_planted_reference"}` (RED artifact); after fix `set()`. Post-condition test: neither `REPO_ROOT/src/breezy/__environ_probe__.py` nor `REPO_ROOT/scripts/venue/_b1_planted_reference.py` exists (L-27, fails closed on stray).
AC6 `scripts/ci/run_tests_parallel.sh` exits 0 (GATE_EXIT read); gate_reviewed.json unchanged (no flake/allowlist/serial_tail move, L-12); serial gate green.
AC7 ruff check, ruff format --check (touched files), mypy, `lint-imports` (not `python -m importlinter`) clean; `scripts/ci/run_tests_no_egress.sh tests/contract` passes.

## Edge Cases & NFRs
Both scanners skip absent/non-dir roots (`find_environ_mutations` explicit is_dir; `_scan` relies on rglob of missing dir yielding nothing on 3.12; implementer creates `tmp_path/scripts/venue` and `tmp_path/src`). `rel` from `repo_root` else relative_to raises. KEEP THE NEW GUARD FILE OUT OF gate_reviewed.json: it must contain none of the `_TIMING_RE`/`_PATH_RE` tokens from scripts/ci/gate_classify.py:158-163 (`/tmp/`, `deadline`, `timeout_s`, `Path.home()` …) or gate_classify demands a review-group entry (breaks AC6). Guard needs no self-exclusion (its planted snippets are string constants). REPO_ROOT stays module constant; new params keyword-only, typed Path, default REPO_ROOT. No production/pin/EXEMPT change.

## Architecture & Data Flow
Before: A and B1 write into real src/ and scripts/ while other shards rglob the same tree. After: each writes into its own tmp_path and calls its scanner with repo_root=tmp_path; real tree only read; AST guard statically forbids recurrence under tests/.

## File-by-File Plan
| Path | Status | Exact changes |
|---|---|---|
| tests/unit/test_polymarket_us_permit_issuance.py | modified | (1) L1635 `def find_environ_mutations(roots: tuple[str, ...] = ("src", "scripts"), *, repo_root: Path = REPO_ROOT) -> list[str]:`; L1647 `base = repo_root / root`; L1653 `rel = path.relative_to(repo_root).as_posix()`; one docstring line. (2) L1702-1721: `probe = tmp_path / "src" / "breezy" / "__environ_probe__.py"`, `probe.parent.mkdir(parents=True)`, same write_text body, `assert find_environ_mutations(repo_root=tmp_path) == [<AC2 list>]`; drop try/finally. (3) AC4 test (`monkeypatch.setattr(Path, "read_text", spy)`; precedent test_exec_par_o3_promo_record.py:118). |
| tests/unit/test_polymarket_us_cancel_transport.py | modified | (1) L249 `def _scan(tokens: tuple[str, ...], allowed: frozenset[str], *, repo_root: Path = REPO_ROOT) -> list[tuple[str, str]]:`; L252 `(repo_root / root).rglob`; L253 `relative_to(repo_root)`. (2) L282-288: `planted = tmp_path / "scripts" / "venue" / "_b1_planted_reference.py"`, `planted.parent.mkdir(parents=True)`, write_text, AC2b equality; drop try/finally. |
| tests/unit/test_no_test_writes_into_the_shipped_tree.py | new | AST guard (spec below). |
| scripts/ci/gate_reviewed.json | unchanged | claim becomes true |
| tests/unit/test_iem_cli_fetch.py | unchanged | victim not cause; don't make glob tolerant |
| docs/core/PROGRESS.md | at close | close GATE-RACE row; no GATE-RACE-2 (folded in) |

AST guard spec: inputs `sorted((repo_root / "tests").rglob("*.py"))` skipping `__pycache__`; `find_shipped_tree_writes(*, repo_root: Path = REPO_ROOT) -> set[str]` with pure helper `writes_in_source(source: str, rel: str) -> set[str]`. Root base: Name id in {"REPO_ROOT","_REPO_ROOT","ROOT","_ROOT"} or Subscript whose .value is Attribute(attr="parents"). Shipped expression E: BinOp(Div) chain whose innermost left is a root base and innermost right is a str Constant == "src"/"scripts" or startswith "src/"/"scripts/". Tainted T: E; Name in taint set; Attribute(attr="parent", value=T); Call(Attribute(attr="resolve", value=T)); BinOp(Div, left=T). Taint set: module-level names assigned a T value (Assign single Name target / AnnAssign); per FunctionDef/AsyncFunctionDef: (module taint minus names the function assigns a non-T value) plus names it assigns a T value; order-insensitive within scope; no cross-module. Sinks: Call(func=Attribute(attr in {write_text, write_bytes, unlink, mkdir, touch}, value=T)); Call(func=Name("open")) first arg T; Call(func=Attribute("open", value=T)); for both open forms the mode (positional or mode=) must be a str Constant containing w/a/x/+. Hit key `f"{rel}::{innermost enclosing def}"` or `::<module>`. Tests: (1) `test_no_test_writes_into_the_shipped_tree`: == set(); (2) `test_the_shipped_tree_write_guard_has_teeth`: `writes_in_source` on an in-memory snippet — positives each in its own def: write_text, write_bytes, unlink, mkdir via .parent, touch, open(p,"w"), p.open("a"), derived `q = p / "x"` then q.write_text, `.parents[2] / "scripts"` base; negatives: tmp_path/"src" with a write, read_text, open(p) default mode, name rebound to tmp_path in its own function; assert exact positive key set; (3) `test_no_probe_or_plant_is_left_in_the_shipped_tree` (AC5 post-condition).

## Test Strategy
1. R6 pre-check: `git status --porcelain --untracked-files=all -- src/breezy/__environ_probe__.py scripts/venue/_b1_planted_reference.py` prints nothing; free disk ≥10 GB; basetemp under worktree (L-66).
2. RED: add the guard file only; `scripts/ci/run_tests_no_egress.sh tests/unit/test_no_test_writes_into_the_shipped_tree.py` fails with exactly the 2-key set (RED artifact). Teeth test passes from the start; post-condition passes unless a stray exists. Third key → real write: STOP, report scope change; false positive: narrow matcher, record why.
3. Edits → guard returns set() (GREEN).
4. Focused GREEN: `scripts/ci/run_tests_no_egress.sh tests/unit/test_no_test_writes_into_the_shipped_tree.py tests/unit/test_polymarket_us_permit_issuance.py tests/unit/test_polymarket_us_cancel_transport.py tests/unit/test_iem_cli_fetch.py tests/unit/test_truth_units.py`.
5. `scripts/ci/run_tests_no_egress.sh tests/contract`; `lint-imports`; ruff check; ruff format --check (3 touched files); mypy.
6. `scripts/ci/run_tests_parallel.sh; GATE_EXIT=$?`; read before push; then serial gate.
7. Empirical race loop: DROPPED.

## Execution Order
R6 pre-check → guard (RED) → two scanner edits → focused GREEN → contract guards + lint-imports + ruff + mypy → full gate (GATE_EXIT) → python-reviewer → commit `test: GATE-RACE scanner probes write under tmp_path; tree-wide shipped-tree write guard [#GATE-RACE]` by explicit paths → push only if GATE_EXIT==0 → PROGRESS.md + lesson (dedupe vs L-27). One seam, one implementer (3 test files coupled through the RED set). Worktree: L-51 python + PYTHONPATH.

## Risk Register
R1 (Med) tmp-rooted probe proves less → AC3 defaults + L277 behavioural + AC4 spy. R2 (Low) unknown writer keeps gate red → read individually, never allowlist. R3 (Low) read_text monkeypatch interference → function-scoped delegating read-only. R4 (Low) guard false positives break exact RED → function-scoped matching; triage rule step 2. R5 load flake already in load_flakes. R6 (Low) stray file → fail-closed + pre-check. R7 (Low, accepted) computed-string / cross-module writes invisible → recorded, YAGNI.

## LESSONS Compliance
L-27 tmp_path + post-condition; L-81 root-caused; L-12 no flake/allowlist, gate_reviewed.json untouched; L-66 basetemp under repo; L-51 shared venv + PYTHONPATH. No test weakened; both non-vacuity assertions stronger (exact lists). Pins/EXEMPT/Nautilus untouched.

## Confidence
Root cause 0.9; fix 0.9 (two in-file scanners, callers 2 and 4); AC2 exact list 0.85 (BFS order by hand, confirmed by RED/GREEN); exact 2-key RED 0.8; gate fully green 0.8.

## Changes from r1
B1 folded in (`_scan` repo_root; L285 only; AC1 both files; cancel_transport in focused set). Sweep done (findings above; R7). AC5 → tree-wide AST guard with exact patterns, exact 2-key RED, teeth test, L-27 post-condition; spy + test-calls-test removed. AC2 exact ordered 6-string list; AC2b for B1. Empirical loop dropped. AC4 → behavioural read_text spy requiring safety.py. lint-imports / contract guards / GATE_EXIT added. R6 pre-check + post-condition. "~130 readers" withdrawn; GATE-RACE-2 removed; confidence recalibrated.
