"""AUT-2 r7 WP0: ``breezy.runtime.venue_positions_read``, the reviewed GET-only egress dependency.

Authority: ``docs/plans/backlog/AUTONOMY_2026-10-03/AUT-2-outcome-labeling_plan_r7.md`` WP0 and
§3.2.1 (RB-2, P8, V6). Every test is offline: the venue call is a real
:class:`PolymarketUSHttpClient` and a real signer over a fake transport, never a fake client, and
the production transport builder is never exercised here.
"""

from __future__ import annotations

import ast
import asyncio
import base64
import dataclasses
import importlib.util
import json
import re
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType
from typing import Any
from urllib.parse import parse_qs, urlsplit

import pytest
from nacl.signing import SigningKey

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.errors import CredentialSourceError
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.secure import RedactedSecureString
from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner
from breezy.adapters.polymarket_us.transport import VenueResponse
from breezy.persistence.autonomy import pins
from breezy.runtime import venue_positions_read as vpr

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MODULE_PATH = _REPO_ROOT / "src" / "breezy" / "runtime" / "venue_positions_read.py"
_SHAPE_SCRIPT = _REPO_ROOT / "scripts" / "venue" / "polymarket_us_shape_capture.py"
_API_BASE = "https://api.example.invalid"
_GATEWAY_BASE = "https://gateway.example.invalid"
_KEY_ID = "11111111-2222-3333-4444-555555555555"
_LONG_DEADLINE_S = 30.0


def _secret_b64() -> str:
    return base64.b64encode(bytes(SigningKey.generate())).decode("ascii")


def _signer() -> Ed25519RequestSigner:
    from nautilus_trader.common.component import TestClock

    clock = TestClock()
    clock.set_time(1_700_000_000_000 * 1_000_000)
    return Ed25519RequestSigner(
        PolymarketUSCredentials(
            key_id=RedactedSecureString(_KEY_ID),
            secret_key=RedactedSecureString(_secret_b64()),
        ),
        clock=clock,
    )


class _Log:
    def debug(self, message: str) -> None: ...

    def info(self, message: str) -> None: ...

    def warning(self, message: str) -> None: ...

    def error(self, message: str) -> None: ...


class _ScriptedTransport:
    """Replays scripted responses (the last repeats); optionally delays or hangs."""

    def __init__(self, responses: list[VenueResponse], *, delay_s: float = 0.0) -> None:
        self._responses = list(responses)
        self._delay_s = delay_s
        self.calls: list[dict[str, Any]] = []

    async def get(self, url: str, *, headers: Mapping[str, str], quota_key: str) -> VenueResponse:
        self.calls.append({"url": url, "headers": dict(headers), "quota_key": quota_key})
        if self._delay_s:
            await asyncio.sleep(self._delay_s)
        index = min(len(self.calls) - 1, len(self._responses) - 1)
        return self._responses[index]


class _HangingTransport:
    def __init__(self) -> None:
        self.calls = 0

    async def get(self, url: str, *, headers: Mapping[str, str], quota_key: str) -> VenueResponse:
        self.calls += 1
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def _client(transport: Any) -> PolymarketUSHttpClient:
    return PolymarketUSHttpClient(
        transport=transport,
        signer=_signer(),
        api_base_url=_API_BASE,
        gateway_base_url=_GATEWAY_BASE,
        logger=_Log(),
    )


def _resp(payload: dict[str, Any], *, status: int = 200) -> VenueResponse:
    return VenueResponse(status=status, headers={}, body=json.dumps(payload).encode("utf-8"))


def _page(
    positions: dict[str, Any], *, eof: bool, next_cursor: str | None = None
) -> dict[str, Any]:
    page: dict[str, Any] = {"positions": positions, "eof": eof}
    if next_cursor is not None:
        page["nextCursor"] = next_cursor
    return page


def _pos(net: str, *, expired: bool = False, **extra: Any) -> dict[str, Any]:
    return {"netPosition": net, "expired": expired, **extra}


def _read(client: PolymarketUSHttpClient, **kwargs: Any) -> vpr.VenuePositionsRead:
    kwargs.setdefault("deadline_s", _LONG_DEADLINE_S)
    return asyncio.run(vpr.read_venue_positions(client, **kwargs))


def _module_tree() -> ast.Module:
    return ast.parse(_MODULE_PATH.read_text(encoding="utf-8"))


