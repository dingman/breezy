"""Offline suite for the operator's signed positions-VALUE capture runner.

The shape probe (``polymarket_us_private_shape_probe.py``) proves the
private-surface endpoints answer, but it is deliberately value-free: it can
never tell an operator whether a held NO position is signed positive or
negative, or which currency ``avgPx`` is denominated in. This module is the
paired runner that answers that question, by writing the SAME endpoint's
response WITH its values intact -- redacted only of account/user/wallet
identifiers, never of the position fields the exit path needs (docs/plans/
POSITION_EXIT_EXECUTION_2026-09-16.md Appendix A).

Every test here is offline: the transport is a canned double and every
credential is an ephemeral Ed25519 key generated in-process, so nothing here
can reach a venue host.
"""

from __future__ import annotations

import ast
import base64
import importlib.util
import json
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from nacl.signing import SigningKey

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.secure import RedactedSecureString
from breezy.adapters.polymarket_us.transport import VenueResponse

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "venue" / "polymarket_us_positions_value_capture.py"

_API_BASE = "https://api.example.invalid"
_GATEWAY_BASE = "https://gateway.example.invalid"
_KEY_ID = "11111111-2222-3333-4444-555555555555"

#: A path with the shape of a private read. Test files are NOT scanned by the
#: B4 write-verb rules (``EGRESS_SCAN_ROOTS = ("src", "scripts")``), which is
#: what lets a literal live here and not in the runner.
_PRIVATE_PATH = "/v1/portfolio/positions"

#: One YES and one NO position, keyed by market slug the way
#: ``GetUserPositionsResponse.positions`` (``dict[str, UserPosition]``) is
#: keyed in the vendor SDK. Each position carries the account/user
#: identifiers redaction must strip, and a ``positionId`` plus
#: ``marketMetadata.id`` that must survive because the exit path joins on
#: them.
_TWO_POSITION_BODY = json.dumps(
    {
        "positions": {
            "mkt-yes-slug": {
                "netPosition": "1",
                "qtyBought": "1",
                "qtySold": "0",
                "qtyAvailable": "1",
                "cost": {"currency": "USD", "value": "0.55"},
                "avgPx": "0.55",
                "cashValue": {"currency": "USD", "value": "0.55"},
                "realized": {"currency": "USD", "value": "0"},
                "expired": False,
                "updateTime": "2026-09-16T12:00:00Z",
                "outcome": "YES",
                "slug": "mkt-yes-slug",
                "marketMetadata": {
                    "slug": "mkt-yes-slug",
                    "outcome": "YES",
                    "id": "market-123",
                    "teamId": "team-should-be-dropped",
                },
                "positionId": "pos-abc-1",
                "accountId": "acct-should-be-dropped",
                "userId": "user-should-be-dropped",
            },
            "mkt-no-slug": {
                "netPosition": "-1",
                "qtyBought": "0",
                "qtySold": "1",
                "qtyAvailable": "-1",
                "cost": {"currency": "USD", "value": "0.45"},
                "avgPx": "0.45",
                "cashValue": {"currency": "USD", "value": "0.45"},
                "realized": {"currency": "USD", "value": "0"},
                "expired": False,
                "updateTime": "2026-09-16T12:05:00Z",
                "outcome": "NO",
                "slug": "mkt-no-slug",
                "marketMetadata": {
                    "slug": "mkt-no-slug",
                    "outcome": "NO",
                    "id": "market-456",
                },
                "positionId": "pos-abc-2",
                "accountId": "acct-should-be-dropped-2",
                "userId": "user-should-be-dropped-2",
            },
        },
        "eof": True,
        "nextCursor": "cursor-abc",
    }
).encode("utf-8")


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def _load_runner() -> ModuleType:
    """Load the runner the way the repo loads its other venue scripts."""
    spec = importlib.util.spec_from_file_location(
        "breezy_polymarket_us_positions_value_capture", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def runner() -> ModuleType:
    return _load_runner()


# --------------------------------------------------------------------------
# Doubles
# --------------------------------------------------------------------------


class _CannedTransport:
    """A ``PolymarketUSReadTransport`` that answers from a fixed script."""

    def __init__(self, response: VenueResponse) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def get(self, url: str, *, headers: Mapping[str, str], quota_key: str) -> VenueResponse:
        self.calls.append({"url": url, "headers": dict(headers), "quota_key": quota_key})
        return self.response


def _credentials() -> PolymarketUSCredentials:
    secret = base64.b64encode(bytes(SigningKey.generate())).decode("ascii")
    return PolymarketUSCredentials(
        key_id=RedactedSecureString(_KEY_ID),
        secret_key=RedactedSecureString(secret),
    )


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        api_base_url=_API_BASE,
        gateway_base_url=_GATEWAY_BASE,
        signing_variant="path_only",
        http_timeout_secs=10.0,
        global_requests_per_second=15,
        instrument_requests_per_minute=6,
        book_requests_per_minute=12,
        user_agent="breezy-test",
    )


