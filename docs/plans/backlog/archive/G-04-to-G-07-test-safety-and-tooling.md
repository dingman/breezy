# G-04 to G-07 Test Safety and Tooling Plan

Status: execution plan before implementation, 2026-08-26.

Scope: one seam only: pytest safety, dependency pinning, marker registration,
and import-linter configuration. Nautilus Trader remains immutable; this work
only changes Breezy tests/tooling around native extension points.

## Shared constraints

- Package manager and gates: `uv run pytest -q`, `uv run ruff check .`,
  `uv run mypy`.
- In this sandbox, `uv` must run with a workspace-local cache because
  `/home/jon/.cache/uv` is read-only. That changes only command environment,
  not repo state.
- Do not weaken the existing three-lock venue-live gate:
  `BREEZY_VENUE_LIVE=1`,
  `BREEZY_ALLOW_CREDENTIALED_PYTEST=1`, and `--venue-live`.
- Preserve the existing `allow_socket` loopback tests; they are intentionally
  local-only integration tests and are not live venue access.

## G-04: pyo3 network escape from Python socket monkeypatch

Problem:

- `docs/plans/archive/TRADING_ENABLEMENT_REVIEW.md` STK-1 says a
  `nautilus_pyo3` client can reach the OS and return ECONNREFUSED while the
  Python `socket` monkeypatch is green.
- The current autouse fixture patches `socket.socket.connect` and
  `connect_ex`, then replaces `nautilus_pyo3.HttpClient` and
  `WebSocketClient` during the test call.
- That is too late for import-time aliases such as
  `from nautilus_trader.core.nautilus_pyo3 import HttpClient`: test modules
  are imported before autouse fixtures run, so the alias can still point at
  the original Rust-backed client.

Approach:

- Add a focused regression test with a module-level alias to
  `nautilus_pyo3.HttpClient`, captured before fixture setup.
- The test will allocate and close a local loopback port, prove Python
  `socket.connect(("127.0.0.1", port))` is blocked by the fixture, then try
  the captured pyo3 `HttpClient` against `http://127.0.0.1:<closed-port>/`.
- The RED condition is the captured pyo3 call reaching the OS and producing
  connection-refused text for a loopback address.
- Harden `tests/conftest.py` by installing the pyo3 network-client sentinels
  during `pytest_configure`, before test module import/collection can capture
  the original constructors.
- Preserve `allow_socket`, `live`, `venue_live`, and `real_money` semantics by
  restoring the original pyo3 constructors only inside those opted-out tests,
  and re-installing the sentinels afterward.

Files touched:

- `tests/conftest.py`
- new focused test under `tests/unit/`
- this plan file

RED test:

- Run the new test before the fixture hardening.
- Expected failure: assertion identifies that pyo3 reached
  `127.0.0.1:<closed-port>` and got connection refused / `os error 111` while
  the Python socket call was blocked.

GREEN criterion:

- The same test passes because the pre-collection captured alias is the
  `_BlockedPyo3NetworkClient` sentinel and never reaches the OS.
- The existing `allow_socket` loopback tests still pass in the full pytest
  gate.

Residual limit:

- This is the strongest in-process defense that preserves per-test loopback
  opt-outs. It is not a kernel firewall and not a proof that arbitrary future
  native extensions cannot call `connect(2)`.
- A complete OS/process-level egress block would need pytest to be launched
  inside an external network sandbox, such as a dedicated network namespace or
  CI runner firewall policy. That mode is outside a removable per-test pytest
  fixture, because syscall/network-namespace restrictions cannot be safely
  toggled off for `allow_socket` tests once installed.
- The code comment must state this exact limit so the suite does not overclaim
  "OS-level" protection.

Risks:

- Patching too early could break local loopback tests that intentionally use
  native pyo3 WebSocket clients. Mitigation: keep original constructors and
  restore them for explicitly marked real-network tests.
- Module-level `from ... import WebSocketClient` in future tests could capture
  the sentinel. That is acceptable for ordinary tests; loopback tests needing
  the real class should import at runtime under `allow_socket`.

## G-05: exact Nautilus Trader pin

Problem:

- `pyproject.toml` declares `nautilus-trader~=1.231`, but the contract suite
  pins measured behavior of Nautilus Trader 1.231.0.

Approach:

- Change dependency to `nautilus-trader==1.231.0`.
- Run a lock/env resolution check with `uv lock --check` or equivalent local
  resolution evidence.
- Run `uv run pytest -q tests/contract`.

Files touched:

- `pyproject.toml`
- `uv.lock` only if `uv lock` says it must change

RED test:

- The pre-change contract is configuration-level: the dependency spec allows a
  future 1.231.x even though tests only measure 1.231.0.

GREEN criterion:

- `pyproject.toml` requires exactly `nautilus-trader==1.231.0`.
- Lock/env resolution succeeds.
- `tests/contract/` passes.

Risks:

- The existing dirty `pyproject.toml` has unrelated user edits; patch only the
  dependency line and requested tool sections.

## G-06: register and wire `venue_live`

Problem:

- STK-6 requires a registered `venue_live` marker under `--strict-markers`.
- The three-lock gate already exists in `tests/conftest.py`; duplicating it
  would be a safety regression.

Approach:

- Keep the existing `--venue-live` flag and
  `missing_venue_live_unlocks(...)` gate in `tests/conftest.py`.
- Update the `pyproject.toml` marker docstring to the exact requested meaning:
  "test performs real authenticated calls against the live Polymarket.us venue;
  gated behind BREEZY_VENUE_LIVE=1 AND
  BREEZY_ALLOW_CREDENTIALED_PYTEST=1 AND --venue-live".
- Add or adjust a focused test that parses pytest markers/config or exercises
  strict marker behavior without running a real venue call.

Files touched:

- `pyproject.toml`
- possibly existing unit tests around credential gating

RED test:

- A config/strict-marker test should fail if `venue_live` is absent or its
  meaning drifts away from the three-lock gate.

GREEN criterion:

- `--strict-markers` accepts `venue_live`.
- `venue_live` tests remain deselected/skipped unless all three locks are
  present.
- No code path weakens credential scrubbing for ordinary tests.

Risks:

- Accidentally broadening "venue_live" to "any prediction venue" would hide the
  Polymarket.us credential specificity. Keep the marker text venue-specific.

## G-07: enforce import-linter contracts

Problem:

- `import-linter` is declared as a dependency but has no config, so it is
  cosmetic.
- ARC-4 requires a dependency-direction rule for Breezy packages, and STK-9
  requires a hard ban on importing a Polymarket .com adapter.

Observed import graph before configuration:

- Top-level source packages under `src/breezy/` are `adapters`, `domain`,
  `features`, `ingest`, `normalize`, `persistence`, `registry`, `runtime`, and
  `settlement`.
- Existing source imports support the directional stack:
  `runtime` -> `adapters` -> `ingest` -> `persistence` / `registry` /
  `normalize` -> `domain`.
- There are existing cycles/debt that must be explicitly named rather than
  hidden: `adapters.polymarket_us.config` and `factories` import
  `runtime.settings`, `ingest.nws_actor` imports `runtime.health`, and
  `persistence.quote_tape_gaps` imports
  `adapters.polymarket_us.tape_records`.

Approach:

- Add `[tool.importlinter]` to `pyproject.toml` with root package `breezy`
  and external-package graphing enabled.
- Add a `layers` contract for `breezy` that lists every current top-level
  source package. Use `exhaustive = true` so new top-level packages cannot skip
  architectural classification.
- Add narrow `ignore_imports` entries for the current, inspected debt edges so
  the contract passes without pretending the cycle does not exist.
- Add a `forbidden` contract over the external `nautilus_trader` top-level
  package, with each currently inspected legitimate direct Nautilus import
  allowlisted. In import-linter/grimp 2.13, external imports are squashed to
  `nautilus_trader`, so this contract cannot distinguish
  `nautilus_trader.model` from `nautilus_trader.adapters.polymarket` inside a
  source module that already has an allowlisted Nautilus import.
- Add a companion AST guard in the test suite scanning `src/` and `scripts/`
  for direct imports of `breezy.adapters.polymarket` or
  `nautilus_trader.adapters.polymarket`. This supplies the precise .com
  adapter ban that import-linter's external graph cannot express alone.
- Verify with `uv run lint-imports`.
- Note CI addition: add `uv run lint-imports` to the required gate list
  alongside pytest, Ruff, and mypy.

Files touched:

- `pyproject.toml`
- possibly a focused unit test for config presence/forbidden module names

RED test:

- Run `uv run lint-imports` after adding a deliberately too-strict contract or
  before adding required ignores, to capture the existing layering violations.
- Then adjust to the real graph.

GREEN criterion:

- `uv run lint-imports` exits 0.
- The import-linter contract includes an exhaustive Breezy layer list and
  rejects unallowlisted Nautilus imports.
- The companion AST test rejects direct Polymarket .com adapter imports
  repo-wide under `src/` and `scripts/`.

Risks:

- Import-linter checks static imports only and squashes external imports by
  top-level package. Dynamic `importlib.import_module` strings are not fully
  covered by this contract; existing AST/literal safety tests remain
  responsible for policy scans outside import-linter's graph.
- A too-idealized layer model would fail immediately on existing code. The
  contract must encode the intended direction while explicitly preserving named
  current exceptions.