def _portfolio_positions_path_literal() -> str:
    """``PORTFOLIO_POSITIONS_PATH`` read from the exec package's source, never imported: a test
    that imports ``exec/`` would have to widen the x1 guard, and the literal needs no import."""
    endpoints = _REPO_ROOT / "src/breezy/adapters/polymarket_us/exec/endpoints.py"
    for node in ast.parse(endpoints.read_text(encoding="utf-8")).body:
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "PORTFOLIO_POSITIONS_PATH"
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            return node.value.value
    raise AssertionError("PORTFOLIO_POSITIONS_PATH literal not found")


# --------------------------------------------------------------------------
# Egress shape
# --------------------------------------------------------------------------


def test_poststop_venue_read_is_get_only() -> None:
    tree = _module_tree()
    attrs = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "get_authenticated" in attrs
    banned = {"get_public", "post", "put", "patch", "delete", "request", "_dispatch", "_transport"}
    assert not attrs & banned
    # exactly one call attribute reaches the venue, and it is the GET-only one
    called = {
        n.func.attr
        for n in ast.walk(tree)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }
    venue_calls = {a for a in called if a.startswith("get_") and a != "get_running_loop"}
    assert venue_calls == {"get_authenticated"}
    # the one endpoint literal
    literals = {
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("/v1/")
    }
    assert literals == {vpr.POSITIONS_LITERAL}
    # behaviour: only the literal path, only a cursor query, only the portfolio quota key
    transport = _ScriptedTransport(
        [
            _resp(_page({"a": _pos("1")}, eof=False, next_cursor="c2")),
            _resp(_page({"b": _pos("-2")}, eof=True)),
        ]
    )
    result = _read(_client(transport))
    assert result.complete is True
    for call in transport.calls:
        parts = urlsplit(call["url"])
        assert parts.path == vpr.POSITIONS_LITERAL
        assert set(parse_qs(parts.query)) <= {"cursor"}
        assert call["quota_key"] == "portfolio"
    assert "cursor" not in transport.calls[0]["url"]
    assert "cursor=c2" in transport.calls[1]["url"]


def test_literal_equals_portfolio_positions_path() -> None:
    assert vpr.POSITIONS_LITERAL == _portfolio_positions_path_literal() == "/v1/portfolio/positions"


def test_module_imports_no_order_path() -> None:
    roots: set[str] = set()
    for node in ast.walk(_module_tree()):
        if isinstance(node, ast.Import):
            roots |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots.add(node.module or "")
    forbidden = (
        "breezy.adapters.polymarket_us.exec",
        "breezy.adapters.polymarket_us.write_transport",
        "breezy.strategy",
        "breezy.app",
    )
    assert not {r for r in roots if r.startswith(forbidden)}
    source = _MODULE_PATH.read_text(encoding="utf-8")
    assert "write_transport" not in source
    assert "Ed25519RequestSigner" in source  # sanity: the read signer is the one imported


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------


def test_follows_cursor_to_eof_else_incomplete() -> None:
    transport = _ScriptedTransport(
        [
            _resp(_page({"a": _pos("1")}, eof=False, next_cursor="c2")),
            _resp(_page({"b": _pos("-3", expired=True)}, eof=False, next_cursor="c3")),
            _resp(_page({"c": _pos("0")}, eof=True)),
        ]
    )
    result = _read(_client(transport))
    assert result.read_status is vpr.ReadStatus.OK
    assert result.complete is True
    assert result.pages == 3
    from decimal import Decimal

    assert result.rows == (
        ("a", Decimal(1), False),
        ("b", Decimal(-3), True),
        ("c", Decimal(0), False),
    )

    # a page that is neither eof nor carries a cursor is an incomplete set, never complete
    stuck = _ScriptedTransport([_resp(_page({"a": _pos("1")}, eof=False))])
    incomplete = _read(_client(stuck))
    assert incomplete.complete is False
    assert incomplete.pages == 1
    assert len(stuck.calls) == 1


def test_page_cap_is_pins_poststop_max_pages() -> None:
    assert vpr.MAX_PAGES == pins.POSTSTOP_POSITIONS_MAX_PAGES == 20
    transport = _ScriptedTransport([_resp(_page({"a": _pos("1")}, eof=False, next_cursor="more"))])
    result = _read(_client(transport))
    assert result.complete is False
    assert result.pages == pins.POSTSTOP_POSITIONS_MAX_PAGES
    assert len(transport.calls) == pins.POSTSTOP_POSITIONS_MAX_PAGES
    assert result.read_status is vpr.ReadStatus.OK


# --------------------------------------------------------------------------
# Failure mapping
# --------------------------------------------------------------------------


def test_quota_refusal_maps_to_quota_refused() -> None:
    transport = _ScriptedTransport([_resp({"error": "slow down"}, status=429)])
    result = _read(_client(transport))
    assert result.read_status is vpr.ReadStatus.QUOTA_REFUSED
    assert result.complete is False
    assert result.rows == ()
    assert len(transport.calls) == 1  # never retried inside a slot


