"""Repo-wide pytest fixtures.

This module is intentionally minimal: it exists to guarantee that no test in
this suite can reach the real network. Weather-settlement data is fetched
over HTTP from untrusted third parties (NWS), and a test suite that can
silently fall through to a live socket is a supply-chain risk in its own
right (flaky CI, accidental data exfiltration, accidental real requests to
a rate-limited government API).

``respx`` (used to mock ``httpx`` traffic) does NOT need real sockets — it
intercepts requests at the transport layer — so this fixture does not
conflict with respx-based tests.

Opt-out: mark an individual test with ``@pytest.mark.allow_socket`` if it
genuinely needs a real socket (e.g. a loopback-only integration test).

``@pytest.mark.live`` (``tests/live/``) is the OTHER opt-out. Those tests
perform real network I/O against ``api.weather.gov`` by design, so a
``live``-marked test is exempted from the socket block exactly like an
``allow_socket``-marked one -- see :func:`_block_network_sockets`. They are
additionally gated by :func:`pytest_collection_modifyitems` below: deselected
by default (``pyproject.toml``'s ``addopts`` runs ``-m 'not live'``), and
even under an explicit ``-m live`` override they SKIP with a clear reason
unless ``BREEZY_LIVE=1`` is set, so a live test can never silently attempt
real network I/O from a job that merely overrode ``-m``.
"""

from __future__ import annotations

import os
import socket
import sys
from collections.abc import Iterator, Mapping
from typing import Any, cast

import pytest

_BLOCKED_MESSAGE = (
    "Network access is disabled in this test suite. "
    "If this test genuinely needs a real socket, mark it with "
    "@pytest.mark.allow_socket."
)

_LIVE_ENV_VAR = "BREEZY_LIVE"
VENUE_LIVE_ENV_VAR = "BREEZY_VENUE_LIVE"
_VENUE_LIVE_ENV_VAR = VENUE_LIVE_ENV_VAR
_REAL_MONEY_ENV_VAR = "BREEZY_REAL_MONEY"

#: Second, distinctly-named confirmation for a credentialed session. On its
#: own it unlocks NOTHING -- the marker gate still deselects/skips
#: ``venue_live`` -- so it cannot do the double duty that made revision 1's
#: single ``BREEZY_VENUE_LIVE`` gate unsafe.
ALLOW_CREDENTIALED_PYTEST_ENV_VAR = "BREEZY_ALLOW_CREDENTIALED_PYTEST"

#: Third factor. A command-line flag is the one confirmation a stray line in
#: a shell profile, a CI environment block, or an IDE run configuration's
#: env-var pane cannot supply.
VENUE_LIVE_CLI_FLAG = "--venue-live"
_TEST_USER_AGENT = "breezy-test/1.0 (+mailto:ops@example.com)"
POLYMARKET_CREDENTIAL_ENV_VARS = (
    "POLYMARKET_US_KEY_ID",
    "POLYMARKET_US_ACCESS_KEY",
    "POLYMARKET_US_API_KEY",
    "POLYMARKET_US_SECRET_KEY",
    "POLYMARKET_US_SECRET_KEY_FILE",
    "POLYMARKET_API_KEY",
    "POLYMARKET_API_SECRET",
    "POLYMARKET_PASSPHRASE",
    "POLYMARKET_PK",
    "POLYMARKET_FUNDER",
    "PM_ACCESS_KEY",
    "PM_SECRET_KEY",
)
PYO3_EGRESS_GAP = (
    "The Python socket monkeypatch blocks Python-level network calls and the "
    "test fixture replaces nautilus_pyo3 HttpClient/WebSocketClient constructors, "
    "but it cannot prove that every future Rust-side socket path is blocked after "
    "a client object is obtained before the fixture runs. Close that remaining "
    "process-level gap by running pytest in an OS network namespace."
)
OS_EGRESS_BLOCK_COMMAND = (
    "unshare -r -n env BREEZY_TEST_OS_EGRESS_BLOCK=1 .venv/bin/python -m pytest"
)
_PYO3_NETWORK_CLIENT_NAMES = ("HttpClient", "WebSocketClient")
_ORIGINAL_PYO3_NETWORK_CLIENTS: dict[str, Any] | None = None


