"""Offline suite for R-6.5P -- the Polymarket.us write-SIGNING probe.

Authority: ``docs/plans/EXEC_SPINE_R65_R7_2026-09-02.md`` section 1;
``docs/plans/EXEC_SPINE_R5_R6_2026-09-02.md`` section 3 R-6.5P.

Every test here is offline: every transport is a double, every credential is
an ephemeral Ed25519 key generated in-process, and nothing can reach a venue
host. The barrier proofs (B4 exemption non-vacuity, the zero-importers pin)
live in ``tests/unit/test_polymarket_us_readonly_guard.py`` and
``tests/unit/test_cage_rule_constants_are_pinned.py``; this module pins the
probe's own behaviour.
"""

from __future__ import annotations

import ast
import asyncio
import base64
import importlib.util
import inspect
import json
import stat
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest
from nacl.signing import SigningKey
from nautilus_trader.common.component import TestClock
from nautilus_trader.core import nautilus_pyo3

from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.secure import RedactedSecureString
from breezy.adapters.polymarket_us.transport import VenueResponse

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "venue" / "polymarket_us_write_signing_probe.py"

_API_BASE = "https://api.example.invalid"
_GATEWAY_BASE = "https://gateway.example.invalid"
_KEY_ID = "11111111-2222-3333-4444-555555555555"

#: Words a reader could mistake for a conclusion about the venue (L-8).
_VERDICT_LEXICON = (
    "TRANSIENT",
    "DURABLE",
    "UNAVAILABLE",
    "verdict",
    "healthy",
    "unhealthy",
    "degraded",
    "PASS",
    "FAIL",
)


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def _load_probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "breezy_polymarket_us_write_signing_probe", SCRIPT_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def probe() -> ModuleType:
    return _load_probe()


# --------------------------------------------------------------------------
# Doubles
# --------------------------------------------------------------------------


class _SequencedReadTransport:
    """A ``PolymarketUSReadTransport`` answering from a fixed queue, in order."""

    def __init__(self, responses: list[VenueResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def get(self, url: str, *, headers: Any, quota_key: str) -> VenueResponse:
        self.calls.append({"url": url, "headers": dict(headers), "quota_key": quota_key})
        return self._responses.pop(0)


class _StubWriteClient:
    """A raw-pyo3-``HttpClient`` double exposing only ``post``."""

    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b'{"canceledOrderIds": []}',
        raises: BaseException | None = None,
    ) -> None:
        self.status = status
        self.body = body
        self.raises = raises
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, *, headers: Any, body: bytes, keys: list[str]) -> Any:
        self.calls.append({"url": url, "headers": dict(headers), "body": body, "keys": list(keys)})
        if self.raises is not None:
            raise self.raises
        return SimpleNamespace(status=self.status, body=self.body)


class _RefusingWriteClientFactory:
    """Fails if the write client is ever constructed.

    The claim under test is "the POST callable is never invoked", and the
    only honest way to assert that is to make CONSTRUCTING it an error.
    """

    def __init__(self) -> None:
        self.entered = False

    def __call__(self, config: Any) -> Any:
        self.entered = True
        raise AssertionError("write client was constructed; the write path was reached")


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


def _prepared(probe: ModuleType) -> Any:
    return probe.Prepared(core_limit=(0, 0), config=_config(), credentials=_credentials())


