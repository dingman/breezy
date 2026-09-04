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
    _imported_module_strings,
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
        "submit_chain.py",
        "trading.py",
        "write_transport.py",
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



#: X1 -- roots scanned for the exec-test marker ban.
TEST_SCAN_ROOTS = ("tests",)

#: X1 -- the execution package, as an import string and as a path prefix.
EXEC_PACKAGE_MODULE = "breezy.adapters.polymarket_us.exec"
EXEC_PACKAGE_PATH_PREFIX = "src/breezy/adapters/polymarket_us/exec/"

#: X1 -- the four markers for which ``tests/conftest.py`` (:455-459) restores
#: the ORIGINAL native pyo3 network clients, undoing barrier N1 for that test.
SOCKET_RESTORING_MARKERS = frozenset({"allow_socket", "live", "venue_live", "real_money"})

#: X2 -- native constructs banned BY NAME (plan section 6.1).
#:
#: ``SandboxExecutionClient`` hardcodes a ``MakerTakerFeeModel`` and a
#: ``LatencyModel(0)``; ``BettingAccount`` and ``AccountType.BETTING`` model
#: back/lay stake, which is not a drop-in for a 0-1 binary.
BANNED_NATIVE_NAMES = frozenset({"SandboxExecutionClient", "BettingAccount"})
BANNED_ACCOUNT_TYPE_MEMBER = "BETTING"
BANNED_NATIVE_MODULE_SUBSTRING = "accounting.accounts.betting"

#: X3 -- direction vocabulary prohibited anywhere under ``exec/``.
BANNED_EXEC_DIRECTION_TOKENS = frozenset({"_SHORT", "OUTCOME_SIDE_NO"})


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

    R-3 is the first increment to exercise that: ``endpoints.py`` (GET path
    templates plus a Decimal-preserving decoder) and ``reports.py`` (venue
    payload -> native execution report mapping) are registered below. Both are
    read/map only and neither performs I/O, but E0 classifies by PATH and is
    right to: what makes them egress surfaces is where they live, not what
    they currently do.

    EXEC SPINE W adds the LAST row. ``PolymarketUSLiveExecClientFactory``
    (``adapters/polymarket_us/factories.py``) subclasses
    ``LiveExecClientFactory`` -- one of ``_EGRESS_CLASS_BASES`` -- so E2 fires
    on it exactly as it does on ``exec/client.py``'s own base. ``factories.py``
    sits OUTSIDE the ``exec/`` prefix, so E0/E1 do not fire on it, and it
    defines none of the six order-lifecycle coroutines, so E3 does not either
    -- ONE new row, not seven. Non-vacuity: delete the row below and this test
    must go red the moment the factory class exists; see
    ``test_n2_e0_does_not_fire_outside_the_exec_package`` for the general
    shape of that proof.
    """
    found = [(v.path, v.rule) for v in find_execution_egress_modules()]
    assert found == [
        ("src/breezy/adapters/polymarket_us/exec/__init__.py", "E0"),
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E0"),
        # R-4's client is the first module here that E2 and E3 can SEE: it
        # subclasses `LiveExecutionClient` and defines all six order
        # coroutines. Six E3 rows, one per coroutine -- the COUNT is part of
        # the pin, so a seventh order verb cannot appear silently.
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E2"),
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E3"),
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E3"),
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E3"),
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E3"),
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E3"),
        ("src/breezy/adapters/polymarket_us/exec/client.py", "E3"),
        ("src/breezy/adapters/polymarket_us/exec/endpoints.py", "E0"),
        # EXEC SPINE R-6d: `refusals.py` classifies a venue refusal as
        # TRANSIENT or DURABLE. Like `endpoints.py` and `reports.py` it is
        # pure and performs no I/O -- and like them it is an egress surface
        # by PATH, which is the classification E0 exists to make. ONE new row:
        # it defines no class in `_EGRESS_CLASS_BASES` (E2) and no
        # order-lifecycle function (E3).
        ("src/breezy/adapters/polymarket_us/exec/refusals.py", "E0"),
        ("src/breezy/adapters/polymarket_us/exec/reports.py", "E0"),
        ("src/breezy/adapters/polymarket_us/exec/submit_chain.py", "E0"),
        ("src/breezy/adapters/polymarket_us/exec/submit_chain.py", "E1"),
        # EXEC SPINE W: `PolymarketUSLiveExecClientFactory(LiveExecClientFactory)`.
        ("src/breezy/adapters/polymarket_us/factories.py", "E2"),
        # R-6.5b: basename added voluntarily so E1 classifies the write
        # transport. No E0 (outside exec/), no E2, no E3.
        ("src/breezy/adapters/polymarket_us/write_transport.py", "E1"),
    ]


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



# ==========================================================================
# X1-X3 -- the detectors (single implementations; the proofs above run these)
# ==========================================================================


def _marker_names(tree: ast.AST) -> set[str]:
    """Every pytest marker NAME the module applies, however it is spelled.

    Covers ``@pytest.mark.x``, ``@pytest.mark.x(...)``, the bare
    ``from pytest import mark`` / ``@mark.x`` form, and the module-level
    ``pytestmark = ...`` assignment -- all of which reduce to an
    ``ast.Attribute`` whose receiver is spelled ``mark``.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        receiver = node.value
        receiver_name = (
            receiver.attr
            if isinstance(receiver, ast.Attribute)
            else getattr(receiver, "id", "")
        )
        if receiver_name == "mark":
            names.add(node.attr)
    return names


def _imports_exec_package(tree: ast.AST) -> bool:
    """True when the module imports the execution package or a submodule.

    An AST check, not a text match: a planted SOURCE STRING naming the
    package -- of which this very module holds several -- must not count as
    an import of it.
    """
    for module in _imported_module_strings(tree):
        if module == EXEC_PACKAGE_MODULE or module.startswith(EXEC_PACKAGE_MODULE + "."):
            return True
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.level != 0 or not node.module:
            continue
        if node.module != EXEC_PACKAGE_MODULE.rsplit(".", 1)[0]:
            continue
        if any(alias.name == "exec" for alias in node.names):
            return True  # ``from breezy.adapters.polymarket_us import exec``
    return False


def find_exec_test_marker_violations(path: str, source: str) -> list[Violation]:
    """X1: a test module importing ``exec/`` may carry no socket-restoring marker."""
    tree = ast.parse(source, filename=path)
    if not _imports_exec_package(tree):
        return []
    offending = sorted(_marker_names(tree) & SOCKET_RESTORING_MARKERS)
    return [
        Violation(
            path,
            0,
            "X1",
            f"imports {EXEC_PACKAGE_MODULE} under @pytest.mark.{marker}, "
            f"which restores the real pyo3 network clients",
        )
        for marker in offending
    ]


def scan_exec_test_markers(roots: tuple[str, ...] = TEST_SCAN_ROOTS) -> list[Violation]:
    return [
        v
        for path, src in iter_python_sources(roots)
        for v in find_exec_test_marker_violations(path, src)
    ]


def find_banned_native_constructs(path: str, source: str) -> list[Violation]:
    """X2: the constructs the plan bans by name, detected through the AST.

    AST rather than raw text, deliberately and load-bearingly:
    ``runtime/backtest_harness.py:684`` carries a COMMENT saying the account
    type is deliberately NOT ``BETTING``. That comment is correct in context
    and must never be "fixed" to satisfy a barrier -- the same hazard the plan
    names for ``risk.py``'s "short YES is spelled buy NO".
    """
    tree = ast.parse(source, filename=path)
    found: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if BANNED_NATIVE_MODULE_SUBSTRING in alias.name:
                    found.append(
                        Violation(path, node.lineno, "X2", f"imports {alias.name}")
                    )
        elif isinstance(node, ast.ImportFrom):
            if node.module and BANNED_NATIVE_MODULE_SUBSTRING in node.module:
                found.append(Violation(path, node.lineno, "X2", f"imports {node.module}"))
            for alias in node.names:
                if alias.name in BANNED_NATIVE_NAMES or alias.name == BANNED_ACCOUNT_TYPE_MEMBER:
                    found.append(
                        Violation(path, node.lineno, "X2", f"imports the name {alias.name}")
                    )
        elif isinstance(node, ast.Attribute):
            if node.attr in BANNED_NATIVE_NAMES or node.attr == BANNED_ACCOUNT_TYPE_MEMBER:
                found.append(Violation(path, node.lineno, "X2", f"references .{node.attr}"))
        elif isinstance(node, ast.Name):
            if node.id in BANNED_NATIVE_NAMES:
                found.append(Violation(path, node.lineno, "X2", f"references {node.id}"))
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and node.slice.value == BANNED_ACCOUNT_TYPE_MEMBER
        ):
            found.append(
                Violation(path, node.lineno, "X2", f"reaches [{BANNED_ACCOUNT_TYPE_MEMBER!r}]")
            )
    # An ``import ... import Name`` reports the module AND the imported name;
    # collapse to one finding per line so a count assertion stays meaningful.
    seen: set[tuple[int, str]] = set()
    unique: list[Violation] = []
    for violation in found:
        key = (violation.lineno, violation.rule)
        if key in seen:
            continue
        seen.add(key)
        unique.append(violation)
    return unique


