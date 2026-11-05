# NOTIFIER-IMPORT-ISOLATION plan r2: delta over r1 (BINDING; r2 wins where the two conflict)

## Round-1 peer reviews (run blind)
- **architect:** REQUEST_CHANGES, with 3 blocking items. It confirmed the diagnosis, confirmed that none of the 33 `from breezy.runtime import` hits uses a facade name, and confirmed the correction to the L-52 citation.
- **python-reviewer:** MEDIUM. Scores: C8, I7, T5, R8, S9, F7. One blocking item.

There are no contradictions between the two. The coordinator's merge follows.

## D-1. Pick option (d): delete the facade (architect blocking 3)
There are zero callers, and nothing in the tests pins the facade (architect). Replace `src/breezy/runtime/__init__.py:18-104` with the docstring alone, plus a paragraph stating that the package init must stay import-free. The stated reason is the last-line alert delivery described at `study_failure_notifier.py:55-56`.

Consequences of deleting instead of making the facade lazy:
- `__getattr__`, `_LAZY`, T5 and T6 are dropped. This is simpler (KISS/YAGNI).
- mypy can no longer be tricked into accepting a `breezy.runtime.<typo>`, which the architect flagged.
- The python-reviewer's idiom items about the `__getattr__` signature and `Final` no longer apply.
- Rejected alternative: keeping a curated lazy surface. It has no consumer.

## D-2. Stage 0 covers every entry point, measured statically (architect blocking 1)
**Entry set:**
- every `[project.scripts]` entry, including `breezy-trade`, `pyproject.toml:323`;
- the module of every `ExecStart` under `deploy/systemd/`;
- every `scripts/**/*.py` that imports `breezy.runtime`, including imports inside functions.

**Method:**
1. Build the import graph with `grimp`, which is already installed as import-linter's engine.
2. For each entry, list the modules that define a `register_arrow(` call and are reachable from it. Do this twice:
   - (i) on the graph as it is;
   - (ii) on the graph with the package-init edges from `breezy.runtime` removed.
3. grimp counts imports made inside functions, so it closes the gap the architect found, where a runtime `sys.modules` snapshot misses those imports.
4. Any registration module in set (i) but not set (ii) gets an explicit import in that entry module, plus a fresh-subprocess test that imports the entry and asserts the registration module is loaded.
5. There is no escalation threshold (architect blocking 2). Every affected entry is fixed. Any structural surprise goes back to the peer-review loop, never to the operator.
6. Also prove that a missing registration fails loudly on catalog read and write, never silently. If the evidence shows it would fail silently, the per-entry explicit imports above are mandatory, however few entries are affected.

## D-3. The T2/T3 import blocker uses `find_spec` (python blocking)
The repo targets Python 3.13 (`pyproject.toml:9,222`), where the legacy `find_module` path no longer exists.

In the child process:
1. Before any other import, install at `sys.meta_path[0]` a finder whose `find_spec(self, fullname, path, target=None)` raises `ImportError` for `nautilus_trader` and for any name starting with `nautilus_trader.`.
2. Record every blocked attempt in a list.
3. **Positive control, in the same child:**
   - `import nautilus_trader` raises;
   - after the notifier call, `print` the list of blocked attempts;
   - the parent asserts the list shows the positive-control attempt.

## D-4. Smaller changes adopted from the non-blocking suggestions
- **`test_study_failure_alert.py:249-259`:** rewrite the docstring to point at T1 as the proof that Nautilus is absent. Remove the "unfixed" caveat. The assertions stay unchanged.
- **Stale comments:** in the same slice, update the justification comments at `node_config.py:103-109` and `nws_actor.py:307-326`. Change comments only. The function-local imports stay, because removing them is a separate YAGNI item.

## Final test set
All in `tests/unit/test_runtime_import_isolation.py`:
- **T1:** importing the notifier leaves Nautilus unloaded.
- **T2:** the notifier sends when Nautilus is blocked, using the D-3 finder.
- **T3:** the webhook sink resolves when Nautilus is blocked.
- **T4:** a bare `import breezy.runtime` leaves Nautilus unloaded.
- **T7:** an AST pin that `breezy/runtime/__init__.py` contains no `Import` or `ImportFrom` nodes.
- **T8-n:** one registration test per entry that Stage 0 flags.

## Mutants
- **M-a:** re-add any import to the init. Killed by T1, T4 and T7.
- **M-b:** the notifier or `health` imports a module that pulls in Nautilus. Killed by T1 and T2.
- **M-c:** the finder never intercepts the import. Killed by the D-3 positive control.
- **M-d:** remove an explicit import added in Stage 0. Killed by the matching T8-n.

**Confidence:** HIGH, provided Stage 0 runs as D-2 specifies.

## r3 amendments (round-2 architect review: REQUEST_CHANGES, 2 blocking items, fixes adopted verbatim; these are BINDING)
Verified in round 2:
- D-1 is safe. There are no facade consumers and no `breezy.runtime:` entry points. The `pyproject.toml:104` ignore stays, and so does its pin at `test_test_safety_tooling_config.py:87-92`.
- D-3 is sound.
- A missing Arrow registration fails LOUDLY: `TypeError` at `serializer.py:240-247,313-323` and `KeyError` at `:81-82`.
- Every Breezy `register_arrow` call sits at module scope in the class's own defining module. Any caller holding the class has therefore already registered it, so the residual risk is structurally near zero.

- **R3-1 (fixes the D-2 false negative).** grimp adds no edge from a submodule to its parent package, so comparing set (i) with set (ii) would always come out equal. The fix:
  1. Before computing reachability, add synthetic `module → ancestor package` edges with `graph.add_import`.
  2. Stage 0 positive control: at HEAD, `breezy.runtime.study_failure_notifier` must be able to reach `nautilus_trader.live.node`. If it cannot, Stage 0 is invalid.
  3. Union the reachable set with a runtime `sys.modules` snapshot per entry, taken in a fresh child process. This catches string and dynamic imports.
- **R3-2 (new test T9: fresh-process import smoke per entry).**
  - Parametrize over every `[project.scripts]` module (`pyproject.toml:311-381`), every module named in a `deploy/systemd` `ExecStart`, and every `scripts/**` module that imports `breezy.runtime`.
  - For each, run `subprocess.run([sys.executable, "-c", "import <mod>"], timeout=60)` and require returncode 0.
  - Mutant M-e: add a module-scope `from breezy.runtime.health import …` to `nws_actor`. T9 must fail on it.
- **T3 detail.** In the child, set `ALERT_WEBHOOK_URL_ENV_VAR` to `https://example.invalid/x`. Assert that `emit` is never called.
- **D-4 scope.** The comment edits keep every function-local import and leave the `:104` ignore untouched.

**Confidence after round 2: HIGH.** Every blocking item came with a precise fix from the reviewer, and the implementation review must confirm R3-1 and R3-2.
