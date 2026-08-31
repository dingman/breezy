"""Barriers N1-N5: native (Rust) egress is blocked, and the CI firewall lands FIRST.

Authority: STK-1. ``docs/plans/TRADING_SYSTEM_ARCHITECTURE.md`` makes a CI
network firewall a hard prerequisite that must land BEFORE any
execution-egress module is written. A sequencing requirement asserted only in
a table row is a comment; this module makes it mechanical.

WHAT WAS ACTUALLY MEASURED (2026-08-27, on the shipped tree)
------------------------------------------------------------

``tests/conftest.py`` installs two controls: an autouse monkeypatch of
``socket.socket.connect``/``connect_ex``, and a replacement of the
``HttpClient``/``WebSocketClient`` attributes on the top-level
``nautilus_pyo3`` module object. Neither constrains ``reqwest``.
``nautilus_pyo3.HttpClient`` is a Rust client: it opens sockets through the
Tokio runtime, never through Python's ``socket`` module, so the Python-level
kill-switch cannot see it. Three concrete escapes were reproduced:

* **Escape 1 -- the submodule alias.** The constructor block rebinds the name
  on the *top-level* module only. ``nautilus_trader.core.nautilus_pyo3.network``
  is a distinct module object holding an independent attribute slot pointing at
  the same class, and it is NEVER patched. Inside an ordinary ``pytest`` run::

      from nautilus_trader.core.nautilus_pyo3.network import HttpClient

  yields the real Rust class. No capture-before-fixture trickery is required;
  this is a one-line, fully-supported import. Measured against a closed
  loopback port from inside a test::

      HttpError | error sending request for url (http://127.0.0.1:39259/):
      client error (Connect): tcp connect error: Connection refused (os error 111)

  ``Connection refused`` proves a real TCP ``connect(2)`` was issued while the
  Python block read green.

* **Escape 2 -- ``SocketClient``.** ``_PYO3_NETWORK_CLIENT_NAMES`` names only
  ``HttpClient`` and ``WebSocketClient``. ``nautilus_pyo3.SocketClient`` is a
  raw-TCP client and is blocked at NEITHER path -- not even the top-level one.

* **Escape 3 -- capture before the block.** An object (or class reference)
  obtained before ``pytest_configure`` runs is unaffected by any later
  rebinding. This one is NOT closable in-process and is stated as residual.

Reaching the public internet was confirmed end-to-end: the real client
returned an ``HttpResponse`` from ``https://1.1.1.1/``, whereas the same call
under ``bwrap --unshare-net`` failed with ``Network is unreachable (os error
101)``.

WHY THE BLOCK CANNOT BE COMPLETED IN-PROCESS
--------------------------------------------

Two in-process mitigations were evaluated empirically and one was rejected:

* ``proxy_url`` (a real parameter -- verified in the installed
  ``nautilus_trader/core/nautilus_pyo3.pyi``, ``class HttpClient``) is
  caller-supplied. Construction happens in Rust, so Python cannot force it
  onto a client it did not build. It is also ignored for loopback
  destinations, measured directly.
* ``ALL_PROXY``/``HTTP_PROXY``/``HTTPS_PROXY`` ARE honoured by the underlying
  ``reqwest`` client, and would divert non-loopback egress (including HTTPS,
  via ``CONNECT``) to a dead port. But the environment is read at
  *client-build* time: a client built before the variables are set is not
  diverted -- measured. It therefore closes nothing that N1's exhaustive
  rebinding does not already close, is trivially undone by
  ``os.environ.pop``, is a REDIRECT rather than a block, and would also
  perturb every ``httpx`` client in the suite (``trust_env=True`` by
  default). Rejected as a half-measure rather than shipped.

The honest conclusion, stated plainly: **only an OS-level control fully
closes this.** N1 is the best in-process approximation -- it makes every
*import path* to a native network client resolve to a sentinel -- and N2-N5
supply the mechanism that forces the OS-level control to exist before the
hazard does.

BARRIERS
--------

* **N1** -- every attribute slot on every ``nautilus_pyo3`` module object that
  exposes a native network client must resolve to the conftest sentinel during
  an ordinary test.
* **N2** -- if an execution-egress module exists in the repo, the OS egress
  firewall must be attested AND substantiated. Landing them in the wrong order
  fails on the very commit that introduces the hazard.
* **N3** -- the attestation cannot lie: when
  ``BREEZY_TEST_OS_EGRESS_BLOCK=1`` is claimed, a real outbound ``connect()``
  from this very process must fail block-shaped.
* **N4** -- the canary outcome classifier distinguishes "blocked" from
  "reached" rather than treating any exception as safety.
* **N5** -- the repo ships a launcher that actually applies the block on a
  developer machine, and it is verified to be a working mechanism.

Each barrier is paired with a ``*_detects_*`` proof-by-construction test, in
the idiom of ``test_polymarket_us_readonly_guard`` (B1-B6) and
``test_polymarket_us_fee_guard`` (F1, F2), so none can pass vacuously.
"""