def scan_banned_native_constructs(
    roots: tuple[str, ...] = EGRESS_SCAN_ROOTS,
) -> list[Violation]:
    return [
        v
        for path, src in iter_python_sources(roots)
        for v in find_banned_native_constructs(path, src)
    ]


def _is_one(node: ast.expr) -> bool:
    """True for ``1``, ``1.0``, and one-argument constructors of either."""
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return bool(node.value == 1)
    if (
        isinstance(node, ast.Call)
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
    ):
        value = node.args[0].value
        if isinstance(value, str):
            return value.strip() in {"1", "1.0"}
        if isinstance(value, int | float):
            return bool(value == 1)
    return False


def find_exec_direction_violations(path: str, source: str) -> list[Violation]:
    """X3: direction vocabulary and complement arithmetic, under ``exec/`` only.

    Two passes, because neither alone suffices: raw text sees identifiers and
    comments the AST cannot, and the AST sees implicitly concatenated string
    literals the raw text cannot. One finding per token per file.
    """
    if not path.startswith(EXEC_PACKAGE_PATH_PREFIX):
        return []
    tree = ast.parse(source, filename=path)
    constants = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    found: list[Violation] = []
    for token in sorted(BANNED_EXEC_DIRECTION_TOKENS):
        if token in source or any(token in value for value in constants):
            found.append(
                Violation(path, 0, "X3", f"carries the banned direction token {token!r}")
            )
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub) and _is_one(node.left):
            found.append(
                Violation(
                    path,
                    node.lineno,
                    "X3",
                    "complement arithmetic `1 - x`: the YES/NO flip this plan does not build",
                )
            )
    return found


def scan_exec_direction_vocabulary(
    roots: tuple[str, ...] = EGRESS_SCAN_ROOTS,
) -> list[Violation]:
    return [
        v
        for path, src in iter_python_sources(roots)
        for v in find_exec_direction_violations(path, src)
    ]

# ==========================================================================
# X1 -- no exec test may carry a marker that restores the real pyo3 clients
# ==========================================================================
#
# ``tests/conftest.py:455-459`` restores the ORIGINAL native network clients
# for any test carrying ``allow_socket``, ``live``, ``venue_live`` or
# ``real_money``. A test that imports the execution package and carries one of
# those markers therefore runs execution-adjacent code with barrier N1 lifted.
#
# The ban is sound only because no exec test ever needs a socket: composition
# is observed by calling ``node.build()``, which constructs clients and opens
# nothing, with both factories' transports monkeypatched. If that ever stops
# being true, the answer is a different technique, not a marker.

#: Planted test module: imports the execution package AND lifts N1.
_PLANTED_EXEC_TEST_WITH_MARKER = (
    "import pytest\n"
    "\n"
    "from breezy.adapters.polymarket_us.exec import endpoints\n"
    "\n"
    "\n"
    "@pytest.mark.allow_socket\n"
    "def test_reaches_the_venue():\n"
    "    assert endpoints is not None\n"
)

#: Same import, no marker. The exemption that keeps X1 from being a blanket
#: ban on testing the exec package at all.
_PLANTED_EXEC_TEST_WITHOUT_MARKER = (
    "from breezy.adapters.polymarket_us.exec import endpoints\n"
    "\n"
    "\n"
    "def test_reaches_nothing():\n"
    "    assert endpoints is not None\n"
)

#: A marked test that does NOT touch the exec package -- the shipped suite has
#: these (the ``live`` weather tests), and X1 must not touch them.
_PLANTED_MARKED_TEST_OUTSIDE_THE_EXEC_PACKAGE = (
    "import pytest\n"
    "\n"
    "\n"
    "@pytest.mark.live\n"
    "def test_weather():\n"
    "    assert True\n"
)


def test_x1_no_shipped_test_imports_the_exec_package_under_a_socket_marker() -> None:
    """The live barrier. Vacuous today by construction -- see the proofs below."""
    violations = scan_exec_test_markers()
    assert violations == [], "X1 violations:\n" + "\n".join(str(v) for v in violations)


@pytest.mark.parametrize("marker", sorted(SOCKET_RESTORING_MARKERS))
def test_x1_detects_every_marker_that_restores_the_real_pyo3_clients(marker: str) -> None:
    """One case per marker: all four restore the clients, all four are banned."""
    source = _PLANTED_EXEC_TEST_WITH_MARKER.replace("allow_socket", marker)
    violations = find_exec_test_marker_violations("tests/unit/test_planted.py", source)
    assert [v.rule for v in violations] == ["X1"]
    assert marker in violations[0].detail


def test_x1_detects_the_module_level_pytestmark_form() -> None:
    """``pytestmark = pytest.mark.allow_socket`` marks every test in the file."""
    source = (
        "import pytest\n"
        "\n"
        "from breezy.adapters.polymarket_us import exec as exec_pkg\n"
        "\n"
        "pytestmark = [pytest.mark.venue_live]\n"
        "\n"
        "\n"
        "def test_x():\n"
        "    assert exec_pkg is not None\n"
    )
    assert [v.rule for v in find_exec_test_marker_violations("tests/unit/t.py", source)] == ["X1"]


def test_x1_detects_the_bare_mark_import_form() -> None:
    """``from pytest import mark`` then ``@mark.allow_socket``."""
    source = (
        "from pytest import mark\n"
        "\n"
        "from breezy.adapters.polymarket_us.exec import client\n"
        "\n"
        "\n"
        "@mark.allow_socket\n"
        "def test_x():\n"
        "    assert client is not None\n"
    )
    assert [v.rule for v in find_exec_test_marker_violations("tests/unit/t.py", source)] == ["X1"]


def test_x1_does_not_fire_on_an_exec_test_that_carries_no_marker() -> None:
    violations = find_exec_test_marker_violations(
        "tests/unit/test_planted.py", _PLANTED_EXEC_TEST_WITHOUT_MARKER
    )
    assert violations == []


def test_x1_does_not_fire_on_a_marked_test_outside_the_exec_package() -> None:
    """The shipped ``live`` and ``venue_live`` suites must stay untouched."""
    violations = find_exec_test_marker_violations(
        "tests/live/test_weather.py", _PLANTED_MARKED_TEST_OUTSIDE_THE_EXEC_PACKAGE
    )
    assert violations == []


