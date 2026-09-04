"""The Polymarket.us write-SIGNING probe, evidence-only (EXEC SPINE / R-OP-SEQ).

Authority: ``docs/plans/EXEC_SPINE_R65_R7_2026-09-02.md`` section 1 (R-6.5P
origin); ``docs/plans/OP_SEQ_BOT_POSITIVE_CONTROL_2026-09-04.md`` (R-OP-SEQ,
``--sequence``).

**What this answers.** OQ-D: does this repo's Ed25519 signer -- unmodified,
GET-only by construction (``PERMITTED_METHODS``, barrier B2) -- produce a
canonical string the venue accepts on a WRITE verb? The POST is signed by
hand, using the same public canonical-string builder
(:func:`~breezy.adapters.polymarket_us.signing.build_canonical_path_without_query`,
OQ-M closed: the query string is never signed) and the same private
key-loading helper the signer itself uses, over ``method="POST"`` -- a value
``sign_headers`` itself would refuse to sign. Nothing here widens
``PERMITTED_METHODS`` or touches ``signing.py``.

**Two modes.** ``--positive-control`` (legacy, R-6.5P): the operator rests a
BUY 1@$0.01 by hand; the probe must refuse at the pre-flight with
:data:`PREFLIGHT_NOT_EMPTY`, and issues ``POST /v1/orders/open/cancel``
(cancel-all) on its one write path once the account is proven flat.
``--sequence`` (R-OP-SEQ): the bot rests its OWN control
(``POST /v1/orders``), enumerates it, cancels it, and re-verifies flat --
S0-S6 in :func:`run_sequence`. Both modes share the hard safety gate: REFUSE
past pre-flight unless an unfiltered ``GET /v1/orders/open`` is 200-and-empty,
held to the same standard post-write. Reason codes never carry a count or a
length; emptiness is decided in memory and never written down.

**Value-free artefacts, closed schemas (L-8).** v1 (7 fields, legacy) and v2
(13 fields, sequence) carry only statuses, reason codes, response *type
names*, and (v2) the computed verdict -- never a body, a count, an order id,
or a list length. ``PRIVATE_``-prefixed, ``0600`` under a ``0700`` directory.

**Narrow excepts only.** POST transport failures are caught as
``except (nautilus_pyo3.HttpError, nautilus_pyo3.HttpTimeoutError)`` --
never bare ``Exception``/``BaseException`` -- as two DISTINCT Breezy-owned
types. ``asyncio.CancelledError`` propagates uncaught.

**The one B4 exemption.** This script builds a second, raw
``nautilus_pyo3.HttpClient`` for its writes -- exactly what barrier B4 exists
to catch, and this file is the plan family's one deliberate, reviewed
exemption from it (``tests/unit/test_polymarket_us_readonly_guard.py``'s
``B4_EXEMPT_PATHS``, ``tests/unit/test_cage_rule_constants_are_pinned.py``'s
``CAGE_EXEMPTIONS``). Not importable by the trading process (scripts are not
a package); a zero-importers pin keeps it that way. Instrument selection,
body-building, schema/artefact rendering and writing live in the pure sibling
module ``_write_sequence.py`` -- local disk I/O only, zero venue egress, so
it needs no exemption of its own.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import fields
from pathlib import Path
from typing import Any, Final

from nautilus_trader.core import nautilus_pyo3

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_DIRECTORY = Path(__file__).resolve().parent
for _entry in (REPO_ROOT / "src", _SCRIPT_DIRECTORY):  # pragma: no cover - bootstrap
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from _write_sequence import (
    CLOSED_NO,
    CLOSED_YES_BOTH_VERBS,
    INCONCLUSIVE,
    INTENT_MARKER_TOKEN,
    MARKER_DOCUMENT_FIELDS,
    PRIVATE_ARTIFACT_PREFIX,
    PRIVATE_SHAPE_DIRECTORY,
    PROBE_DOCUMENT_FIELDS,
    SEQUENCE_DOCUMENT_FIELDS,
    ArtifactSchemaError,
    CollectingLog,
    ProbeObservation,
    ProbeRefusal,
    SequenceObservation,
    build_control_order_body,
    classify_enumeration,
    compute_verdict,
    is_empty_open_orders,
    json_top_level_type,
    market_list_query,
    observation_document,
    probe_artifact_filename,
    probe_intent_marker_filename,
    render_probe_report,
    select_control_instrument,
    sequence_artifact_filename,
    write_intent_marker,
    write_probe_artifact,
    write_sequence_artifact,
)
from polymarket_us_auth_smoke import (
    POST_CREDENTIAL_SUPPRESSION_NOTE,
    CredentialGuard,
    Prepared,
    RecordingTransport,
    SmokeRefusal,
    build_safe_excepthook,
    describe_exception,
    prepare,
)

from breezy.adapters.polymarket_us.config import PolymarketUSMarketDiscoveryConfig
from breezy.adapters.polymarket_us.credentials import PolymarketUSCredentials
from breezy.adapters.polymarket_us.errors import PolymarketUSError
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.signing import (
    ACCESS_KEY_HEADER,
    PERMITTED_METHODS,
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    CanonicalRequest,
    Ed25519RequestSigner,
    SigningVariant,
    _load_signing_key,
    build_canonical_path_without_query,
)
from breezy.adapters.polymarket_us.transport import (
    QUOTA_KEY_DISCOVERY,
    QUOTA_KEY_PORTFOLIO,
    NautilusHttpTransport,
    PolymarketUSReadTransport,
    build_default_quota,
    build_keyed_quotas,
    build_shared_http_client,
)

__all__ = [
    "CANCEL_NOT_OK",
    "CLOSED_NO",
    "CLOSED_YES_BOTH_VERBS",
    "CONTROL_FILLED",
    "INCONCLUSIVE",
    "INTENT_MARKER_TOKEN",
    "INTERRUPTED",
    "MARKER_DOCUMENT_FIELDS",
    "NO_ELIGIBLE_INSTRUMENT",
    "OQB_NO",
    "PERMITTED_METHODS",
    "POSTFLIGHT_NOT_200",
    "POSTFLIGHT_NOT_EMPTY",
    "PREFLIGHT_NOT_200",
    "PREFLIGHT_NOT_EMPTY",
    "PRIVATE_ARTIFACT_PREFIX",
    "PRIVATE_SHAPE_DIRECTORY",
    "PROBE_DOCUMENT_FIELDS",
    "REST_AMBIGUOUS",
    "REST_UNAUTHORIZED",
    "SEQUENCE_DOCUMENT_FIELDS",
    "ArtifactSchemaError",
    "ProbeObservation",
    "ProbeRefusal",
    "SequenceObservation",
    "WriteTimeoutError",
    "WriteTransportError",
    "main",
    "observation_document",
    "parse_args",
    "probe_artifact_filename",
    "probe_intent_marker_filename",
    "render_probe_report",
    "run_probe",
    "run_sequence",
    "sequence_artifact_filename",
    "write_probe_artifact",
    "write_sequence_artifact",
]

#: Endpoints this probe touches. Hardcoded (D4 exemption): auditable at a glance.
_OPEN_ORDERS_PATH: Final[str] = "/v1/orders/open"
_CANCEL_ALL_PATH: Final[str] = "/v1/orders/open/cancel"
_ORDERS_PATH: Final[str] = "/v1/orders"
_MARKET_LIST_PATH: Final[str] = "/v1/markets"

#: Paths this file signs a POST for; enforced by ``_sign_write_headers``/``_signed_post``.
_SIGNABLE_WRITE_PATHS: Final[frozenset[str]] = frozenset({_CANCEL_ALL_PATH, _ORDERS_PATH})

_WRITE_QUOTA_KEY: Final[str] = QUOTA_KEY_PORTFOLIO
_ENUMERATION_RETRY_SLEEP_SECS: Final[float] = 0.25  # S4's one bounded re-read delay

#: D1's pre-/post-flight reason codes. Never carry a count or a length.
PREFLIGHT_NOT_200: Final[str] = "PREFLIGHT_NOT_200"
PREFLIGHT_NOT_EMPTY: Final[str] = "PREFLIGHT_NOT_EMPTY"
POSTFLIGHT_NOT_200: Final[str] = "POSTFLIGHT_NOT_200"
POSTFLIGHT_NOT_EMPTY: Final[str] = "POSTFLIGHT_NOT_EMPTY"
#: D1's positive-control failure: the venue did not enumerate an order Breezy
#: never placed; also reused for R-OP-SEQ's S4 "id absent" branch.
OQB_NO: Final[str] = "OQB_NO"
#: The process was interrupted between a write and the post-flight GET. A
#: VALUE of ``postflight_reason``, not a new field.
INTERRUPTED: Final[str] = "INTERRUPTED"

#: R-OP-SEQ stop codes (S2-S5 of the bot-driven positive-control sequence).
NO_ELIGIBLE_INSTRUMENT: Final[str] = "NO_ELIGIBLE_INSTRUMENT"
REST_UNAUTHORIZED: Final[str] = "REST_UNAUTHORIZED"
REST_AMBIGUOUS: Final[str] = "REST_AMBIGUOUS"
CONTROL_FILLED: Final[str] = "CONTROL_FILLED"
CANCEL_NOT_OK: Final[str] = "CANCEL_NOT_OK"


class WriteTransportError(PolymarketUSError):
    """A write failed at the transport layer (``nautilus_pyo3.HttpError``)."""


class WriteTimeoutError(PolymarketUSError):
    """A write timed out at the transport layer. Kept DISTINCT from
    :class:`WriteTransportError` rather than collapsed into one type."""


def _build_read_transport(config: Any) -> PolymarketUSReadTransport:
    """The shipped GET-only transport, budgeted exactly as the smoke budgets it."""
    client = build_shared_http_client(
        timeout_secs=config.http_timeout_secs,
        default_quota=build_default_quota(config.global_requests_per_second),
        keyed_quotas=build_keyed_quotas(
            instrument_requests_per_minute=config.instrument_requests_per_minute,
            book_requests_per_minute=config.book_requests_per_minute,
        ),
        default_headers={"User-Agent": str(config.user_agent)},
    )
    return NautilusHttpTransport(client=client)


def _build_write_client(config: Any) -> Any:
    """A SECOND, raw pyo3 client for writes -- NOT ``NautilusHttpTransport``,
    which has no ``post`` (barrier B3). Write capability stays in this one
    exempted file."""
    return nautilus_pyo3.HttpClient(
        default_headers={"User-Agent": str(config.user_agent)},
        header_keys=[],
        keyed_quotas=[],
        default_quota=build_default_quota(config.global_requests_per_second),
        timeout_secs=int(config.http_timeout_secs),
    )


async def _signed_get_open_orders(
    client: PolymarketUSHttpClient, transport: RecordingTransport
) -> tuple[int | None, bytes | None]:
    """One unfiltered ``GET /v1/orders/open``. Never raises -- only
    :class:`PolymarketUSError` is absorbed."""
    try:
        await client.get_authenticated(_OPEN_ORDERS_PATH, quota_key=_WRITE_QUOTA_KEY)
    except PolymarketUSError:
        pass
    event = transport.last()
    response = None if event is None else event.response
    status = None if response is None else response.status
    body = None if response is None else response.body
    return status, body


def _sign_write_headers(
    credentials: PolymarketUSCredentials,
    signer: Ed25519RequestSigner,
    clock: Any,
    *,
    path: str = _CANCEL_ALL_PATH,
) -> list[tuple[str, str]]:
    """Sign a POST the way ``sign_headers`` signs a GET, minus barrier B2 --
    same canonical builder, same key loader, same headers, over ``POST``.
    ``path`` is constrained to :data:`_SIGNABLE_WRITE_PATHS`; the default
    preserves the legacy cancel-all-only behaviour byte-for-byte."""
    if path not in _SIGNABLE_WRITE_PATHS:
        raise ValueError(f"refusing to sign an unrecognised write path: {path!r}")
    timestamp_ms = clock.timestamp_ms()
    signer.assert_within_window(timestamp_ms)
    canonical = build_canonical_path_without_query(
        CanonicalRequest(timestamp_ms=timestamp_ms, method="POST", path=path)
    )
    signing_key = _load_signing_key(credentials.secret_key.get_value())
    signature = base64.b64encode(signing_key.sign(canonical).signature).decode("ascii")
    return [
        (ACCESS_KEY_HEADER, credentials.key_id.get_value()),
        (TIMESTAMP_HEADER, str(timestamp_ms)),
        (SIGNATURE_HEADER, signature),
    ]


async def _signed_post(
    write_client: Any,
    api_base_url: str,
    credentials: PolymarketUSCredentials,
    signer: Ed25519RequestSigner,
    clock: Any,
    *,
    path: str,
    body: Mapping[str, Any],
) -> tuple[int, str | None, bytes | None]:
    """The ONE signed-POST primitive. Computes the canonical string AND the
    URL from ``path``, validated against :data:`_SIGNABLE_WRITE_PATHS`, no
    query. The two wrappers below are thin, body-fixed callers -- no second
    egress path."""
    if path not in _SIGNABLE_WRITE_PATHS:
        raise ValueError(f"refusing to POST an unrecognised write path: {path!r}")
    headers = dict(_sign_write_headers(credentials, signer, clock, path=path))
    headers["Content-Type"] = "application/json"
    url = f"{api_base_url.rstrip('/')}{path}"
    try:
        response = await write_client.post(
            url,
            headers=headers,
            body=json.dumps(body).encode("ascii"),
            keys=[_WRITE_QUOTA_KEY],
        )
    except (nautilus_pyo3.HttpError, nautilus_pyo3.HttpTimeoutError) as exc:
        if isinstance(exc, nautilus_pyo3.HttpTimeoutError):
            raise WriteTimeoutError(f"POST {path} timed out at the transport layer") from None
        raise WriteTransportError(
            f"POST {path} failed at the transport layer: {type(exc).__name__}"
        ) from None
    response_body = bytes(response.body)
    return int(response.status), json_top_level_type(response_body), response_body


async def _signed_post_cancel_all(
    write_client: Any,
    api_base_url: str,
    credentials: PolymarketUSCredentials,
    signer: Ed25519RequestSigner,
    clock: Any,
) -> tuple[int, str | None]:
    """The legacy write (R-6.5P). No ``query``/``body`` parameter -- both
    refused by construction, never accepted from a caller."""
    status, response_type, _body = await _signed_post(
        write_client, api_base_url, credentials, signer, clock, path=_CANCEL_ALL_PATH, body={}
    )
    return status, response_type


def _extract_order_id(body: bytes | None) -> str | None:
    """The create-order response's ``id`` field, read once, never persisted."""
    if not body:
        return None
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    order_id = payload.get("id")
    return order_id if isinstance(order_id, str) and order_id else None