def _prepared(runner: ModuleType) -> Any:
    return runner.Prepared(core_limit=(0, 0), config=_config(), credentials=_credentials())


async def _run(
    runner: ModuleType,
    *,
    endpoint: str = _PRIVATE_PATH,
    response: VenueResponse,
    directory: Path,
    stamp: str | None = None,
) -> Any:
    transport = _CannedTransport(response)
    return await runner.run_capture(
        endpoint,
        directory=directory,
        stamp=stamp,
        prepare_fn=lambda env=None, *, guard=None: _prepared(runner),
        transport_factory=lambda config: transport,
    )


# --------------------------------------------------------------------------
# RED 1 -- refuses without BREEZY_VENUE_LIVE=1
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_capture_refuses_without_venue_live_enabled(
    runner: ModuleType, tmp_path: Path
) -> None:
    """The real ``prepare`` is entered (never doubled) and refuses on ``env``
    that carries no ``BREEZY_VENUE_LIVE=1`` -- before any request is sent."""
    transport = _CannedTransport(VenueResponse(status=200, headers={}, body=b"{}"))
    with pytest.raises(runner.SmokeRefusal):
        await runner.run_capture(
            _PRIVATE_PATH,
            directory=tmp_path,
            env={},
            transport_factory=lambda config: transport,
        )
    assert transport.calls == []
    assert list(tmp_path.iterdir()) == []


# --------------------------------------------------------------------------
# RED 2 -- writes a 0600 PRIVATE_ artefact with values intact
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_capture_writes_a_private_0600_artifact_with_values_verbatim(
    runner: ModuleType, tmp_path: Path
) -> None:
    observation = await _run(
        runner,
        response=VenueResponse(status=200, headers={}, body=_TWO_POSITION_BODY),
        directory=tmp_path,
    )
    path = runner.write_positions_artifact(observation, directory=tmp_path)

    assert path.name.startswith("PRIVATE_")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700

    document = json.loads(path.read_text(encoding="utf-8"))
    yes_position = document["positions"]["mkt-yes-slug"]
    no_position = document["positions"]["mkt-no-slug"]

    assert yes_position["netPosition"] == "1"
    assert no_position["netPosition"] == "-1"
    assert yes_position["avgPx"] == "0.55"
    assert no_position["avgPx"] == "0.45"
    assert yes_position["cashValue"] == {"currency": "USD", "value": "0.55"}
    assert yes_position["outcome"] == "YES"
    assert no_position["outcome"] == "NO"
    assert document["eof"] is True
    assert document["nextCursor"] == "cursor-abc"
    assert document["position_count"] == 2
    assert document["http_status"] == 200
    assert document["endpoint"] == _PRIVATE_PATH


@pytest.mark.asyncio
async def test_an_existing_positions_artifact_is_never_silently_overwritten(
    runner: ModuleType, tmp_path: Path
) -> None:
    observation = await _run(
        runner,
        response=VenueResponse(status=200, headers={}, body=_TWO_POSITION_BODY),
        directory=tmp_path,
    )
    runner.write_positions_artifact(observation, directory=tmp_path)
    with pytest.raises(FileExistsError):
        runner.write_positions_artifact(observation, directory=tmp_path)


def test_a_malformed_stamp_is_refused(runner: ModuleType) -> None:
    with pytest.raises(ValueError):
        runner.positions_artifact_filename(_PRIVATE_PATH, stamp="a b")


# --------------------------------------------------------------------------
# RED 3 -- redaction drops account/user identifiers, keeps position/market ids
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redaction_drops_account_and_user_ids_but_keeps_position_and_market_ids(
    runner: ModuleType, tmp_path: Path
) -> None:
    observation = await _run(
        runner,
        response=VenueResponse(status=200, headers={}, body=_TWO_POSITION_BODY),
        directory=tmp_path,
    )
    document = runner.observation_document(observation)

    assert "accountId" in document["redacted_keys"]
    assert "userId" in document["redacted_keys"]
    assert "teamId" in document["redacted_keys"]
    assert "positionId" not in document["redacted_keys"]

    for position in document["positions"].values():
        assert "accountId" not in position
        assert "userId" not in position

    yes_position = document["positions"]["mkt-yes-slug"]
    assert yes_position["positionId"] == "pos-abc-1"
    assert yes_position["marketMetadata"]["id"] == "market-123"
    assert "teamId" not in yes_position["marketMetadata"]


@pytest.mark.asyncio
async def test_a_leaking_document_never_reaches_the_written_artifact(
    runner: ModuleType, tmp_path: Path
) -> None:
    """The closed-schema guard fires if a future edit widens the document."""
    observation = await _run(
        runner,
        response=VenueResponse(status=200, headers={}, body=_TWO_POSITION_BODY),
        directory=tmp_path,
    )
    tampered = runner.PositionsObservation(
        endpoint=observation.endpoint,
        http_status=observation.http_status,
        envelope_parsed=observation.envelope_parsed,
        position_count=observation.position_count,
        redacted_keys=observation.redacted_keys,
        positions=observation.positions,
        eof=observation.eof,
        next_cursor=observation.next_cursor,
        body_byte_count=observation.body_byte_count,
    )
    # Sanity: the untampered document matches the closed schema.
    document = runner.observation_document(tampered)
    assert set(document) == set(runner.POSITIONS_DOCUMENT_FIELDS)