def test_build_read_transport_constructs_a_nautilus_http_transport(
    probe: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The probe's own builder must construct without TypeError (R-6.5b-0)."""
    from nautilus_trader.core import nautilus_pyo3

    from breezy.adapters.polymarket_us import transport as transport_module
    from breezy.adapters.polymarket_us.transport import NautilusHttpTransport

    class _FakeHttpClient:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    transport_module.build_shared_http_client._reset_for_tests()
    monkeypatch.setattr(nautilus_pyo3, "HttpClient", _FakeHttpClient)
    try:
        built = probe._build_read_transport(_config())
    finally:
        transport_module.build_shared_http_client._reset_for_tests()
    assert isinstance(built, NautilusHttpTransport)


def _clock_at(timestamp_ms: int) -> TestClock:
    clock = TestClock()
    clock.set_time(timestamp_ms * 1_000_000)
    return clock


async def _run(
    probe: ModuleType,
    *,
    positive_control: bool = False,
    read_responses: list[VenueResponse],
    write_client_factory: Any,
    tmp_path: Path,
    stamp: str | None = None,
) -> tuple[Any, _SequencedReadTransport]:
    transport = _SequencedReadTransport(read_responses)
    observation = await probe.run_probe(
        positive_control=positive_control,
        directory=tmp_path,
        stamp=stamp,
        prepare_fn=lambda env=None, *, guard=None: _prepared(probe),
        read_transport_factory=lambda config: transport,
        write_client_factory=write_client_factory,
    )
    return observation, transport


# ==========================================================================
# RED 1 -- refuses unless the pre-flight is 200 with an empty list
# ==========================================================================


@pytest.mark.asyncio
async def test_preflight_non_200_refuses_with_the_status_only_and_never_posts(
    probe: ModuleType, tmp_path: Path
) -> None:
    stub_write = _RefusingWriteClientFactory()
    observation, transport = await _run(
        probe,
        read_responses=[VenueResponse(status=503, headers={}, body=b"")],
        write_client_factory=stub_write,
        tmp_path=tmp_path,
    )
    assert observation.preflight_status == 503
    assert observation.preflight_reason == probe.PREFLIGHT_NOT_200
    assert observation.write_status is None
    assert observation.postflight_status is None
    assert stub_write.entered is False
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_preflight_non_empty_refuses_and_never_posts(
    probe: ModuleType, tmp_path: Path
) -> None:
    stub_write = _RefusingWriteClientFactory()
    observation, transport = await _run(
        probe,
        read_responses=[VenueResponse(status=200, headers={}, body=b'{"orders": [{"id": "x"}]}')],
        write_client_factory=stub_write,
        tmp_path=tmp_path,
    )
    assert observation.preflight_status == 200
    assert observation.preflight_reason == probe.PREFLIGHT_NOT_EMPTY
    assert observation.write_status is None
    assert stub_write.entered is False
    assert len(transport.calls) == 1


@pytest.mark.asyncio
async def test_full_run_issues_exactly_three_signed_requests(
    probe: ModuleType, tmp_path: Path
) -> None:
    write_client = _StubWriteClient(status=200, body=b'{"canceledOrderIds": []}')
    observation, transport = await _run(
        probe,
        read_responses=[
            VenueResponse(status=200, headers={}, body=b'{"orders": []}'),
            VenueResponse(status=200, headers={}, body=b'{"orders": []}'),
        ],
        write_client_factory=lambda config: write_client,
        tmp_path=tmp_path,
    )
    assert observation.preflight_status == 200
    assert observation.preflight_reason is None
    assert observation.write_status == 200
    assert observation.write_response_type == "dict"
    assert observation.postflight_status == 200
    assert observation.postflight_reason is None
    assert len(transport.calls) == 2
    assert len(write_client.calls) == 1
    assert len(transport.calls) + len(write_client.calls) == 3


@pytest.mark.asyncio
async def test_postflight_non_200_is_recorded_distinctly_from_preflight(
    probe: ModuleType, tmp_path: Path
) -> None:
    write_client = _StubWriteClient(status=200, body=b"{}")
    observation, _ = await _run(
        probe,
        read_responses=[
            VenueResponse(status=200, headers={}, body=b'{"orders": []}'),
            VenueResponse(status=500, headers={}, body=b""),
        ],
        write_client_factory=lambda config: write_client,
        tmp_path=tmp_path,
    )
    assert observation.postflight_status == 500
    assert observation.postflight_reason == probe.POSTFLIGHT_NOT_200


@pytest.mark.asyncio
async def test_postflight_non_empty_is_recorded_distinctly(
    probe: ModuleType, tmp_path: Path
) -> None:
    write_client = _StubWriteClient(status=200, body=b"{}")
    observation, _ = await _run(
        probe,
        read_responses=[
            VenueResponse(status=200, headers={}, body=b'{"orders": []}'),
            VenueResponse(status=200, headers={}, body=b'{"orders": [{"id": "x"}]}'),
        ],
        write_client_factory=lambda config: write_client,
        tmp_path=tmp_path,
    )
    assert observation.postflight_status == 200
    assert observation.postflight_reason == probe.POSTFLIGHT_NOT_EMPTY


# ==========================================================================
# RED 2 -- AST order check: an unfiltered GET before AND after the write
# ==========================================================================


def _ordered_probe_calls(tree: ast.AST) -> list[str]:
    calls: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in ("_signed_get_open_orders", "_signed_post_cancel_all"):
                calls.append((node.lineno, name))
    calls.sort()
    return [name for _, name in calls]


def test_the_write_is_bracketed_by_a_get_before_and_a_get_after_in_run_probe() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"), filename=str(SCRIPT_PATH))
    run_probe_fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "run_probe"
    )
    assert _ordered_probe_calls(run_probe_fn) == [
        "_signed_get_open_orders",
        "_signed_post_cancel_all",
        "_signed_get_open_orders",
    ]


