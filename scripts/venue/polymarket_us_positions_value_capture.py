"""One signed GET of a caller-supplied private portfolio path, WITH VALUES.

The shape probe (``polymarket_us_private_shape_probe.py``) proves a private
endpoint answers, but it is value-free by design: it can never say whether a
held NO position signs positive or negative on ``netPosition``, or what
currency ``avgPx`` is denominated in -- the open questions the exit path
needs answered (docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md Appendix A).

This module is the paired runner that answers them: one signed GET, written
as a ``PRIVATE_``-prefixed ``0600`` artefact, WITH the position fields
intact. It reuses -- by import, never by copy -- everything the shape probe
already proved safe: GET-only construction and the read transport
(:func:`assert_get_only`, barrier B2); credential handling and the
``BREEZY_VENUE_LIVE=1`` guard (``prepare``/``CredentialGuard``/
``SmokeRefusal``); and the endpoint charset -- the caller-supplied path is
never a literal here, because Barrier B4 rule V2 bans an order-path literal
anywhere under ``src/`` or ``scripts/``. It imports no write surface, pinned
by an AST import allowlist in the paired suite.

What it redacts is narrower than the shape describer, and different: any key
name identifying the ACCOUNT or the OPERATOR (``account``, ``user``,
``wallet``, ``email``, ``key``, ``token``, or a bare ``id``), at any depth,
is dropped and its name recorded in ``redacted_keys``. ``positionId`` and
``marketMetadata.id`` are kept, because the exit path joins a position to its
orders on exactly those two fields. Every other value -- ``netPosition``,
``avgPx``, ``cashValue``, and so on -- is written byte-for-byte as received.

The exit code reports whether an OBSERVATION was recorded, never whether the
venue was healthy: a recorded 503 is a successful run. Only status, byte
count, position count and the artefact path are ever printed -- the body
itself never reaches stdout, stderr, or a log.

It lives under ``scripts/venue/`` for the same reason its neighbours do: it
writes into ``docs/evidence/``, which ``test_probe_containment.py`` bans as a
runtime constant anywhere under ``src/``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections.abc import Callable, Mapping
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
from polymarket_us_private_shape_probe import (
    DEFAULT_QUOTA_KEY,
    PERMITTED_METHODS,
    assert_get_only,
)
from polymarket_us_private_shape_probe import _build_read_transport as build_read_transport
from polymarket_us_private_shape_probe import _CollectingLog as CollectingLog
from polymarket_us_private_shape_probe import _decode_object as decode_object
from polymarket_us_shape_capture import (
    PRIVATE_ARTIFACT_PREFIX,
    PRIVATE_SHAPE_DIRECTORY,
    SHAPE_DIR_MODE,
    SHAPE_FILE_MODE,
)
from polymarket_us_shape_capture import _validate_endpoint as validate_endpoint

from breezy.adapters.polymarket_us.errors import (
    MethodNotPermittedError,
    PolymarketUSError,
)
from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner, SigningVariant
from breezy.adapters.polymarket_us.transport import PolymarketUSReadTransport

__all__ = [
    "DEFAULT_QUOTA_KEY", "HTTP_METHOD", "PERMITTED_METHODS", "POSITIONS_DOCUMENT_FIELDS",
    "PRIVATE_ARTIFACT_PREFIX", "PRIVATE_SHAPE_DIRECTORY", "MethodNotPermittedError",
    "PositionsCaptureError", "PositionsObservation", "Prepared", "SmokeRefusal",
    "assert_get_only", "capture", "main", "observation_document", "parse_args",
    "positions_artifact_filename", "redact_positions", "render_positions_report",
    "run_capture", "validate_endpoint", "write_positions_artifact",
]

_ARTIFACT_SUFFIX: Final[str] = ".positions.json"
_DOCUMENT_TITLE: Final[str] = "breezy venue private-surface positions capture (values intact)"

#: The COMPLETE set of fields an artefact carries -- a closed schema, same
#: discipline as the shape probe's own.
POSITIONS_DOCUMENT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "artifact", "endpoint", "http_status", "envelope_parsed", "position_count",
        "redacted_keys", "positions", "eof", "nextCursor",
    }
)

#: Stamp charset. A fresh, small predicate rather than an import: this is a
#: formatting convenience, not a safety-relevant behaviour.
_STAMP_CHARSET: Final[str] = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-"

#: Key-name substrings identifying the ACCOUNT/OPERATOR rather than the
#: position or market, matched case-insensitively at any depth.
_DENY_SUBSTRINGS: Final[tuple[str, ...]] = (
    "id", "account", "user", "wallet", "email", "key", "token",
)

#: The two named exceptions: the exit path joins a position to its orders on
#: exactly these two identifiers.
_KEPT_KEY_NAME: Final[str] = "positionId"
_KEPT_NESTED_KEY: Final[str] = "id"
_KEPT_NESTED_PARENT: Final[str] = "marketMetadata"


class PositionsCaptureError(RuntimeError):
    """A positions document failed its closed schema, or could not be
    written safely. Never raised for a venue refusal -- see ``capture``."""


def _is_plain_stamp(value: str) -> bool:
    return bool(value) and all(character in _STAMP_CHARSET for character in value)


def _is_denied_key(key: str, *, parent_key: str | None) -> bool:
    """``positionId`` is kept everywhere; a bare ``id`` only under
    ``marketMetadata``. Every other deny-substring match, anywhere, is dropped."""
    if key == _KEPT_KEY_NAME:
        return False
    if parent_key == _KEPT_NESTED_PARENT and key == _KEPT_NESTED_KEY:
        return False
    lowered = key.lower()
    return any(token in lowered for token in _DENY_SUBSTRINGS)


def redact_positions(value: Any, *, parent_key: str | None, dropped: list[str]) -> Any:
    """Redact ``value`` recursively. Unlike the shape describer, values are
    never inspected -- only key NAMES are checked, via :func:`_is_denied_key`."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, sub in value.items():
            if isinstance(key, str) and _is_denied_key(key, parent_key=parent_key):
                dropped.append(key)
                continue
            next_parent = key if isinstance(key, str) else parent_key
            result[key] = redact_positions(sub, parent_key=next_parent, dropped=dropped)
        return result
    if isinstance(value, list):
        return [redact_positions(item, parent_key=parent_key, dropped=dropped) for item in value]
    return value