def test_other_venue_error_maps_to_read_failed_and_is_not_retried() -> None:
    transport = _ScriptedTransport([_resp({"error": "boom"}, status=500)])
    result = _read(_client(transport))
    assert result.read_status is vpr.ReadStatus.READ_FAILED
    assert result.complete is False
    assert result.rows == ()
    assert len(transport.calls) == 1


@pytest.mark.parametrize(
    "bad_page",
    [
        {"positions": [], "eof": True},
        {"eof": True},
        {"positions": {"a": {"expired": False}}, "eof": True},
        {"positions": {"a": {"netPosition": "not-a-number", "expired": False}}, "eof": True},
        {"positions": {"a": {"netPosition": "1"}}, "eof": True},
        {"positions": {"a": "x"}, "eof": True},
    ],
)
def test_malformed_page_is_read_failed_never_partial(bad_page: dict[str, Any]) -> None:
    good = _page({"ok": _pos("1")}, eof=False, next_cursor="c2")
    result = _read(_client(_ScriptedTransport([_resp(good), _resp(bad_page)])))
    assert result.read_status is vpr.ReadStatus.READ_FAILED
    assert result.complete is False
    assert result.rows == ()


def test_output_has_no_account_or_order_ids() -> None:
    payload = _page(
        {
            "slug-a": _pos(
                "2",
                accountId="ACCT-SECRET",
                positionId="POS-SECRET",
                orderId="ORD-SECRET",
                marketMetadata={"slug": "slug-a", "title": "x"},
            )
        },
        eof=True,
    )
    result = _read(_client(_ScriptedTransport([_resp(payload)])))
    assert {f.name for f in dataclasses.fields(result)} == {
        "snapshot_ns",
        "complete",
        "pages",
        "read_status",
        "rows",
    }
    rendered = repr(result) + json.dumps(dataclasses.asdict(result), default=str)
    for secret in ("ACCT-SECRET", "POS-SECRET", "ORD-SECRET", "marketMetadata"):
        assert secret not in rendered
    assert [len(r) for r in result.rows] == [3]


def test_snapshot_ns_is_stamped_from_the_injected_clock_at_read_end() -> None:
    ticks = iter([111, 222, 333])
    result = _read(
        _client(_ScriptedTransport([_resp(_page({}, eof=True))])),
        now_ns=lambda: next(ticks),
    )
    assert result.snapshot_ns == 111
    assert result.rows == ()
    assert result.complete is True


# --------------------------------------------------------------------------
# Credentials and the moved endpoint validator
# --------------------------------------------------------------------------


def test_credentials_from_polymarket_env_never_operator_env(tmp_path: Path) -> None:
    key_file = tmp_path / "secret.key"
    key_file.write_text(_secret_b64(), encoding="utf-8")
    key_file.chmod(0o600)
    transport = _ScriptedTransport([_resp(_page({}, eof=True))])
    good_env = {
        "POLYMARKET_US_KEY_ID": _KEY_ID,
        "POLYMARKET_US_SECRET_KEY_FILE": str(key_file),
        "POLYMARKET_US_USER_AGENT": "breezy-test contact@example.invalid",
    }
    client = vpr.build_positions_client(good_env, transport=transport)
    assert isinstance(client, PolymarketUSHttpClient)

    # Credentials absent from the mapping given: refused, no fallback to any other source.
    no_creds = {"POLYMARKET_US_USER_AGENT": "breezy-test contact@example.invalid"}
    with pytest.raises(CredentialSourceError):
        vpr.build_positions_client(no_creds, transport=transport)

    source = _MODULE_PATH.read_text(encoding="utf-8").lower()
    assert "operator" not in source
    assert "prepare(" not in source