def test_x1_the_marker_set_is_exactly_the_set_conftest_restores_clients_for() -> None:
    """Pins X1's set to its REASON. Read off conftest's source, not recalled.

    If conftest starts restoring the clients for a fifth marker, X1's set is
    stale and this fails -- rather than X1 silently covering three of four.
    """
    source = (REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    tree = ast.parse(source, filename="tests/conftest.py")
    restoring: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "get_closest_marker"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            restoring.add(node.args[0].value)
    assert SOCKET_RESTORING_MARKERS <= restoring


# ==========================================================================
# X2 -- constructs banned BY NAME (plan section 6.1, "Banned by name")
# ==========================================================================


def test_x2_no_module_in_src_or_scripts_uses_a_banned_native_construct() -> None:
    violations = scan_banned_native_constructs()
    assert violations == [], "X2 violations:\n" + "\n".join(str(v) for v in violations)


def test_x2_detects_the_sandbox_execution_client_by_import() -> None:
    source = "from nautilus_trader.adapters.sandbox.execution import SandboxExecutionClient\n"
    assert [v.rule for v in find_banned_native_constructs("src/breezy/x.py", source)] == ["X2"]


def test_x2_detects_the_sandbox_execution_client_used_as_a_base() -> None:
    source = (
        "from nautilus_trader.adapters.sandbox import execution\n"
        "\n"
        "\n"
        "class C(execution.SandboxExecutionClient):\n"
        "    pass\n"
    )
    assert [v.rule for v in find_banned_native_constructs("src/breezy/x.py", source)] == ["X2"]


def test_x2_detects_the_betting_account_type_member() -> None:
    source = "from nautilus_trader.model.enums import AccountType\n\nT = AccountType.BETTING\n"
    assert [v.rule for v in find_banned_native_constructs("src/breezy/x.py", source)] == ["X2"]


def test_x2_detects_the_betting_member_reached_by_subscript() -> None:
    """``AccountType['BETTING']`` is the same member by another spelling."""
    source = "from nautilus_trader.model.enums import AccountType\n\nT = AccountType['BETTING']\n"
    assert [v.rule for v in find_banned_native_constructs("src/breezy/x.py", source)] == ["X2"]


def test_x2_detects_the_betting_account_module() -> None:
    source = "from nautilus_trader.accounting.accounts.betting import BettingAccount\n"
    rules = [v.rule for v in find_banned_native_constructs("src/breezy/x.py", source)]
    assert rules and set(rules) == {"X2"}


def test_x2_does_not_fire_on_the_shipped_comment_that_explains_the_refusal() -> None:
    """``backtest_harness.py:684`` says why BETTING is NOT used. That comment
    is correct in context and must never be "fixed".

    X2 is an AST rule precisely so a comment cannot trip it -- the same
    hazard the plan names for ``risk.py``'s "short YES is spelled buy NO".
    """
    path = REPO_ROOT / "src" / "breezy" / "runtime" / "backtest_harness.py"
    source = path.read_text(encoding="utf-8")
    assert "BETTING" in source
    assert find_banned_native_constructs("src/breezy/runtime/backtest_harness.py", source) == []


def test_x2_does_not_fire_on_an_unrelated_attribute_named_after_a_different_member() -> None:
    source = "from nautilus_trader.model.enums import AccountType\n\nT = AccountType.CASH\n"
    assert find_banned_native_constructs("src/breezy/x.py", source) == []


# ==========================================================================
# X3 -- direction vocabulary banned under exec/ (prohibition, not purity)
# ==========================================================================
#
# ``_SHORT`` and ``OUTCOME_SIDE_NO`` are the tokens by which a direction model
# this plan does not build would enter, and ``1 - price`` is the complement
# arithmetic that silently converts one side into the other. All three are
# PROHIBITED under ``exec/`` rather than proven absent, so indirection cannot
# defeat them: the token scan reads raw text, not the AST.
#
# The ban is scoped to ``exec/`` by path and to nothing else, deliberately.
# ``risk.py:75-78``'s comment "short YES is spelled buy NO" is CORRECT in its
# own context and must not be "fixed"; a repo-wide token ban would have
# demanded exactly that.
#
# At NS-2 ``exec/`` holds one docstring-only ``__init__.py``, so the live scan
# below passes over nothing. That is why each ban ships with a planted-source
# proof: a scan that cannot fire on the day it lands is decoration until
# proven otherwise.


def test_x3_no_module_under_exec_carries_direction_vocabulary() -> None:
    """The live barrier. Vacuous at NS-2 -- the proofs below are the content."""
    violations = scan_exec_direction_vocabulary()
    assert violations == [], "X3 violations:\n" + "\n".join(str(v) for v in violations)


def test_x3_the_live_scan_actually_reaches_the_exec_package() -> None:
    """Non-vacuity of the SCAN's reach, distinct from the rule's reach.

    Without this the live test above would pass identically if the scan
    walked an empty root -- which is exactly how a vacuous barrier reads.

    Since R-3 the root is no longer empty: the token scan now reads two
    modules of real source, so the live test above stopped being vacuous. The
    equality is kept anyway, for the same reason N2's is -- a module that
    appears under ``exec/`` without a reviewer noticing is the thing being
    prevented.
    """
    scanned = {
        path
        for path, _ in iter_python_sources(EGRESS_SCAN_ROOTS)
        if path.startswith(EXEC_PACKAGE_PATH_PREFIX)
    }
    assert scanned == {
        "src/breezy/adapters/polymarket_us/exec/__init__.py",
        "src/breezy/adapters/polymarket_us/exec/client.py",
        "src/breezy/adapters/polymarket_us/exec/endpoints.py",
        # EXEC SPINE R-6d: the transient/durable refusal classifier. Pure,
        # stdlib-only, and under `exec/` because that is where the venue's
        # error payloads are parsed -- WIDENED, not relaxed: the comparison
        # stays `==` and the new module is brought INSIDE both scans.
        "src/breezy/adapters/polymarket_us/exec/refusals.py",
        "src/breezy/adapters/polymarket_us/exec/reports.py",
        "src/breezy/adapters/polymarket_us/exec/submit_chain.py",
    }


@pytest.mark.parametrize("token", sorted(BANNED_EXEC_DIRECTION_TOKENS))
def test_x3_detects_each_banned_token_in_planted_exec_source(token: str) -> None:
    source = f'"""Docstring."""\n\nINTENT = "ORDER_INTENT_SELL{token}"\n'
    violations = find_exec_direction_violations(f"{EXEC_PACKAGE_PATH_PREFIX}reports.py", source)
    assert [v.rule for v in violations] == ["X3"]
    assert token in violations[0].detail


def test_x3_detects_a_banned_token_split_across_an_implicit_concatenation() -> None:
    """Two scans, because neither alone is enough.

    The raw-text pass sees nothing here -- the token does not appear in the
    source at all. Python's parser folds adjacent string literals into ONE
    ``ast.Constant``, so the AST pass does see it. Conversely the AST pass
    cannot see an identifier or a comment, which the raw-text pass can.

    Residual, stated rather than claimed away: an EXPLICIT ``"OUTCOME_SIDE_"
    + "NO"`` is folded by neither, and is not detected. The ban is a
    prohibition on the vocabulary, not a proof of semantic absence.
    """
    source = 'SIDE = "OUTCOME_SIDE_" "NO"\n'
    assert "OUTCOME_SIDE_NO" not in source
    violations = find_exec_direction_violations(f"{EXEC_PACKAGE_PATH_PREFIX}reports.py", source)
    assert [v.rule for v in violations] == ["X3"]


def test_x3_detects_the_complement_arithmetic() -> None:
    source = "def no_price(price):\n    return 1 - price\n"
    violations = find_exec_direction_violations(f"{EXEC_PACKAGE_PATH_PREFIX}reports.py", source)
    assert [v.rule for v in violations] == ["X3"]
    assert "complement" in violations[0].detail


def test_x3_detects_the_complement_through_a_decimal_constructor() -> None:
    source = (
        "from decimal import Decimal\n\n\ndef no_price(price):\n    return Decimal('1') - price\n"
    )
    path = f"{EXEC_PACKAGE_PATH_PREFIX}reports.py"
    rules = [v.rule for v in find_exec_direction_violations(path, source)]
    assert rules == ["X3"]


def test_x3_does_not_fire_on_ordinary_subtraction() -> None:
    source = "def remaining(quantity, filled):\n    return quantity - filled\n"
    assert find_exec_direction_violations(f"{EXEC_PACKAGE_PATH_PREFIX}reports.py", source) == []


def test_x3_does_not_fire_outside_the_exec_package() -> None:
    """``risk.py``'s correct-in-context comment is why this scope exists."""
    source = "OUTCOME_SIDE_NO = 'no'\n\n\ndef no_price(price):\n    return 1 - price\n"
    assert find_exec_direction_violations("src/breezy/strategy/risk.py", source) == []


# ==========================================================================
# E0-INERT -- the shipped exec/ modules must be inert, not merely classified
# ==========================================================================
#
# COMPENSATING STRENGTHENING, banked while it is free. E0 says every module
# under ``exec/`` IS an execution-egress surface, by path. That is a statement
# about WHERE a module lives; it is not, and cannot be, a statement about what
# the module DOES. Set membership proves a module EXISTS -- never that it is
# INERT.
#
# R-3 ships two real modules under that path whose entire claim is that they
# perform no I/O of any kind: a table of GET path templates plus pure decoders
# and mappers. Both hold today, so the rule costs nothing to add and closes
# the gap between "classified" and "harmless" before the increment that would
# make it expensive. It is a PROHIBITION, in the idiom of X3: the vocabulary
# by which egress would enter is banned outright rather than proven absent.
#
# Strengthening only. Nothing below relaxes E0, which continues to classify
# every module here regardless of what this rule finds.


#: Dotted module prefixes that can open a socket, directly or through a
#: runtime. ``asyncio`` is here because R-3 is synchronous by contract: a
#: coroutine under ``exec/`` is the shape an I/O path arrives in.
NETWORK_IMPORT_PREFIXES = frozenset(
    {
        "aiohttp",
        "asyncio",
        "http",
        "httpx",
        "nautilus_trader.core.nautilus_pyo3",
        "nautilus_trader.network",
        "requests",
        "socket",
        "ssl",
        "urllib",
        "websocket",
        "websockets",
    }
)


#: E0-INERT NARROWING (R-4), paid for by the three strengthenings below.
#:
#: R-3 could be inert because it was pure mapping. A ``LiveExecutionClient``
#: cannot: ``live/execution_client.py:598-633`` declares ``_connect``,
#: ``_disconnect`` and all six order coroutines as ``async def``, and
#: ``:246-256`` drives them through ``create_task``. So the async BAN is
#: narrowed to exactly the modules named here, and ONLY the async passes plus
#: the ``asyncio`` import are relaxed for them -- every other network-capable
#: import stays banned, for them as for every other module under ``exec/``.
#:
#: A frozenset of EXACT paths, never a prefix: a prefix would relax the rule
#: for every module later added beside the client.
EXEC_ASYNC_LIFECYCLE_MODULES = frozenset({"src/breezy/adapters/polymarket_us/exec/client.py"})

#: STRENGTHENING 1 of 3. Inside an async-permitted module, only these
#: coroutine names may exist. The narrowing above buys the SHAPE of I/O; this
#: keeps the INVENTORY closed, so a new coroutine -- which is how a send path
#: would arrive -- cannot appear without a reviewer editing this set.
#:
#: Every name is either a Nautilus lifecycle method the base declares, or a
#: Breezy private the client's own docstring accounts for.
EXEC_PERMITTED_COROUTINE_NAMES = frozenset(
    {
        # Nautilus `LiveExecutionClient` coroutines (`live/execution_client.py`)
        "_connect",
        "_disconnect",
        "_query_account",
        "_query_order",
        "_submit_order",
        "_submit_order_list",
        "_modify_order",
        "_cancel_order",
        "_cancel_all_orders",
        "_batch_cancel_orders",
        "generate_order_status_report",
        "generate_order_status_reports",
        "generate_fill_reports",
        "generate_position_status_reports",
        "generate_mass_status",
        # Breezy privates, each named in the client's module docstring.
        "_publish_account_state",
        "_wait_for_instruments",
        "_confirm_account_registered",
        # The injected read protocol's own call signature.
        "__call__",
    }
)

#: STRENGTHENING 2 of 3. Breezy modules that CARRY a network client. E0-INERT
#: listed only stdlib and third-party prefixes, so the shortest route to the
#: network from under ``exec/`` -- ``from breezy.adapters.polymarket_us.http
#: import PolymarketUSHttpClient`` -- matched NOTHING. It does now, for every
#: module under ``exec/``, async-permitted or not.
#:
#: ``transport`` is not banned wholesale because ``exec/endpoints.py`` already
#: imports ``QUOTA_KEY_PORTFOLIO`` from it, and a quota key is a constant, not
#: a socket. The class that owns the socket is banned by NAME instead.
BANNED_EXEC_TRANSPORT_MODULES = frozenset(
    {
        "breezy.adapters.polymarket_us.data",
        "breezy.adapters.polymarket_us.http",
        "breezy.adapters.polymarket_us.websocket",
        "breezy.ingest.http",
        # BL-24 Seam B (S1): the NWS observation parser, the transport that
        # owns the socket, and the Actor that drives it. Widened, never
        # relaxed (L-12).
        "breezy.ingest.nws_observation_actor",
        "breezy.ingest.nws_observation_config",
        "breezy.ingest.nws_observation_transport",
        "breezy.ingest.nws_observations",
        "breezy.ingest.probe_transport",
        "breezy.runtime.health",
    }
)

#: STRENGTHENING 2, second half: the client CLASSES themselves, wherever they
#: are imported from and however they are reached, including as an attribute
#: on an otherwise-permitted module.
BANNED_EXEC_TRANSPORT_NAMES = frozenset(
    {
        "MarketsFeed",
        "NautilusHttpTransport",
        # BL-24 Seam B (S1) -- widened, never relaxed (L-12).
        "NwsObservationActor",
        "NwsObservationTransport",
        "PolymarketUSDataClient",
        "PolymarketUSHttpClient",
        "PolymarketUSMarketsWebSocketPool",
        "WebhookAlertSink",
    }
)

#: STRENGTHENING 3 of 3. The order-lifecycle coroutines, which R-4 must leave
#: unsendable. Their refusal is made MECHANICAL rather than asserted in prose,
#: by an allowlist of what their bodies may CALL -- see
#: :data:`EXEC_ORDER_COROUTINE_PERMITTED_CALLEES`.
#:
#: An earlier form of this rule banned only ``await``, on the reasoning that
#: every send path at this venue is async (``http.py:116``
#: ``get_authenticated`` is a coroutine, and so is every transport method under
#: it). That reasoning is TRUE of the transport and FALSE of the coroutine
#: body: scheduling the coroutine (``self.create_task(...)``,
#: ``asyncio.create_task(...)``), hopping through a synchronous helper, or
#: handing it to a thread all reach the same transport with no ``await`` in
#: sight. R-7 lands the submit path and must narrow THIS rule, in its own
#: commit, with its own compensating strengthening -- which is the point of
#: stating it here.
ORDER_LIFECYCLE_COROUTINES = frozenset(
    {
        "_submit_order",
        "_submit_order_list",
        "_modify_order",
        "_cancel_order",
        "_cancel_all_orders",
        "_batch_cancel_orders",
    }
)

#: STRENGTHENING 3, second half. The ONLY callees an order coroutine may
#: invoke, as the dotted name written in the source.
#:
#: An ``await`` ban alone was measured to be worth far less than it reads. On
#: the async-PERMITTED module every one of these passed it CLEAN:
#: ``self.create_task(self._private_read('/x'))`` -- the exact native mechanism
#: the narrowing's own docstring cites -- ``asyncio.create_task(...)``, a plain
#: synchronous hop ``self._send(command)``, and
#: ``threading.Thread(target=...).start()``. None of them contains an
#: ``await``, and every one of them can send an order.
#:
#: So the rule is inverted: an order coroutine may make ONLY the calls listed
#: here, and ANY other call -- by name, by attribute, or on the result of
#: another call -- is a violation. An allowlist cannot be defeated by finding a
#: mechanism nobody thought to ban.
EXEC_ORDER_COROUTINE_PERMITTED_CALLEES = frozenset(
    {
        # Logging a refusal.
        "self._log.error",
        "self._log.warning",
        # The native denial / lifecycle surface (`execution/client.pyx`).
        "self.generate_order_denied",
        "self.generate_order_cancel_rejected",
        "self.generate_order_submitted",
        "self.generate_order_rejected",
        "self.generate_order_filled",
        "self.generate_order_canceled",
        # Reading local state: the cached account, the clock, the instrument.
        "self._cache.account_for_venue",
        "self._cache.instrument",
        "self._clock.timestamp_ns",
        "self._refuse",
        "self._deny",
        "self._retire",
        "self._generate_submitted",
        # The shared "this path is not implemented" message, and the raise.
        "self._unsupported",
        "NotImplementedError",
        # R-7 chokepoint: permit, ledger, latch, signer, sender, pure helpers.
        "assert_live_order_submission_permitted",
        "self._ledger.authorize_order_cost",
        "self._ledger.release_booking",
        "self._ledger.true_up_booking",
        "self._latch.arm",
        "self._latch.retire",
        "self._write_signer.sign_headers",
        "self._order_sender.post_order",
        "submit_chain.latched_refusal_reason",
        "submit_chain.missing_account_reason",
        "submit_chain.permit_is_missing",
        "submit_chain.order_notional_usd",
        "submit_chain.order_fingerprint_bytes",
        "submit_chain.unmappable_order_reason",
        "submit_chain.build_order_body",
        "submit_chain.encode_order_body",
        "submit_chain.order_price_decimal",
        "submit_chain.order_quantity_decimal",
        "submit_chain.intent_fingerprint",
        "submit_chain.is_latch_arm_refusal",
        "submit_chain.is_cancelled",
        "submit_chain.classify_create_order_outcome",
        "submit_chain.retirement_member",
        "submit_chain.venue_order_id",
    }
)

#: Coroutines named in :data:`EXEC_PERMITTED_COROUTINE_NAMES` that the shipped
#: client does NOT define, so the inventory check can be an EQUALITY.
#:
#: A subset check (``defined <= permitted``) passes just as happily when a
#: coroutine is DELETED, which is how ``_query_account`` -- the method
#: ``live/execution_client.py:332`` calls with nothing defining it in the base
#: -- could disappear without a failure. ``_query_order`` is declared here
#: because the base DOES define it and this client does not override it.
#:
#: "Declared unimplemented" means two DIFFERENT fates, and this set only ever
#: holds the second one. ``_query_account`` is genuinely absent -- the base
#: has nothing defining it, so the ``QueryAccount`` path would raise
#: ``AttributeError`` were it ever left undeclared. ``_query_order`` is NOT
#: absent: the base defines a real method (``live/execution_client.py:516-532``)
#: that calls ``generate_order_status_report`` and, if the result is
#: non-``None``, ``_send_order_status_report`` -- a report-injection seam that
#: bypasses ``_submit_order``'s refusal latch. For this entry, "unimplemented"
#: means the NATIVE default RUNS, unmodified, every time; the seam stays
#: closed only because this client's own ``generate_order_status_report``
#: always returns ``None`` (pinned in
#: ``tests/unit/test_polymarket_us_exec_client.py`` by
#: ``test_native_query_order_never_reaches_the_send_seam``), never because
#: the coroutine is missing or raises.
EXEC_DECLARED_UNIMPLEMENTED_COROUTINES = frozenset({"_query_order"})


def _dotted_import_strings(tree: ast.AST) -> set[str]:
    """Every dotted name an import statement binds, module and member alike."""
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            for alias in node.names:
                found.add(f"{node.module}.{alias.name}")
    return found


def find_exec_transport_violations(path: str, source: str) -> list[Violation]:
    """E0-TRANSPORT: no module under ``exec/`` may reach a Breezy network client.

    The compensating strengthening for the async narrowing, and it closes a
    hole that predates it: E0-INERT's prefix list is stdlib and third-party
    only, so the capability could always have arrived through a Breezy module
    that owns a socket. It cannot now.
    """
    tree = ast.parse(source, filename=path)
    violations: list[Violation] = []

    for dotted in sorted(_dotted_import_strings(tree)):
        if dotted in BANNED_EXEC_TRANSPORT_MODULES:
            violations.append(
                Violation(path, 0, "E0-TRANSPORT", f"imports {dotted!r}, which owns a socket")
            )
    for node in ast.walk(tree):
        name = ""
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in BANNED_EXEC_TRANSPORT_NAMES:
                    violations.append(
                        Violation(
                            path,
                            node.lineno,
                            "E0-TRANSPORT",
                            f"imports the network client {alias.name!r}",
                        )
                    )
            continue
        if isinstance(node, ast.Attribute):
            name = node.attr
        elif isinstance(node, ast.Name):
            name = node.id
        if name in BANNED_EXEC_TRANSPORT_NAMES:
            violations.append(
                Violation(
                    path,
                    getattr(node, "lineno", 0),
                    "E0-TRANSPORT",
                    f"reaches the network client {name!r}",
                )
            )
    return violations


def _dotted_callee(node: ast.expr) -> str | None:
    """Render a call target as the dotted name written in the source.

    ``None`` when the target is not a plain dotted name -- a call on the result
    of another call (``threading.Thread(...).start()``), a subscript, a lambda.
    Those are violations by construction: an allowlist cannot vet an expression
    whose value is not decidable from the source text.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_callee(node.value)
        return None if base is None else f"{base}.{node.attr}"
    return None


def find_exec_send_path_violations(path: str, source: str) -> list[Violation]:
    """E0-NOSEND: what an order-lifecycle coroutine under ``exec/`` may DO.

    Two rules, and the second is the one that carries the weight:

    1. No ``await``, ``async for`` or ``async with``.
    2. No call except the ones in
       :data:`EXEC_ORDER_COROUTINE_PERMITTED_CALLEES`.

    Rule 1 alone was MEASURED to be nearly empty (see that constant's comment):
    ``self.create_task(...)``, ``asyncio.create_task(...)``, a synchronous
    ``self._send(...)`` and ``threading.Thread(...).start()`` all passed it
    clean, and each of them sends. "No order may become sendable" is a claim
    about EVERY mechanism, so the rule has to be an allowlist.
    """
    if not path.startswith(EXEC_PACKAGE_PATH_PREFIX):
        return []
    tree = ast.parse(source, filename=path)
    violations: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef):
            continue
        if node.name not in ORDER_LIFECYCLE_COROUTINES:
            continue
        for inner in ast.walk(node):
            if isinstance(inner, ast.AsyncFor | ast.AsyncWith) or (
                isinstance(inner, ast.Await) and node.name != "_submit_order"
            ):
                violations.append(
                    Violation(
                        path,
                        inner.lineno,
                        "E0-NOSEND",
                        f"{node.name}() awaits; an order path is exactly what that is",
                    )
                )
            elif isinstance(inner, ast.Call):
                callee = _dotted_callee(inner.func)
                if callee not in EXEC_ORDER_COROUTINE_PERMITTED_CALLEES:
                    violations.append(
                        Violation(
                            path,
                            inner.lineno,
                            "E0-NOSEND",
                            f"{node.name}() calls "
                            f"{callee or ast.dump(inner.func)[:48]}, which is not one of "
                            "the refusal-only callees an order path may reach",
                        )
                    )
    return violations


def find_exec_inertness_violations(path: str, source: str) -> list[Violation]:
    """E0-INERT: a module under ``exec/`` may not import a network client, and
    may not define a coroutine unless it is an async-lifecycle module.

    Three passes now, none of which alone is enough. The import pass catches
    the CAPABILITY arriving (``import httpx``, ``from
    nautilus_trader.core.nautilus_pyo3 import HttpClient``); the async pass
    catches the SHAPE that I/O arrives in, which can be written without any
    banned import at all; the name pass keeps the coroutine inventory of an
    async-permitted module closed.
    """
    tree = ast.parse(source, filename=path)
    violations: list[Violation] = []
    async_permitted = path in EXEC_ASYNC_LIFECYCLE_MODULES
    banned_prefixes = (
        NETWORK_IMPORT_PREFIXES - {"asyncio"} if async_permitted else NETWORK_IMPORT_PREFIXES
    )

    for module in _imported_module_strings(tree):
        parts = module.split(".")
        heads = {".".join(parts[: depth + 1]) for depth in range(len(parts))}
        for prefix in sorted(heads & banned_prefixes):
            violations.append(
                Violation(
                    path,
                    0,
                    "E0-INERT",
                    f"imports {module!r}, a network-capable module ({prefix})",
                )
            )

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in NATIVE_NETWORK_CLIENT_NAMES:
                    violations.append(
                        Violation(
                            path,
                            node.lineno,
                            "E0-INERT",
                            f"imports the native network client {alias.name!r}",
                        )
                    )
        elif isinstance(node, ast.AsyncFunctionDef):
            if not async_permitted:
                violations.append(
                    Violation(
                        path,
                        node.lineno,
                        "E0-INERT",
                        f"defines the coroutine {node.name!r}; this slice is read/map only",
                    )
                )
            elif node.name not in EXEC_PERMITTED_COROUTINE_NAMES:
                violations.append(
                    Violation(
                        path,
                        node.lineno,
                        "E0-INERT",
                        f"defines the coroutine {node.name!r}, which is not a "
                        "declared execution-client lifecycle method",
                    )
                )
        elif isinstance(node, (ast.Await, ast.AsyncFor, ast.AsyncWith)) and not async_permitted:
            violations.append(
                Violation(path, node.lineno, "E0-INERT", "carries async control flow")
            )

    violations.extend(find_exec_transport_violations(path, source))
    violations.extend(find_exec_send_path_violations(path, source))
    return violations


def scan_exec_module_inertness(
    roots: tuple[str, ...] = EGRESS_SCAN_ROOTS,
) -> list[Violation]:
    return [
        v
        for path, source in iter_python_sources(roots)
        if path.startswith(EXEC_PACKAGE_PATH_PREFIX)
        for v in find_exec_inertness_violations(path, source)
    ]


def test_e0_inert_no_shipped_exec_module_can_reach_the_network() -> None:
    """The live barrier."""
    violations = scan_exec_module_inertness()
    assert violations == [], "E0-INERT violations:\n" + "\n".join(str(v) for v in violations)


def test_e0_inert_the_live_scan_actually_reaches_the_exec_package() -> None:
    """Non-vacuity of the SCAN's reach, in X3's shape and for X3's reason."""
    scanned = {
        path
        for path, _ in iter_python_sources(EGRESS_SCAN_ROOTS)
        if path.startswith(EXEC_PACKAGE_PATH_PREFIX)
    }
    assert scanned == {
        "src/breezy/adapters/polymarket_us/exec/__init__.py",
        "src/breezy/adapters/polymarket_us/exec/client.py",
        "src/breezy/adapters/polymarket_us/exec/endpoints.py",
        # EXEC SPINE R-6d: the transient/durable refusal classifier. Pure,
        # stdlib-only, and under `exec/` because that is where the venue's
        # error payloads are parsed -- WIDENED, not relaxed: the comparison
        # stays `==` and the new module is brought INSIDE both scans.
        "src/breezy/adapters/polymarket_us/exec/refusals.py",
        "src/breezy/adapters/polymarket_us/exec/reports.py",
        "src/breezy/adapters/polymarket_us/exec/submit_chain.py",
    }


#: The path every E0-INERT detector proof plants against.
#:
#: It is deliberately NOT ``client.py``. Before R-4 these proofs used the
#: client's own path, which after the async narrowing would have made three of
#: them assert that a permitted module is permitted -- a detector proving
#: nothing, which is the exact defect ``test_cage_rule_constants_are_pinned``
#: exists to catch one level up. A module NOT in
#: ``EXEC_ASYNC_LIFECYCLE_MODULES`` keeps them measuring the unnarrowed rule.
_PLANTED_INERT_PATH = f"{EXEC_PACKAGE_PATH_PREFIX}planted_not_the_client.py"


def test_the_planted_inert_path_is_not_an_async_permitted_module() -> None:
    """The proofs above are worth nothing if the path they plant on is exempt."""
    assert _PLANTED_INERT_PATH not in EXEC_ASYNC_LIFECYCLE_MODULES
    assert _PLANTED_INERT_PATH.startswith(EXEC_PACKAGE_PATH_PREFIX)


@pytest.mark.parametrize(
    "statement",
    [
        "import httpx",
        "import socket",
        "import asyncio",
        "from urllib.request import urlopen",
        "import http.client",
        "from nautilus_trader.core.nautilus_pyo3 import HttpClient",
    ],
)
def test_e0_inert_detects_each_network_capable_import(statement: str) -> None:
    source = f'"""Docstring."""\n\n{statement}\n'
    violations = find_exec_inertness_violations(_PLANTED_INERT_PATH, source)
    assert [v.rule for v in violations][:1] == ["E0-INERT"]


def test_e0_inert_detects_a_coroutine_definition() -> None:
    source = '"""Docstring."""\n\n\nasync def read(path):\n    return path\n'
    violations = find_exec_inertness_violations(_PLANTED_INERT_PATH, source)
    assert [v.rule for v in violations] == ["E0-INERT"]
    assert "coroutine" in violations[0].detail


def test_e0_inert_detects_async_control_flow_without_a_banned_import() -> None:
    """An ``await`` needs no import at all, which is why the second pass exists."""
    source = (
        '"""Docstring."""\n'
        "\n"
        "\n"
        "def outer(send):\n"
        "    async def inner():\n"
        "        async with send() as response:\n"
        "            return await response\n"
        "\n"
        "    return inner\n"
    )
    rules = {v.rule for v in find_exec_inertness_violations("src/breezy/x/exec/c.py", source)}
    assert rules == {"E0-INERT"}


def test_e0_inert_does_not_fire_on_the_shipped_read_only_idiom() -> None:
    """Control: the pure-mapping shape R-3 actually ships must stay legal."""
    source = (
        '"""Docstring."""\n'
        "\n"
        "import json\n"
        "from decimal import Decimal\n"
        "\n"
        "from nautilus_trader.model.objects import Money\n"
        "\n"
        "\n"
        "def decode(body):\n"
        "    return json.loads(body, parse_float=Decimal)\n"
    )
    assert find_exec_inertness_violations(f"{EXEC_PACKAGE_PATH_PREFIX}endpoints.py", source) == []


def test_e0_inert_is_scoped_to_the_exec_package() -> None:
    """``transport.py`` legitimately holds the venue HTTP client. This rule is
    a prohibition under ``exec/`` only, exactly like X3."""
    scanned = {path for path, _ in iter_python_sources(EGRESS_SCAN_ROOTS)}
    assert "src/breezy/adapters/polymarket_us/transport.py" in scanned
    assert [v.path for v in scan_exec_module_inertness()] == []


# ==========================================================================
# The R-4 NARROWING, and the three strengthenings that pay for it
# ==========================================================================
#
# What was narrowed, stated plainly so it cannot be read as a deletion:
# E0-INERT banned `async def`, `await` and `import asyncio` under `exec/`
# outright. A `LiveExecutionClient` cannot honour that -- Nautilus declares
# `_connect`, `_disconnect` and all six order coroutines as `async def`
# (`live/execution_client.py:598-633`) and drives them through `create_task`
# (`:246-256`). Nautilus is immutable, so the alternatives were: reimplement
# the lifecycle synchronously (a fork of the framework in all but name), move
# the client OUT of `exec/` (evading the classification by relocation, which
# is worse than narrowing it), or narrow precisely and pay for it. This is the
# third.
#
# The narrowing is exactly: for the modules in `EXEC_ASYNC_LIFECYCLE_MODULES`,
# and ONLY those, the async passes are skipped and `asyncio` is removed from
# the banned import prefixes. Every other banned prefix, and every other rule,
# applies unchanged.
#
# Paid for by three rules that did not exist before, each strictly additive:
#
#   1. EXEC_PERMITTED_COROUTINE_NAMES -- an async-permitted module's coroutine
#      INVENTORY is closed. Before R-4 there was no such rule because there
#      were no coroutines to inventory.
#   2. E0-TRANSPORT -- no module under `exec/` may reach a Breezy network
#      client. This closes a hole OLDER than the narrowing: E0-INERT's prefix
#      list is stdlib and third-party only, so `from
#      breezy.adapters.polymarket_us.http import PolymarketUSHttpClient`
#      matched nothing at all.
#   3. E0-NOSEND -- an order-lifecycle coroutine may call ONLY the refusal
#      callees on `EXEC_ORDER_COROUTINE_PERMITTED_CALLEES`, and may not
#      `await`. "No order may become sendable" stops being prose a reviewer
#      must re-check and becomes a scan. It is an ALLOWLIST because the
#      `await`-only form it replaces passed four measured send shapes clean.


def test_the_async_narrowing_names_exactly_one_module_and_it_exists() -> None:
    """A narrowing that grew a second member without a reviewer noticing would
    be indistinguishable from a deletion of the rule."""
    assert EXEC_ASYNC_LIFECYCLE_MODULES == frozenset(
        {"src/breezy/adapters/polymarket_us/exec/client.py"},
    )
    for relative in EXEC_ASYNC_LIFECYCLE_MODULES:
        assert (REPO_ROOT / relative).is_file(), f"{relative} names no file"
        assert relative.startswith(EXEC_PACKAGE_PATH_PREFIX)


def test_the_narrowing_is_scoped_a_second_exec_module_still_may_not_await() -> None:
    """Non-vacuity of the narrowing's SCOPE: it is a path allowlist, not an
    exemption for the package."""
    source = '"""Docstring."""\n\n\nasync def fetch(read):\n    return await read()\n'
    permitted = find_exec_inertness_violations(
        "src/breezy/adapters/polymarket_us/exec/client.py",
        source,
    )
    assert [v.rule for v in permitted] == ["E0-INERT"]  # only the NAME rule fires
    assert "not a declared execution-client lifecycle method" in permitted[0].detail

    neighbour = find_exec_inertness_violations(_PLANTED_INERT_PATH, source)
    assert {v.rule for v in neighbour} == {"E0-INERT"}
    assert any("coroutine" in v.detail for v in neighbour)
    assert any("async control flow" in v.detail for v in neighbour)


def test_the_async_permitted_module_still_may_not_import_a_network_client() -> None:
    """Only ``asyncio`` was removed from the prefix ban, and only here."""
    for statement in (
        "import httpx",
        "import socket",
        "from nautilus_trader.core.nautilus_pyo3 import HttpClient",
    ):
        source = f'"""Docstring."""\n\n{statement}\n'
        violations = find_exec_inertness_violations(
            "src/breezy/adapters/polymarket_us/exec/client.py",
            source,
        )
        assert violations != [], statement


def test_the_shipped_exec_coroutines_are_EXACTLY_the_declared_inventory() -> None:
    """The live barrier for strengthening 1, as an EQUALITY.

    ``defined <= EXEC_PERMITTED_COROUTINE_NAMES`` was a subset, and a subset
    check is satisfied by DELETION as well as by conformance: dropping
    ``_query_account`` -- which ``live/execution_client.py:332`` calls with
    nothing defining it in the base, so its absence makes the ``QueryAccount``
    path raise ``AttributeError`` -- would have passed silently. The declared
    inventory is now accounted for name by name.
    """
    scanned = 0
    for path, source in iter_python_sources(EGRESS_SCAN_ROOTS):
        if path not in EXEC_ASYNC_LIFECYCLE_MODULES:
            continue
        scanned += 1
        defined = {
            node.name
            for node in ast.walk(ast.parse(source, filename=path))
            if isinstance(node, ast.AsyncFunctionDef)
        }
        assert defined | EXEC_DECLARED_UNIMPLEMENTED_COROUTINES == (
            EXEC_PERMITTED_COROUTINE_NAMES
        ), {
            "undeclared": sorted(defined - EXEC_PERMITTED_COROUTINE_NAMES),
            "missing": sorted(
                EXEC_PERMITTED_COROUTINE_NAMES - defined - EXEC_DECLARED_UNIMPLEMENTED_COROUTINES,
            ),
        }
        assert not (defined & EXEC_DECLARED_UNIMPLEMENTED_COROUTINES), (
            "a coroutine declared UNIMPLEMENTED is implemented; move it out of "
            "EXEC_DECLARED_UNIMPLEMENTED_COROUTINES in this commit"
        )
    assert scanned == len(EXEC_ASYNC_LIFECYCLE_MODULES)


def test_the_unimplemented_declaration_cannot_hide_a_deleted_coroutine() -> None:
    """Non-vacuity of the equality: the escape hatch is itself accounted for.

    Every name declared unimplemented must be a name the permitted inventory
    contains, or the set would be a place to park anything.
    """
    assert EXEC_DECLARED_UNIMPLEMENTED_COROUTINES < EXEC_PERMITTED_COROUTINE_NAMES
    assert "_submit_order" not in EXEC_DECLARED_UNIMPLEMENTED_COROUTINES


def test_the_coroutine_inventory_rule_detects_a_new_name() -> None:
    """Non-vacuity of strengthening 1: a plausible I/O coroutine is refused."""
    source = '"""Docstring."""\n\n\nasync def _send(payload):\n    return payload\n'
    violations = find_exec_inertness_violations(
        "src/breezy/adapters/polymarket_us/exec/client.py",
        source,
    )
    assert [v.rule for v in violations] == ["E0-INERT"]
    assert "_send" in violations[0].detail


@pytest.mark.parametrize(
    "statement",
    [
        "from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient",
        "import breezy.adapters.polymarket_us.http",
        "from breezy.adapters.polymarket_us.websocket import PolymarketUSMarketsWebSocketPool",
        "from breezy.adapters.polymarket_us.transport import NautilusHttpTransport",
        "from breezy.runtime.health import WebhookAlertSink",
        "from breezy.ingest.http import something",
    ],
)
def test_e0_transport_detects_every_breezy_route_to_a_socket(statement: str) -> None:
    """Non-vacuity of strengthening 2, on the async-PERMITTED module -- the one
    the narrowing could otherwise have opened up."""
    source = f'"""Docstring."""\n\n{statement}\n'
    violations = find_exec_transport_violations(
        "src/breezy/adapters/polymarket_us/exec/client.py",
        source,
    )
    assert [v.rule for v in violations][:1] == ["E0-TRANSPORT"], statement


def test_e0_transport_closes_a_hole_the_original_inertness_rule_never_saw() -> None:
    """The measured justification for strengthening 2, not an assertion of it.

    Run the PRE-R-4 rule -- imports and async shape only -- over a module that
    imports the venue HTTP client. It reports nothing: the class is reached
    through a Breezy module, and no Breezy module was ever in
    ``NETWORK_IMPORT_PREFIXES``. That is the hole, and it predates the
    narrowing this rule pays for.
    """
    source = (
        '"""Docstring."""\n'
        "\n"
        "from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient\n"
        "\n"
        "\n"
        "def build(transport, signer):\n"
        "    return PolymarketUSHttpClient(transport=transport, signer=signer)\n"
    )
    tree = ast.parse(source)
    prefix_hits = [
        module
        for module in _imported_module_strings(tree)
        if {".".join(module.split(".")[: d + 1]) for d in range(len(module.split(".")))}
        & NETWORK_IMPORT_PREFIXES
    ]
    assert prefix_hits == []  # the ORIGINAL rule sees nothing
    assert find_exec_transport_violations(_PLANTED_INERT_PATH, source) != []


def test_e0_transport_does_not_fire_on_the_shipped_quota_key_import() -> None:
    """Control: ``exec/endpoints.py`` imports a quota-key CONSTANT from
    ``transport``. A constant is not a socket, and banning the module
    wholesale would have forced a shipped, harmless import to be rewritten to
    suit a barrier."""
    source = (
        '"""Docstring."""\n'
        "\n"
        "from breezy.adapters.polymarket_us.transport import QUOTA_KEY_PORTFOLIO\n"
    )
    assert find_exec_transport_violations(_PLANTED_INERT_PATH, source) == []


def test_no_shipped_exec_order_coroutine_awaits_anything() -> None:
    """The live barrier for strengthening 3: R-4 cannot send, mechanically."""
    violations = [
        v
        for path, source in iter_python_sources(EGRESS_SCAN_ROOTS)
        for v in find_exec_send_path_violations(path, source)
    ]
    assert violations == [], "E0-NOSEND violations:\n" + "\n".join(str(v) for v in violations)


def test_e0_nosend_scan_actually_reaches_the_six_order_coroutines() -> None:
    """A rule that reaches nothing reports nothing -- X3's lesson, applied.

    The six coroutines must be PRESENT in the shipped client, or the live
    barrier above is measuring an empty set.
    """
    source = (REPO_ROOT / "src/breezy/adapters/polymarket_us/exec/client.py").read_text()
    defined = {
        node.name for node in ast.walk(ast.parse(source)) if isinstance(node, ast.AsyncFunctionDef)
    }
    assert ORDER_LIFECYCLE_COROUTINES <= defined, sorted(ORDER_LIFECYCLE_COROUTINES - defined)


@pytest.mark.parametrize(
    "body",
    [
        "    return await send(command)\n",
        "    async with session() as s:\n        return s\n",
        "    async for chunk in stream():\n        return chunk\n",
    ],
)
def test_e0_nosend_detects_an_order_coroutine_that_reaches_out(body: str) -> None:
    """Non-vacuity of strengthening 3, in all three async shapes."""
    source = f'"""Docstring."""\n\n\nasync def _submit_order(command):\n{body}'
    violations = find_exec_send_path_violations(
        "src/breezy/adapters/polymarket_us/exec/client.py",
        source,
    )
    assert [v.rule for v in violations][:1] == ["E0-NOSEND"]


def test_e0_nosend_permits_the_denial_body_r4_actually_ships() -> None:
    """Control: a refusal that logs and denies is legal, or the rule would
    forbid the very thing it exists to protect."""
    source = (
        '"""Docstring."""\n'
        "\n"
        "\n"
        "async def _submit_order(self, command):\n"
        "    self._log.error('refused')\n"
        "    self.generate_order_denied(\n"
        "        reason='refused',\n"
        "        ts_event=self._clock.timestamp_ns(),\n"
        "    )\n"
    )
    assert (
        find_exec_send_path_violations(
            "src/breezy/adapters/polymarket_us/exec/client.py",
            source,
        )
        == []
    )


#: The four send mechanisms an ``await`` ban does NOT see. Each was RUN
#: against the pre-allowlist rule on the async-permitted module and came back
#: CLEAN; each of them can put an order on the wire.
_AWAIT_FREE_SEND_SHAPES: tuple[tuple[str, str], ...] = (
    (
        "native create_task",
        # `live/execution_client.py:246-256` drives the lifecycle through
        # exactly this, and the narrowing's own docstring cites it.
        "    self.create_task(self._private_read('/x'))\n",
    ),
    ("asyncio create_task", "    asyncio.create_task(self._private_read('/x'))\n"),
    ("a synchronous hop", "    self._send(command)\n"),
    ("a thread", "    threading.Thread(target=self._send, args=(command,)).start()\n"),
)


@pytest.mark.parametrize(
    ("label", "body"),
    _AWAIT_FREE_SEND_SHAPES,
    ids=[label for label, _ in _AWAIT_FREE_SEND_SHAPES],
)
def test_e0_nosend_detects_the_send_shapes_that_carry_no_await(
    label: str,
    body: str,
) -> None:
    """The measured justification for the allowlist, as four live RED proofs.

    Under the ``await``-only rule every one of these returned ``[]`` on
    ``exec/client.py`` -- the async-PERMITTED module, where it matters most.
    """
    source = f'"""Docstring."""\n\n\nasync def _submit_order(self, command):\n{body}'
    violations = find_exec_send_path_violations(
        "src/breezy/adapters/polymarket_us/exec/client.py",
        source,
    )
    assert [v.rule for v in violations][:1] == ["E0-NOSEND"], label
    assert not any(isinstance(n, ast.Await) for n in ast.walk(ast.parse(source))), (
        f"{label} must contain NO await, or it proves nothing about the new rule"
    )


def test_e0_nosend_detects_a_call_on_the_result_of_a_call() -> None:
    """A callee this rule cannot NAME is refused, never waved through: the
    allowlist is only sound if an unrenderable target is a violation."""
    source = (
        '"""Docstring."""\n'
        "\n"
        "\n"
        "async def _cancel_order(self, command):\n"
        "    self._transport()(command)\n"
    )
    violations = find_exec_send_path_violations(
        "src/breezy/adapters/polymarket_us/exec/client.py",
        source,
    )
    assert [v.rule for v in violations][:1] == ["E0-NOSEND"]


def test_the_order_coroutine_callee_allowlist_reaches_no_venue() -> None:
    """The allowlist is the rule's whole surface, so it is read here too.

    Every entry is either a log, a native event generator that publishes on
    the message bus, a read of local state, a pure `submit_chain` helper, or
    the R-7 chokepoint (permit, ledger, latch, signer, the ONE sanctioned
    sender call). Nothing else on it takes a path, a payload or a socket.

    Set EQUALITY, not membership: R-7 widens this allowlist from R-4's eight
    entries, and equality is what keeps a NINTH widening from landing
    silently -- exactly the shape `test_cage_rule_constants_are_pinned.py`
    already enforces on `BARRED_CALLEES`. And the keyword ban below is
    restored alongside it, unweakened: every entry is still checked for
    "read"/"send"/"post"/"request", and `self._order_sender.post_order` is
    the ONLY exemption -- the one sanctioned egress call this whole firewall
    exists to fence. `submit_chain.order_fingerprint_bytes` is named, not
    `..._request_fingerprint_bytes`, precisely so a PURE hashing helper never
    needs a second exemption from a ban that means "no I/O verb here".
    """
    assert EXEC_ORDER_COROUTINE_PERMITTED_CALLEES == frozenset(
        {
            "self._log.error",
            "self._log.warning",
            "self.generate_order_denied",
            "self.generate_order_cancel_rejected",
            "self.generate_order_submitted",
            "self.generate_order_rejected",
            "self.generate_order_filled",
            "self.generate_order_canceled",
            "self._cache.account_for_venue",
            "self._cache.instrument",
            "self._clock.timestamp_ns",
            "self._refuse",
            "self._deny",
            "self._retire",
            "self._generate_submitted",
            "self._unsupported",
            "NotImplementedError",
            "assert_live_order_submission_permitted",
            "self._ledger.authorize_order_cost",
            "self._ledger.release_booking",
            "self._ledger.true_up_booking",
            "self._latch.arm",
            "self._latch.retire",
            "self._write_signer.sign_headers",
            "self._order_sender.post_order",
            "submit_chain.latched_refusal_reason",
            "submit_chain.missing_account_reason",
            "submit_chain.permit_is_missing",
            "submit_chain.order_notional_usd",
            "submit_chain.order_fingerprint_bytes",
            "submit_chain.unmappable_order_reason",
            "submit_chain.build_order_body",
            "submit_chain.encode_order_body",
            "submit_chain.order_price_decimal",
            "submit_chain.order_quantity_decimal",
            "submit_chain.intent_fingerprint",
            "submit_chain.is_latch_arm_refusal",
            "submit_chain.is_cancelled",
            "submit_chain.classify_create_order_outcome",
            "submit_chain.retirement_member",
            "submit_chain.venue_order_id",
        }
    )
    for callee in EXEC_ORDER_COROUTINE_PERMITTED_CALLEES:
        assert "create_task" not in callee
        for banned_word in ("read", "send", "post", "request"):
            if banned_word in callee:
                assert callee == "self._order_sender.post_order", (
                    f"{callee!r} contains the banned keyword {banned_word!r} and "
                    "is not the one sanctioned egress call"
                )


# ==========================================================================
# X1 non-vacuity -- the live marker scan must actually reach an exec test
# ==========================================================================
#
# X1's live scan passed identically whether or not ANY shipped test imported
# ``exec/``: a rule that reaches nothing reports nothing. X3's live scan ships
# a companion pin for exactly this reason (``test_x3_the_live_scan_actually_
# reaches_the_exec_package``); X1's did not, so its non-vacuity rested on an
# unpinned test filename and a rename would have re-vacuumed it in silence.


def exec_importing_test_modules(roots: tuple[str, ...] = TEST_SCAN_ROOTS) -> set[str]:
    """Every scanned test module that X1's rule can actually fire on."""
    return {
        path
        for path, source in iter_python_sources(roots)
        if _imports_exec_package(ast.parse(source, filename=path))
    }


def test_x1_the_live_scan_actually_reaches_a_test_that_imports_the_exec_package() -> None:
    """Set EQUALITY, in X3's shape: a rename cannot re-vacuum the scan, and a
    new exec test cannot appear without a reviewer seeing it here.

    EXEC SPINE W adds two: `test_polymarket_us_factories.py` now imports
    `PolymarketUSExecutionClient` to assert the factory's return type, and
    `test_exec_client_wiring_contract.py` drives a real node built with a
    real `PolymarketUSExecutionClient`. Neither carries any of
    `SOCKET_RESTORING_MARKERS` -- both stub the transport, exactly like the
    data-side suite already does.

    R-6c adds one: `test_exec_refusal_health_surface.py` imports
    `exec.endpoints` and drives the real client through `_connect` to prove a
    refusal degrades the component. WIDENED, not relaxed (L-6/L-12): the
    comparison is still `==`, and the effect of this row is to bring that
    module INSIDE X1's rule, which it satisfies -- it carries no marker at
    all, and its whole point is that `_refuse` is a LOCAL latch reachable with
    no socket. Note for the next increment: this equality fires on any new
    TEST that imports `exec/`, independently of what the increment does to
    `src/`, so an increment whose barrier analysis covers only E0/E1/E2/E3 and
    the cage constants will miss it (L-15).

    R-6d adds one more: `test_polymarket_us_exec_refusals.py` imports
    `exec.refusals`, the transient/durable classifier. WIDENED, not relaxed,
    on the same terms: the comparison is still `==`, the module carries no
    marker at all, and it cannot want one -- the classifier is a pure
    function over an int and a byte string, so the suite never opens a
    socket and never constructs a client.
    """
    # CRH step 8 wiring adds one: `test_current_rung_hold_order_submission_
    # wiring.py` imports `PolymarketUSExecutionClient` to drive the real
    # order-submission path (`CurrentRungHoldStrategy.submit_order` -> a real
    # `RiskEngine`/`ExecutionEngine` -> the exec client) end to end. WIDENED,
    # not relaxed (L-6/L-12): it carries no `SOCKET_RESTORING_MARKERS`, same
    # as every sibling exec suite -- it stubs the transport with the shipped
    # `_FakeSender`/`_FakeSigner` (imported from
    # `test_polymarket_us_submit_order_chain.py`, never a parallel fake), so
    # it never opens a socket either.
    assert exec_importing_test_modules() == {
        "tests/contract/test_exec_client_reconciliation_contract.py",
        "tests/contract/test_exec_client_wiring_contract.py",
        "tests/unit/test_current_rung_hold_order_submission_wiring.py",
        "tests/unit/test_exec_refusal_health_surface.py",
        "tests/unit/test_polymarket_us_exec_client.py",
        "tests/unit/test_polymarket_us_exec_endpoints.py",
        "tests/unit/test_polymarket_us_exec_positions.py",
        "tests/unit/test_polymarket_us_exec_refusals.py",
        "tests/unit/test_polymarket_us_exec_reports.py",
        "tests/unit/test_polymarket_us_exec_snapshot_drift.py",
        "tests/unit/test_polymarket_us_factories.py",
        "tests/unit/test_polymarket_us_submit_order_chain.py",
    }


def test_x1_the_reach_detector_is_the_same_predicate_the_rule_uses() -> None:
    """The pin above is worth nothing if it uses a second, looser import test.

    ``_imports_exec_package`` is the SAME function ``find_exec_test_marker_
    violations`` gates on, so a module counted as reachable here is exactly a
    module X1 would inspect.
    """
    marked = _PLANTED_EXEC_TEST_WITH_MARKER
    assert _imports_exec_package(ast.parse(marked))
    assert [v.rule for v in find_exec_test_marker_violations("tests/unit/t.py", marked)] == ["X1"]

    unrelated = _PLANTED_MARKED_TEST_OUTSIDE_THE_EXEC_PACKAGE
    assert not _imports_exec_package(ast.parse(unrelated))
    assert find_exec_test_marker_violations("tests/live/t.py", unrelated) == []
