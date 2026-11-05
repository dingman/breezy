**Review of ARCH-0 seam A build plan r1 (plan only; no code reviewed)**

## Scores

| # | Dimension | Score |
|---|---|---|
| 1 | Correctness vs acceptance criteria | 6 |
| 2 | Repo idiom and convention fit | 8 |
| 3 | Test coverage (happy, failure, edge) | 8 |
| 4 | Risk mitigation | 7 |
| 5 | Scope minimality | 7 |
| 6 | Feasibility (hidden blockers) | 6 |

**Overall: MEDIUM.** The decomposition, layering and fail-closed posture are strong. Three AC claims are falsified by probes, and the WP sizing is not credible.

## Blocking issues

**B1. AC 2 / Modules `net_position`, `entry_guard`: "Nautilus-free" is false for the guard half.**
- Problem: `breezy.domain.__init__` eagerly imports Nautilus-backed record modules.
- Probe: a fresh `import breezy.domain.instrument_leg` loads 120 `nautilus_trader*` modules.
- `net_position` and `entry_guard` both import `domain.instrument_leg`.
- Contract (b) still passes, because `allow_indirect_imports=false` only looks at direct imports. That makes the contract vacuous for these two modules.
- The plan's "resolver loads 0" claim holds only if nothing in the resolver closure imports `breezy.domain`, `net_position` or `entry_guard`. The plan never states or tests that.
- Fix, either of these:
  - Restate the leg suffix parsing (`^no.`) in `net_position` with a test asserting equality with `instrument_leg`, as the plan already does for `FAMILY_ID_RE`.
  - Keep the dependency, but make AC 2 explicit about which modules are Nautilus-free. Add a subprocess test per module in the core list, not only for `resolver`. Drop the claim for `entry_guard`.
- Probe that supports the lazy-init claim itself:
  - With a stub package `__init__`, `family_manifest` and `live_orders_gate` load 0 Nautilus modules.
  - Today they load 126.
  - So the lazy `__init__` does achieve its goal for those two.

**B2. AC 7 / Store: the `BEFORE DELETE` trigger does not cover `INSERT OR REPLACE`.**
- Probe on SQLite 3.50.4, with UPDATE and DELETE triggers present:
  ```
  IntegrityError append-only | update t set v='b'
  IntegrityError append-only | delete from t
  OK(!) insert or replace into t(seq,v) values(1,'z')
  recursive_triggers (0,)
  ```
- A REPLACE conflict deletes the old row silently, because `recursive_triggers` is off by default.
- The plan's mutation test only covers the UPDATE trigger.
- Fix:
  - Set `PRAGMA recursive_triggers=ON` on every writer connection.
  - Add a RED test for `INSERT OR REPLACE`, and for `ON CONFLICT DO UPDATE` (this one does fire the UPDATE trigger).
  - State that `verify_venue_chain` is the real backstop.
  - Forbid `OR REPLACE` and `OR IGNORE` in the store with an AST test.

**B3. AC 4 / `canonical.py`: `decimal_str` does not give zero as `"0"`.**
- Probes:
  - `format(Decimal('-0').normalize(),'f')` gives `'-0'`. So does `-0.0`. AC 4 and AUT-4 K9 require `"0"`.
  - `Decimal('NaN')` and `Decimal('Infinity')` format as `'NaN'` and `'Infinity'`, and the plan never says they are refused.
  - `Decimal('1E+100000').normalize()` formats to a 100,001-character string. That is an unbounded allocation from untrusted input.
- Fix:
  - Special-case zero to `"0"`.
  - Refuse `is_nan()`, `is_infinite()` and any exponent beyond a pinned bound.
  - Add golden fixtures for `-0`, `0E-10`, `1E+2` and `1.50`.
- Related `canonical_json` holes:
  - `json.dumps({1:2,"1":3})` yields duplicate keys `{"1": 2, "1": 3}`. The writer must refuse non-`str` keys with `CanonicalTypeError`.
  - A lone surrogate with `ensure_ascii=False` raises `UnicodeEncodeError` at `.encode()`, not `CanonicalTypeError`. Wrap it.
  - Say whether `float` is allowed. AC 4 says "any other type raises", but `json` accepts it. Decide, and test it.