def test_validate_endpoint_moved_byte_identical() -> None:
    original = re.compile(r"\A/[A-Za-z0-9/_-]*\Z")
    corpus = [
        "/v1/portfolio/positions",
        "/",
        "",
        "v1/x",
        "/v1/x?y=1",
        "/a b",
        "/v1/portfolio/positions\n",
        "/v1/ünï",
        "/a-b_c/D9",
        "//",
    ]
    for endpoint in corpus:
        if original.fullmatch(endpoint):
            assert vpr.validate_endpoint(endpoint) == endpoint
        else:
            with pytest.raises(ValueError, match="plain path of"):
                vpr.validate_endpoint(endpoint)

    spec = importlib.util.spec_from_file_location("polymarket_us_shape_capture_wp0", _SHAPE_SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    assert module._validate_endpoint is vpr.validate_endpoint
    script_tree = ast.parse(_SHAPE_SCRIPT.read_text(encoding="utf-8"))
    defined = {n.name for n in ast.walk(script_tree) if isinstance(n, ast.FunctionDef)}
    assert "_validate_endpoint" not in defined
    assigned = {
        t.id
        for n in ast.walk(script_tree)
        if isinstance(n, ast.Assign | ast.AnnAssign)
        for t in ([n.target] if isinstance(n, ast.AnnAssign) else n.targets)
        if isinstance(t, ast.Name)
    }
    assert "_ENDPOINT_PATTERN" not in assigned


# --------------------------------------------------------------------------
# Real default client (L-55) and timeouts (P8)
# --------------------------------------------------------------------------


def test_real_default_client_on_fake_transport(tmp_path: Path) -> None:
    key_file = tmp_path / "secret.key"
    key_file.write_text(_secret_b64(), encoding="utf-8")
    key_file.chmod(0o600)
    env = {
        "POLYMARKET_US_KEY_ID": _KEY_ID,
        "POLYMARKET_US_SECRET_KEY_FILE": str(key_file),
        "POLYMARKET_US_USER_AGENT": "breezy-test contact@example.invalid",
    }
    transport = _ScriptedTransport([_resp(_page({"slug-a": _pos("-4")}, eof=True))])
    client = vpr.build_positions_client(env, transport=transport)
    result = asyncio.run(vpr.read_venue_positions(client, deadline_s=_LONG_DEADLINE_S))
    assert result.read_status is vpr.ReadStatus.OK
    assert result.complete is True
    assert [r[0] for r in result.rows] == ["slug-a"]
    # the real default signer signed the request (three auth headers, none empty)
    headers = transport.calls[0]["headers"]
    assert len(headers) >= 3
    assert all(v for v in headers.values())
    assert vpr.VENUE_READ_REQUEST_TIMEOUT_S == 10


def test_request_timeout_returns_read_failed_incomplete() -> None:
    transport = _HangingTransport()
    started = time.monotonic()
    result = _read(_client(transport), request_timeout_s=0.05, deadline_s=_LONG_DEADLINE_S)
    assert time.monotonic() - started < 5
    assert result.read_status is vpr.ReadStatus.READ_FAILED
    assert result.complete is False
    assert result.rows == ()
    assert transport.calls == 1


def test_overall_deadline_returns_read_failed_incomplete() -> None:
    # every page answers well inside the request timeout, yet the page set outlasts the deadline
    transport = _ScriptedTransport(
        [_resp(_page({"a": _pos("1")}, eof=False, next_cursor="more"))], delay_s=0.05
    )
    started = time.monotonic()
    result = _read(_client(transport), request_timeout_s=5.0, deadline_s=0.12)
    elapsed = time.monotonic() - started
    assert elapsed < 2.0
    assert result.read_status is vpr.ReadStatus.READ_FAILED
    assert result.complete is False
    assert result.rows == ()
    assert 1 <= len(transport.calls) < pins.POSTSTOP_POSITIONS_MAX_PAGES


def test_deadline_expiry_never_raises_past_module() -> None:
    # an exhausted deadline before the first page, and a client that raises an arbitrary error
    expired = _read(_client(_HangingTransport()), deadline_s=0.0)
    assert expired.read_status is vpr.ReadStatus.READ_FAILED
    assert expired.complete is False
    assert expired.rows == ()

    class _Exploding:
        async def get_authenticated(self, *args: Any, **kwargs: Any) -> Mapping[str, Any]:
            raise RuntimeError("defect")

    result = asyncio.run(vpr.read_venue_positions(_Exploding(), deadline_s=_LONG_DEADLINE_S))
    assert result.read_status is vpr.ReadStatus.READ_FAILED
    assert result.rows == ()


# --------------------------------------------------------------------------
# Egress review coverage: the module sits inside the guards' scans and trips none
# --------------------------------------------------------------------------


def test_module_is_in_the_egress_guard_scan_and_trips_no_rule() -> None:
    from tests.unit.test_execution_egress_firewall_guard import (
        EGRESS_SCAN_ROOTS,
        find_execution_egress_modules,
    )
    from tests.unit.test_polymarket_us_readonly_guard import (
        find_sdk_import_violations,
        iter_python_sources,
    )

    relative = "src/breezy/runtime/venue_positions_read.py"
    scanned = dict(iter_python_sources(EGRESS_SCAN_ROOTS))
    assert relative in scanned
    assert relative not in {v.path for v in find_execution_egress_modules()}
    assert find_sdk_import_violations(relative, scanned[relative]) == []
