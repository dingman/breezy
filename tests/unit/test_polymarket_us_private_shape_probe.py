"""Offline suite for the R-5R-0 private-surface shape RUNNER.

Authority: ``docs/plans/EXEC_SPINE_R5_R6_2026-09-02.md`` section 3, R-5R-0.

R-1 landed a shape *describer* (``polymarket_us_shape_capture.py``) that is
pure by construction: no ``main()``, no ``argparse``, no I/O. The evidence that
produced the R-5R availability table therefore required an ephemeral driver
supplied from outside the repository, which is not repeatable and cannot be
re-run when the venue's backend changes state. R-5R-0 is that driver, made
part of the tree.

What this suite pins, and why each pin is load-bearing:

* **GET-only before a credential exists.** The runner refuses a non-GET method
  as its first act, ahead of the credential read, so the refusal cannot depend
  on a process that already holds an Ed25519 secret. Asserted with a
  ``prepare`` double that FAILS if it is entered at all.
* **No write surface reachable by import.** An AST scan pinned to a closed
  allowlist, so a future import has to be added here deliberately rather than
  arriving as a diff nobody read.
* **A status class, never a verdict (L-8).** A refusal is recorded as the HTTP
  status plus the gRPC ``code`` the envelope carried, and nothing else. No
  classification word, no cause, no inference about the venue's health --
  those are the reader's job, and a bare code presented as a conclusion is the
  exact failure L-8 names.
* **Value-freeness is inherited, not re-derived.** The runner routes every
  payload through the R-1 describer and re-runs ``verify_value_free`` on what
  it is about to write. The private endpoints ARE the operator's financial
  position; the artefact is ``PRIVATE_``-prefixed and ``0600`` for the same
  reason.

Every test is offline. The transport is a double returning canned envelopes
and every credential is an ephemeral Ed25519 key generated in-process, so
nothing here can reach a venue host.
"""

from __future__ import annotations

import ast
import base64
import importlib.util
import json
import os
import stat
import sys
from collections.abc import Mapping
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from nacl.signing import SigningKey

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.errors import MethodNotPermittedError
from breezy.adapters.polymarket_us.secure import RedactedSecureString
from breezy.adapters.polymarket_us.transport import VenueResponse

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "venue" / "polymarket_us_private_shape_probe.py"

_API_BASE = "https://api.example.invalid"
_GATEWAY_BASE = "https://gateway.example.invalid"
_KEY_ID = "11111111-2222-3333-4444-555555555555"

#: A path with the shape of a private read. Test files are NOT scanned by the
#: B4 write-verb rules (``EGRESS_SCAN_ROOTS = ("src", "scripts")``), which is
#: what lets a literal live here and not in the runner.
_PRIVATE_PATH = "/v1/portfolio/positions"

#: The measured 503 body class: a gRPC-gateway error envelope.
_UNAVAILABLE_BODY = b'{"code": 14, "message": "upstream connect error"}'