**B4. WP Sizing / Test Strategy: the carried-test bodies are not budgeted anywhere.**
- The "~150 owner-carried tests" are written "as real test bodies that call the ARCH-named API". No WP's scope or line estimate includes them. WP-A lists only "placeholder ledger…", and WP-D's tests are named, not these.
- Realistic totals:
  - WP-B has about 6 modules plus C2/C3/C4 exact-set records with golden tests in ~800 lines.
  - WP-C has about 25 store tests, 16 fold tests and the DDL, mask, CAS, export and `RegistryReader`, in 1,000 lines.
  - WP-D has about 30 resolver tests, each needing a fixture chain, plus the parse split, in 800 lines.
  - I estimate 1.5–2.5x those figures.
- The plan already admits that WP-C may split. WP-A (~850) and WP-D carry equal risk.
- Fix:
  - Add an explicit WP-E for the ledger bodies (~1,500+ lines, mostly boilerplate), or fold them into the WP that owns each API surface.
  - Re-estimate honestly: probably 6–7 WPs.
  - Name split seams for A, C and D, not only C.

**B5. AC 5 / `single_read`: the `lstat` walk followed by `O_NOFOLLOW` is racy.**
- The plan has both an `lstat` walk for each component and an `openat` implementation, but `read_once_nofollow(path, root=…)` uses `lstat`. An attacker with the same uid can swap a directory for a symlink between the `lstat` and the open.
- Fix: implement `read_once_nofollow` by walking `openat(dirfd, comp, O_DIRECTORY|O_NOFOLLOW)` from `root`. Reuse `open_dir_nofollow` and `read_once_at`, and drop the `lstat` walk. Consider `os.open(..., dir_fd=)`, which Python supports. Then AC 5 is TOCTOU-free, matching the "single read, one fd" intent.

## Non-blocking suggestions

- **`write_once` mode.** `mkstemp` creates 0600, and `os.link` shares the inode.
  - The 0444 modes (artefacts, journal, exports) need `os.fchmod` before the link.
  - Add a test asserting the final `st_mode` through `stat`.
  - `EEXIST_EQUAL` needs a nofollow read-compare of the existing file.
  - Name the fail-closed outcome when the filesystem lacks hard links (`EPERM`, `EXDEV`, `EOPNOTSUPP`).
- **`append` idempotency.** "All ids already present gives a logged no-op" leaves the partial overlap case undefined. Refuse it explicitly (`PartialReplay`) and add a test.
- **sqlite3 transaction mode.** On Python 3.13, `BEGIN IMMEDIATE` needs `isolation_level=None` (or autocommit mode). Otherwise the legacy implicit transactions interfere.
  - Probe: with `isolation_level=None` the triggers and `BEGIN IMMEDIATE` behaved correctly.
  - `synchronous=FULL` is a per-connection pragma. Set it on every writer connection, not only in DDL.
  - Add a test for it.
- **Hot journal (AC 10).** Verified: a `mode=ro` plus `query_only` open on a database with a hot journal copy raised `OperationalError: attempt to write a readonly database`. The journal file was left in place.
  - `OperationalError` is a `DatabaseError`, so the plan's `RegistryUnreadable` mapping is correct.
  - A reader cannot distinguish a dead-writer hot journal from a writer mid-commit (the latter yields `BUSY`). Document that, and say how the engine clears it.
- **Root permission test (R12).** `unshare -r` itself is refused in my sandbox, so I could not probe uid 0 behaviour directly. The plan's approach (assert mode by `stat`, rely on SQLite `mode=ro` semantics) is sound, since SQLite's flag is not uid-dependent.
- **`xfail` semantics, verified on pytest 9.1.1.**
  - Probe:
    ```
    FAILED test_x.py::test_d - assert 0
    FAILED test_x.py::test_b - TypeError: x
    FAILED test_x.py::test_c - [XPASS(strict)] o
    3 failed, 1 xfailed
    ```
  - `raises=OwnerPending` with a non-matching exception (`TypeError` or `AssertionError`) FAILs the test. Only `OwnerPending` xfails, and an unexpected pass is a strict failure.
  - R9 and the ledger design are therefore sound.
  - Caveat: a fixture or setup error is reported as ERROR, never xfail. Keep carried bodies fixture-free until the owner lands.