def _count_positions(positions: Any) -> int:
    if isinstance(positions, Mapping | list):
        return len(positions)
    return 0


# -- the observation ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PositionsObservation:
    """One signed read, reduced to what may be published. ``http_status`` is
    ``None`` on a transport failure; ``positions``/``eof``/``next_cursor`` are
    ``None`` when the body never parsed as a JSON object."""

    endpoint: str
    http_status: int | None
    envelope_parsed: bool
    position_count: int
    redacted_keys: tuple[str, ...]
    positions: Any
    eof: Any
    next_cursor: Any
    body_byte_count: int


async def capture(
    client: Any,
    transport: RecordingTransport,
    *,
    endpoint: str,
    quota_key: str,
) -> PositionsObservation:
    """Issue the read and reduce whatever came back to an observation. A
    venue refusal is an OUTCOME, not an error: this records a 500 or a 503 as
    faithfully as a 200. Only :class:`PolymarketUSError` is absorbed."""
    try:
        await client.get_authenticated(endpoint, quota_key=quota_key)
    except PolymarketUSError:
        pass

    event = transport.last()
    response = None if event is None else event.response
    status = None if response is None else response.status
    body = None if response is None else response.body

    payload, parsed = decode_object(body)
    dropped: list[str] = []
    positions_value: Any = None
    eof_value: Any = None
    next_cursor_value: Any = None
    if parsed:
        if "positions" in payload:
            positions_value = redact_positions(
                payload["positions"], parent_key=None, dropped=dropped
            )
        eof_value = payload.get("eof")
        next_cursor_value = payload.get("nextCursor")

    return PositionsObservation(
        endpoint=endpoint,
        http_status=status,
        envelope_parsed=parsed,
        position_count=_count_positions(positions_value),
        redacted_keys=tuple(sorted(set(dropped))),
        positions=positions_value,
        eof=eof_value,
        next_cursor=next_cursor_value,
        body_byte_count=len(body) if body else 0,
    )