#: Words a reader could mistake for a conclusion about the venue. None of them
#: may appear in an artefact (L-8): the artefact records what was observed, and
#: the classification is a separate, reviewable step.
_VERDICT_LEXICON = (
    "TRANSIENT",
    "DURABLE",
    "UNAVAILABLE",
    "INTERNAL",
    "UNIMPLEMENTED",
    "verdict",
    "outage",
    "healthy",
    "unhealthy",
    "degraded",
    "down",
    "PASS",
    "FAIL",
)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def _load_runner() -> ModuleType:
    """Load the runner the way the repo loads its other venue scripts.

    It is a ``scripts/venue/`` module rather than a ``breezy`` package module
    for the same reason the describer is: it WRITES into ``docs/evidence/``,
    and ``test_probe_containment.py`` bans that path as a runtime constant
    anywhere under ``src/``.
    """
    spec = importlib.util.spec_from_file_location(
        "breezy_polymarket_us_private_shape_probe", SCRIPT_PATH
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


class _RefusingPrepare:
    """A ``prepare`` double that records -- and fails -- on entry.

    The claim under test is "refused BEFORE any credential is touched", and the
    only honest way to assert it is to make the credential step itself an
    error rather than to inspect a flag it set.
    """

    def __init__(self) -> None:
        self.entered = False

    def __call__(self, env: Any = None, *, guard: Any = None) -> Any:
        self.entered = True
        raise AssertionError("prepare() was entered; a credential read had begun")


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


def test_build_read_transport_constructs_a_nautilus_http_transport(
    runner: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runner's own builder must construct without TypeError (R-6.5b-0)."""
    from nautilus_trader.core import nautilus_pyo3

    from breezy.adapters.polymarket_us import transport as transport_module
    from breezy.adapters.polymarket_us.transport import NautilusHttpTransport

    class _FakeHttpClient:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    transport_module.build_shared_http_client._reset_for_tests()
    monkeypatch.setattr(nautilus_pyo3, "HttpClient", _FakeHttpClient)
    try:
        built = runner._build_read_transport(_config())
    finally:
        transport_module.build_shared_http_client._reset_for_tests()
    assert isinstance(built, NautilusHttpTransport)


async def _run(
    runner: ModuleType,
    *,
    endpoint: str = _PRIVATE_PATH,
    response: VenueResponse,
    directory: Path,
    stamp: str | None = None,
) -> Any:
    transport = _CannedTransport(response)
    return await runner.run_probe(
        endpoint,
        directory=directory,
        stamp=stamp,
        prepare_fn=lambda env=None, *, guard=None: _prepared(runner),
        transport_factory=lambda config: transport,
    )


# --------------------------------------------------------------------------
# R-5R-0 RED 1 -- GET-only, before any credential
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_shape_runner_is_get_only(runner: ModuleType, tmp_path: Path) -> None:
    """A non-GET method is refused before the credential read is entered."""
    refusing = _RefusingPrepare()
    with pytest.raises(MethodNotPermittedError):
        await runner.run_probe(
            _PRIVATE_PATH,
            method="POST",
            directory=tmp_path,
            prepare_fn=refusing,
            transport_factory=lambda config: _CannedTransport(
                VenueResponse(status=200, headers={}, body=b"{}")
            ),
        )
    assert refusing.entered is False
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("method", ["post", "PUT", "PATCH", "DELETE", "HEAD", "", "GET "])
@pytest.mark.asyncio
async def test_every_method_outside_the_signer_allowlist_is_refused(
    runner: ModuleType, method: str, tmp_path: Path
) -> None:
    """The allowlist is the signer's own ``PERMITTED_METHODS``, not a copy."""
    refusing = _RefusingPrepare()
    with pytest.raises(MethodNotPermittedError):
        await runner.run_probe(
            _PRIVATE_PATH,
            method=method,
            directory=tmp_path,
            prepare_fn=refusing,
            transport_factory=lambda config: _CannedTransport(
                VenueResponse(status=200, headers={}, body=b"{}")
            ),
        )
    assert refusing.entered is False


def test_the_runner_reuses_the_signers_permitted_methods(runner: ModuleType) -> None:
    """No second, drifting allowlist: the runner reads the signer's frozenset."""
    from breezy.adapters.polymarket_us.signing import PERMITTED_METHODS

    assert runner.PERMITTED_METHODS is PERMITTED_METHODS
    assert runner.HTTP_METHOD in PERMITTED_METHODS


# --------------------------------------------------------------------------
# R-5R-0 RED 2 -- no write surface reachable by import
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


#: Every module the runner may import, pinned. A GET-only probe has a small,
#: enumerable dependency set; making it an allowlist means a future import
#: cannot arrive without a paired edit here.
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
        "breezy.adapters.polymarket_us.exec.refusals",
        "breezy.adapters.polymarket_us.http",
        "breezy.adapters.polymarket_us.signing",
        "breezy.adapters.polymarket_us.transport",
        "polymarket_us_auth_smoke",
        "polymarket_us_shape_capture",
    }
)

#: Substrings that name an order-submission surface. R-6.5P and R-6.5 do not
#: exist yet; this fires if the runner ever reaches for one, under any of the
#: names the spine uses for them.
_WRITE_SURFACE_TOKENS = ("order", "submit", "preview", "write", "trading", "permit")


def test_the_shape_runner_imports_no_write_surface() -> None:
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