async def _signed_post_order(
    write_client: Any,
    api_base_url: str,
    credentials: PolymarketUSCredentials,
    signer: Ed25519RequestSigner,
    clock: Any,
    *,
    slug: str,
) -> tuple[int, str | None, str | None]:
    """The S3 control write. Takes a slug, never caller bytes -- the body is
    built in-function by :func:`build_control_order_body`."""
    status, response_type, body = await _signed_post(
        write_client,
        api_base_url,
        credentials,
        signer,
        clock,
        path=_ORDERS_PATH,
        body=build_control_order_body(slug),
    )
    return status, response_type, _extract_order_id(body)


#: ``probe_intent_marker_filename``, ``write_intent_marker`` and
#: ``MARKER_DOCUMENT_FIELDS`` (converged review item 6) live in
#: ``_write_sequence`` -- local disk I/O only, no venue egress.


async def run_probe(
    *,
    positive_control: bool = False,
    env: Mapping[str, str] | None = None,
    directory: Path = PRIVATE_SHAPE_DIRECTORY,
    stamp: str | None = None,
    guard: CredentialGuard | None = None,
    prepare_fn: Callable[..., Prepared] = prepare,
    read_transport_factory: Callable[[Any], PolymarketUSReadTransport] = _build_read_transport,
    write_client_factory: Callable[[Any], Any] = _build_write_client,
) -> ProbeObservation:
    """Run the legacy probe end to end: pre-flight GET, one POST,
    post-flight GET, in that order. Every refusal path issues strictly
    fewer requests."""
    from nautilus_trader.common.component import LiveClock

    filename = probe_artifact_filename(stamp=stamp)
    if (directory / filename).exists():
        raise FileExistsError(
            f"{directory / filename} already exists; supply a new --stamp."
        )

    prepared = prepare_fn(env, guard=guard)
    config = prepared.config
    credentials = prepared.credentials
    clock = LiveClock()
    variant = SigningVariant(config.signing_variant)
    signer = Ed25519RequestSigner.for_variant(credentials, clock=clock, variant=variant)

    read_transport = RecordingTransport(inner=read_transport_factory(config))
    read_client = PolymarketUSHttpClient(
        transport=read_transport,
        signer=signer,
        api_base_url=str(config.api_base_url),
        gateway_base_url=str(config.gateway_base_url),
        logger=CollectingLog(),
    )

    def _obs(**overrides: Any) -> ProbeObservation:
        fields: dict[str, Any] = {
            "preflight_status": None,
            "preflight_reason": None,
            "write_status": None,
            "write_response_type": None,
            "postflight_status": None,
            "postflight_reason": None,
        }
        fields.update(overrides)
        return ProbeObservation(**fields)

    # --- pre-flight: unfiltered GET, before any write is attempted ---------
    preflight_status, preflight_body = await _signed_get_open_orders(read_client, read_transport)
    if preflight_status != 200:
        return _obs(preflight_status=preflight_status, preflight_reason=PREFLIGHT_NOT_200)
    if not is_empty_open_orders(preflight_body):
        return _obs(preflight_status=preflight_status, preflight_reason=PREFLIGHT_NOT_EMPTY)
    if positive_control:
        # The positive-control order was NOT enumerated: OQ-B is answered NO.
        # The write client is never constructed and the POST is never issued.
        raise ProbeRefusal(
            f"{OQB_NO}: an unfiltered GET /v1/orders/open reported an empty "
            "list with the positive-control order supposedly resting. The "
            "venue did not enumerate an order Breezy did not place; OQ-B is "
            "answered NO and R-6.5P is dead as designed. No POST was issued."
        )

    # --- the write: exactly one signed POST, reached only 200-and-empty ----
    # Written BEFORE the POST: if the process is interrupted anywhere from
    # here to the final artefact write, this durable marker is what proves a
    # live cancel-all fired, rather than leaving the operator believing
    # nothing happened.
    write_intent_marker(directory=directory, stamp=stamp, paths=(_CANCEL_ALL_PATH,))
    write_client = write_client_factory(config)

    write_status: int | None = None
    write_response_type: str | None = None
    try:
        write_status, write_response_type = await _signed_post_cancel_all(
            write_client,
            str(config.api_base_url),
            credentials,
            signer,
            clock,
        )

        # --- post-flight: the same unfiltered GET, held to the same standard
        postflight_status, postflight_body = await _signed_get_open_orders(
            read_client, read_transport
        )
    except BaseException:  # never swallowed: partial artefact, then re-raise
        write_probe_artifact(
            _obs(
                preflight_status=preflight_status,
                write_status=write_status,
                write_response_type=write_response_type,
                postflight_reason=INTERRUPTED,
            ),
            directory=directory,
            stamp=stamp,
        )
        raise

    postflight_reason: str | None
    if postflight_status != 200:
        postflight_reason = POSTFLIGHT_NOT_200
    elif not is_empty_open_orders(postflight_body):
        postflight_reason = POSTFLIGHT_NOT_EMPTY
    else:
        postflight_reason = None

    return _obs(
        preflight_status=preflight_status,
        write_status=write_status,
        write_response_type=write_response_type,
        postflight_status=postflight_status,
        postflight_reason=postflight_reason,
    )