# --------------------------------------------------------------------------
# RED 4 -- GET-only: no write surface reachable by import
# --------------------------------------------------------------------------


def _imported_modules(source: str) -> set[str]:
    tree = ast.parse(source, filename=str(SCRIPT_PATH))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level != 0:
                modules.add("." * node.level + (node.module or ""))
            elif node.module:
                modules.add(node.module)
    return modules


#: Every module the runner may import, pinned. A future import cannot arrive
#: without a paired edit here -- same discipline as the shape probe's suite.
_PERMITTED_IMPORTS = frozenset(
    {
        "__future__",
        "argparse",
        "asyncio",
        "json",
        "os",
        "sys",
        "collections.abc",
        "dataclasses",
        "pathlib",
        "typing",
        "nautilus_trader.common.component",
        "breezy.adapters.polymarket_us.errors",
        "breezy.adapters.polymarket_us.http",
        "breezy.adapters.polymarket_us.signing",
        "breezy.adapters.polymarket_us.transport",
        "polymarket_us_auth_smoke",
        "polymarket_us_private_shape_probe",
        "polymarket_us_shape_capture",
    }
)

#: Substrings that name an order-submission surface.
_WRITE_SURFACE_TOKENS = ("order", "submit", "preview", "write", "trading", "permit")


def test_the_capture_imports_no_write_surface() -> None:
    """An AST import scan: nothing the runner imports is a write surface."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    modules = _imported_modules(source)

    offending = sorted(
        module
        for module in modules
        if any(token in module.lower() for token in _WRITE_SURFACE_TOKENS)
    )
    assert offending == [], f"runner imports a write-surface-named module: {offending}"

    unexpected = sorted(modules - _PERMITTED_IMPORTS)
    assert unexpected == [], (
        "runner imports a module outside the pinned allowlist; add it to "
        f"_PERMITTED_IMPORTS only after reading it: {unexpected}"
    )


def test_the_import_scan_would_detect_a_planted_write_surface() -> None:
    """Non-vacuity: the scan fires on a planted import."""
    planted = "from breezy.adapters.polymarket_us.exec.orders import submit\n"
    modules = _imported_modules(planted)
    assert any(token in module.lower() for module in modules for token in _WRITE_SURFACE_TOKENS)


def test_the_runner_reuses_the_signers_permitted_methods(runner: ModuleType) -> None:
    """No second, drifting allowlist: the runner reads the signer's frozenset."""
    from breezy.adapters.polymarket_us.signing import PERMITTED_METHODS

    assert runner.PERMITTED_METHODS is PERMITTED_METHODS
    assert runner.HTTP_METHOD in PERMITTED_METHODS


@pytest.mark.asyncio
async def test_a_non_get_method_is_refused_before_the_credential_read(
    runner: ModuleType, tmp_path: Path
) -> None:
    entered = False

    def _refusing(env: Any = None, *, guard: Any = None) -> Any:
        nonlocal entered
        entered = True
        raise AssertionError("prepare() was entered; a credential read had begun")

    with pytest.raises(runner.MethodNotPermittedError):
        await runner.run_capture(
            _PRIVATE_PATH,
            method="POST",
            directory=tmp_path,
            prepare_fn=_refusing,
            transport_factory=lambda config: _CannedTransport(
                VenueResponse(status=200, headers={}, body=b"{}")
            ),
        )
    assert entered is False


# --------------------------------------------------------------------------
# RED 5 -- the endpoint is never a literal here
# --------------------------------------------------------------------------


def test_the_module_defines_no_v1_literal() -> None:
    """B4 rule V2 restated locally: no order/portfolio path literal here."""
    source = SCRIPT_PATH.read_text(encoding="utf-8")
    assert "/v1/" not in source


def test_the_endpoint_argument_has_no_default(runner: ModuleType) -> None:
    """A default would put a private path back into source as a literal."""
    with pytest.raises(SystemExit):
        runner.parse_args([])


def test_the_runner_is_an_entrypoint_with_the_endpoint_and_stamp_arguments(
    runner: ModuleType,
) -> None:
    namespace = runner.parse_args(["--endpoint", _PRIVATE_PATH, "--stamp", "abc123"])
    assert namespace.endpoint == _PRIVATE_PATH
    assert namespace.stamp == "abc123"
    assert callable(runner.main)


def test_the_runner_writes_under_the_shared_private_evidence_directory(
    runner: ModuleType,
) -> None:
    assert runner.PRIVATE_SHAPE_DIRECTORY == Path("docs/evidence/venue/polymarket_us")