- **Lazy `persistence/__init__`, probed with a faithful stub.**
  - `from pk import *` returns all `__all__` names and triggers the load.
  - The `globals()` cache keeps identity (`pk.A is pk.cat.A` gives `True`).
  - Pickling is by `catalog`'s own `__module__`, so it is unaffected.
  - `mypy --strict` on the TYPE_CHECKING plus `__getattr__` plus `__dir__` shape passes.
  - Import-linter is static (grimp), so it sees the TYPE_CHECKING import of `catalog` as it saw the old import. Nothing changes for the layers contract.
  - `exclude_type_checking_imports` is not set in `pyproject.toml`.
  - Add one test for `dir()` and `import *`.
  - Add a test that no code does `mock.patch("breezy.persistence.X")`. My grep of `src` and `tests` found none, which supports R7.
- **Layers, `pyproject.toml:78-100`.**
  - Layers `persistence | registry | normalize` are independent siblings (`|`). The plan's prose that persistence "may import … registry|normalize" is wrong, though harmless. It needs `settlement` and `domain` only.
  - `exhaustive = true` is satisfied, because `strategy/autonomy` and `analysis/autonomy` are subpackages.
- **Contract (b) membership.** The module list is hand-maintained.
  - Add an AST test that every module in the package is either in the list or in a named exemption set (`label_schema`, future `capture_*`). Otherwise a newly added module silently escapes the ban.
  - "pyarrow only in `label_schema`" is stated but not enforced. Add that check to the same test.
- **mypy ratchet.** `tests/unit` is ceilinged at 1451 and `tests/support` at 2, with `analysis` at 13.
  - The plan should state that all new test files, `tests/support/autonomy_owner.py` and `offline_plugins.py` are written at 0 errors.
  - Bodies calling Any-returning `require_owner_symbol` are fine, but verify.
  - `MappingProxyType` literals typed `Final[Mapping[str, X]]` and Protocols with attribute members (`id`, `kind`) are feasible under strict. Use `@property` in the Protocols to avoid invariance errors.
- **Resolver and `load_family_manifest`.** The split drops `assert_prereg_directory_eligible`, which stays on `load_family_manifest`. State explicitly that the resolver's paths (`registry/families`, `derived/artefacts`) are outside the prereg guard, and why.
- **LESSONS.** Every L-number cited, from L-1 to L-55, matches its header in `docs/core/LESSONS.md` (the greps match titles).
- **Nautilus-free claim for the lazy init (AC 2).** It depends on `mechanism_test_guard`, which the plan imports from `family_manifest`. My stub run covered this: 0 Nautilus modules.
  - The resolver's own import set (`settlement`, `registry` and so on) also needs the subprocess test across everything it imports.

## Prohibited-command scan

The plan contains no executable `ddev poweroff`, `apt-get`, `sudo apt-get` or `git stash`. `uv` and `pip` appear only as prohibitions: "never `uv` or `pip` (L-51)" and "no `git stash`". My probes used only `/home/jon/breezy/.venv/bin/python`, scratch files under `/tmp/claude-1000/p`, and read-only commands.

## Relevant files

- `/home/jon/breezy/docs/plans/backlog/AUTONOMY_2026-10-03/ARCH-0-seamA_plan_r1.md`
- `/home/jon/breezy/src/breezy/persistence/__init__.py`
- `/home/jon/breezy/src/breezy/persistence/family_manifest.py`
- `/home/jon/breezy/src/breezy/domain/__init__.py`
- `/home/jon/breezy/pyproject.toml`
- `/home/jon/breezy/tests/unit/test_mypy_ratchet.py`