def test_order_check_non_vacuity_a_reordered_write_would_fail() -> None:
    """Move the POST ahead of the pre-flight GET: the shape check must fail."""
    snippet = (
        "async def run_probe():\n"
        "    await _signed_post_cancel_all()\n"
        "    await _signed_get_open_orders()\n"
        "    await _signed_get_open_orders()\n"
    )
    tree = ast.parse(snippet)
    assert _ordered_probe_calls(tree.body[0]) != [
        "_signed_get_open_orders",
        "_signed_post_cancel_all",
        "_signed_get_open_orders",
    ]


def test_order_check_non_vacuity_a_missing_postflight_read_would_fail() -> None:
    """Delete the post-write GET: the shape check must fail."""
    snippet = (
        "async def run_probe():\n"
        "    await _signed_get_open_orders()\n"
        "    await _signed_post_cancel_all()\n"
    )
    tree = ast.parse(snippet)
    assert _ordered_probe_calls(tree.body[0]) != [
        "_signed_get_open_orders",
        "_signed_post_cancel_all",
        "_signed_get_open_orders",
    ]


# ==========================================================================
# RED 3 -- the write callable has no `query` parameter and no `body` parameter
# ==========================================================================


def test_the_write_callable_has_no_query_or_body_parameter(probe: ModuleType) -> None:
    params = set(inspect.signature(probe._signed_post_cancel_all).parameters)
    assert "query" not in params
    assert "body" not in params


# ==========================================================================
# RED 4 -- signed with the same headers, path-only canonical string, over POST
# ==========================================================================


def test_write_headers_use_the_signers_exact_header_names(probe: ModuleType) -> None:
    credentials = _credentials()
    clock = _clock_at(1_700_000_000_000)
    signer = probe.Ed25519RequestSigner.for_variant(credentials, clock=clock)

    headers = dict(probe._sign_write_headers(credentials, signer, clock))
    assert set(headers) == {
        probe.ACCESS_KEY_HEADER,
        probe.TIMESTAMP_HEADER,
        probe.SIGNATURE_HEADER,
    }


def test_write_headers_sign_the_path_only_canonical_string_over_post(probe: ModuleType) -> None:
    """OQ-M closed: the query string is never signed, even for the write."""
    seed = SigningKey.generate()
    secret_b64 = base64.b64encode(bytes(seed)).decode("ascii")
    credentials = PolymarketUSCredentials(
        key_id=RedactedSecureString(_KEY_ID),
        secret_key=RedactedSecureString(secret_b64),
    )
    clock = _clock_at(1_700_000_000_000)
    signer = probe.Ed25519RequestSigner.for_variant(credentials, clock=clock)

    headers = dict(probe._sign_write_headers(credentials, signer, clock))
    timestamp_ms = int(headers[probe.TIMESTAMP_HEADER])
    canonical = probe.build_canonical_path_without_query(
        probe.CanonicalRequest(
            timestamp_ms=timestamp_ms, method="POST", path=probe._CANCEL_ALL_PATH
        )
    )
    signature = base64.b64decode(headers[probe.SIGNATURE_HEADER])
    seed.verify_key.verify(canonical, signature)  # raises BadSignatureError if wrong


def test_the_write_path_never_calls_sign_headers(probe: ModuleType) -> None:
    """``sign_headers`` refuses POST (B2); the write path must not call it.

    Scans CALL nodes only -- not source text -- so this module's own
    docstrings, which name ``sign_headers`` in prose, cannot trip it.
    """
    for fn in (probe._sign_write_headers, probe._signed_post_cancel_all):
        tree = ast.parse(inspect.getsource(fn))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
                assert name != "sign_headers", f"{fn.__name__} calls sign_headers()"


def test_permitted_methods_is_unchanged_and_read_not_copied(probe: ModuleType) -> None:
    from breezy.adapters.polymarket_us.signing import PERMITTED_METHODS

    assert probe.PERMITTED_METHODS is PERMITTED_METHODS
    assert probe.PERMITTED_METHODS == frozenset({"GET"})


# ==========================================================================
# RED 5 (D1) -- two DISTINCT reason codes, and no artefact carries a length
# ==========================================================================