def test_the_runner_defines_no_order_path_literal() -> None:
    """B4 rule V2 restated locally, so this suite fails for its own reason too."""
    import re

    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"), filename=str(SCRIPT_PATH))
    pattern = re.compile(r"/v\d+/orders?\b", re.IGNORECASE)
    offending = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and pattern.search(node.value)
    ]
    assert offending == []


# --------------------------------------------------------------------------
# R-5R-0 RED 3 -- a status class, never a verdict (L-8)
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_shape_runner_records_a_grpc_status_class_not_a_verdict(
    runner: ModuleType, tmp_path: Path
) -> None:
    """A synthetic 503 records status + gRPC code, and states no conclusion."""
    observation = await _run(
        runner,
        response=VenueResponse(status=503, headers={}, body=_UNAVAILABLE_BODY),
        directory=tmp_path,
    )
    assert observation.http_status == 503
    assert observation.grpc_code == 14

    path = runner.write_probe_artifact(observation, directory=tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))

    assert set(document) == set(runner.PROBE_DOCUMENT_FIELDS)
    assert document["http_status"] == 503
    assert document["grpc_code"] == 14
    assert document["endpoint"] == _PRIVATE_PATH

    text = path.read_text(encoding="utf-8")
    leaked = [word for word in _VERDICT_LEXICON if word in text]
    assert leaked == [], f"artefact states a conclusion rather than an observation: {leaked}"


@pytest.mark.asyncio
async def test_a_body_with_no_grpc_code_records_a_null_code_not_a_guess(
    runner: ModuleType, tmp_path: Path
) -> None:
    """``None`` means "the body told us nothing" -- never a substituted default."""
    observation = await _run(
        runner,
        response=VenueResponse(status=500, headers={}, body=b"<html>gateway</html>"),
        directory=tmp_path,
    )
    assert observation.http_status == 500
    assert observation.grpc_code is None
    assert observation.envelope_parsed is False


@pytest.mark.asyncio
async def test_a_two_hundred_envelope_is_recorded_as_parsed(
    runner: ModuleType, tmp_path: Path
) -> None:
    observation = await _run(
        runner,
        response=VenueResponse(status=200, headers={}, body=b'{"positions": {}, "eof": true}'),
        directory=tmp_path,
    )
    assert observation.http_status == 200
    assert observation.grpc_code is None
    assert observation.envelope_parsed is True


# --------------------------------------------------------------------------
# Artefact containment
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_artifact_is_private_prefixed_and_owner_only(
    runner: ModuleType, tmp_path: Path
) -> None:
    observation = await _run(
        runner,
        response=VenueResponse(status=200, headers={}, body=b'{"eof": true}'),
        directory=tmp_path,
    )
    path = runner.write_probe_artifact(observation, directory=tmp_path)

    assert path.name.startswith("PRIVATE_")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(tmp_path.stat().st_mode) == 0o700


@pytest.mark.asyncio
async def test_an_existing_artifact_is_never_silently_overwritten(
    runner: ModuleType, tmp_path: Path
) -> None:
    observation = await _run(
        runner,
        response=VenueResponse(status=200, headers={}, body=b'{"eof": true}'),
        directory=tmp_path,
    )
    runner.write_probe_artifact(observation, directory=tmp_path)
    with pytest.raises(FileExistsError):
        runner.write_probe_artifact(observation, directory=tmp_path)


@pytest.mark.asyncio
async def test_a_colliding_artifact_is_refused_before_the_request_is_spent(
    runner: ModuleType, tmp_path: Path
) -> None:
    """The venue is the scarce resource: a doomed write fails for free."""
    (tmp_path / runner.probe_artifact_filename(_PRIVATE_PATH)).write_text("", encoding="utf-8")
    transport = _CannedTransport(VenueResponse(status=200, headers={}, body=b"{}"))
    with pytest.raises(FileExistsError):
        await runner.run_probe(
            _PRIVATE_PATH,
            directory=tmp_path,
            prepare_fn=lambda env=None, *, guard=None: _prepared(runner),
            transport_factory=lambda config: transport,
        )
    assert transport.calls == []


