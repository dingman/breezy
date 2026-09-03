"""R-6.5P -- the Polymarket.us write-SIGNING probe, evidence-only (EXEC SPINE).

Authority: ``docs/plans/EXEC_SPINE_R65_R7_2026-09-02.md`` section 1;
``docs/plans/EXEC_SPINE_R5_R6_2026-09-02.md`` section 3 R-6.5P;
``docs/plans/EXEC_SPINE_2026-09-01.md`` (R-6.5P origin).

**What this answers.** OQ-D: does this repo's Ed25519 signer -- unmodified,
GET-only by construction (``PERMITTED_METHODS``, barrier B2) -- produce a
canonical string the venue accepts on a WRITE verb? Nothing here widens
``PERMITTED_METHODS`` or touches ``signing.py``: the POST is signed by hand,
using the same public canonical-string builder
(:func:`~breezy.adapters.polymarket_us.signing.build_canonical_path_without_query`,
OQ-M closed: the query string is never signed) and the same private
key-loading helper the signer itself uses, over ``method="POST"`` -- a value
:meth:`~breezy.adapters.polymarket_us.signing.Ed25519RequestSigner.sign_headers`
would itself refuse to sign.

**The write verb.** ``POST /v1/orders/open/cancel`` -- cancel ALL open orders
(SDK snapshot ``docs/evidence/venue/polymarket_us/sdk_snapshot/
polymarket_us_0.1.2/resources/orders.py:59-64``). No preview, no single-order
cancel: ``POST /v1/order/preview`` stays withdrawn (OQ-3 is unproven and the
standing rule is "if unproven, never call it").

**The hard safety gate.** This script REFUSES TO RUN past its pre-flight
unless an unfiltered ``GET /v1/orders/open`` returns HTTP 200 with an empty
order list, and holds the post-write GET to the same standard. Two distinct
reason codes -- never a value -- record which half of that compound
condition failed: :data:`PREFLIGHT_NOT_200` carries the HTTP status, and
:data:`PREFLIGHT_NOT_EMPTY` carries NOTHING -- no count, no length. Emptiness
is decided in memory and never written down.

**Positive control (D1, ``--positive-control``).** The operator has rested a
BUY 1@$0.01 by hand. This run must refuse at the pre-flight with
:data:`PREFLIGHT_NOT_EMPTY` -- that refusal, and only that refusal, answers
OQ-B ``ANSWERED``. If the pre-flight instead comes back 200-and-empty in this
mode, the venue did not enumerate an order Breezy never placed: OQ-B is
answered NO, R-6.5P is dead as designed, and this script exits non-zero with
:data:`OQB_NO` **without ever constructing the write client or issuing the
POST**, and writes no artefact.

**Value-free artefact, 7 fields, closed schema (L-8).** Only statuses, reason
codes, and the WRITE response's top-level JSON *type name* are ever recorded
-- never a body, a count, an order id, or a list length. ``PRIVATE_``-prefixed,
``0600``, under a ``0700`` directory, following R-5R-0's conventions exactly
(``polymarket_us_private_shape_probe.py``, ``polymarket_us_auth_smoke.py``).

**Request budget: exactly three signed requests** on the only path that
reaches the write -- pre-flight GET, the one POST, post-flight GET. Every
refusal path issues strictly fewer.

**Narrow excepts only.** The POST's transport failures are caught as
``except (nautilus_pyo3.HttpError, nautilus_pyo3.HttpTimeoutError)`` --
never bare ``Exception``, never ``BaseException`` -- and produce two DISTINCT
Breezy-owned types rather than one collapsed type (the read path's own
comment at ``transport.py:343`` is the model for the tuple, not for the
collapse). ``asyncio.CancelledError`` is a ``BaseException`` in 3.13 and is
never caught here; it propagates.

**Order-submission barriers B1-B3 are unmodified and irrelevant to this
file's write capability.** This script does not go through
``PolymarketUSHttpClient`` or ``NautilusHttpTransport`` for the POST -- both
are GET-only by construction (B1, B3) -- it builds a second, raw
``nautilus_pyo3.HttpClient`` for exactly one write. That is precisely what
barrier B4 exists to catch, and this file is the plan family's first
deliberate, reviewed exemption from it: see
``tests/unit/test_polymarket_us_readonly_guard.py``'s ``B4_EXEMPT_PATHS`` and
``tests/unit/test_cage_rule_constants_are_pinned.py``'s ``CAGE_EXEMPTIONS``.
This module is not importable by the trading process (scripts are not a
package) and a zero-importers pin keeps it that way.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import datetime as dt
import json
import os
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from nautilus_trader.core import nautilus_pyo3

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_DIRECTORY = Path(__file__).resolve().parent
for _entry in (REPO_ROOT / "src", _SCRIPT_DIRECTORY):  # pragma: no cover - bootstrap
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from polymarket_us_auth_smoke import (
    CredentialGuard,
    Prepared,
    RecordingTransport,
    SmokeRefusal,
    build_safe_excepthook,
    describe_exception,
    prepare,
)

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
    QUOTA_KEY_PORTFOLIO,
    NautilusHttpTransport,
    PolymarketUSReadTransport,
    build_default_quota,
    build_keyed_quotas,
    build_shared_http_client,
)

__all__ = [
    "INTENT_MARKER_TOKEN",
    "INTERRUPTED",
    "OQB_NO",
    "PERMITTED_METHODS",
    "POSTFLIGHT_NOT_200",
    "POSTFLIGHT_NOT_EMPTY",
    "PREFLIGHT_NOT_200",
    "PREFLIGHT_NOT_EMPTY",
    "PRIVATE_ARTIFACT_PREFIX",
    "PRIVATE_SHAPE_DIRECTORY",
    "PROBE_DOCUMENT_FIELDS",
    "ArtifactSchemaError",
    "ProbeObservation",
    "ProbeRefusal",
    "WriteTimeoutError",
    "WriteTransportError",
    "main",
    "observation_document",
    "parse_args",
    "probe_artifact_filename",
    "probe_intent_marker_filename",
    "render_probe_report",
    "run_probe",
    "write_probe_artifact",
]

#: Shared with the other R-5R/R-6.5P evidence: one place an operator looks.
PRIVATE_SHAPE_DIRECTORY: Final[Path] = Path("docs/evidence/venue/polymarket_us")
PRIVATE_ARTIFACT_PREFIX: Final[str] = "PRIVATE_"
SHAPE_DIR_MODE: Final[int] = 0o700
SHAPE_FILE_MODE: Final[int] = 0o600

#: The two endpoints this probe touches. Hardcoded, not caller arguments: this
#: file is the one deliberate B4 exemption in the tree (D4), so nothing is
#: gained by hiding the order-path literals from the scan they are exempt
#: from, and everything is gained by making them auditable at a glance.
_OPEN_ORDERS_PATH: Final[str] = "/v1/orders/open"
_CANCEL_ALL_PATH: Final[str] = "/v1/orders/open/cancel"

_WRITE_QUOTA_KEY: Final[str] = QUOTA_KEY_PORTFOLIO

#: D1's two pre-flight reason codes. Never carry a count or a length.
PREFLIGHT_NOT_200: Final[str] = "PREFLIGHT_NOT_200"
PREFLIGHT_NOT_EMPTY: Final[str] = "PREFLIGHT_NOT_EMPTY"
#: The post-write half, held to the same standard.
POSTFLIGHT_NOT_200: Final[str] = "POSTFLIGHT_NOT_200"
POSTFLIGHT_NOT_EMPTY: Final[str] = "POSTFLIGHT_NOT_EMPTY"
#: D1's positive-control failure: the venue did not enumerate an order Breezy
#: never placed. OQ-B is answered NO. The POST is never reached in this branch.
OQB_NO: Final[str] = "OQB_NO"
#: Security follow-up: the process was interrupted (KeyboardInterrupt /
#: CancelledError / any BaseException) between the POST and the post-flight
#: GET. A VALUE of ``postflight_reason`` -- not a new field, so the closed
#: 7-field schema is unchanged.
INTERRUPTED: Final[str] = "INTERRUPTED"
#: The write-ahead intent marker's only content word. Written IMMEDIATELY
#: BEFORE the POST is issued, so an interruption that kills the process
#: before ANY response arrives -- including the final artefact write -- still
#: leaves a durable, on-disk record that a live cancel-all fired.
INTENT_MARKER_TOKEN: Final[str] = "WRITE_ATTEMPTED"

_ARTIFACT_TITLE: Final[str] = "breezy venue write-signing probe (value-free)"

#: The COMPLETE set of fields an artefact carries (L-8). A closed schema is
#: what makes "this file states no conclusion" a property a test can assert.
PROBE_DOCUMENT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "artifact",
        "preflight_status",
        "preflight_reason",
        "write_status",
        "write_response_type",
        "postflight_status",
        "postflight_reason",
    }
)

_STAMP_CHARSET: Final[str] = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)


def _is_plain_token(value: str) -> bool:
    return bool(value) and all(character in _STAMP_CHARSET for character in value)


class ProbeRefusal(PolymarketUSError):
    """The hard safety gate refused this run before any write was attempted."""


class WriteTransportError(PolymarketUSError):
    """The one POST failed at the transport layer (``nautilus_pyo3.HttpError``)."""


class WriteTimeoutError(PolymarketUSError):
    """The one POST timed out at the transport layer.

    Kept DISTINCT from :class:`WriteTransportError` rather than collapsed into
    one type -- ``transport.py:343``'s narrow ``except`` tuple is the model
    here, its single resulting exception type is not.
    """


class ArtifactSchemaError(PolymarketUSError):
    """The rendered artefact does not match the closed 7-field schema."""


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    """Everything this probe may publish. Statuses and reason codes only."""

    preflight_status: int | None
    preflight_reason: str | None
    write_status: int | None
    write_response_type: str | None
    postflight_status: int | None
    postflight_reason: str | None


class _CollectingLog:
    """A ``SupportsVenueLog`` that keeps lines instead of printing them."""

    __slots__ = ("lines",)

    def __init__(self) -> None:
        self.lines: list[str] = []

    def debug(self, message: str) -> None:
        self.lines.append(message)

    def info(self, message: str) -> None:
        self.lines.append(message)

    def warning(self, message: str) -> None:
        self.lines.append(message)

    def error(self, message: str) -> None:
        self.lines.append(message)


def _is_empty_open_orders(body: bytes | None) -> bool | None:
    """Whether ``body`` decodes to ``{"orders": []}``.

    Checked ONCE, in memory, and never recorded (D1): the artefact carries the
    reason code this produced, never the list or its length. ``None`` means
    the body could not be read as the expected shape at all, which the caller
    treats the same as "not proven empty".
    """
    if not body:
        return None
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    orders = payload.get("orders")
    if not isinstance(orders, list):
        return None
    return len(orders) == 0


def _json_top_level_type(body: bytes | None) -> str | None:
    """The top-level JSON type name of ``body`` -- never its content."""
    if not body:
        return None
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return None
    return type(payload).__name__


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
    """A SECOND, raw pyo3 client used for exactly one POST.

    Deliberately NOT ``NautilusHttpTransport``: that wrapper has no ``post``
    method at all (barrier B3). This is the one write-capable reference in
    the tree, contained to this one exempted file.
    """
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
    """One unfiltered ``GET /v1/orders/open``. Never raises.

    Mirrors ``polymarket_us_private_shape_probe.capture``: only
    :class:`PolymarketUSError` is absorbed here, so a defect in this script
    still propagates rather than being reported as a venue observation.
    """
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
) -> list[tuple[str, str]]:
    """Sign a POST the way ``sign_headers`` signs a GET, minus barrier B2.

    Same canonical builder (:func:`build_canonical_path_without_query` --
    OQ-M closed, path-only is signed), same private key-loading helper the
    signer itself uses, same three header names, over ``method="POST"`` --
    which ``sign_headers`` itself would refuse to sign. ``PERMITTED_METHODS``
    and ``sign_headers`` are read here, never copied, and neither is widened
    by this function's existence.
    """
    timestamp_ms = clock.timestamp_ms()
    signer.assert_within_window(timestamp_ms)
    canonical = build_canonical_path_without_query(
        CanonicalRequest(timestamp_ms=timestamp_ms, method="POST", path=_CANCEL_ALL_PATH)
    )
    signing_key = _load_signing_key(credentials.secret_key.get_value())
    signature = base64.b64encode(signing_key.sign(canonical).signature).decode("ascii")
    return [
        (ACCESS_KEY_HEADER, credentials.key_id.get_value()),
        (TIMESTAMP_HEADER, str(timestamp_ms)),
        (SIGNATURE_HEADER, signature),
    ]


async def _signed_post_cancel_all(
    write_client: Any,
    api_base_url: str,
    credentials: PolymarketUSCredentials,
    signer: Ed25519RequestSigner,
    clock: Any,
) -> tuple[int, str | None]:
    """The ONE write this script performs. No ``query`` parameter, no ``body`` parameter.

    A query smuggled into the path would sign one string while the venue
    verifies another (same reasoning as ``PrivateRead.__call__(self, path)``);
    a caller-supplied body would do the same for a POST whose canonical string
    never signs the body at all. Both are refused by construction: neither
    parameter exists.
    """
    headers = dict(_sign_write_headers(credentials, signer, clock))
    headers["Content-Type"] = "application/json"
    url = f"{api_base_url.rstrip('/')}{_CANCEL_ALL_PATH}"
    try:
        response = await write_client.post(
            url,
            headers=headers,
            body=json.dumps({}).encode("ascii"),
            keys=[_WRITE_QUOTA_KEY],
        )
    except (nautilus_pyo3.HttpError, nautilus_pyo3.HttpTimeoutError) as exc:
        if isinstance(exc, nautilus_pyo3.HttpTimeoutError):
            raise WriteTimeoutError(
                f"POST {_CANCEL_ALL_PATH} timed out at the transport layer"
            ) from None
        raise WriteTransportError(
            f"POST {_CANCEL_ALL_PATH} failed at the transport layer: {type(exc).__name__}"
        ) from None
    return int(response.status), _json_top_level_type(bytes(response.body))


def probe_intent_marker_filename(*, stamp: str | None = None) -> str:
    """``PRIVATE_``-prefixed filename for the write-ahead intent marker."""
    suffix = ""
    if stamp is not None:
        if not _is_plain_token(stamp):
            raise ValueError("stamp must be a plain [A-Za-z0-9_-] token")
        suffix = f"_{stamp}"
    return f"{PRIVATE_ARTIFACT_PREFIX}write_signing_probe_intent{suffix}.json"


def _write_intent_marker(*, directory: Path, stamp: str | None) -> Path:
    """Write-ahead marker, written IMMEDIATELY BEFORE the POST is issued.

    Value-free: the write PATH (a constant, not a request/response value), a
    wall-clock timestamp, and the literal :data:`INTENT_MARKER_TOKEN`. Same
    ``0600``-under-``0700``, ``O_EXCL`` discipline as the final artefact, so
    an interruption between this write and the final artefact -- including
    one that kills the process before any response arrives -- still leaves a
    durable, on-disk record that a live cancel-all fired.
    """
    filename = probe_intent_marker_filename(stamp=stamp)
    text = (
        json.dumps(
            {
                "artifact": "breezy venue write-signing probe intent marker (value-free)",
                "path": _CANCEL_ALL_PATH,
                "written_at_utc": dt.datetime.now(tz=dt.UTC).isoformat(),
                "marker": INTENT_MARKER_TOKEN,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(SHAPE_DIR_MODE)
    path = directory / filename
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SHAPE_FILE_MODE)
    try:
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
    except BaseException:
        os.close(descriptor)
        raise
    with handle:
        handle.write(text)
    os.chmod(path, SHAPE_FILE_MODE)
    return path


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
    """Run the probe end to end, in the order the hard safety gate depends on.

    Exactly three signed requests reach the venue on the only path that
    reaches the write: the pre-flight GET, the one POST, the post-flight GET
    -- in that order, in this function (mechanised order check, D-6.5P
    HARD SAFETY GATE item 1). Every refusal path issues strictly fewer.
    """
    from nautilus_trader.common.component import LiveClock

    filename = probe_artifact_filename(stamp=stamp)
    if (directory / filename).exists():
        raise FileExistsError(
            f"{directory / filename} already exists; supply a new --stamp. "
            "Refused before any request rather than after it."
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
        logger=_CollectingLog(),
    )

    # --- pre-flight: unfiltered GET, before any write is attempted ---------
    preflight_status, preflight_body = await _signed_get_open_orders(read_client, read_transport)
    if preflight_status != 200:
        return ProbeObservation(
            preflight_status=preflight_status,
            preflight_reason=PREFLIGHT_NOT_200,
            write_status=None,
            write_response_type=None,
            postflight_status=None,
            postflight_reason=None,
        )
    preflight_empty = _is_empty_open_orders(preflight_body)
    if not preflight_empty:
        return ProbeObservation(
            preflight_status=preflight_status,
            preflight_reason=PREFLIGHT_NOT_EMPTY,
            write_status=None,
            write_response_type=None,
            postflight_status=None,
            postflight_reason=None,
        )
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
    _write_intent_marker(directory=directory, stamp=stamp)
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
    except BaseException:
        # Never swallowed: a partial, honest artefact is written and the
        # original exception (KeyboardInterrupt, CancelledError, or any
        # other fault) is re-raised unchanged.
        write_probe_artifact(
            ProbeObservation(
                preflight_status=preflight_status,
                preflight_reason=None,
                write_status=write_status,
                write_response_type=write_response_type,
                postflight_status=None,
                postflight_reason=INTERRUPTED,
            ),
            directory=directory,
            stamp=stamp,
        )
        raise

    postflight_reason: str | None
    if postflight_status != 200:
        postflight_reason = POSTFLIGHT_NOT_200
    elif not _is_empty_open_orders(postflight_body):
        postflight_reason = POSTFLIGHT_NOT_EMPTY
    else:
        postflight_reason = None

    return ProbeObservation(
        preflight_status=preflight_status,
        preflight_reason=None,
        write_status=write_status,
        write_response_type=write_response_type,
        postflight_status=postflight_status,
        postflight_reason=postflight_reason,
    )


def probe_artifact_filename(*, stamp: str | None = None) -> str:
    """``PRIVATE_``-prefixed filename, matching the ``.gitignore`` rule."""
    suffix = ""
    if stamp is not None:
        if not _is_plain_token(stamp):
            raise ValueError("stamp must be a plain [A-Za-z0-9_-] token")
        suffix = f"_{stamp}"
    return f"{PRIVATE_ARTIFACT_PREFIX}write_signing_probe{suffix}.json"


def observation_document(observation: ProbeObservation) -> dict[str, Any]:
    """The closed document. Every field is a status, a reason code, or a type name."""
    document: dict[str, Any] = {
        "artifact": _ARTIFACT_TITLE,
        "preflight_status": observation.preflight_status,
        "preflight_reason": observation.preflight_reason,
        "write_status": observation.write_status,
        "write_response_type": observation.write_response_type,
        "postflight_status": observation.postflight_status,
        "postflight_reason": observation.postflight_reason,
    }
    if set(document) != PROBE_DOCUMENT_FIELDS:
        raise ArtifactSchemaError("the probe document does not match its closed schema")
    return document


def render_probe_report(observation: ProbeObservation) -> str:
    """Render the artefact body. Deterministic: no timestamp, no digest."""
    return json.dumps(observation_document(observation), indent=2, sort_keys=True) + "\n"


def write_probe_artifact(
    observation: ProbeObservation,
    *,
    directory: Path = PRIVATE_SHAPE_DIRECTORY,
    stamp: str | None = None,
) -> Path:
    """Render, re-verify the schema, then write ``0600`` under a ``0700`` directory.

    ``O_EXCL`` means an existing artefact is never silently overwritten -- a
    re-probe carries a new stamp or it fails loudly.
    """
    filename = probe_artifact_filename(stamp=stamp)
    if not filename.startswith(PRIVATE_ARTIFACT_PREFIX) or os.sep in filename:
        raise ArtifactSchemaError("refusing to write an artefact without the PRIVATE_ prefix")

    text = render_probe_report(observation)
    if set(json.loads(text)) != PROBE_DOCUMENT_FIELDS:
        raise ArtifactSchemaError("round-tripped document does not match the closed schema")

    directory.mkdir(parents=True, exist_ok=True)
    directory.chmod(SHAPE_DIR_MODE)

    path = directory / filename
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, SHAPE_FILE_MODE)
    try:
        handle = os.fdopen(descriptor, "w", encoding="utf-8")
    except BaseException:
        os.close(descriptor)
        raise
    with handle:
        handle.write(text)
    os.chmod(path, SHAPE_FILE_MODE)
    return path


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
    return namespace


def main(argv: list[str] | None = None) -> int:
    """Operator entrypoint. Returns 0 when an OBSERVATION was recorded.

    This script measures and, on the one permitted path, writes -- it never
    judges. A refused run at any gate is reported as a refusal, not a fault.
    """
    guard = CredentialGuard()
    sys.excepthook = build_safe_excepthook(guard)

    args = parse_args(argv)
    try:
        observation = asyncio.run(
            run_probe(
                positive_control=args.positive_control,
                directory=args.evidence_dir,
                stamp=args.stamp,
                guard=guard,
            )
        )
    except ProbeRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except SmokeRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except (ValueError, FileExistsError, ArtifactSchemaError) as exc:
        print(f"REFUSED: {describe_exception(exc, ())}", file=sys.stderr)
        return 2
    except PolymarketUSError as exc:
        print(f"CONFIGURATION ERROR: {describe_exception(exc, ())}", file=sys.stderr)
        return 2

    path = write_probe_artifact(observation, directory=args.evidence_dir, stamp=args.stamp)
    print(f"preflight status  : {observation.preflight_status}")
    print(f"preflight reason  : {observation.preflight_reason}")
    print(f"write status      : {observation.write_status}")
    print(f"write resp. type  : {observation.write_response_type}")
    print(f"postflight status : {observation.postflight_status}")
    print(f"postflight reason : {observation.postflight_reason}")
    print(f"artefact          : {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
