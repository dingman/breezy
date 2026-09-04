"""R-6.5b -- shipped Polymarket.us write transport (signed POST, zero send sites).

Authority: ``docs/plans/R65B_BUILD_BRIEF_2026-09-04.md``.

The module under test is file-exact-exempted from B4 and ships with ZERO send
call sites: ``factories.py`` constructs it; nothing dispatches through it
until R-7. These ten named tests are the increment's RED→GREEN artifact.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from nacl.signing import SigningKey
from nautilus_trader.common.component import TestClock

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.errors import MethodNotPermittedError
from breezy.adapters.polymarket_us.secure import RedactedSecureString
from breezy.adapters.polymarket_us.signing import (
    ACCESS_KEY_HEADER,
    PERMITTED_METHODS,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    Ed25519RequestSigner,
)
from breezy.adapters.polymarket_us.transport import QUOTA_KEY_PORTFOLIO, VenueResponse
from tests.unit.test_polymarket_us_readonly_guard import (
    B4_EXEMPT_PATHS,
    BARRED_CALLEES,
    Violation,
    find_barred_callers,
    find_write_capable_receiver_exposures,
    find_write_egress_violations,
    iter_python_sources,
    scan_write_egress,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
_WRITE_TRANSPORT_PATH = "src/breezy/adapters/polymarket_us/write_transport.py"
_WRITE_TRANSPORT_MODULE_NAME = "write_transport"
_FACTORIES_PATH = "src/breezy/adapters/polymarket_us/factories.py"
_PROBE_PATH = REPO_ROOT / "scripts" / "venue" / "polymarket_us_write_signing_probe.py"
_CANCEL_ALL_PATH = "/v1/orders/open/cancel"
_KEY_ID = "11111111-2222-3333-4444-555555555555"
_TS_MS = 1_700_000_000_000
_PERMITTED_PYO3_MEMBERS = frozenset({"HttpError", "HttpTimeoutError"})
_IMPORTER_SCAN_ROOTS: tuple[str, ...] = ("src", "scripts")
_CALLER_SCAN_ROOTS: tuple[str, ...] = ("src", "scripts", "tests")


# --------------------------------------------------------------------------
# AST / scan helpers (RED 3 needs a net-new pyo3-member enumerator)
# --------------------------------------------------------------------------


def _is_nautilus_pyo3_expr(expr: ast.AST) -> bool:
    if isinstance(expr, ast.Name) and expr.id == "nautilus_pyo3":
        return True
    return isinstance(expr, ast.Attribute) and expr.attr == "nautilus_pyo3"


def find_nautilus_pyo3_members(source: str) -> frozenset[str]:
    """Enumerate ``nautilus_pyo3.X`` attribute refs and ``from ...nautilus_pyo3 import X``.

    No such helper existed; D2's pin needs one. A name that is only mentioned
    in a string or comment is invisible, matching C6's identifier-only rule.
    """
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and _is_nautilus_pyo3_expr(node.value):
            found.add(node.attr)
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.split(".")[-1] == "nautilus_pyo3"
        ):
            for alias in node.names:
                if alias.name != "*":
                    found.add(alias.name)
    return frozenset(found)


def find_write_transport_importers(path: str, source: str) -> list[Violation]:
    """Copy of ``find_probe_importers`` with the write-transport token.

    Four forms: plain import, from-import, ``import_module``/``__import__``,
    and any dotted-string literal naming the module.
    """
    tree = ast.parse(source, filename=path)
    found: list[Violation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _WRITE_TRANSPORT_MODULE_NAME in alias.name.split("."):
                    found.append(Violation(path, node.lineno, "D4", f"import {alias.name}"))
        elif (
            isinstance(node, ast.ImportFrom)
            and node.module
            and _WRITE_TRANSPORT_MODULE_NAME in node.module.split(".")
        ):
            found.append(Violation(path, node.lineno, "D4", f"from {node.module} import ..."))
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in ("import_module", "__import__") and node.args:
                arg = node.args[0]
                if (
                    isinstance(arg, ast.Constant)
                    and isinstance(arg.value, str)
                    and _WRITE_TRANSPORT_MODULE_NAME in arg.value
                ):
                    found.append(Violation(path, node.lineno, "D4", f"{name}({arg.value!r})"))
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _WRITE_TRANSPORT_MODULE_NAME in node.value
        ):
            found.append(
                Violation(path, node.lineno, "D4", f"dotted-string literal {node.value!r}")
            )
    return found


def scan_write_transport_importers(
    roots: tuple[str, ...] = _IMPORTER_SCAN_ROOTS,
) -> list[Violation]:
    return [
        v
        for path, src in iter_python_sources(roots)
        if path != _WRITE_TRANSPORT_PATH
        for v in find_write_transport_importers(path, src)
    ]


_WRITE_TRANSPORT_EXPORT_NAMES = frozenset(
    {
        "CANCEL_ALL_PATH",
        "Ed25519WriteRequestSigner",
        "PERMITTED_WRITE_METHODS",
        "PolymarketUSWriteTransport",
        "WRITE_CANONICAL_STRING_VERIFIED",
        "_build_post_only_callable",
    }
)


def _module_level_all_literals(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in tree.body if isinstance(tree, ast.Module) else ():
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            continue
        value = node.value
        elts: list[ast.expr]
        if isinstance(value, ast.List | ast.Tuple | ast.Set):
            elts = list(value.elts)
        else:
            continue
        for elt in elts:
            if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                names.add(elt.value)
    return names


def find_write_transport_reexports(path: str, source: str) -> list[Violation]:
    """The one importer must not re-export the builder (no ``__all__``, alias, ``*``)."""
    tree = ast.parse(source, filename=path)
    found: list[Violation] = []
    exported = _module_level_all_literals(tree) & _WRITE_TRANSPORT_EXPORT_NAMES
    if exported:
        found.append(
            Violation(path, 0, "D4", f"__all__ re-exports {sorted(exported)}")
        )
    imported_aliases: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and _WRITE_TRANSPORT_MODULE_NAME in node.module.split(".")
        ):
            for alias in node.names:
                if alias.name == "*":
                    found.append(
                        Violation(path, node.lineno, "D4", "from write_transport import *")
                    )
                imported_aliases.add(alias.asname or alias.name)
    for node in tree.body if isinstance(tree, ast.Module) else ():
        if not isinstance(node, ast.Assign):
            continue
        if not isinstance(node.value, ast.Name) or node.value.id not in imported_aliases:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id != node.value.id:
                found.append(
                    Violation(
                        path,
                        node.lineno,
                        "D4",
                        f"module-level alias {target.id} = {node.value.id}",
                    )
                )
    return found


def _rule_token(violation: Violation) -> tuple[str, str]:
    detail = violation.detail
    if violation.rule == "V1":
        return ("V1", "POST") if "POST" in detail else (violation.rule, detail)
    if violation.rule == "V2":
        return (
            ("V2", _CANCEL_ALL_PATH)
            if _CANCEL_ALL_PATH in detail
            else (violation.rule, detail)
        )
    if violation.rule == "V3":
        return ("V3", ".post") if ".post" in detail else (violation.rule, detail)
    return (violation.rule, detail)


def _d3_callers(roots: tuple[str, ...] = _CALLER_SCAN_ROOTS) -> list[Violation]:
    return [
        v
        for path, src in iter_python_sources(roots)
        for v in find_barred_callers(path, src)
        if v.rule == "D3"
    ]


# --------------------------------------------------------------------------
# Doubles
# --------------------------------------------------------------------------


class _FakeResponse:
    def __init__(
        self,
        status: int = 200,
        body: bytes = b"{}",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status = status
        self.body = body
        self.headers = headers if headers is not None else {}


class _RecordingWriteClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.response = _FakeResponse()
        self.raises: BaseException | None = None

    async def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append({"url": url, **kwargs})
        if self.raises is not None:
            raise self.raises
        return self.response

    async def get(self, *_args: Any, **_kwargs: Any) -> _FakeResponse:
        raise AssertionError("write transport must not call get")


class _WriteCapableClient:
    def post(self) -> object:
        return object()

    async def get(self, *_args: Any, **_kwargs: Any) -> object:
        return object()


def _new_secret_b64() -> str:
    import base64

    return base64.b64encode(bytes(SigningKey.generate())).decode("ascii")


def _credentials(secret_b64: str | None = None) -> PolymarketUSCredentials:
    secret = secret_b64 if secret_b64 is not None else _new_secret_b64()
    return PolymarketUSCredentials(
        key_id=RedactedSecureString(_KEY_ID),
        secret_key=RedactedSecureString(secret),
    )


def _clock_at(timestamp_ms: int) -> TestClock:
    clock = TestClock()
    clock.set_time(timestamp_ms * 1_000_000)
    return clock


def _load_probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "breezy_polymarket_us_write_signing_probe_for_r65b", _PROBE_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_transport_source() -> str:
    return (REPO_ROOT / _WRITE_TRANSPORT_PATH).read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# 1. signature has no method / query / body
# --------------------------------------------------------------------------


def test_the_write_callable_has_no_method_query_or_body_parameter() -> None:
    from breezy.adapters.polymarket_us.write_transport import PolymarketUSWriteTransport

    params = inspect.signature(PolymarketUSWriteTransport.post_cancel_all).parameters
    assert "method" not in params
    assert "query" not in params
    assert "body" not in params
    assert "params" not in params
    assert "timeout_secs" not in params


# --------------------------------------------------------------------------
# 2. exactly one POST to the one pinned path
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_it_issues_exactly_one_post_to_the_one_pinned_path() -> None:
    """Equality to the one path, never membership in a widened allowlist."""
    from breezy.adapters.polymarket_us.write_transport import (
        CANCEL_ALL_PATH,
        PolymarketUSWriteTransport,
    )

    client = _RecordingWriteClient()
    transport = PolymarketUSWriteTransport(client=client)
    response = await transport.post_cancel_all(
        "https://api.example.invalid",
        headers={ACCESS_KEY_HEADER: "k"},
    )

    assert len(client.calls) == 1
    call = client.calls[0]
    assert set(call) == {"url", "headers", "keys"}
    assert call["keys"] == [QUOTA_KEY_PORTFOLIO]
    assert call["headers"] == {ACCESS_KEY_HEADER: "k"}
    path = call["url"].removeprefix("https://api.example.invalid")
    assert {path} == {CANCEL_ALL_PATH} == {_CANCEL_ALL_PATH}
    assert isinstance(response, VenueResponse)
    assert response.status == 200


# --------------------------------------------------------------------------
# 3. pyo3 member pin
# --------------------------------------------------------------------------


def test_write_transport_references_exactly_the_permitted_pyo3_members() -> None:
    source = _write_transport_source()
    assert find_nautilus_pyo3_members(source) == _PERMITTED_PYO3_MEMBERS

    planted_socket = "client = nautilus_pyo3.SocketClient()\n"
    planted_ws = (
        "from nautilus_trader.core import nautilus_pyo3\n\n"
        "x = nautilus_pyo3.WebSocketClient\n"
    )
    planted_exec = "from nautilus_trader.core.nautilus_pyo3 import LiveExecClientConfig\n"
    assert find_nautilus_pyo3_members(planted_socket) == frozenset({"SocketClient"})
    assert find_nautilus_pyo3_members(planted_ws) == frozenset({"WebSocketClient"})
    assert find_nautilus_pyo3_members(planted_exec) == frozenset({"LiveExecClientConfig"})
    assert find_nautilus_pyo3_members(source) & {
        "SocketClient",
        "WebSocketClient",
        "LiveExecClientConfig",
        "HttpClient",
        "Quota",
        "HttpMethod",
    } == frozenset()


# --------------------------------------------------------------------------
# 4. _build_post_only_callable has exactly one caller
# --------------------------------------------------------------------------


def test_build_post_only_callable_has_exactly_one_caller() -> None:
    """Remove the constructor call → red; a second caller under tests/ → red."""
    assert BARRED_CALLEES.get("_build_post_only_callable") == "D3"
    callers = _d3_callers()
    assert [(v.path, v.rule) for v in callers] == [(_WRITE_TRANSPORT_PATH, "D3")]

    planted = "def go(client):\n    return _build_post_only_callable(client)\n"
    planted_hits = find_barred_callers("tests/unit/rogue_write_builder.py", planted)
    assert [v.rule for v in planted_hits] == ["D3"]
    empty = find_barred_callers("tests/unit/rogue_write_builder.py", "def go():\n    return None\n")
    assert empty == []


# --------------------------------------------------------------------------
# 5. exactly one importer, and it does not re-export
# --------------------------------------------------------------------------


def test_write_transport_has_exactly_one_importer_and_it_does_not_re_export() -> None:
    importers = scan_write_transport_importers()
    assert {v.path for v in importers} == {_FACTORIES_PATH}

    factories_source = (REPO_ROOT / _FACTORIES_PATH).read_text(encoding="utf-8")
    assert find_write_transport_reexports(_FACTORIES_PATH, factories_source) == []

    assert find_write_transport_importers(
        "src/breezy/rogue.py", "import breezy.adapters.polymarket_us.write_transport\n"
    )
    assert find_write_transport_importers(
        "src/breezy/rogue.py",
        "from breezy.adapters.polymarket_us.write_transport import PolymarketUSWriteTransport\n",
    )
    assert find_write_transport_importers(
        "scripts/venue/rogue.py",
        "import importlib\n\n"
        "importlib.import_module('breezy.adapters.polymarket_us.write_transport')\n",
    )
    assert find_write_transport_importers(
        "src/breezy/rogue.py",
        "__import__('breezy.adapters.polymarket_us.write_transport')\n",
    )
    assert find_write_transport_importers(
        "src/breezy/rogue.py",
        "NAME = 'breezy.adapters.polymarket_us.write_transport'\n",
    )

    starred = "from breezy.adapters.polymarket_us.write_transport import *\n"
    starred_hits = find_write_transport_reexports(_FACTORIES_PATH, starred)
    assert any("import *" in v.detail for v in starred_hits)
    aliased = (
        "from breezy.adapters.polymarket_us.write_transport import PolymarketUSWriteTransport\n"
        "WriteTransport = PolymarketUSWriteTransport\n"
    )
    aliased_hits = find_write_transport_reexports(_FACTORIES_PATH, aliased)
    assert any("alias" in v.detail for v in aliased_hits)
    reexported = (
        "from breezy.adapters.polymarket_us.write_transport import PolymarketUSWriteTransport\n"
        "__all__ = ['PolymarketUSWriteTransport']\n"
    )
    reexport_hits = find_write_transport_reexports(_FACTORIES_PATH, reexported)
    assert any("__all__" in v.detail for v in reexport_hits)


# --------------------------------------------------------------------------
# 6. write signer refuses GET; read signer refuses POST
# --------------------------------------------------------------------------


def test_the_write_signer_refuses_get_and_the_read_signer_refuses_post() -> None:
    from breezy.adapters.polymarket_us.write_transport import (
        PERMITTED_WRITE_METHODS,
        Ed25519WriteRequestSigner,
    )

    assert PERMITTED_METHODS == frozenset({"GET"})
    assert PERMITTED_WRITE_METHODS == frozenset({"POST"})
    credentials = _credentials()
    clock = _clock_at(_TS_MS)
    write_signer = Ed25519WriteRequestSigner(credentials, clock=clock)
    read_signer = Ed25519RequestSigner(credentials, clock=clock)
    with pytest.raises(MethodNotPermittedError):
        write_signer.sign_headers("GET", _CANCEL_ALL_PATH)
    with pytest.raises(MethodNotPermittedError):
        read_signer.sign_headers("POST", _CANCEL_ALL_PATH)


# --------------------------------------------------------------------------
# 7. B3: constructed write transport exposes no write-capable receiver
# --------------------------------------------------------------------------


def test_b3_the_constructed_write_transport_exposes_no_write_capable_receiver() -> None:
    from breezy.adapters.polymarket_us.write_transport import PolymarketUSWriteTransport

    transport = PolymarketUSWriteTransport(client=_WriteCapableClient())
    assert find_write_capable_receiver_exposures(transport) == []

    class Leaky:
        def __init__(self) -> None:
            self._client = _WriteCapableClient()

    leaked = find_write_capable_receiver_exposures(Leaky())
    assert leaked != []
    assert {v.rule for v in leaked} == {"B3"}


# --------------------------------------------------------------------------
# 8. B4 raw content is exactly the three expected violations
# --------------------------------------------------------------------------


def test_b4_raw_content_is_exactly_the_three_expected_violations() -> None:
    """Exact set ``[(V1,'POST'),(V2,'/v1/orders/open/cancel'),(V3,'.post')]``.

    Non-vacuity both directions: without the exemption the real file trips
    ``scan_write_egress``; a second file with the same literals still trips
    with the exemption in place.
    """
    source = _write_transport_source()
    raw = find_write_egress_violations(_WRITE_TRANSPORT_PATH, source)
    expected = [("V1", "POST"), ("V2", _CANCEL_ALL_PATH), ("V3", ".post")]
    assert sorted(_rule_token(v) for v in raw) == sorted(expected)
    assert len(raw) == 3
    assert _WRITE_TRANSPORT_PATH in B4_EXEMPT_PATHS
    assert scan_write_egress() == []

    without_exemption = [
        v
        for p, src in [(_WRITE_TRANSPORT_PATH, source)]
        if p not in frozenset()
        for v in find_write_egress_violations(p, src)
    ]
    assert without_exemption != []

    copycat = find_write_egress_violations(
        "src/breezy/adapters/polymarket_us/a_copycat_write.py", source
    )
    assert copycat != []
    assert {v.rule for v in copycat} >= {"V1", "V2", "V3"}


# --------------------------------------------------------------------------
# 9. shipped signer and probe produce the same canonical string
# --------------------------------------------------------------------------


def test_the_shipped_write_signer_and_the_probe_produce_the_same_canonical_string() -> None:
    """Identical signature bytes over one injected timestamp and path."""
    from breezy.adapters.polymarket_us.write_transport import Ed25519WriteRequestSigner

    secret = _new_secret_b64()
    credentials = _credentials(secret)
    clock = _clock_at(_TS_MS)
    shipped = Ed25519WriteRequestSigner(credentials, clock=clock)
    shipped_headers = dict(shipped.sign_headers("POST", _CANCEL_ALL_PATH))

    probe = _load_probe()
    read_signer = Ed25519RequestSigner(credentials, clock=clock)
    probe_headers = dict(probe._sign_write_headers(credentials, read_signer, clock))

    assert shipped_headers[SIGNATURE_HEADER] == probe_headers[SIGNATURE_HEADER]
    assert shipped_headers == probe_headers
    assert list(shipped_headers) == [ACCESS_KEY_HEADER, TIMESTAMP_HEADER, SIGNATURE_HEADER]


# --------------------------------------------------------------------------
# 10. unverified premise stays False until OP-4
# --------------------------------------------------------------------------


def test_write_canonical_string_verified_is_false_until_op4() -> None:
    from breezy.adapters.polymarket_us.write_transport import WRITE_CANONICAL_STRING_VERIFIED

    assert WRITE_CANONICAL_STRING_VERIFIED is False