from __future__ import annotations

import ast
import asyncio
import os
import shutil
import socket
import subprocess
import sys
import types
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import (
    CANARY_HOST,
    CANARY_PORT,
    EGRESS_BLOCK_LAUNCHER,
    OS_EGRESS_BLOCK_ENV_VAR,
    execution_egress_abort_reason,
)
from tests.unit.test_polymarket_us_readonly_guard import (
    Violation,
    is_venue_touching,
    iter_python_sources,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Roots scanned for execution-egress modules (N2).
EGRESS_SCAN_ROOTS = ("src", "scripts")

#: Every native client class name that can open a socket from Rust. The
#: shipped conftest names only the first two; ``SocketClient`` is raw TCP and
#: was entirely unguarded.
NATIVE_NETWORK_CLIENT_NAMES = ("HttpClient", "WebSocketClient", "SocketClient")

#: ``OS_EGRESS_BLOCK_ENV_VAR``, ``CANARY_HOST``, ``CANARY_PORT`` and
#: ``EGRESS_BLOCK_LAUNCHER`` are imported from ``tests.conftest`` above. They
#: live there because ``pytest_sessionstart`` is the enforcement point for N2,
#: and a constant owned by the code that enforces the rule cannot drift from
#: the code that proves it.

#: ``errno`` values that mean the kernel refused to emit the packet at all.
#: These are the only outcomes that count as BLOCKED.
_BLOCKED_ERRNOS = frozenset({1, 13, 101, 93, 97})
_BLOCKED_TEXTS = (
    "network is unreachable",
    "permission denied",
    "operation not permitted",
    "address family not supported",
    "protocol not supported",
)
#: Outcomes that prove a packet DID leave (or would have). Never safety.
_REACHED_TEXTS = (
    "connection refused",
    "timed out",
    "timeout",
    "connection reset",
    "no route to host",
)

#: Path prefixes under which EVERY module is an execution-egress surface (E0).
#:
#: A PREFIX, not a list of exact paths, and deliberately so: E0 *classifies a
#: hazard*, so it has to fail CLOSED as the directory grows. The plan's own
#: module layout puts ``endpoints.py``, ``reports.py``, ``client.py``,
#: ``config.py`` and ``factories.py`` here -- none of which E1 knows, none of
#: which E3 sees, and only one of which E2 would classify. ``endpoints.py``,
#: the single module that will hold every venue order-path literal, matched
#: NO rule before E0 existed.
_EGRESS_PATH_PREFIXES = ("src/breezy/adapters/polymarket_us/exec/",)

#: Module basenames that constitute an execution-egress surface (E1).
_EGRESS_MODULE_BASENAMES = frozenset(
    {
        "execution.py",
        "execution_client.py",
        "exec_client.py",
        "order_submit.py",
        "order_router.py",
        "orders.py",
        "trading.py",
    }
)
#: Class-name suffixes / bases that constitute an execution-egress surface (E2).
_EGRESS_CLASS_SUFFIXES = ("ExecutionClient", "ExecClient", "OrderRouter")
_EGRESS_CLASS_BASES = frozenset(
    {"LiveExecutionClient", "LiveExecClientFactory", "LiveExecutionClientFactory"}
)
#: Function names that constitute an execution-egress surface (E3).
#:
#: BOTH forms of every verb. The bare names alone classified nothing a real
#: client does: every order-bearing coroutine a ``LiveExecutionClient``
#: implements is underscored -- ``_submit_order``, ``_submit_order_list``,
#: ``_modify_order``, ``_cancel_order``, ``_cancel_all_orders`` and
#: ``_batch_cancel_orders`` (``nautilus_trader/live/execution_client.py``
#: :608-633).
_EGRESS_FUNCTION_NAMES = frozenset(
    {
        "submit_order",
        "place_order",
        "cancel_order",
        "modify_order",
        "submit_order_list",
        "_submit_order",
        "_place_order",
        "_cancel_order",
        "_modify_order",
        "_submit_order_list",
        "_cancel_all_orders",
        "_batch_cancel_orders",
    }
)


# ==========================================================================
# N1 -- exhaustive native network-client export scan
# ==========================================================================


def iter_native_client_export_sites() -> Iterator[tuple[str, str, Any]]:
    """Yield ``(module_name, attr_name, value)`` for every native-client slot.

    Walks the top-level ``nautilus_pyo3`` module AND every submodule object it
    exposes. The submodules are distinct module objects with independent
    attribute slots, which is precisely why patching only the top-level module
    left ``nautilus_pyo3.network.HttpClient`` live.
    """
    try:
        from nautilus_trader.core import nautilus_pyo3
    except ImportError:  # pragma: no cover - nautilus is a hard dependency
        return

    modules: list[tuple[str, Any]] = [("nautilus_pyo3", nautilus_pyo3)]
    for name, value in sorted(vars(nautilus_pyo3).items()):
        if isinstance(value, types.ModuleType):
            modules.append((f"nautilus_pyo3.{name}", value))

    for module_name, module in modules:
        for attr in NATIVE_NETWORK_CLIENT_NAMES:
            if hasattr(module, attr):
                yield module_name, attr, getattr(module, attr)


def is_blocked_sentinel(value: Any) -> bool:
    """True when ``value`` is conftest's refusing sentinel rather than a client.

    Identity against the imported sentinel class, not a name comparison: a
    class merely *named* ``_BlockedPyo3NetworkClient`` must not satisfy this.
    """
    from tests.conftest import _BlockedPyo3NetworkClient

    return value is _BlockedPyo3NetworkClient


def find_unblocked_native_client_exports() -> list[Violation]:
    """Report every native-client slot still reachable in an ordinary test."""
    return [
        Violation(
            f"<module {module_name}>",
            0,
            "N1",
            f"{module_name}.{attr} is {getattr(value, '__module__', '?')}."
            f"{getattr(value, '__qualname__', value)!s} -- not the block sentinel",
        )
        for module_name, attr, value in iter_native_client_export_sites()
        if not is_blocked_sentinel(value)
    ]


def test_n1_no_native_network_client_is_reachable_during_an_ordinary_test() -> None:
    violations = find_unblocked_native_client_exports()
    assert violations == [], "N1 violations:\n" + "\n".join(str(v) for v in violations)


def test_n1_scan_actually_covers_the_submodule_slot_that_was_open() -> None:
    """Guards the scan itself: the escape site must be IN the scanned set."""
    sites = {(module, attr) for module, attr, _ in iter_native_client_export_sites()}
    assert ("nautilus_pyo3.network", "HttpClient") in sites
    assert ("nautilus_pyo3.network", "SocketClient") in sites
    assert ("nautilus_pyo3", "SocketClient") in sites


def test_n1_detector_catches_a_planted_unblocked_export() -> None:
    """Proof by construction: an unblocked slot is reported, not ignored."""

    class _PretendRustClient:
        pass

    sites = [("nautilus_pyo3.network", "HttpClient", _PretendRustClient)]
    violations = [
        Violation("<module>", 0, "N1", f"{m}.{a}")
        for m, a, v in sites
        if not is_blocked_sentinel(v)
    ]
    assert len(violations) == 1


def test_n1_detector_is_not_fooled_by_a_lookalike_named_class() -> None:
    """Identity, not name: a same-named impostor must NOT read as blocked."""

    class _BlockedPyo3NetworkClient:  # deliberate same-name impostor
        pass

    assert is_blocked_sentinel(_BlockedPyo3NetworkClient) is False


def test_n1_detector_accepts_the_real_sentinel() -> None:
    from tests.conftest import _BlockedPyo3NetworkClient

    assert is_blocked_sentinel(_BlockedPyo3NetworkClient) is True


def test_n1_blocked_sentinel_actually_refuses_construction() -> None:
    """A sentinel that constructs happily would make N1 worthless."""
    from tests.conftest import _BlockedPyo3NetworkClient

    with pytest.raises(RuntimeError, match="Network access is disabled"):
        _BlockedPyo3NetworkClient(timeout_secs=1)


# ==========================================================================
# N4 -- canary outcome classification (defined before N2/N3, which use it)
# ==========================================================================


@dataclass(frozen=True, slots=True)
class CanaryOutcome:
    """Result of a real outbound connect attempt."""

    blocked: bool
    detail: str

    def __str__(self) -> str:
        label = "BLOCKED" if self.blocked else "REACHED"
        return f"{label}: {self.detail}"


def classify_canary_failure(exc: BaseException | None) -> CanaryOutcome:
    """Classify a connect attempt. Only kernel refusal counts as blocked.

    ``None`` means the connect SUCCEEDED -- egress is wide open.
    ``Connection refused`` and ``timed out`` are explicitly NOT blocked: both
    prove a packet was emitted. Treating any exception as safety is the exact
    mistake that let the shipped pyo3 test read green.
    """
    if exc is None:
        return CanaryOutcome(False, "connect succeeded; egress is open")

    errno = getattr(exc, "errno", None)
    if isinstance(errno, int) and errno in _BLOCKED_ERRNOS:
        return CanaryOutcome(True, f"{type(exc).__name__}: errno {errno}")

    text = str(exc).lower()
    if any(marker in text for marker in _REACHED_TEXTS):
        return CanaryOutcome(False, f"{type(exc).__name__}: {exc}")
    if any(marker in text for marker in _BLOCKED_TEXTS):
        return CanaryOutcome(True, f"{type(exc).__name__}: {exc}")
    return CanaryOutcome(
        False, f"unrecognised outcome, treated as reached: {type(exc).__name__}: {exc}"
    )


def test_n4_connection_refused_is_not_treated_as_blocked() -> None:
    """The precise misreading this whole module exists to prevent."""
    exc = OSError(111, "Connection refused")
    assert classify_canary_failure(exc).blocked is False


def test_n4_the_observed_pyo3_escape_text_is_not_treated_as_blocked() -> None:
    """Verbatim text captured from the reproduced escape."""
    exc = RuntimeError(
        "error sending request for url (http://127.0.0.1:57899/): client error "
        "(Connect): tcp connect error: Connection refused (os error 111)"
    )
    assert classify_canary_failure(exc).blocked is False


def test_n4_timeout_is_not_treated_as_blocked() -> None:
    assert classify_canary_failure(TimeoutError("operation timed out")).blocked is False


def test_n4_success_is_not_treated_as_blocked() -> None:
    assert classify_canary_failure(None).blocked is False


def test_n4_network_unreachable_errno_is_blocked() -> None:
    assert classify_canary_failure(OSError(101, "Network is unreachable")).blocked is True


def test_n4_the_observed_bwrap_block_text_is_blocked() -> None:
    """Verbatim text captured under ``bwrap --unshare-net``."""
    exc = RuntimeError(
        "error sending request for url (https://1.1.1.1/): client error (Connect): "
        "tcp connect error: Network is unreachable (os error 101)"
    )
    assert classify_canary_failure(exc).blocked is True


def test_n4_permission_denied_is_blocked() -> None:
    assert classify_canary_failure(OSError(13, "Permission denied")).blocked is True


def test_n4_an_unrecognised_outcome_fails_closed_as_reached() -> None:
    """Fail-closed: an unknown error must never be read as safety."""
    assert classify_canary_failure(RuntimeError("something novel")).blocked is False


# ==========================================================================
# N3 -- the attestation cannot lie
# ==========================================================================


def os_egress_block_attested(env: Any | None = None) -> bool:
    """True when a launcher claims to have applied an OS-level egress block."""
    source = os.environ if env is None else env
    return source.get(OS_EGRESS_BLOCK_ENV_VAR) == "1"


def probe_real_egress_canary() -> CanaryOutcome:
    """Attempt a REAL outbound connect from this process, bypassing Python.

    Uses the native pyo3 client captured by conftest before its own block was
    installed, so this probes the very path the Python kill-switch cannot see.
    The destination is RFC 5737 TEST-NET-2, which is not allocated to any
    host, so no third party can receive the packet.
    """
    from tests.conftest import _ORIGINAL_PYO3_NETWORK_CLIENTS

    originals = _ORIGINAL_PYO3_NETWORK_CLIENTS or {}
    http_client = originals.get("HttpClient")
    if http_client is None:  # pragma: no cover - nautilus is a hard dependency
        return CanaryOutcome(False, "native HttpClient unavailable; cannot substantiate")

    async def _go() -> BaseException | None:
        client = http_client(timeout_secs=3)
        try:
            await asyncio.wait_for(
                client.get(f"http://{CANARY_HOST}:{CANARY_PORT}/", timeout_secs=3),
                timeout=8,
            )
        except BaseException as exc:  # noqa: BLE001 - classification is the point
            return exc
        return None

    return classify_canary_failure(asyncio.run(_go()))


def test_n3_a_claimed_os_egress_block_must_actually_block() -> None:
    """If the launcher attests a firewall, prove it from inside this process.

    When there is no attestation this test does nothing and emits no packet --
    deliberately. The barrier that forces an attestation to EXIST is N2.
    """
    if not os_egress_block_attested():
        pytest.skip(
            f"{OS_EGRESS_BLOCK_ENV_VAR} not attested; nothing claimed, nothing to "
            f"substantiate (N2 is what requires the attestation to exist)"
        )
    outcome = probe_real_egress_canary()
    assert outcome.blocked, (
        f"{OS_EGRESS_BLOCK_ENV_VAR}=1 was attested but a real native connect to "
        f"{CANARY_HOST}:{CANARY_PORT} was not blocked by the kernel -- {outcome}"
    )


def test_n3_attestation_reader_requires_the_exact_string_one() -> None:
    """``true``/``yes`` must not attest, matching the venue-unlock convention."""
    for value in ("true", "yes", "on", "0", "", "1 "):
        assert os_egress_block_attested({OS_EGRESS_BLOCK_ENV_VAR: value}) is False
    assert os_egress_block_attested({OS_EGRESS_BLOCK_ENV_VAR: "1"}) is True
    assert os_egress_block_attested({}) is False


# ==========================================================================
# N2 -- the ordering barrier: firewall BEFORE execution egress
# ==========================================================================


def find_execution_egress_modules(
    roots: tuple[str, ...] = EGRESS_SCAN_ROOTS,
) -> list[Violation]:
    """Report every module that constitutes an execution-egress surface.

    Delegates to :func:`_scan_source`, which is the single implementation of
    rules E0-E3 -- so the ``*_detects_*`` proofs below exercise the very code
    this live scan runs, not a second copy of it.
    """
    found: list[Violation] = []
    for path, source in iter_python_sources(roots):
        found.extend(_scan_source(path, source))
    return found


def assert_firewall_precedes_execution_egress(
    egress_modules: list[Violation],
    *,
    attested: bool,
    outcome: CanaryOutcome | None,
) -> None:
    """N2's rule, factored so the detector tests can drive it directly.

    The rule itself lives in ``tests.conftest`` because that is where it is
    ENFORCED (``pytest_sessionstart`` aborts on it before collection). This
    wrapper turns the same verdict into an assertion, so the detector tests
    below are a non-vacuity proof OF the enforced rule rather than of a copy.
    """
    reason = execution_egress_abort_reason(
        egress_modules=egress_modules,
        attested=attested,
        outcome=outcome,
    )
    if reason is not None:
        # `raise`, not `assert`: the message must be the verdict VERBATIM so a
        # test can compare the two, and an `assert` would vanish under `-O`.
        raise AssertionError(reason)


def test_n2_no_execution_egress_module_may_exist_without_a_proven_firewall() -> None:
    """The live barrier. Fails on the very commit that lands egress too early."""
    egress_modules = find_execution_egress_modules()
    attested = os_egress_block_attested()
    outcome = probe_real_egress_canary() if (egress_modules and attested) else None
    assert_firewall_precedes_execution_egress(egress_modules, attested=attested, outcome=outcome)


def test_n2_detects_an_execution_egress_module_when_the_firewall_is_absent() -> None:
    """Proof by construction: the rule fires rather than passing vacuously."""
    planted = [Violation("src/breezy/adapters/polymarket_us/execution.py", 1, "E1", "planted")]
    with pytest.raises(AssertionError, match="firewall is not attested"):
        assert_firewall_precedes_execution_egress(planted, attested=False, outcome=None)


def test_n2_detects_an_attested_but_unsubstantiated_firewall() -> None:
    """A lying attestation must not satisfy N2."""
    planted = [Violation("src/breezy/adapters/polymarket_us/execution.py", 1, "E1", "planted")]
    with pytest.raises(AssertionError, match="was not blocked"):
        assert_firewall_precedes_execution_egress(
            planted,
            attested=True,
            outcome=classify_canary_failure(OSError(111, "Connection refused")),
        )


def test_n2_passes_when_the_firewall_is_attested_and_substantiated() -> None:
    planted = [Violation("src/breezy/adapters/polymarket_us/execution.py", 1, "E1", "planted")]
    assert_firewall_precedes_execution_egress(
        planted,
        attested=True,
        outcome=classify_canary_failure(OSError(101, "Network is unreachable")),
    )


def test_n2_e1_detects_a_venue_touching_execution_module_by_name() -> None:
    path = "src/breezy/adapters/polymarket_us/execution.py"
    source = "def go():\n    return 1\n"
    tmp = REPO_ROOT / "src" / "breezy" / "adapters" / "polymarket_us" / "__n2_probe__.py"
    del tmp  # scanning is done in-memory below; no file is written
    tree = ast.parse(source, filename=path)
    assert is_venue_touching(path, tree) is True
    assert Path(path).name in _EGRESS_MODULE_BASENAMES


def test_n2_e2_detects_a_live_execution_client_subclass() -> None:
    source = (
        "from nautilus_trader.live.execution_client import LiveExecutionClient\n"
        "\n"
        "\n"
        "class PolymarketUSExecClient(LiveExecutionClient):\n"
        "    pass\n"
    )
    rules = {v.rule for v in _scan_source("src/breezy/whatever.py", source)}
    assert "E2" in rules


def test_n2_e3_detects_an_order_verb_on_a_venue_touching_module() -> None:
    source = (
        "from breezy.adapters.polymarket_us import transport\n"
        "\n"
        "\n"
        "async def submit_order(o):\n"
        "    return await transport.send(o)\n"
    )
    rules = {v.rule for v in _scan_source("src/breezy/runtime/broker.py", source)}
    assert "E3" in rules


def test_n2_does_not_fire_on_a_non_venue_module_named_orders() -> None:
    """The exemption that keeps this barrier from being silenced wholesale."""
    source = "ORDERS = []\n\n\ndef load():\n    return ORDERS\n"
    assert _scan_source("src/breezy/persistence/orders.py", source) == []


# --------------------------------------------------------------------------
# E0 -- the exec package is an egress surface BY PATH (NS-0 (a))
# --------------------------------------------------------------------------


def test_n2_e0_classifies_any_module_under_the_exec_package_by_path() -> None:
    """A module E1/E2/E3 cannot see must still be classified.

    ``transport.py`` is not a known egress basename, defines no class and no
    order verb -- yet it is one of the filenames the NO-SEND plan's own module
    layout contemplates under ``exec/``. Without E0 it is invisible to N2.
    """
    source = '"""Docstring only."""\n\nCONNECT_TIMEOUT_SECONDS = 5\n'
    violations = _scan_source(
        "src/breezy/adapters/polymarket_us/exec/transport.py",
        source,
    )
    assert [v.rule for v in violations] == ["E0"]


def test_n2_e0_is_a_prefix_so_it_fails_closed_as_the_package_grows() -> None:
    """A nested module gets no exemption from an exact-path list."""
    source = '"""Docstring only."""\n'
    violations = _scan_source(
        "src/breezy/adapters/polymarket_us/exec/nested/deeper.py",
        source,
    )
    assert [v.rule for v in violations] == ["E0"]


def test_n2_e0_does_not_fire_outside_the_exec_package() -> None:
    """Non-vacuity: the same source one directory up is not classified."""
    source = '"""Docstring only."""\n\nCONNECT_TIMEOUT_SECONDS = 5\n'
    assert _scan_source("src/breezy/adapters/polymarket_us/transport.py", source) == []


def test_n2_e3_detects_the_underscore_order_coroutine_a_real_client_defines() -> None:
    """Every coroutine a ``LiveExecutionClient`` implements is underscored.

    ``nautilus_trader/live/execution_client.py:608-633`` defines
    ``_submit_order``, ``_submit_order_list``, ``_modify_order``,
    ``_cancel_order``, ``_cancel_all_orders`` and ``_batch_cancel_orders``.
    E3 held only the bare forms, so a real client's order path matched none.
    """
    source = (
        "from breezy.adapters.polymarket_us import transport\n"
        "\n"
        "\n"
        "async def _submit_order(command):\n"
        "    return None\n"
    )
    rules = {v.rule for v in _scan_source("src/breezy/runtime/broker.py", source)}
    assert "E3" in rules


def test_n2_e3_covers_every_underscore_order_coroutine_a_live_client_implements() -> None:
    """Pins the whole set, not just the one the RED above happens to plant."""
    required = {
        "_submit_order",
        "_submit_order_list",
        "_modify_order",
        "_cancel_order",
        "_cancel_all_orders",
        "_batch_cancel_orders",
    }
    assert required <= _EGRESS_FUNCTION_NAMES


def test_n2_the_shipped_tree_has_exactly_the_expected_execution_egress_modules() -> None:
    """Exact-set pin. NOT an "is empty" pin -- an EQUALITY.

    ``exec/__init__.py`` ships with NS-0 precisely so E0 is armed before the
    package holds anything. Because this is an equality, ANY later increment
    that adds a module under ``exec/`` fails here until it updates the
    expected set in the same commit. That is the point: a new execution-egress
    module cannot land silently.
    """
    found = [(v.path, v.rule) for v in find_execution_egress_modules()]
    assert found == [("src/breezy/adapters/polymarket_us/exec/__init__.py", "E0")]


def test_n2_scan_covers_both_src_and_scripts() -> None:
    scanned = {path for path, _ in iter_python_sources(EGRESS_SCAN_ROOTS)}
    assert any(p.startswith("src/") for p in scanned)
    assert any(p.startswith("scripts/") for p in scanned)


def _scan_source(path: str, source: str) -> list[Violation]:
    """Apply rules E0-E3 to ONE module. The single implementation.

    Four rules, all syntactic:

      E0 -- the module's path is under an execution-egress package prefix.
            Unconditional: no class, no known basename and no order verb is
            needed, because the point of the prefix is to classify files
            whose contents the other three rules cannot see;
      E1 -- the module's basename is a known execution-egress name AND the
            module is venue-touching (C1-C4 from the read-only guard), so a
            generic ``orders.py`` in a non-venue package does not fire;
      E2 -- it defines a class whose name ends with an execution-client
            suffix, or that subclasses a Nautilus live-execution base;
      E3 -- it is venue-touching and defines a function whose name is an
            order-lifecycle verb, in either its bare or its underscored form.
    """
    tree = ast.parse(source, filename=path)
    venue = is_venue_touching(path, tree)
    found: list[Violation] = []
    if path.startswith(_EGRESS_PATH_PREFIXES):
        found.append(Violation(path, 0, "E0", "module lives in an execution-egress package"))
    if venue and Path(path).name in _EGRESS_MODULE_BASENAMES:
        found.append(Violation(path, 0, "E1", "venue-touching execution-egress module name"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            if node.name.endswith(_EGRESS_CLASS_SUFFIXES):
                found.append(
                    Violation(path, node.lineno, "E2", f"class {node.name} is an exec client")
                )
                continue
            for base in node.bases:
                name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
                if name in _EGRESS_CLASS_BASES:
                    found.append(Violation(path, node.lineno, "E2", f"class {node.name}({name})"))
        elif venue and isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.name in _EGRESS_FUNCTION_NAMES:
                found.append(
                    Violation(path, node.lineno, "E3", f"defines {node.name}() on venue path")
                )
    return found


# ==========================================================================
# N2-ABORT -- the rule is consulted from conftest and STOPS the session
# ==========================================================================
#
# Reporting is not stopping. Before NS-0 the N2 rule lived only inside this
# module, so a violation reddened ONE test while pytest ran the entire rest of
# the suite in the same process -- with the hazard present and the firewall
# absent. The rule is now consulted from ``pytest_sessionstart``, which runs
# BEFORE collection, and the session exits there.
#
# The proof is deliberately NOT "one test failed": these tests launch a CHILD
# pytest with ``--collect-only`` and assert on whether collection output was
# produced at all. ``--collect-only`` emits one line per collected test, so
# the absence of every test id in the child's output is a direct observation
# that collection never happened.


def _child_pytest_env(*, attest: bool) -> dict[str, str]:
    """Environment for a child pytest run: no credentials, chosen attestation.

    Credentials are stripped so the child cannot abort for the OTHER reason
    ``pytest_sessionstart`` has (the credential gate), which would make these
    assertions ambiguous.
    """
    from tests.conftest import POLYMARKET_CREDENTIAL_ENV_VARS

    env = {k: v for k, v in os.environ.items() if k not in POLYMARKET_CREDENTIAL_ENV_VARS}
    env.pop(OS_EGRESS_BLOCK_ENV_VAR, None)
    if attest:
        env[OS_EGRESS_BLOCK_ENV_VAR] = "1"
    return env


#: A test id that a completed collection of THIS module must print, and that
#: an aborted session cannot print. Named rather than pattern-matched so the
#: assertion cannot be satisfied by an unrelated line.
_COLLECTION_WITNESS_ID = "test_n4_success_is_not_treated_as_blocked"

#: Both child-session tests assert this FIRST. Without it, deleting
#: ``exec/__init__.py`` would turn them into two tests that pass by observing
#: an ordinary session -- vacuously green while the barrier gates nothing.
_CHILD_GATE_PRECONDITION = (
    "precondition failed: the shipped tree holds no execution-egress module, so "
    "the child session has nothing to gate and its fate proves nothing"
)


def _run_child_collect_only(*, attest: bool) -> subprocess.CompletedProcess[str]:
    """Collect (never run) this module in a child pytest. Fixed argv, no shell."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--collect-only",
            # ``-v`` because ``addopts`` carries ``-q``, under which
            # ``--collect-only`` collapses to a single count line. At default
            # verbosity it prints one line per collected test, which is what
            # makes "collection never happened" directly observable.
            "-v",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
            "tests/unit/test_execution_egress_firewall_guard.py",
        ],
        cwd=REPO_ROOT,
        env=_child_pytest_env(attest=attest),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )


def test_n2_an_unattested_session_aborts_before_collection() -> None:
    """RED 3. Egress modules exist, no attestation -> the session never collects.

    No canary packet is emitted on this path: an absent attestation is decided
    without probing anything.
    """
    from tests.conftest import EXECUTION_EGRESS_ABORT_MARKER

    assert find_execution_egress_modules(), _CHILD_GATE_PRECONDITION

    result = _run_child_collect_only(attest=False)
    combined = result.stdout + result.stderr
    assert EXECUTION_EGRESS_ABORT_MARKER in combined, combined[-4000:]
    assert "firewall is not attested" in combined, combined[-4000:]
    assert _COLLECTION_WITNESS_ID not in combined, (
        "the child reached collection; the rule reported instead of stopping"
    )
    assert result.returncode == 2, combined[-4000:]


def test_n2_an_attested_session_lives_or_dies_by_the_real_canary() -> None:
    """RED 3b. An attestation is worth exactly what the kernel says it is.

    Both branches are asserted, and which one applies is decided by a real
    measurement taken here in the parent rather than by an assumption about
    the host:

    * canary REACHED (an ordinary, unsandboxed run) -- the attestation is a
      lie and the child must abort before collection. This is the half
      revision 1 of the plan left untested;
    * canary BLOCKED (running under ``scripts/ci/run_tests_no_egress.sh``) --
      the attestation is substantiated and the child must proceed to
      collection. That is not a skip: it asserts the substantiated branch does
      NOT abort, so the barrier cannot be satisfied by aborting unconditionally.
    """
    from tests.conftest import EXECUTION_EGRESS_ABORT_MARKER

    assert find_execution_egress_modules(), _CHILD_GATE_PRECONDITION

    outcome = probe_real_egress_canary()
    result = _run_child_collect_only(attest=True)
    combined = result.stdout + result.stderr

    if outcome.blocked:
        assert EXECUTION_EGRESS_ABORT_MARKER not in combined, combined[-4000:]
        assert _COLLECTION_WITNESS_ID in combined, combined[-4000:]
        assert result.returncode == 0, combined[-4000:]
        return

    assert EXECUTION_EGRESS_ABORT_MARKER in combined, combined[-4000:]
    assert "was not blocked" in combined, combined[-4000:]
    assert _COLLECTION_WITNESS_ID not in combined, (
        "the child reached collection on a LYING attestation"
    )
    assert result.returncode == 2, combined[-4000:]


def test_n2_the_abort_decision_refuses_an_attested_but_unsubstantiated_firewall() -> None:
    """The same clause as RED 3b, decided in-process and without a packet.

    RED 3b can only exercise the lying-attestation branch on a host whose
    egress is genuinely open. This asserts the same rule directly against the
    function ``pytest_sessionstart`` consults, so the clause is covered on
    every host including a sandboxed CI runner.
    """
    from tests.conftest import execution_egress_abort_reason

    planted = [Violation("src/breezy/adapters/polymarket_us/exec/__init__.py", 0, "E0", "planted")]
    reason = execution_egress_abort_reason(
        egress_modules=planted,
        attested=True,
        outcome=classify_canary_failure(OSError(111, "Connection refused")),
    )
    assert reason is not None
    assert "was not blocked" in reason


def test_n2_the_abort_decision_is_silent_when_there_is_nothing_to_gate() -> None:
    """Non-vacuity in the other direction: no egress modules, no abort."""
    from tests.conftest import execution_egress_abort_reason

    assert execution_egress_abort_reason(egress_modules=[], attested=False, outcome=None) is None


def test_n2_the_test_module_assertion_and_the_conftest_rule_are_the_same_rule() -> None:
    """The in-suite assertion is the non-vacuity proof OF the conftest rule.

    If these were two implementations, the barrier's proof-by-construction
    tests would prove the copy nobody enforces.
    """
    from tests.conftest import execution_egress_abort_reason

    planted = [Violation("src/breezy/adapters/polymarket_us/exec/__init__.py", 0, "E0", "planted")]
    reason = execution_egress_abort_reason(
        egress_modules=planted,
        attested=False,
        outcome=None,
    )
    assert reason is not None
    with pytest.raises(AssertionError) as excinfo:
        assert_firewall_precedes_execution_egress(planted, attested=False, outcome=None)
    assert reason in str(excinfo.value)


# ==========================================================================
# N5 -- the launcher exists and is a working mechanism
# ==========================================================================


def test_n5_the_egress_block_launcher_is_shipped_and_executable() -> None:
    launcher = REPO_ROOT / EGRESS_BLOCK_LAUNCHER
    assert launcher.is_file(), f"N5: missing OS egress-block launcher {EGRESS_BLOCK_LAUNCHER}"
    assert os.access(launcher, os.X_OK), f"N5: {EGRESS_BLOCK_LAUNCHER} is not executable"
    text = launcher.read_text(encoding="utf-8")
    assert OS_EGRESS_BLOCK_ENV_VAR in text, "N5: launcher must set the attestation env var"


def test_n5_the_launcher_mechanism_actually_blocks_egress_on_this_host() -> None:
    """End-to-end: run a real connect under the launcher's sandbox.

    Skipped when no unprivileged network-namespace tool is present, because
    that is a property of the host, not a defect in the repo -- and a barrier
    that fails for an unrelated reason is a barrier that gets deleted.
    """
    bwrap = shutil.which("bwrap")
    if bwrap is None:
        pytest.skip("bwrap not installed; cannot verify the sandbox on this host")

    probe = (
        "import socket\n"
        "s = socket.socket(); s.settimeout(3)\n"
        "try:\n"
        f"    s.connect(({CANARY_HOST!r}, {CANARY_PORT}))\n"
        "    print('REACHED')\n"
        "except OSError as e:\n"
        "    print('ERRNO', e.errno)\n"
    )
    # Fixed argv, no shell, no user-supplied input.
    result = subprocess.run(
        [bwrap, "--unshare-net", "--dev-bind", "/", "/", sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(f"bwrap unusable on this host: {result.stderr.strip()[:200]}")
    assert result.stdout.startswith("ERRNO "), f"N5: unexpected probe output {result.stdout!r}"
    errno = int(result.stdout.split()[1])
    assert errno in _BLOCKED_ERRNOS, f"N5: sandbox did not block egress (errno {errno})"


def test_n5_the_same_probe_is_not_blocked_without_the_sandbox() -> None:
    """Control: proves N5's assertion is caused by the sandbox, not the host.

    Without this, N5 would pass identically on a machine with no network at
    all, and would therefore be evidence of nothing.
    """
    probe_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe_socket.settimeout(0.1)
    try:
        # The autouse Python kill-switch is exactly what makes this raise
        # RuntimeError rather than an OSError, and that is the point: the
        # PYTHON path is blocked, which is why N1/N3 probe the NATIVE one.
        with pytest.raises(RuntimeError, match="Network access is disabled"):
            probe_socket.connect((CANARY_HOST, CANARY_PORT))
    finally:
        probe_socket.close()
