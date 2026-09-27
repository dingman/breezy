# NOTIFIER-IMPORT-ISOLATION: plan r1 (2026-09-27, planner)

**Problem.** `breezy-study-failed` is the last line of alert delivery. Importing it runs `breezy/runtime/__init__.py`, which eagerly imports `composition`, and that loads `nautilus_trader.live.node`. So a broken Nautilus import also stops the alert from being sent.

**Correction to the brief.** `docs/core/LESSONS.md:1608` L-52 is about corroborating reads. The phrase "a detector without delivery is not a control" comes from `study_failure_notifier.py:55-56`, so cite that instead.

## Options + pick
- **The notifier's own imports are Nautilus-free.**
  - It imports `health` (`study_failure_notifier.py:78-84`) and the leaf `quote_tape_exit_codes` (`:85-90`).
  - `health.py:49-60` pulls in stdlib and httpx only.
  - Nautilus enters only through the package init:
    - `runtime/__init__.py:19` → `composition` → `composition.py:36` (`nautilus_trader.live.node`);
    - init line 49 → `logging_bridge.py:66`;
    - init line 52 → `node_config.py:63-84`.
- **(a) PICK: lazy `__init__` via PEP 562 `__getattr__`.**
  - The init re-exports 41 names (`__init__.py:62-104`).
  - Nothing imports those names through the package. A search of src, tests and scripts found no `from breezy.runtime import <name>` and no `breezy.runtime.<name>` attribute access. Every `from breezy.runtime import X` imports a submodule.
  - It changes one file.
- **(b) REJECT: move the notifier to a new `breezy.alerting` package.**
  - `health` has 111 references across 63 files.
  - A shim would break `monkeypatch.setattr(health_module, …)`.
  - The layers contract is `exhaustive = true` (`pyproject.toml:98`).
  - The ignore entry at `pyproject.toml:104` would have to be rewritten.
- **(c) REJECT on its own: change the console-script entry point.** Any target under `breezy.runtime.*` still runs the package `__init__`.

## File-by-file plan
1. **Stage 0: measure first (read-only).**
   - For each `breezy.runtime.*:main` console script, record which `register_arrow` modules get loaded at import, at HEAD and again with the lazy init. The modules to watch are `tape_records.py:629-637`, the `domain/*` modules, and `monitor_records.py:249`.
   - Any module that disappears under the lazy init: add an explicit import to that entry module, plus a test.
   - If more than 2 entry points are affected, escalate.
2. **`src/breezy/runtime/__init__.py`.**
   - Move the eager imports (lines 18-60) under `if TYPE_CHECKING:`.
   - Add `_LAZY: Final[Mapping[str, tuple[str, str]]]`, mapping name → (module, attr). Include the aliases `install_logging_bridge` → `logging_bridge.install` and `uninstall_logging_bridge` → `logging_bridge.uninstall`.
   - `__getattr__`: `import_module` + `getattr`, cache the result in `globals()`. It raises `AttributeError` for any unknown name; that is required so `from breezy.runtime import <submodule>` still works.
   - `__dir__` returns `__all__` ∪ `globals()`.
   - `__all__` stays unchanged.
3. **`tests/unit/test_study_failure_alert.py:249-259`.** Update only the docstring; the assertions stay unchanged.

## Tests
All tests go in the new file `tests/unit/test_runtime_import_isolation.py`.
- The subprocess tests use `subprocess.run([sys.executable, "-c", …], timeout=30)`.
- The child processes inherit the no-egress namespace (`run_tests_no_egress.sh:36-51`).

| Test | Asserts | RED at HEAD because |
|---|---|---|
| T1 `test_notifier_import_never_loads_nautilus` | Importing the notifier in a fresh subprocess leaves no `nautilus_trader*` key in `sys.modules` | The init eagerly imports Nautilus |
| T2 `test_notifier_sends_when_nautilus_import_fails` | With a meta_path finder that blocks `nautilus_trader*`, `notify_study_failed(..., sink_factory=<recording>)` returns 0 and emits `study_unit_failed WARN` | `ImportError`, so nothing is sent |
| T3 `test_webhook_transport_resolves_without_nautilus` | With the same finder, `resolve_alert_sink(...)` returns a `WebhookAlertSink` and never calls `emit` | The package import fails |
| T4 `test_bare_package_import_is_nautilus_free` | `import breezy.runtime` alone leaves Nautilus unloaded | The init is eager |
| T5 `test_lazy_facade_parity` | Every name in `__all__` resolves to the same object as its source attribute, and `set(_LAZY) == set(__all__)` | `_LAZY` is undefined |
| T6 `test_unknown_attr_raises_and_submodule_fromimport_works` | An unknown name raises `AttributeError`; `from breezy.runtime import cli` still works | Nothing: this is a regression guard, and the test says so |

One more test is needed for each entry point that Stage 0 finds affected.

## Mutants that must be killed
- An eager import comes back in `__init__` (T1, T4).
- A `_LAZY` entry is dropped or mis-mapped (T5).
- `__getattr__` returns `None`, or raises `ImportError` instead of `AttributeError` (T6).
- The notifier or `health` gains an import that pulls in Nautilus (T1, T2).
- Positive control: `import nautilus_trader` must raise inside the blocked child.

## Risk register
| Risk | Blast radius | Mitigation |
|---|---|---|
| Arrow-type registration currently happens as a side effect of the eager chain | Roughly 20 console scripts that read custom catalog data | Stage 0 diff; explicit imports; a test per affected script; full gate |
| An import-order change exposes a latent import cycle | runtime, ingest, adapters | The change removes known cycles (`node_config.py:106-109`, `nws_actor.py:310-315`); full gate |
| The facade's name surface changes | 0 callers | T5 |
| Deployed processes keep running the old code | Node, supervisor | The fix takes effect at the next respawn; this item makes no systemctl changes |

## import-linter impact
- Contracts are unchanged.
- The `TYPE_CHECKING` imports are still counted, because `exclude_type_checking_imports` is unset (`pyproject.toml:59-70`), so the dependency graph is unchanged.
- Run `lint-imports` after the slice.

**Confidence.** High on the diagnosis and the pick. Medium-high overall until Stage 0 confirms that no entry point relies on the eager chain for Arrow registration.