class _BlockedPyo3NetworkClient:
    """Sentinel replacing pyo3 network clients in ordinary tests."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError(
            "Network access is disabled in this test suite: "
            "nautilus_pyo3.HttpClient/WebSocketClient are blocked by default."
        )


def _pyo3_module() -> Any | None:
    try:
        from nautilus_trader.core import nautilus_pyo3
    except ImportError:
        return None
    return nautilus_pyo3


def _set_imported_breezy_pyo3_aliases(*, web_socket_client: Any) -> None:
    websocket_module = sys.modules.get("breezy.adapters.polymarket_us.websocket")
    if websocket_module is not None:
        cast(Any, websocket_module).WebSocketClient = web_socket_client


def _install_pyo3_network_client_block() -> None:
    """Deny pyo3 network-client construction before test modules can alias it.

    Residual limit: this is an in-process constructor block, not a kernel
    firewall. It blocks the known Nautilus pyo3 HTTP/WebSocket construction
    paths while preserving per-test loopback opt-outs; arbitrary future native
    extensions could still call OS networking unless pytest is launched inside
    an external network namespace or CI firewall.
    """
    module = _pyo3_module()
    if module is None:
        return

    global _ORIGINAL_PYO3_NETWORK_CLIENTS
    if _ORIGINAL_PYO3_NETWORK_CLIENTS is None:
        _ORIGINAL_PYO3_NETWORK_CLIENTS = {
            name: getattr(module, name)
            for name in _PYO3_NETWORK_CLIENT_NAMES
            if hasattr(module, name)
        }

    for name in _ORIGINAL_PYO3_NETWORK_CLIENTS:
        setattr(module, name, _BlockedPyo3NetworkClient)
    _set_imported_breezy_pyo3_aliases(web_socket_client=_BlockedPyo3NetworkClient)


def _restore_pyo3_network_clients_for_opted_out_test() -> None:
    module = _pyo3_module()
    if module is None or _ORIGINAL_PYO3_NETWORK_CLIENTS is None:
        return

    for name, original in _ORIGINAL_PYO3_NETWORK_CLIENTS.items():
        setattr(module, name, original)
    web_socket_client = _ORIGINAL_PYO3_NETWORK_CLIENTS.get("WebSocketClient")
    if web_socket_client is not None:
        _set_imported_breezy_pyo3_aliases(web_socket_client=web_socket_client)


def missing_venue_live_unlocks(*, env: Mapping[str, str], venue_live_flag: bool) -> tuple[str, ...]:
    """Return the names of the venue-live unlocks that are NOT satisfied.

    An empty tuple means all three are present and a credentialed session may
    proceed. Each factor is named after what it authorises, and no single one
    both silences the credential abort and unlocks execution:

    * ``BREEZY_VENUE_LIVE`` also gates whether ``venue_live`` tests RUN, so it
      cannot silently pre-authorise a credentialed session by itself;
    * ``BREEZY_ALLOW_CREDENTIALED_PYTEST`` authorises credentials in the
      process but selects no tests;
    * ``--venue-live`` must be typed into the invocation.

    Only the exact string ``"1"`` counts. ``true``/``yes``/``on`` are
    deliberately rejected so a half-remembered convention cannot unlock a
    real-credential session.
    """
    missing: list[str] = []
    if env.get(VENUE_LIVE_ENV_VAR) != "1":
        missing.append(VENUE_LIVE_ENV_VAR)
    if env.get(ALLOW_CREDENTIALED_PYTEST_ENV_VAR) != "1":
        missing.append(ALLOW_CREDENTIALED_PYTEST_ENV_VAR)
    if not venue_live_flag:
        missing.append(VENUE_LIVE_CLI_FLAG)
    return tuple(missing)


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the third D2 unlock as an explicit command-line flag."""
    parser.addoption(
        VENUE_LIVE_CLI_FLAG,
        action="store_true",
        default=False,
        help=(
            "Acknowledge that this session may hold real venue credentials and "
            "run venue_live tests. Required IN ADDITION to "
            f"{VENUE_LIVE_ENV_VAR}=1 and {ALLOW_CREDENTIALED_PYTEST_ENV_VAR}=1."
        ),
    )


def pytest_configure(config: pytest.Config) -> None:
    """Register the opt-out markers so --strict-markers accepts them.

    ``live`` is already declared in ``pyproject.toml``'s ``markers`` list --
    declared again here is harmless (pytest merges the two) and keeps this
    file self-describing for anyone who reads it without the toml alongside.
    """
    config.addinivalue_line(
        "markers",
        "allow_socket: permit this test to open real network sockets "
        "(bypasses the autouse network-blocking fixture)",
    )
    config.addinivalue_line(
        "markers",
        "live: performs REAL network I/O against api.weather.gov and needs "
        f"{_LIVE_ENV_VAR}=1; deselected by default",
    )
    config.addinivalue_line(
        "markers",
        "venue_live: test performs real authenticated calls against the live "
        "Polymarket.us venue; gated behind BREEZY_VENUE_LIVE=1 AND "
        "BREEZY_ALLOW_CREDENTIALED_PYTEST=1 AND --venue-live",
    )
    config.addinivalue_line(
        "markers",
        "real_money: can place or affect real-money venue orders and needs "
        f"{_REAL_MONEY_ENV_VAR}=1 plus operator approval; deselected by default",
    )
    _install_pyo3_network_client_block()


