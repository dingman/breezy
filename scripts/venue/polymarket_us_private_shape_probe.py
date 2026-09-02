"""Repeatable, value-free RUNNER for one signed private read (EXEC SPINE R-5R-0).

R-1 landed a shape DESCRIBER (``polymarket_us_shape_capture.py``) and never a
runner: that module has no ``main()``, no ``argparse`` and performs no I/O, by
design. So the private-surface evidence the spine depends on had to be produced
by an ephemeral driver supplied from outside the repository -- which is not
repeatable, and those endpoints have to be re-probed every time the venue's
backend might have changed state. This module is that runner, and nothing more.

What it does, in one sentence: **one signed GET, described by R-1's describer,
written as a ``PRIVATE_``-prefixed ``0600`` artefact.**

Five constraints, each mechanised rather than asserted in prose:

* **GET-only by construction.** It drives the shipped
  :class:`~breezy.adapters.polymarket_us.http.PolymarketUSHttpClient` over the
  shipped GET-only transport, whose seam protocol has no ``method`` parameter
  at all. The method is checked against the SIGNER's own
  ``PERMITTED_METHODS`` -- imported, never copied -- as this module's FIRST
  act, ahead of the credential read, so a refusal never happens in a process
  that already holds an Ed25519 secret.
* **It imports no write surface.** Nothing named for the spine's order-
  submission increments exists yet, and this module may not be the thing that
  creates one. Pinned by an AST import allowlist in the paired suite.
* **The endpoint is never a literal here.** It is a caller argument validated
  against the describer's plain-path charset. Barrier B4 rule V2 bans an
  order-path literal anywhere under ``src/`` or ``scripts/``, and a barrier
  that has to be silenced is a barrier that will be silenced -- which is the
  whole reason R-1's describer is shaped the way it is.
* **A status class, never a verdict (L-8).** A refusal is recorded as the HTTP
  status plus the gRPC ``code`` the body carried, and nothing else. No
  classification, no cause, no health opinion. ``exec/refusals.py`` owns the
  class mapping and is deliberately NOT applied here: reading a code out of an
  envelope is an observation, and turning it into TRANSIENT or DURABLE is a
  judgement that belongs to the reader of the artefact, not to its writer.
* **Value-free output.** The response body reaches only R-1's
  ``describe_shape``, and ``verify_value_free`` re-checks the tree before
  anything is written. These endpoints ARE the operator's financial position;
  the artefact mode and the ``PRIVATE_`` prefix (which ``.gitignore`` excludes)
  are the second and third layers behind that grammar.

The exit code reports whether an OBSERVATION was recorded, never whether the
venue was healthy. A recorded 503 is a successful run of this script.

It lives under ``scripts/venue/`` for the same reason its two neighbours do:
it writes into ``docs/evidence/``, which ``test_probe_containment.py`` bans as
a runtime constant anywhere under ``src/``. B4 already classifies that
directory venue-touching, so rules V1-V4 apply to this file unchanged and it
needs no allowlist entry -- a GET-only runner trips none of them.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_DIRECTORY = Path(__file__).resolve().parent
for _entry in (REPO_ROOT / "src", _SCRIPT_DIRECTORY):  # pragma: no cover - bootstrap
    if str(_entry) not in sys.path:
        sys.path.insert(0, str(_entry))

from polymarket_us_auth_smoke import (
    HTTP_METHOD,
    CredentialGuard,
    Prepared,
    RecordingTransport,
    SmokeRefusal,
    build_safe_excepthook,
    describe_exception,
    prepare,
)
from polymarket_us_shape_capture import (
    PRIVATE_ARTIFACT_PREFIX,
    PRIVATE_SHAPE_DIRECTORY,
    SHAPE_DIR_MODE,
    SHAPE_FILE_MODE,
    ShapeLeakError,
    describe_shape,
    verify_value_free,
)
from polymarket_us_shape_capture import (
    _validate_endpoint as validate_endpoint,
)

from breezy.adapters.polymarket_us.errors import (
    MethodNotPermittedError,
    PolymarketUSError,
)
from breezy.adapters.polymarket_us.exec.refusals import grpc_status_code
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.signing import (
    PERMITTED_METHODS,
    Ed25519RequestSigner,
    SigningVariant,
)
from breezy.adapters.polymarket_us.transport import (
    QUOTA_KEY_PORTFOLIO,
    NautilusHttpTransport,
    PolymarketUSReadTransport,
    build_default_quota,
    build_keyed_quotas,
)

__all__ = [
    "DEFAULT_QUOTA_KEY",
    "HTTP_METHOD",
    "PERMITTED_METHODS",
    "PRIVATE_ARTIFACT_PREFIX",
    "PRIVATE_SHAPE_DIRECTORY",
    "PROBE_DOCUMENT_FIELDS",
    "ProbeObservation",
    "ShapeLeakError",
    "assert_get_only",
    "main",
    "observation_document",
    "parse_args",
    "parse_query_pairs",
    "probe_artifact_filename",
    "render_probe_report",
    "run_probe",
    "validate_endpoint",
    "verify_value_free",
    "write_probe_artifact",
]

#: The private endpoints all sit in the portfolio budget class. Named once so
#: an unbudgeted read is impossible rather than merely discouraged.
DEFAULT_QUOTA_KEY: Final[str] = QUOTA_KEY_PORTFOLIO

_ARTIFACT_SUFFIX: Final[str] = ".probe.json"

_DOCUMENT_TITLE: Final[str] = "breezy venue private-surface probe (value-free)"

#: The COMPLETE set of fields an artefact carries. A closed schema is what
#: makes "this file states no conclusion" a property a test can assert.
PROBE_DOCUMENT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "artifact",
        "endpoint",
        "http_status",
        "grpc_code",
        "envelope_parsed",
        "signing_variant",
        "shape",
    }
)

#: Query keys and values are operator-chosen constants, never payload data --
#: the same reasoning as the endpoint charset, and the same refusal on a miss.
_QUERY_TOKEN_CHARSET: Final[str] = (
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"
)

_STAMP_CHARSET: Final[str] = _QUERY_TOKEN_CHARSET


def _is_plain_token(value: str, charset: str) -> bool:
    return bool(value) and all(character in charset for character in value)


# ---------------------------------------------------------------------------
# Refusals, checked before anything reads a credential
# ---------------------------------------------------------------------------


def assert_get_only(method: str) -> None:
    """Refuse any method the SIGNER would refuse, and refuse it earlier.

    The allowlist is imported from :mod:`breezy.adapters.polymarket_us.signing`
    rather than restated, so this guard cannot drift away from barrier B2. It
    runs before the credential read so the refusal is provably not taken by a
    process holding a secret.
    """
    if method not in PERMITTED_METHODS:
        raise MethodNotPermittedError(
            "The private-surface probe issues "
            f"{sorted(PERMITTED_METHODS)} only; refused method {method!r}"
        )


def parse_query_pairs(pairs: Iterable[str] | None) -> dict[str, str]:
    """Parse ``KEY=VALUE`` strings into a mapping, refusing anything else.

    Refused rather than sanitised: a query token is a constant the operator
    typed, so anything outside the plain charset is a mistake worth surfacing,
    not input to be repaired.
    """
    if pairs is None:
        return {}
    query: dict[str, str] = {}
    for pair in pairs:
        key, separator, value = str(pair).partition("=")
        if not separator:
            raise ValueError(f"query argument {pair!r} is not KEY=VALUE")
        if not _is_plain_token(key, _QUERY_TOKEN_CHARSET):
            raise ValueError("query keys must be a plain [A-Za-z0-9_-] token")
        if not _is_plain_token(value, _QUERY_TOKEN_CHARSET):
            raise ValueError("query values must be a plain [A-Za-z0-9_-] token")
        if key in query:
            raise ValueError(f"query key {key!r} was supplied twice")
        query[key] = value
    return query


# ---------------------------------------------------------------------------
# The observation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProbeObservation:
    """One signed read, reduced to what may be published.

    ``http_status`` is ``None`` when no response arrived at all -- a timeout or
    a transport failure. ``grpc_code`` is ``None`` when the body carried no
    usable code, which is a distinct fact from "the code was zero" and is kept
    distinct here. Neither field is ever defaulted to a plausible value.
    """

    endpoint: str
    http_status: int | None
    grpc_code: int | None
    envelope_parsed: bool
    signing_variant: str
    shape: Mapping[str, Any]


def _decode_object(body: bytes | None) -> tuple[Any, bool]:
    """Decode ``body`` as a JSON object. Never raises, never inspects values."""
    if not body:
        return None, False
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        return None, False
    if not isinstance(payload, dict):
        return None, False
    return payload, True


class _CollectingLog:
    """A ``SupportsVenueLog`` that keeps lines instead of emitting them.

    The shipped client formats the method, URL, status and the allowlisted
    response headers -- never a credential and never a body. Collecting rather
    than printing keeps the operator's terminal free of anything the artefact
    does not already carry, while leaving the lines available to ``main``.
    """

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


def _build_read_transport(config: Any) -> PolymarketUSReadTransport:
    """The shipped GET-only transport, budgeted exactly as the smoke budgets it."""
    return NautilusHttpTransport(
        timeout_secs=config.http_timeout_secs,
        default_quota=build_default_quota(config.global_requests_per_second),
        keyed_quotas=build_keyed_quotas(
            instrument_requests_per_minute=config.instrument_requests_per_minute,
            book_requests_per_minute=config.book_requests_per_minute,
        ),
        default_headers={"User-Agent": str(config.user_agent)},
    )


async def capture(
    client: Any,
    transport: RecordingTransport,
    *,
    endpoint: str,
    query: Mapping[str, str] | None,
    quota_key: str,
    signing_variant: str,
) -> ProbeObservation:
    """Issue the read and reduce whatever came back to an observation.

    A venue refusal is an OUTCOME here, not an error: the whole point of the
    probe is to record a 500 or a 503 as faithfully as a 200. Only
    :class:`PolymarketUSError` is absorbed; anything else is a defect in this
    script and propagates.
    """
    try:
        await client.get_authenticated(endpoint, query=query, quota_key=quota_key)
    except PolymarketUSError:
        pass

    event = transport.last()
    response = None if event is None else event.response
    status = None if response is None else response.status
    body = None if response is None else response.body

    payload, parsed = _decode_object(body)
    shape = describe_shape(payload) if parsed else describe_shape(None)
    verify_value_free(shape)

    return ProbeObservation(
        endpoint=endpoint,
        http_status=status,
        grpc_code=grpc_status_code(body),
        envelope_parsed=parsed,
        signing_variant=signing_variant,
        shape=shape,
    )


async def run_probe(
    endpoint: str,
    *,
    method: str = HTTP_METHOD,
    query: Mapping[str, str] | None = None,
    signing_variant: str | None = None,
    env: Mapping[str, str] | None = None,
    quota_key: str = DEFAULT_QUOTA_KEY,
    directory: Path = PRIVATE_SHAPE_DIRECTORY,
    stamp: str | None = None,
    guard: CredentialGuard | None = None,
    prepare_fn: Callable[..., Prepared] = prepare,
    transport_factory: Callable[[Any], PolymarketUSReadTransport] = _build_read_transport,
) -> ProbeObservation:
    """Run one probe end to end, in an order the guards depend on.

    The write TARGET is checked before the read is issued. ``write_probe_
    artifact`` opens ``O_EXCL``, so a colliding artefact would otherwise be
    discovered only after the request had already been spent against a
    rate-limited venue -- and the venue is the scarce resource here, not the
    filesystem. A re-probe carries a new ``stamp`` or it fails for free.
    """
    from nautilus_trader.common.component import LiveClock

    assert_get_only(method)
    validate_endpoint(endpoint)
    if query is not None:
        parse_query_pairs(f"{key}={value}" for key, value in query.items())

    filename = probe_artifact_filename(endpoint, stamp=stamp)
    if (directory / filename).exists():
        raise FileExistsError(
            f"{directory / filename} already exists; supply a new --stamp. "
            "Refused before the request rather than after it."
        )

    prepared = prepare_fn(env, guard=guard)
    config = prepared.config
    variant = SigningVariant(signing_variant or config.signing_variant)

    transport = RecordingTransport(inner=transport_factory(config))
    client = PolymarketUSHttpClient(
        transport=transport,
        signer=Ed25519RequestSigner.for_variant(
            prepared.credentials, clock=LiveClock(), variant=variant
        ),
        api_base_url=str(config.api_base_url),
        gateway_base_url=str(config.gateway_base_url),
        logger=_CollectingLog(),
    )
    return await capture(
        client,
        transport,
        endpoint=endpoint,
        query=query,
        quota_key=quota_key,
        signing_variant=str(variant.value),
    )


# ---------------------------------------------------------------------------
# The artefact
# ---------------------------------------------------------------------------


def observation_document(observation: ProbeObservation) -> dict[str, Any]:
    """The closed document. Every field is a caller argument or an observation."""
    validate_endpoint(observation.endpoint)
    verify_value_free(observation.shape)
    document = {
        "artifact": _DOCUMENT_TITLE,
        "endpoint": observation.endpoint,
        "http_status": observation.http_status,
        "grpc_code": observation.grpc_code,
        "envelope_parsed": observation.envelope_parsed,
        "signing_variant": observation.signing_variant,
        "shape": observation.shape,
    }
    if set(document) != PROBE_DOCUMENT_FIELDS:
        raise ShapeLeakError("the probe document does not match its closed schema")
    return document


def render_probe_report(observation: ProbeObservation) -> str:
    """Render the artefact body. Deterministic: no timestamp, no digest.

    Determinism is the same security property it is for R-1's describer: two
    responses differing only in magnitude must render byte-identically, and a
    timestamp in the body would destroy the comparison that proves it. Capture
    provenance belongs in the filename stamp.
    """
    return json.dumps(observation_document(observation), indent=2, sort_keys=True) + "\n"


def probe_artifact_filename(endpoint: str, *, stamp: str | None = None) -> str:
    """``PRIVATE_``-prefixed filename, matching the ``.gitignore`` rule."""
    validate_endpoint(endpoint)
    label = endpoint.strip("/").replace("/", "_")
    suffix = ""
    if stamp is not None:
        if not _is_plain_token(stamp, _STAMP_CHARSET):
            raise ValueError("stamp must be a plain [A-Za-z0-9_-] token")
        suffix = f"_{stamp}"
    return f"{PRIVATE_ARTIFACT_PREFIX}{label}{suffix}{_ARTIFACT_SUFFIX}"


def write_probe_artifact(
    observation: ProbeObservation,
    *,
    directory: Path = PRIVATE_SHAPE_DIRECTORY,
    stamp: str | None = None,
) -> Path:
    """Render, re-verify, then write ``0600`` under a ``0700`` directory.

    Nothing is created before the verification passes, so a refused write
    leaves no partial artefact. ``O_EXCL`` means an existing artefact is never
    silently overwritten -- a re-probe carries a new stamp or it fails loudly.
    """
    filename = probe_artifact_filename(observation.endpoint, stamp=stamp)
    if not filename.startswith(PRIVATE_ARTIFACT_PREFIX) or os.sep in filename:
        raise ShapeLeakError("refusing to write an artefact without the PRIVATE_ prefix")

    text = render_probe_report(observation)
    # Re-verify the round-tripped document: what lands on disk is what was
    # checked, not merely something derived from it.
    verify_value_free(json.loads(text)["shape"])

    directory.mkdir(parents=True, exist_ok=True)
    # `mode=` on `mkdir` is masked by the umask and ignored for an existing
    # directory. Set it explicitly, unconditionally.
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


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument(
        "--endpoint",
        required=True,
        help="Plain path to read, e.g. an account or portfolio path. REQUIRED: "
        "a default would put a private path back into source as a literal.",
    )
    parser.add_argument(
        "--query",
        action="append",
        default=None,
        metavar="KEY=VALUE",
        help="Repeatable query parameter. Plain [A-Za-z0-9_-] tokens only.",
    )
    parser.add_argument(
        "--signing-variant",
        choices=[variant.value for variant in SigningVariant],
        default=None,
        help="Canonical-string builder to sign with. Defaults to the configured one.",
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


def main(argv: Sequence[str] | None = None) -> int:
    """Operator entrypoint. Returns 0 when an OBSERVATION was recorded.

    A recorded 503 exits 0. This script measures; it does not judge, and an
    exit code that encoded venue health would be exactly the bare-status-code
    verdict L-8 forbids.
    """
    guard = CredentialGuard()
    sys.excepthook = build_safe_excepthook(guard)

    args = parse_args(argv)
    try:
        query = parse_query_pairs(args.query)
        observation = asyncio.run(
            run_probe(
                args.endpoint,
                query=query or None,
                signing_variant=args.signing_variant,
                directory=args.evidence_dir,
                stamp=args.stamp,
                guard=guard,
            )
        )
        path = write_probe_artifact(observation, directory=args.evidence_dir, stamp=args.stamp)
    except SmokeRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2
    except (ValueError, FileExistsError, ShapeLeakError) as exc:
        print(f"REFUSED: {describe_exception(exc, ())}", file=sys.stderr)
        return 2
    except PolymarketUSError as exc:
        print(f"CONFIGURATION ERROR: {describe_exception(exc, ())}", file=sys.stderr)
        return 2

    print(f"endpoint        : {observation.endpoint}")
    print(f"signing variant : {observation.signing_variant}")
    print(f"http status     : {observation.http_status}")
    print(f"grpc code       : {observation.grpc_code}")
    print(f"envelope parsed : {observation.envelope_parsed}")
    print(f"artefact        : {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