#: ``probe_artifact_filename``, ``observation_document``, ``render_probe_report``,
#: ``write_probe_artifact``, ``sequence_artifact_filename`` and
#: ``write_sequence_artifact`` all live in ``_write_sequence`` -- local disk
#: I/O only, no venue egress, so no B4 exemption is needed for them.


async def _enumerate_control_with_retry(
    read_client: PolymarketUSHttpClient,
    read_transport: RecordingTransport,
    *,
    order_id: str,
    sleep: Callable[[float], Awaitable[None]],
) -> tuple[int | None, str]:
    """S4: one enumeration read, plus exactly one bounded 250ms retry before
    OQB_NO -- read-your-writes consistency is not venue-documented. Never a
    loop, never adaptive backoff."""
    status, body = await _signed_get_open_orders(read_client, read_transport)
    kind = classify_enumeration(status, body, order_id)
    if kind == "absent":
        await sleep(_ENUMERATION_RETRY_SLEEP_SECS)
        status, body = await _signed_get_open_orders(read_client, read_transport)
        kind = classify_enumeration(status, body, order_id)
    return status, kind


def _cancel_ok(cancel_status: int | None, cancel_response_type: str | None) -> bool:
    """S5 pass: 200, or non-401/403 carrying a ``CancelAllOrdersResponse``-shaped body."""
    if cancel_status == 200:
        return True
    return cancel_status not in (401, 403) and cancel_response_type == "dict"