async def run_capture(
    endpoint: str,
    *,
    method: str = HTTP_METHOD,
    signing_variant: str | None = None,
    env: Mapping[str, str] | None = None,
    quota_key: str = DEFAULT_QUOTA_KEY,
    directory: Path = PRIVATE_SHAPE_DIRECTORY,
    stamp: str | None = None,
    guard: CredentialGuard | None = None,
    prepare_fn: Callable[..., Prepared] = prepare,
    transport_factory: Callable[[Any], PolymarketUSReadTransport] = build_read_transport,
) -> PositionsObservation:
    """Run one capture end to end. The write TARGET is checked before the
    read is issued -- same reasoning as ``run_probe``: the venue is the
    scarce resource, so a doomed write is refused before spending a request."""
    from nautilus_trader.common.component import LiveClock

    assert_get_only(method)
    validate_endpoint(endpoint)

    filename = positions_artifact_filename(endpoint, stamp=stamp)
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
        logger=CollectingLog(),
    )
    return await capture(client, transport, endpoint=endpoint, quota_key=quota_key)


# -- the artefact -------------------------------------------------------


def observation_document(observation: PositionsObservation) -> dict[str, Any]:
    """The closed document. Every field is a caller argument or an observation."""
    validate_endpoint(observation.endpoint)
    document: dict[str, Any] = {
        "artifact": _DOCUMENT_TITLE,
        "endpoint": observation.endpoint,
        "http_status": observation.http_status,
        "envelope_parsed": observation.envelope_parsed,
        "position_count": observation.position_count,
        "redacted_keys": list(observation.redacted_keys),
        "positions": observation.positions,
        "eof": observation.eof,
        "nextCursor": observation.next_cursor,
    }
    if set(document) != POSITIONS_DOCUMENT_FIELDS:
        raise PositionsCaptureError("the positions document does not match its closed schema")
    return document


def render_positions_report(observation: PositionsObservation) -> str:
    """Render the artefact body."""
    return json.dumps(observation_document(observation), indent=2, sort_keys=True) + "\n"


def positions_artifact_filename(endpoint: str, *, stamp: str | None = None) -> str:
    """``PRIVATE_``-prefixed filename. Suffix (``.positions.json``) differs
    from the shape probe's ``.probe.json`` so the two never collide."""
    validate_endpoint(endpoint)
    label = endpoint.strip("/").replace("/", "_")
    suffix = ""
    if stamp is not None:
        if not _is_plain_stamp(stamp):
            raise ValueError("stamp must be a plain [A-Za-z0-9_-] token")
        suffix = f"_{stamp}"
    return f"{PRIVATE_ARTIFACT_PREFIX}{label}{suffix}{_ARTIFACT_SUFFIX}"


def write_positions_artifact(
    observation: PositionsObservation,
    *,
    directory: Path = PRIVATE_SHAPE_DIRECTORY,
    stamp: str | None = None,
) -> Path:
    """Render, then write ``0600`` under a ``0700`` directory. ``O_EXCL``
    means an existing artefact is never silently overwritten."""
    filename = positions_artifact_filename(observation.endpoint, stamp=stamp)
    if not filename.startswith(PRIVATE_ARTIFACT_PREFIX) or os.sep in filename:
        raise PositionsCaptureError("refusing to write an artefact without the PRIVATE_ prefix")

    text = render_positions_report(observation)

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


# -- entrypoint -----------------------------------------------------------


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, add_help=True)
    parser.add_argument(
        "--endpoint",
        required=True,
        help="Plain path to read, e.g. a portfolio-positions path. REQUIRED: "
        "a default would put a private path back into source as a literal.",
    )
    parser.add_argument(
        "--stamp",
        default=None,
        help="Filename suffix distinguishing one re-capture from the next.",
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
    """Returns 0 when an OBSERVATION was recorded -- a 503 exits 0 too. Only
    status, byte count, position count and the artefact path are printed."""
    guard = CredentialGuard()
    sys.excepthook = build_safe_excepthook(guard)

    args = parse_args(argv)
    try:
        observation = asyncio.run(
            run_capture(
                args.endpoint,
                directory=args.evidence_dir,
                stamp=args.stamp,
                guard=guard,
            )
        )
        path = write_positions_artifact(observation, directory=args.evidence_dir, stamp=args.stamp)
    except SmokeRefusal as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    except (ValueError, FileExistsError, PositionsCaptureError) as exc:
        print(f"REFUSED: {describe_exception(exc, ())}", file=sys.stderr)
        return 1
    except PolymarketUSError as exc:
        print(f"CONFIGURATION ERROR: {describe_exception(exc, ())}", file=sys.stderr)
        return 1

    print(f"http status    : {observation.http_status}")
    print(f"body bytes     : {observation.body_byte_count}")
    print(f"position count : {observation.position_count}")
    print(f"artefact       : {path}")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator entrypoint
    raise SystemExit(main())