@pytest.mark.parametrize(
    "endpoint",
    [
        "/v1/portfolio/positions?limit=1",
        "v1/portfolio/positions",
        "/v1/portfolio/../../etc/passwd",
        "/v1/portfolio/positions\n",
        "",
    ],
)
@pytest.mark.asyncio
async def test_an_endpoint_outside_the_plain_path_charset_is_refused_before_any_request(
    runner: ModuleType, endpoint: str, tmp_path: Path
) -> None:
    """Refused ahead of the credential read AND ahead of the request."""
    refusing = _RefusingPrepare()
    transport = _CannedTransport(VenueResponse(status=200, headers={}, body=b"{}"))
    with pytest.raises(ValueError):
        await runner.run_probe(
            endpoint,
            directory=tmp_path,
            prepare_fn=refusing,
            transport_factory=lambda config: transport,
        )
    assert refusing.entered is False
    assert transport.calls == []
    assert list(tmp_path.iterdir()) == []


@pytest.mark.asyncio
async def test_the_runner_verifies_the_describer_output_is_value_free(
    runner: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``verify_value_free`` is invoked on what is described, not trusted."""
    calls: list[Mapping[str, Any]] = []
    original = runner.verify_value_free

    def _spy(shape: Mapping[str, Any], **kwargs: Any) -> None:
        calls.append(shape)
        original(shape, **kwargs)

    monkeypatch.setattr(runner, "verify_value_free", _spy)
    observation = await _run(
        runner,
        response=VenueResponse(status=200, headers={}, body=b'{"eof": true}'),
        directory=tmp_path,
    )
    assert calls, "the describer output reached the artefact unverified"
    runner.write_probe_artifact(observation, directory=tmp_path)
    assert len(calls) >= 2, "the rendered document was not re-verified before writing"


@pytest.mark.asyncio
async def test_a_leaking_shape_is_refused_and_writes_nothing(
    runner: ModuleType, tmp_path: Path
) -> None:
    """A shape outside the closed grammar refuses rather than writes."""
    observation = await _run(
        runner,
        response=VenueResponse(status=200, headers={}, body=b'{"eof": true}'),
        directory=tmp_path,
    )
    tampered = runner.ProbeObservation(
        endpoint=observation.endpoint,
        http_status=observation.http_status,
        grpc_code=observation.grpc_code,
        envelope_parsed=observation.envelope_parsed,
        signing_variant=observation.signing_variant,
        shape={"type": "object", "balance_usd": "987654321.05"},
    )
    with pytest.raises(runner.ShapeLeakError):
        runner.write_probe_artifact(tampered, directory=tmp_path)
    assert [p for p in tmp_path.iterdir() if p.name.startswith("PRIVATE_")] == []


@pytest.mark.asyncio
async def test_two_payloads_differing_only_in_value_render_identically(
    runner: ModuleType, tmp_path: Path
) -> None:
    """Value-invariance, inherited from the R-1 describer and re-asserted here."""
    poor = await _run(
        runner,
        response=VenueResponse(status=200, headers={}, body=b'{"cash": 1.0, "eof": true}'),
        directory=tmp_path,
    )
    rich = await _run(
        runner,
        response=VenueResponse(status=200, headers={}, body=b'{"cash": 987654321.05, "eof": true}'),
        directory=tmp_path,
    )
    assert runner.render_probe_report(poor) == runner.render_probe_report(rich)


# --------------------------------------------------------------------------
# Wiring
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_request_is_signed_and_carries_the_three_x_pm_headers(
    runner: ModuleType, tmp_path: Path
) -> None:
    """The runner drives the shipped signer, not an ad-hoc header builder."""
    from breezy.adapters.polymarket_us.signing import (
        ACCESS_KEY_HEADER,
        SIGNATURE_HEADER,
        TIMESTAMP_HEADER,
    )

    transport = _CannedTransport(VenueResponse(status=200, headers={}, body=b'{"eof": true}'))
    await runner.run_probe(
        _PRIVATE_PATH,
        directory=tmp_path,
        prepare_fn=lambda env=None, *, guard=None: _prepared(runner),
        transport_factory=lambda config: transport,
    )
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == f"{_API_BASE}{_PRIVATE_PATH}"
    assert set(call["headers"]) >= {ACCESS_KEY_HEADER, TIMESTAMP_HEADER, SIGNATURE_HEADER}


@pytest.mark.asyncio
async def test_the_query_string_is_rendered_by_the_shipped_client(
    runner: ModuleType, tmp_path: Path
) -> None:
    """OQ-M needs a query on a signed request; it is built by ``http.py``."""
    transport = _CannedTransport(VenueResponse(status=200, headers={}, body=b'{"eof": true}'))
    await runner.run_probe(
        _PRIVATE_PATH,
        query={"limit": "1"},
        directory=tmp_path,
        prepare_fn=lambda env=None, *, guard=None: _prepared(runner),
        transport_factory=lambda config: transport,
    )
    assert transport.calls[0]["url"] == f"{_API_BASE}{_PRIVATE_PATH}?limit=1"


@pytest.mark.parametrize("variant", ["path_only", "path_with_query"])
@pytest.mark.asyncio
async def test_the_signing_variant_is_a_caller_argument(
    runner: ModuleType, variant: str, tmp_path: Path
) -> None:
    """Both canonical-string builders are reachable, so OQ-M is measurable."""
    transport = _CannedTransport(VenueResponse(status=200, headers={}, body=b'{"eof": true}'))
    observation = await runner.run_probe(
        _PRIVATE_PATH,
        query={"limit": "1"},
        signing_variant=variant,
        directory=tmp_path,
        prepare_fn=lambda env=None, *, guard=None: _prepared(runner),
        transport_factory=lambda config: transport,
    )
    assert observation.signing_variant == variant


@pytest.mark.parametrize("pair", ["limit", "limit=1=2", "limit=a b", "=1", "li mit=1"])
def test_a_malformed_query_pair_is_refused(runner: ModuleType, pair: str) -> None:
    with pytest.raises(ValueError):
        runner.parse_query_pairs([pair])


def test_query_pairs_parse_to_a_mapping(runner: ModuleType) -> None:
    assert runner.parse_query_pairs(["limit=1", "cursor=abc-def"]) == {
        "limit": "1",
        "cursor": "abc-def",
    }


@pytest.mark.parametrize("stamp", ["a b", "a/b", "a.b", ""])
def test_a_malformed_stamp_is_refused(runner: ModuleType, stamp: str) -> None:
    with pytest.raises(ValueError):
        runner.probe_artifact_filename(_PRIVATE_PATH, stamp=stamp)


# --------------------------------------------------------------------------
# Entrypoint shape
# --------------------------------------------------------------------------


def test_the_runner_is_an_entrypoint_with_the_endpoint_as_an_argument(
    runner: ModuleType,
) -> None:
    """The R-5R-0 gap in one assertion: it has a ``main`` and takes a path."""
    assert callable(runner.main)
    namespace = runner.parse_args(["--endpoint", _PRIVATE_PATH])
    assert namespace.endpoint == _PRIVATE_PATH


def test_the_endpoint_argument_has_no_default(runner: ModuleType) -> None:
    """A default would put a private path back into source as a literal."""
    with pytest.raises(SystemExit):
        runner.parse_args([])


def test_the_runner_writes_under_the_shared_private_evidence_directory(
    runner: ModuleType,
) -> None:
    from breezy.adapters.polymarket_us.transport import QUOTA_KEY_PORTFOLIO

    assert runner.PRIVATE_SHAPE_DIRECTORY == Path("docs/evidence/venue/polymarket_us")
    assert runner.DEFAULT_QUOTA_KEY == QUOTA_KEY_PORTFOLIO


def test_the_runner_never_reads_a_credential_value(runner: ModuleType) -> None:
    """S16 restated: nothing here unwraps a ``SecureString``."""
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"), filename=str(SCRIPT_PATH))
    offending = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr == "get_value"
    ]
    assert offending == []


def test_the_artifact_directory_is_created_with_no_public_window(
    runner: ModuleType, tmp_path: Path
) -> None:
    target = tmp_path / "nested"
    observation = runner.ProbeObservation(
        endpoint=_PRIVATE_PATH,
        http_status=200,
        grpc_code=None,
        envelope_parsed=True,
        signing_variant="path_only",
        shape={"type": "object"},
    )
    path = runner.write_probe_artifact(observation, directory=target)
    assert stat.S_IMODE(target.stat().st_mode) == 0o700
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert os.access(path, os.R_OK)