async def run_sequence(
    *,
    env: Mapping[str, str] | None = None,
    directory: Path = PRIVATE_SHAPE_DIRECTORY,
    stamp: str | None = None,
    guard: CredentialGuard | None = None,
    prepare_fn: Callable[..., Prepared] = prepare,
    read_transport_factory: Callable[[Any], PolymarketUSReadTransport] = _build_read_transport,
    write_client_factory: Callable[[Any], Any] = _build_write_client,
    discovery: PolymarketUSMarketDiscoveryConfig | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> SequenceObservation:
    """Run the bot-driven positive-control sequence S0-S6, in order. Every
    stop is terminal (except S4's one bounded re-read). S2 (no eligible
    instrument) raises without writing an artefact; every other stop returns
    an observation for the caller to persist."""
    from nautilus_trader.common.component import LiveClock

    if discovery is None:
        discovery = PolymarketUSMarketDiscoveryConfig()
    filename = sequence_artifact_filename(stamp=stamp)
    if (directory / filename).exists():
        raise FileExistsError(
            f"{directory / filename} already exists; supply a new --stamp."
        )

    prepared = prepare_fn(env, guard=guard)
    config = prepared.config
    credentials = prepared.credentials
    clock = LiveClock()
    variant = SigningVariant(config.signing_variant)
    signer = Ed25519RequestSigner.for_variant(credentials, clock=clock, variant=variant)

    read_transport = RecordingTransport(inner=read_transport_factory(config))
    read_client = PolymarketUSHttpClient(
        transport=read_transport,
        signer=signer,
        api_base_url=str(config.api_base_url),
        gateway_base_url=str(config.gateway_base_url),
        logger=CollectingLog(),
    )

    def _obs(**overrides: Any) -> SequenceObservation:
        """Build one observation. Every field defaults to ``None``/``INCONCLUSIVE``."""
        fields: dict[str, Any] = {
            "preflight_status": None,
            "preflight_reason": None,
            "selection_reason": None,
            "rest_status": None,
            "rest_reason": None,
            "enumeration_status": None,
            "enumeration_reason": None,
            "cancel_status": None,
            "cancel_response_type": None,
            "postflight_status": None,
            "postflight_reason": None,
            "verdict": INCONCLUSIVE,
        }
        fields.update(overrides)
        return SequenceObservation(**fields)

    # --- S1: pre-flight, unfiltered, before any write is attempted --------
    preflight_status, preflight_body = await _signed_get_open_orders(read_client, read_transport)
    if preflight_status != 200:
        return _obs(preflight_status=preflight_status, preflight_reason=PREFLIGHT_NOT_200)
    if not is_empty_open_orders(preflight_body):
        return _obs(preflight_status=preflight_status, preflight_reason=PREFLIGHT_NOT_EMPTY)

    # --- S2: instrument selection, one PUBLIC read -------------------------
    market_payload = await read_client.get_public(
        _MARKET_LIST_PATH,
        query=market_list_query(discovery),
        quota_key=QUOTA_KEY_DISCOVERY,
    )
    slug = select_control_instrument(market_payload, city_codes=discovery.city_codes)
    if slug is None:
        raise ProbeRefusal(
            f"{NO_ELIGIBLE_INSTRUMENT}: no weather-bucket market satisfied the eligibility "
            "rules (not resolved/closed, ask >= $0.20, tick $0.01, min qty <= 1). No POST "
            "was issued; no artefact was written."
        )

    # --- S3 onward: the write-ahead marker, then the first write ----------
    write_intent_marker(directory=directory, stamp=stamp, paths=(_ORDERS_PATH, _CANCEL_ALL_PATH))
    write_client = write_client_factory(config)

    rest_status: int | None = None
    order_id: str | None = None
    enumeration_status: int | None = None
    enumeration_reason: str | None = None
    cancel_status: int | None = None
    cancel_response_type: str | None = None
    try:
        rest_status, _rest_response_type, order_id = await _signed_post_order(
            write_client, str(config.api_base_url), credentials, signer, clock, slug=slug
        )

        if rest_status in (401, 403):
            return _obs(
                preflight_status=preflight_status,
                rest_status=rest_status,
                rest_reason=REST_UNAUTHORIZED,
                verdict=CLOSED_NO,
            )

        order_id_present = rest_status == 200 and order_id is not None
        rest_reason: str | None = None if order_id_present else REST_AMBIGUOUS
        enumeration_ok = False

        if order_id_present:
            assert order_id is not None
            enumeration_status, kind = await _enumerate_control_with_retry(
                read_client, read_transport, order_id=order_id, sleep=sleep
            )
            if kind == "absent":
                enumeration_reason = OQB_NO
            elif kind == "filled":
                enumeration_reason = CONTROL_FILLED
            else:
                enumeration_ok = True

        # --- S5: cleanup cancel-all, issued whenever S3 was not a clean 401/403
        cancel_status, cancel_response_type = await _signed_post_cancel_all(
            write_client, str(config.api_base_url), credentials, signer, clock
        )
        cancel_ok = _cancel_ok(cancel_status, cancel_response_type)

        # --- S6: post-flight, held to the same standard as S1 -------------
        postflight_status, postflight_body = await _signed_get_open_orders(
            read_client, read_transport
        )
    except BaseException:
        write_sequence_artifact(
            _obs(
                preflight_status=preflight_status,
                rest_status=rest_status,
                enumeration_status=enumeration_status,
                enumeration_reason=enumeration_reason,
                cancel_status=cancel_status,
                cancel_response_type=cancel_response_type,
                postflight_reason=INTERRUPTED,
            ),
            directory=directory,
            stamp=stamp,
        )
        raise

    if postflight_status != 200:
        postflight_reason: str | None = POSTFLIGHT_NOT_200
    elif not is_empty_open_orders(postflight_body):
        postflight_reason = POSTFLIGHT_NOT_EMPTY
    else:
        postflight_reason = None
    postflight_ok = postflight_reason is None

    verdict = compute_verdict(
        rest_status=rest_status,
        order_id_present=order_id_present,
        enumeration_ok=enumeration_ok,
        cancel_ok=cancel_ok,
        postflight_ok=postflight_ok,
    )

    return _obs(
        preflight_status=preflight_status,
        rest_status=rest_status,
        rest_reason=rest_reason,
        enumeration_status=enumeration_status,
        enumeration_reason=enumeration_reason,
        cancel_status=cancel_status,
        cancel_response_type=cancel_response_type,
        postflight_status=postflight_status,
        postflight_reason=postflight_reason,
        verdict=verdict,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument(
        "--positive-control",
        action="store_true",
        default=False,
        help="The operator has rested a BUY 1@$0.01 by hand (D1). Refuses at "
        "the pre-flight and never issues the POST.",
    )
    parser.add_argument(
        "--sequence",
        action="store_true",
        default=False,
        help="R-OP-SEQ: the bot rests, enumerates, cancels and re-verifies its "
        "own positive control (S0-S6), in one run.",
    )
    parser.add_argument(
        "--stamp",
        default=None,
        help="Filename suffix distinguishing one re-probe from the next.",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        default=PRIVATE_SHAPE_DIRECTORY,
        help="Where to write the PRIVATE_ artefact.",
    )
    namespace: argparse.Namespace = parser.parse_args(argv)
    if namespace.sequence and namespace.positive_control:
        parser.error("--sequence and --positive-control are mutually exclusive")
    return namespace


def _report(observation: ProbeObservation | SequenceObservation, path: Path) -> None:
    """Print every field (no body, no id, no slug) plus the artefact path."""
    for field in fields(observation):
        print(f"{field.name:19}: {getattr(observation, field.name)}")
    print(f"{'artefact':19}: {path}")


def _refusal_detail(exc: BaseException, guard: CredentialGuard) -> str:
    """Render ``exc`` for a refusal/error line, gated the same way
    :func:`~polymarket_us_auth_smoke.build_safe_excepthook` gates the uncaught
    path: before a credential read begins there is no secret in the process to
    leak, so the full (redaction-seamed) description is shown; once a
    credential read has begun, only the type name is shown, matching that
    hook's conservative post-credential branch exactly. Without this gate,
    ``describe_exception`` was called with an empty secrets tuple regardless of
    ``guard`` state -- the only literal-secret check it can do -- and a
    caught, credential-adjacent exception's raw message (e.g. an echoed
    header, order id, or body fragment) went straight to stderr."""
    if guard.credential_read_begun:
        return f"{type(exc).__name__}. {POST_CREDENTIAL_SUPPRESSION_NOTE}"
    return describe_exception(exc, ())


def _run_refusable(coro: Any, guard: CredentialGuard) -> tuple[Any, int | None]:
    """Run ``coro``; ``(result, None)`` on success, ``(None, exit_code)`` on a
    refusal. Shared by both CLI modes so the refusal taxonomy is stated once."""
    try:
        return asyncio.run(coro), None
    except (ProbeRefusal, SmokeRefusal) as exc:
        print(f"REFUSED: {_refusal_detail(exc, guard)}", file=sys.stderr)
        return None, 2
    except (ValueError, FileExistsError, ArtifactSchemaError) as exc:
        print(f"REFUSED: {_refusal_detail(exc, guard)}", file=sys.stderr)
        return None, 2
    except PolymarketUSError as exc:
        print(f"CONFIGURATION ERROR: {_refusal_detail(exc, guard)}", file=sys.stderr)
        return None, 2


def main(argv: list[str] | None = None) -> int:
    """Operator entrypoint. Measures and writes; never judges. A refused run
    at any gate is reported as a refusal, not a fault."""
    guard = CredentialGuard()
    sys.excepthook = build_safe_excepthook(guard)
    args = parse_args(argv)

    if args.sequence:
        sequence_observation, code = _run_refusable(
            run_sequence(directory=args.evidence_dir, stamp=args.stamp, guard=guard),
            guard,
        )
        if code is not None:
            return code
        sequence_path = write_sequence_artifact(
            sequence_observation, directory=args.evidence_dir, stamp=args.stamp
        )
        _report(sequence_observation, sequence_path)
        return 0 if sequence_observation.verdict in (CLOSED_YES_BOTH_VERBS, CLOSED_NO) else 2

    observation, code = _run_refusable(
        run_probe(
            positive_control=args.positive_control,
            directory=args.evidence_dir,
            stamp=args.stamp,
            guard=guard,
        ),
        guard,
    )
    if code is not None:
        return code
    path = write_probe_artifact(observation, directory=args.evidence_dir, stamp=args.stamp)
    _report(observation, path)
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