def pytest_sessionstart(session: pytest.Session) -> None:
    present = sorted(name for name in POLYMARKET_CREDENTIAL_ENV_VARS if os.environ.get(name))
    if not present:
        return

    missing = missing_venue_live_unlocks(
        env=os.environ,
        venue_live_flag=bool(session.config.getoption(VENUE_LIVE_CLI_FLAG)),
    )
    if missing:
        pytest.exit(
            "Polymarket credential environment variable(s) present during pytest: "
            + ", ".join(present)
            + ". Remove credentials from the pytest process; tests must not run on a "
            "credentialed host environment. To run the gated venue_live suite "
            "deliberately, supply the missing unlock(s): " + ", ".join(missing) + ".",
            returncode=2,
        )

    # Names only -- never values. `present` is a list of environment variable
    # NAMES built by membership test above; no value is read here.
    print(
        "[breezy] credentialed pytest session explicitly unlocked "
        f"({VENUE_LIVE_ENV_VAR}, {ALLOW_CREDENTIALED_PYTEST_ENV_VAR}, "
        f"{VENUE_LIVE_CLI_FLAG}); credential variables present: " + ", ".join(present)
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip every ``live``-marked test unless ``BREEZY_LIVE=1`` is set.

    The default ``addopts`` (``-m 'not live'``) already keeps these OUT of an
    ordinary run via deselection, which is silent by design (deselected tests
    do not appear as skipped). This hook covers the other path: an explicit
    ``-m live`` invocation bypasses that default marker expression entirely,
    and without this hook a bare ``pytest -m live`` would attempt real network
    I/O unconditionally. Gating on the env var here, in the SAME place the
    marker itself is enforced, means there is exactly one place a live test's
    run/skip decision is made.
    """
    if os.environ.get(_LIVE_ENV_VAR) == "1":
        skip_live = None
    else:
        skip_live = pytest.mark.skip(
            reason=(
                f"live test requires real network I/O against api.weather.gov; "
                f"set {_LIVE_ENV_VAR}=1 to run it"
            )
        )
    skip_venue_live = None
    venue_live_missing = missing_venue_live_unlocks(
        env=os.environ,
        venue_live_flag=bool(config.getoption(VENUE_LIVE_CLI_FLAG)),
    )
    if venue_live_missing:
        skip_venue_live = pytest.mark.skip(
            reason=(
                "venue_live test requires real network I/O against a prediction venue; "
                "missing unlock(s): " + ", ".join(venue_live_missing)
            )
        )
    skip_real_money = None
    if os.environ.get(_REAL_MONEY_ENV_VAR) != "1":
        skip_real_money = pytest.mark.skip(
            reason=(
                "real_money test can place or affect real-money venue orders; "
                f"set {_REAL_MONEY_ENV_VAR}=1 only with explicit operator approval"
            )
        )
    for item in items:
        if skip_live is not None and item.get_closest_marker("live") is not None:
            item.add_marker(skip_live)
        if skip_venue_live is not None and item.get_closest_marker("venue_live") is not None:
            item.add_marker(skip_venue_live)
        if skip_real_money is not None and item.get_closest_marker("real_money") is not None:
            item.add_marker(skip_real_money)


def _is_real_network_test(request: pytest.FixtureRequest) -> bool:
    return (
        request.node.get_closest_marker("allow_socket") is not None
        or request.node.get_closest_marker("live") is not None
        or request.node.get_closest_marker("venue_live") is not None
        or request.node.get_closest_marker("real_money") is not None
    )


def _blocked_connect(self: socket.socket, *args: Any, **kwargs: Any) -> None:
    raise RuntimeError(_BLOCKED_MESSAGE)


def _blocked_connect_ex(self: socket.socket, *args: Any, **kwargs: Any) -> int:
    raise RuntimeError(_BLOCKED_MESSAGE)


@pytest.fixture(autouse=True)
def _default_breezy_user_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BREEZY_USER_AGENT", _TEST_USER_AGENT)


@pytest.fixture(autouse=True)
def _scrub_venue_credentials(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Remove venue credentials from the environment of every ordinary test.

    Plan D2 point 3. `pytest_sessionstart` can be deliberately exempted so the
    gated `venue_live` suite can run; this fixture makes that exemption
    *narrow*. Inside such a session, every test NOT marked `venue_live` or
    `real_money` still observes an empty credential environment, so a unit
    test that calls the credential loader raises instead of silently picking
    up a real key and signing something.

    `monkeypatch.delenv` restores the original values at teardown, so the
    gated tests that legitimately need them are unaffected.
    """
    if (
        request.node.get_closest_marker("venue_live") is not None
        or request.node.get_closest_marker("real_money") is not None
    ):
        return
    for name in POLYMARKET_CREDENTIAL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture(autouse=True)
def _block_network_sockets(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> Iterator[None]:
    """Block real socket connections for every test unless opted out.

    Patches ``socket.socket.connect``/``connect_ex`` rather than the socket
    constructor, so socket *objects* can still be created (some libraries
    construct sockets for introspection without connecting), but any attempt
    to actually reach a peer raises immediately.
    """
    if _is_real_network_test(request):
        # `live` tests are real-network-by-design (`tests/live/`); gating
        # whether they RUN AT ALL is `pytest_collection_modifyitems`'s job.
        _restore_pyo3_network_clients_for_opted_out_test()
        try:
            yield
        finally:
            _install_pyo3_network_client_block()
        return

    _install_pyo3_network_client_block()
    monkeypatch.setattr(socket.socket, "connect", _blocked_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _blocked_connect_ex)
    yield