@pytest.mark.asyncio
async def test_a_503_preflight_and_a_non_empty_200_preflight_differ(
    probe: ModuleType, tmp_path: Path
) -> None:
    stub_write = _RefusingWriteClientFactory()
    not_200, _ = await _run(
        probe,
        read_responses=[VenueResponse(status=503, headers={}, body=b"")],
        write_client_factory=stub_write,
        tmp_path=tmp_path,
    )
    not_empty, _ = await _run(
        probe,
        read_responses=[VenueResponse(status=200, headers={}, body=b'{"orders": [{"id": "x"}]}')],
        write_client_factory=stub_write,
        tmp_path=tmp_path,
    )
    assert not_200.preflight_reason != not_empty.preflight_reason
    assert {not_200.preflight_reason, not_empty.preflight_reason} == {
        probe.PREFLIGHT_NOT_200,
        probe.PREFLIGHT_NOT_EMPTY,
    }

    document = probe.observation_document(not_empty)
    rendered = json.dumps(document)
    assert "1" not in rendered.replace(not_200.preflight_status.__str__(), "")  # no length leaks
    for forbidden in ("length", "count", "len("):
        assert forbidden not in json.dumps(document).lower()


# ==========================================================================
# Positive control (D1)
# ==========================================================================


@pytest.mark.asyncio
async def test_positive_control_success_refuses_not_empty_and_never_posts(
    probe: ModuleType, tmp_path: Path
) -> None:
    stub_write = _RefusingWriteClientFactory()
    observation, _ = await _run(
        probe,
        positive_control=True,
        read_responses=[VenueResponse(status=200, headers={}, body=b'{"orders": [{"id": "x"}]}')],
        write_client_factory=stub_write,
        tmp_path=tmp_path,
    )
    assert observation.preflight_reason == probe.PREFLIGHT_NOT_EMPTY
    assert stub_write.entered is False


@pytest.mark.asyncio
async def test_positive_control_failure_raises_oqb_no_and_never_posts(
    probe: ModuleType, tmp_path: Path
) -> None:
    stub_write = _RefusingWriteClientFactory()
    with pytest.raises(probe.ProbeRefusal) as excinfo:
        await _run(
            probe,
            positive_control=True,
            read_responses=[VenueResponse(status=200, headers={}, body=b'{"orders": []}')],
            write_client_factory=stub_write,
            tmp_path=tmp_path,
        )
    assert probe.OQB_NO in str(excinfo.value)
    assert stub_write.entered is False


# ==========================================================================
# Narrow excepts only -- two distinct error types, CancelledError propagates
# ==========================================================================


@pytest.mark.asyncio
async def test_http_error_raises_the_write_transport_error_type(probe: ModuleType) -> None:
    write_client = _StubWriteClient(raises=nautilus_pyo3.HttpError("boom"))
    credentials = _credentials()
    clock = _clock_at(1_700_000_000_000)
    signer = probe.Ed25519RequestSigner.for_variant(credentials, clock=clock)
    with pytest.raises(probe.WriteTransportError):
        await probe._signed_post_cancel_all(write_client, _API_BASE, credentials, signer, clock)


@pytest.mark.asyncio
async def test_http_timeout_error_raises_a_distinct_timeout_type(probe: ModuleType) -> None:
    write_client = _StubWriteClient(raises=nautilus_pyo3.HttpTimeoutError("timed out"))
    credentials = _credentials()
    clock = _clock_at(1_700_000_000_000)
    signer = probe.Ed25519RequestSigner.for_variant(credentials, clock=clock)
    with pytest.raises(probe.WriteTimeoutError):
        await probe._signed_post_cancel_all(write_client, _API_BASE, credentials, signer, clock)
    assert probe.WriteTimeoutError is not probe.WriteTransportError


@pytest.mark.asyncio
async def test_cancelled_error_propagates_uncaught(probe: ModuleType) -> None:
    write_client = _StubWriteClient(raises=asyncio.CancelledError())
    credentials = _credentials()
    clock = _clock_at(1_700_000_000_000)
    signer = probe.Ed25519RequestSigner.for_variant(credentials, clock=clock)
    with pytest.raises(asyncio.CancelledError):
        await probe._signed_post_cancel_all(write_client, _API_BASE, credentials, signer, clock)


def test_no_bare_except_exception_or_baseexception_in_the_write_path(probe: ModuleType) -> None:
    """Scoped to the write path only.

    ``write_probe_artifact`` legitimately catches ``BaseException`` around
    ``os.fdopen`` to avoid an fd leak -- the same pattern R-5R-0's own writer
    uses -- which is a file-handle safety net, not a venue-transport catch,
    and is out of scope for this rule.
    """
    source = inspect.getsource(probe._signed_post_cancel_all)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is not None:
            if isinstance(node.type, ast.Tuple):
                names = [getattr(elt, "id", "") for elt in node.type.elts]
            else:
                names = [getattr(node.type, "id", "")]
            assert "Exception" not in names, node.lineno
            assert "BaseException" not in names, node.lineno


# ==========================================================================
# Value-free artefact: closed 7-field schema, no verdict lexicon, 0600/0700
# ==========================================================================


def test_document_schema_is_closed_to_exactly_seven_fields(probe: ModuleType) -> None:
    assert len(probe.PROBE_DOCUMENT_FIELDS) == 7


@pytest.mark.asyncio
async def test_artifact_is_value_free_carries_no_verdict_word_and_is_0600(
    probe: ModuleType, tmp_path: Path
) -> None:
    write_client = _StubWriteClient(
        status=200, body=b'{"canceledOrderIds": ["a", "b", "c", "d", "e"]}'
    )
    observation, _ = await _run(
        probe,
        read_responses=[
            VenueResponse(status=200, headers={}, body=b'{"orders": []}'),
            VenueResponse(status=200, headers={}, body=b'{"orders": []}'),
        ],
        write_client_factory=lambda config: write_client,
        tmp_path=tmp_path,
    )
    path = probe.write_probe_artifact(observation, directory=tmp_path)
    text = path.read_text(encoding="utf-8")
    document = json.loads(text)

    assert set(document) == set(probe.PROBE_DOCUMENT_FIELDS)
    assert "canceledOrderIds" not in text
    assert '"a"' not in text and '"e"' not in text

    leaked = [word for word in _VERDICT_LEXICON if word in text]
    assert leaked == [], f"artefact states a conclusion rather than an observation: {leaked}"

    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600
    dir_mode = stat.S_IMODE(tmp_path.stat().st_mode)
    assert dir_mode == 0o700
    assert path.name.startswith(probe.PRIVATE_ARTIFACT_PREFIX)


def test_a_document_missing_a_required_field_is_refused(probe: ModuleType) -> None:
    broken = probe.ProbeObservation(
        preflight_status=200,
        preflight_reason=None,
        write_status=200,
        write_response_type="dict",
        postflight_status=200,
        postflight_reason=None,
    )
    document = probe.observation_document(broken)
    document.pop("write_status")
    assert set(document) != probe.PROBE_DOCUMENT_FIELDS


# ==========================================================================
# Security review follow-up -- durable write-ahead marker across interruption
# ==========================================================================


@pytest.mark.asyncio
async def test_a_keyboard_interrupt_during_the_post_leaves_a_write_attempted_marker(
    probe: ModuleType, tmp_path: Path
) -> None:
    """Ctrl-C between the POST and the post-flight GET must not look like nothing happened."""
    write_client = _StubWriteClient(raises=KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        await _run(
            probe,
            read_responses=[VenueResponse(status=200, headers={}, body=b'{"orders": []}')],
            write_client_factory=lambda config: write_client,
            tmp_path=tmp_path,
        )
    marker_path = tmp_path / probe.probe_intent_marker_filename()
    assert marker_path.exists()
    text = marker_path.read_text(encoding="utf-8")
    assert probe.INTENT_MARKER_TOKEN in text
    assert stat.S_IMODE(marker_path.stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_a_postflight_failure_leaves_the_final_artefact_marked_interrupted(
    probe: ModuleType, tmp_path: Path
) -> None:
    """A post-flight transport fault must not be silently lost -- the artefact records it."""

    class _RaisingSecondReadTransport(_SequencedReadTransport):
        async def get(self, url: str, *, headers: Any, quota_key: str) -> VenueResponse:
            if not self.calls:
                return await super().get(url, headers=headers, quota_key=quota_key)
            self.calls.append({"url": url, "headers": dict(headers), "quota_key": quota_key})
            raise RuntimeError("post-flight transport fault")

    write_client = _StubWriteClient(status=200, body=b'{"canceledOrderIds": []}')
    transport = _RaisingSecondReadTransport(
        [VenueResponse(status=200, headers={}, body=b'{"orders": []}')]
    )
    with pytest.raises(RuntimeError):
        await probe.run_probe(
            directory=tmp_path,
            prepare_fn=lambda env=None, *, guard=None: _prepared(probe),
            read_transport_factory=lambda config: transport,
            write_client_factory=lambda config: write_client,
        )
    path = tmp_path / probe.probe_artifact_filename()
    assert path.exists()
    document = json.loads(path.read_text(encoding="utf-8"))
    assert set(document) == set(probe.PROBE_DOCUMENT_FIELDS)
    assert document["postflight_reason"] == probe.INTERRUPTED
    assert document["write_status"] == 200


def test_the_seven_field_schema_is_unchanged_by_the_interruption_fix(probe: ModuleType) -> None:
    """INTERRUPTED is a new VALUE of postflight_reason, not a new field."""
    assert len(probe.PROBE_DOCUMENT_FIELDS) == 7
