"""Capture a NO-side ``/v1/order/preview`` and the same market's book -- evidence only.

Authority: ``docs/plans/NO_SIDE_EDGE_2026-09-14.md`` S5 exit criterion N2-9 and
risk section 5 item 5. Answers two questions BEFORE any NO-side code under
``exec/`` ships:

1. Does the venue accept ``outcomeSide=OUTCOME_SIDE_NO`` + ``action=ORDER_ACTION_BUY``
   on the CAPTURED create-order schema, and what price does the previewed order carry?
2. Does the venue serve a separate NO book, or is the NO price exactly
   ``1 - YES_bid`` off the one book ``GET /v1/markets/{slug}/book`` returns?

Never creates, modifies, or cancels an order. The ONLY write verb it can issue is
the preview, and only under ``--execute``. Default mode is a dry run: it prints the
exact request it WOULD send (auth headers redacted) and exits 0 with zero egress.

Schema note (load-bearing). The SDK snapshot
(``docs/evidence/venue/polymarket_us/sdk_snapshot/polymarket_us_0.1.2/types/orders.py``)
types ``CreateOrderParams`` with a single ``intent`` enum
(``ORDER_INTENT_BUY_LONG`` ...). The schema Breezy actually sends and the venue has
accepted live (``src/breezy/adapters/polymarket_us/exec/submit_chain.py``
``ORDER_BODY_KEYS`` / ``build_order_body``) carries NO ``intent`` at all; it carries
``outcomeSide`` + ``action`` instead. This script mirrors the CAPTURED key set
byte-for-byte and varies ONLY the ``outcomeSide`` value. ``ORDER_BODY_KEYS`` is
restated here rather than imported: nothing under ``exec/`` may be imported by this
script (import barrier), and a test pins the two sets equal.

Preview envelope. ``PreviewOrderParams`` in the SDK snapshot wraps the order as
``{"request": CreateOrderParams}``; that envelope is the default. ``--unwrapped``
sends the bare order body instead, for the case where the venue rejects the
envelope -- both variants are recorded verbatim in the artefact when used.

Cage note. Under the repo's read-only barriers
(``tests/unit/test_polymarket_us_readonly_guard.py``) this file is venue-touching
(C4/C5) and carries a POST literal, an order-path literal and a ``.post`` attribute
(V1/V2/V3). It therefore CANNOT ship under ``scripts/`` without being added to
``B4_EXEMPT_PATHS`` (and the pinned ``CAGE_EXEMPTIONS`` count) by explicit review,
exactly as the write-signing probe script under ``scripts/venue/`` was. That is
a deliberate, visible cost, not something to route around. (D4 pins the
write-signing probe's OWN module name as unimportable anywhere else, INCLUDING
in a dotted-string literal -- naming its path/module here as a plain string
would itself trip that scan, so this note deliberately does not spell it out.)

Usage (dry run, no network)::

    uv run python scripts/analysis/capture_no_side_preview.py \\
        --slug tc-temp-mdwhigh-2026-09-14-gte76lt77f --price 0.05

Usage (live capture, under the operator permit context ONLY)::

    BREEZY_VENUE_LIVE=1 uv run python scripts/analysis/capture_no_side_preview.py \\
        --slug tc-temp-mdwhigh-2026-09-14-gte76lt77f --price 0.05 --execute

CLOSE mode (``--close``). ``docs/plans/POSITION_EXIT_EXECUTION_2026-09-16.md``
Section 4 step 1: capture a CLOSING order preview against a held position
instead of a NO-side opening buy. Same 10-key schema, ``action=
ORDER_ACTION_SELL`` and ``outcomeSide`` per ``--outcome``; the wire price is
the shipped ``leg_prices.wire_price_for_leg`` complement of ``--price`` (the
INSTRUMENT price), never re-derived here. Still only ever POSTs the preview
path -- ``assert_preview_path_only`` refuses anything else::

    uv run python scripts/analysis/capture_no_side_preview.py \\
        --close --slug tc-temp-mdwhigh-2026-09-15-gte80lt81f --outcome yes --price 0.01

    BREEZY_VENUE_LIVE=1 uv run python scripts/analysis/capture_no_side_preview.py \\
        --close --slug tc-temp-mdwhigh-2026-09-15-gte80lt81f --outcome yes \\
        --price 0.01 --execute
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Final, cast

# ---------------------------------------------------------------------------
# Constants -- the captured schema, restated (see module docstring)
# ---------------------------------------------------------------------------

#: Exact key set of the live CreateOrderRequest Breezy sends
#: (``exec/submit_chain.py`` ``ORDER_BODY_KEYS``). Pinned equal by test.
ORDER_BODY_KEYS: Final[frozenset[str]] = frozenset(
    {
        "marketSlug",
        "type",
        "price",
        "quantity",
        "tif",
        "outcomeSide",
        "action",
        "manualOrderIndicator",
        "synchronousExecution",
        "maxBlockTime",
    }
)

OUTCOME_SIDE_NO: Final[str] = "OUTCOME_SIDE_NO"
OUTCOME_SIDE_YES: Final[str] = "OUTCOME_SIDE_YES"
ORDER_ACTION_BUY: Final[str] = "ORDER_ACTION_BUY"
#: CLOSE mode only (a SELL of a held leg). Never used by the NO-side opening
#: buy path above, which stays ORDER_ACTION_BUY.
ORDER_ACTION_SELL: Final[str] = "ORDER_ACTION_SELL"
ORDER_TYPE_LIMIT: Final[str] = "ORDER_TYPE_LIMIT"
TIF_IOC: Final[str] = "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL"
MANUAL_AUTOMATIC: Final[str] = "MANUAL_ORDER_INDICATOR_AUTOMATIC"
MAX_BLOCK_TIME: Final[str] = "5"
QUANTITY: Final[int] = 1
CURRENCY: Final[str] = "USD"

PREVIEW_PATH: Final[str] = "/v1/order/preview"
BOOK_PATH_TEMPLATE: Final[str] = "/v1/markets/{slug}/book"
WRITE_METHOD: Final[str] = "POST"
READ_METHOD: Final[str] = "GET"

EVIDENCE_DIRECTORY: Final[Path] = Path("docs/evidence/venue/polymarket_us")
EVIDENCE_PREFIX: Final[str] = "NO_SIDE_PREVIEW_"
#: CLOSE mode's evidence prefix (POSITION_EXIT_EXECUTION_2026-09-16.md S4.1).
CLOSE_EVIDENCE_PREFIX: Final[str] = "CLOSE_PREVIEW_"
EVIDENCE_FILE_MODE: Final[int] = 0o600

#: CLOSE mode's ``--outcome`` -> ``outcomeSide`` table. A plain dict, not a
#: branch, so a third outcome cannot silently fall through to a wrong side.
CLOSE_OUTCOME_SIDE: Final[dict[str, str]] = {"yes": OUTCOME_SIDE_YES, "no": OUTCOME_SIDE_NO}

#: Header NAMES whose values are never printed or written. Same set the
#: adapter's ``redaction.py`` blanks; restated so the dry run needs no imports.
SENSITIVE_HEADERS: Final[frozenset[str]] = frozenset(
    {"x-pm-access-key", "x-pm-signature", "x-pm-timestamp", "authorization", "cookie"}
)
REDACTED: Final[str] = "<redacted>"

PRICE_EXCLUSIVE_LOW: Final[Decimal] = Decimal("0.00")
PRICE_EXCLUSIVE_HIGH: Final[Decimal] = Decimal("1.00")
PRICE_TICK: Final[Decimal] = Decimal("0.01")

#: Two requests total. Held to the shipped read budgets; no retry on a
#: refusal -- a 429 or a 5xx is an OUTCOME to record, not a reason to hammer.
REQUEST_COUNT: Final[int] = 2

REPO_ROOT: Final[Path] = Path(
    os.environ.get("BREEZY_REPO_ROOT") or Path(__file__).resolve().parents[2]
)


# ---------------------------------------------------------------------------
# Pure helpers (no egress, no adapter imports)
# ---------------------------------------------------------------------------


def parse_price(raw: str) -> Decimal:
    """A 2-dp price strictly inside (0, 1), on the 0.01 tick."""
    try:
        price = Decimal(raw)
    except InvalidOperation as exc:
        raise argparse.ArgumentTypeError(f"price is not a decimal: {raw!r}") from exc
    if not PRICE_EXCLUSIVE_LOW < price < PRICE_EXCLUSIVE_HIGH:
        raise argparse.ArgumentTypeError("price must be strictly between 0.00 and 1.00")
    if price != price.quantize(PRICE_TICK):
        raise argparse.ArgumentTypeError("price must sit on the 0.01 tick")
    return price.quantize(PRICE_TICK)


def parse_quantity(raw: str) -> int:
    """A positive integer contract count (``--close`` only)."""
    try:
        quantity = int(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"quantity is not an integer: {raw!r}") from exc
    if quantity < 1:
        raise argparse.ArgumentTypeError("quantity must be a positive integer")
    return quantity


def validate_slug(slug: str) -> str:
    """Weather slug grammar as observed on the tape: ``tc-temp-<sta>high-YYYY-MM-DD-<bucket>``."""
    parts = slug.split("-")
    if len(parts) < 6 or parts[0] != "tc" or parts[1] != "temp":
        raise argparse.ArgumentTypeError(
            f"slug does not match the observed weather grammar: {slug!r}"
        )
    if any(not p or not p.isalnum() for p in parts):
        raise argparse.ArgumentTypeError(
            f"slug contains an empty or non-alphanumeric segment: {slug!r}"
        )
    return slug


def build_preview_order_body(*, slug: str, price: Decimal, outcome_side: str) -> dict[str, Any]:
    """The CAPTURED create-order body with only ``outcomeSide`` varied."""
    body = {
        "marketSlug": slug,
        "type": ORDER_TYPE_LIMIT,
        "price": {"value": f"{price:.2f}", "currency": CURRENCY},
        "quantity": QUANTITY,
        "tif": TIF_IOC,
        "outcomeSide": outcome_side,
        "action": ORDER_ACTION_BUY,
        "manualOrderIndicator": MANUAL_AUTOMATIC,
        "synchronousExecution": True,
        "maxBlockTime": MAX_BLOCK_TIME,
    }
    if set(body) != ORDER_BODY_KEYS:
        raise ValueError("preview body key set drifted from the captured schema")
    return body


def _wire_price_for_close(outcome: str, price: Decimal) -> Decimal:
    """The wire ``price.value`` for a CLOSING order, via the SHIPPED
    complement helper -- never re-derived here.

    ``leg_prices.wire_price_for_leg`` already carries the ``1 - x`` flip for
    the live NO buy (``exec/submit_chain.build_order_body``); importing it
    keeps exactly one place in the repo doing that arithmetic. Local import:
    this is the only function in the module that needs the adapter package,
    and the dry run for the opening-buy modes above must stay import-free.
    """
    if outcome not in CLOSE_OUTCOME_SIDE:
        raise ValueError(f"unknown outcome {outcome!r}; expected 'yes' or 'no'")
    src_dir = REPO_ROOT / "src"
    if str(src_dir) not in sys.path:
        sys.path.insert(0, str(src_dir))
    from breezy.adapters.polymarket_us.leg_prices import Leg, wire_price_for_leg

    return wire_price_for_leg(cast(Leg, outcome), price)


def build_close_order_body(
    *, slug: str, price: Decimal, outcome: str, quantity: int
) -> dict[str, Any]:
    """The CLOSING create-order body: ``action=ORDER_ACTION_SELL``,
    ``outcomeSide`` per ``outcome``, same 10-key schema as the opening buy.

    ``price`` is the INSTRUMENT price (Nautilus convention, strictly inside
    (0, 1)); see :func:`_wire_price_for_close` for the wire conversion.
    """
    if outcome not in CLOSE_OUTCOME_SIDE:
        raise ValueError(f"unknown outcome {outcome!r}; expected 'yes' or 'no'")
    wire_price = _wire_price_for_close(outcome, price)
    body = {
        "marketSlug": slug,
        "type": ORDER_TYPE_LIMIT,
        "price": {"value": f"{wire_price:.2f}", "currency": CURRENCY},
        "quantity": quantity,
        "tif": TIF_IOC,
        "outcomeSide": CLOSE_OUTCOME_SIDE[outcome],
        "action": ORDER_ACTION_SELL,
        "manualOrderIndicator": MANUAL_AUTOMATIC,
        "synchronousExecution": True,
        "maxBlockTime": MAX_BLOCK_TIME,
    }
    if set(body) != ORDER_BODY_KEYS:
        raise ValueError("close order body key set drifted from the captured schema")
    return body


def assert_preview_path_only(path: str) -> None:
    """Refuse absolutely: every write this script issues must be exactly
    ``PREVIEW_PATH``. Never creates, modifies, or cancels an order."""
    if path != PREVIEW_PATH:
        raise ValueError(f"refusing to send to {path!r}; only {PREVIEW_PATH!r} is permitted")


def extract_order_echo(preview_record: Mapping[str, Any]) -> dict[str, Any]:
    """Pull the venue's echoed ``order`` fields out of a preview response.

    Returns an empty mapping (never raises) when the body did not parse to
    the expected ``{"order": {...}}`` shape -- an unparsed or error response
    is still a valid, recordable outcome for this capture.
    """
    response = preview_record.get("response")
    body = response.get("body") if isinstance(response, dict) else None
    order = body.get("order") if isinstance(body, dict) else None
    return order if isinstance(order, dict) else {}


def build_preview_envelope(order_body: Mapping[str, Any], *, unwrapped: bool) -> dict[str, Any]:
    """SDK ``PreviewOrderParams`` shape (``{"request": ...}``) unless ``--unwrapped``."""
    return dict(order_body) if unwrapped else {"request": dict(order_body)}


def encode_body(body: Mapping[str, Any]) -> bytes:
    """Same encoding discipline as the live submit path: compact, sorted keys."""
    return json.dumps(body, separators=(",", ":"), sort_keys=True).encode("utf-8")


def redact_header_pairs(headers: Mapping[str, str]) -> dict[str, str]:
    return {
        name: (REDACTED if name.lower() in SENSITIVE_HEADERS else value)
        for name, value in headers.items()
    }


def request_record(
    *, method: str, base_url: str, path: str, headers: Mapping[str, str], body: bytes | None
) -> dict[str, Any]:
    """What is printed and what is written: never an unredacted header."""
    record: dict[str, Any] = {
        "method": method,
        "url": f"{base_url.rstrip('/')}{path}",
        "path": path,
        "headers": redact_header_pairs(headers),
    }
    if body is not None:
        record["body"] = json.loads(body.decode("utf-8"))
    return record


def decode_response_body(body: bytes | None) -> Any:
    """Verbatim JSON when it parses; otherwise the raw text, flagged."""
    if body is None:
        return None
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return {"_unparsed_text": body.decode("utf-8", errors="replace")}


def utc_stamp(now: dt.datetime | None = None) -> str:
    moment = now or dt.datetime.now(dt.UTC)
    return moment.strftime("%Y%m%dT%H%M%SZ")


def evidence_path(stamp: str) -> Path:
    return REPO_ROOT / EVIDENCE_DIRECTORY / f"{EVIDENCE_PREFIX}{stamp}.json"


def close_evidence_path(outcome: str, stamp: str) -> Path:
    return REPO_ROOT / EVIDENCE_DIRECTORY / f"{CLOSE_EVIDENCE_PREFIX}{outcome}_{stamp}.json"


def write_evidence_excl(path: Path, text: str) -> None:
    """Append-only evidence: refuse to overwrite, 0600, fsync."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, EVIDENCE_FILE_MODE)
    try:
        os.write(fd, text.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="capture_no_side_preview",
        description=(
            "Capture a NO-side /v1/order/preview and the same market's book as "
            "N2-9 evidence. Default is a DRY RUN with zero network egress; "
            "--execute performs exactly one preview POST and one book GET. "
            "Never creates, modifies, or cancels an order. "
            "--execute requires the venue credentials env sourced (the same "
            "env file the write-signing probe and node use): at minimum "
            "POLYMARKET_US_USER_AGENT plus the signing key material. Running "
            "--execute without it FATALs -- expected and correct, never a "
            "silent skip; source the venue env file first."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Fields to inspect in the response: preview.response.status; "
            "preview.response.body.order.{marketSlug,side,intent,price,quantity,state}; "
            "book.response.body.{bids,offers,state} -- compare the previewed NO price "
            "against 1 - best YES bid."
        ),
    )
    parser.add_argument(
        "--slug", required=True, type=validate_slug, help="Market slug (weather grammar)."
    )
    parser.add_argument(
        "--price",
        required=True,
        type=parse_price,
        help=(
            "NO-leg limit price in USD, 2 dp, strictly inside (0, 1). Choose an "
            "UNMARKETABLE value."
        ),
    )
    parser.add_argument(
        "--outcome-side",
        default=OUTCOME_SIDE_NO,
        choices=(OUTCOME_SIDE_NO, OUTCOME_SIDE_YES),
        help="outcomeSide value; default OUTCOME_SIDE_NO (YES is offered only as a control).",
    )
    parser.add_argument(
        "--unwrapped",
        action="store_true",
        help='Send the bare order body instead of the SDK {"request": ...} envelope.',
    )
    parser.add_argument(
        "--close",
        action="store_true",
        help=(
            "Capture a CLOSING order preview (action=ORDER_ACTION_SELL) against a "
            "held position instead of a NO-side opening buy. Requires --outcome; "
            "--outcome-side is ignored in this mode."
        ),
    )
    parser.add_argument(
        "--outcome",
        default=None,
        choices=("yes", "no"),
        help="Held leg to close (--close only): 'yes' or 'no'.",
    )
    parser.add_argument(
        "--quantity",
        default=1,
        type=parse_quantity,
        help="Contracts to close (--close only); default 1.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help=(
            "Perform the preview POST (and, outside --close, the book GET). "
            "Without this flag nothing leaves the host."
        ),
    )
    args = parser.parse_args(argv)
    if args.close and args.outcome is None:
        parser.error("--close requires --outcome {yes,no}")
    if not args.close and args.outcome is not None:
        parser.error("--outcome is only valid with --close")
    return args


# ---------------------------------------------------------------------------
# Live capture (imports are deliberately local: the dry run needs none of them)
# ---------------------------------------------------------------------------


async def _capture_live(args: argparse.Namespace, envelope: Mapping[str, Any]) -> dict[str, Any]:
    """One preview POST, one book GET. Adapter imports live here on purpose."""
    scripts_venue = REPO_ROOT / "scripts" / "venue"
    for entry in (REPO_ROOT / "src", scripts_venue):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))

    from nautilus_trader.common.component import LiveClock
    from nautilus_trader.core import nautilus_pyo3
    from polymarket_us_auth_smoke import CredentialGuard, build_safe_excepthook, prepare

    from breezy.adapters.polymarket_us.errors import PolymarketUSError
    from breezy.adapters.polymarket_us.http import PolymarketUSHttpClient
    from breezy.adapters.polymarket_us.signing import Ed25519RequestSigner
    from breezy.adapters.polymarket_us.transport import (
        QUOTA_KEY_BOOK,
        QUOTA_KEY_PORTFOLIO,
        NautilusHttpTransport,
        build_default_quota,
        build_keyed_quotas,
        build_shared_http_client,
    )
    from breezy.adapters.polymarket_us.write_transport import Ed25519WriteRequestSigner

    guard = CredentialGuard()
    sys.excepthook = build_safe_excepthook(guard)
    prepared = prepare(os.environ, guard=guard)  # core dumps off -> enable gate -> creds
    config = prepared.config
    credentials = prepared.credentials
    clock = LiveClock()

    class _Quiet:
        def debug(self, message: str) -> None: ...
        def info(self, message: str) -> None: ...
        def warning(self, message: str) -> None: ...
        def error(self, message: str) -> None: ...

    # -- book read: the shipped GET-only path -----------------------------
    read_client = build_shared_http_client(
        timeout_secs=config.http_timeout_secs,
        default_quota=build_default_quota(config.global_requests_per_second),
        keyed_quotas=build_keyed_quotas(
            instrument_requests_per_minute=config.instrument_requests_per_minute,
            book_requests_per_minute=config.book_requests_per_minute,
        ),
        default_headers={"User-Agent": str(config.user_agent)},
    )
    http = PolymarketUSHttpClient(
        transport=NautilusHttpTransport(client=read_client),
        signer=Ed25519RequestSigner(credentials, clock=clock),
        api_base_url=config.api_base_url,
        gateway_base_url=config.gateway_base_url,
        logger=_Quiet(),
    )
    book_path = BOOK_PATH_TEMPLATE.format(slug=args.slug)
    book_record: dict[str, Any] = {
        "request": request_record(
            method=READ_METHOD,
            base_url=config.api_base_url,
            path=book_path,
            headers={"User-Agent": str(config.user_agent)},
            body=None,
        )
    }
    try:
        book_response = await http.get_authenticated(book_path, quota_key=QUOTA_KEY_BOOK)
        book_record["response"] = {"status": 200, "body": book_response}
    except PolymarketUSError as exc:
        book_record["response"] = {"status": None, "error_type": type(exc).__name__}

    # -- preview POST: the ONE write verb, signed by the shipped write signer --
    write_signer = Ed25519WriteRequestSigner(credentials, clock=clock)
    signed = dict(write_signer.sign_headers(WRITE_METHOD, PREVIEW_PATH))
    headers = {**signed, "Content-Type": "application/json", "User-Agent": str(config.user_agent)}
    body = encode_body(envelope)
    preview_record: dict[str, Any] = {
        "request": request_record(
            method=WRITE_METHOD,
            base_url=config.api_base_url,
            path=PREVIEW_PATH,
            headers=headers,
            body=body,
        )
    }
    write_client = nautilus_pyo3.HttpClient(
        default_headers={"User-Agent": str(config.user_agent)},
        header_keys=[],
        keyed_quotas=[],
        default_quota=build_default_quota(config.global_requests_per_second),
        timeout_secs=int(config.http_timeout_secs),
    )
    url = f"{config.api_base_url.rstrip('/')}{PREVIEW_PATH}"
    try:
        response = await write_client.post(
            url, headers=headers, body=body, keys=[QUOTA_KEY_PORTFOLIO]
        )
        preview_record["response"] = {
            "status": int(response.status),
            "body": decode_response_body(bytes(response.body)),
        }
    except (nautilus_pyo3.HttpError, nautilus_pyo3.HttpTimeoutError) as exc:
        preview_record["response"] = {"status": None, "error_type": type(exc).__name__}

    secrets = [credentials.key_id.get_value(), credentials.secret_key.get_value()]
    return {"preview": preview_record, "book": book_record, "_secrets": secrets}


async def _capture_close_live(
    args: argparse.Namespace, envelope: Mapping[str, Any]
) -> dict[str, Any]:
    """One preview POST for a CLOSING order. No book GET, no other write verb.

    Adapter imports live here on purpose -- the dry run needs none of them.
    """
    scripts_venue = REPO_ROOT / "scripts" / "venue"
    for entry in (REPO_ROOT / "src", scripts_venue):
        if str(entry) not in sys.path:
            sys.path.insert(0, str(entry))

    from nautilus_trader.common.component import LiveClock
    from nautilus_trader.core import nautilus_pyo3
    from polymarket_us_auth_smoke import CredentialGuard, build_safe_excepthook, prepare

    from breezy.adapters.polymarket_us.transport import QUOTA_KEY_PORTFOLIO, build_default_quota
    from breezy.adapters.polymarket_us.write_transport import Ed25519WriteRequestSigner

    guard = CredentialGuard()
    sys.excepthook = build_safe_excepthook(guard)
    prepared = prepare(os.environ, guard=guard)  # core dumps off -> enable gate -> creds
    config = prepared.config
    credentials = prepared.credentials
    clock = LiveClock()

    assert_preview_path_only(PREVIEW_PATH)
    write_signer = Ed25519WriteRequestSigner(credentials, clock=clock)
    signed = dict(write_signer.sign_headers(WRITE_METHOD, PREVIEW_PATH))
    headers = {**signed, "Content-Type": "application/json", "User-Agent": str(config.user_agent)}
    body = encode_body(envelope)
    preview_record: dict[str, Any] = {
        "request": request_record(
            method=WRITE_METHOD,
            base_url=config.api_base_url,
            path=PREVIEW_PATH,
            headers=headers,
            body=body,
        )
    }
    write_client = nautilus_pyo3.HttpClient(
        default_headers={"User-Agent": str(config.user_agent)},
        header_keys=[],
        keyed_quotas=[],
        default_quota=build_default_quota(config.global_requests_per_second),
        timeout_secs=int(config.http_timeout_secs),
    )
    url = f"{config.api_base_url.rstrip('/')}{PREVIEW_PATH}"
    try:
        response = await write_client.post(
            url, headers=headers, body=body, keys=[QUOTA_KEY_PORTFOLIO]
        )
        preview_record["response"] = {
            "status": int(response.status),
            "body": decode_response_body(bytes(response.body)),
        }
    except (nautilus_pyo3.HttpError, nautilus_pyo3.HttpTimeoutError) as exc:
        preview_record["response"] = {"status": None, "error_type": type(exc).__name__}

    secrets = [credentials.key_id.get_value(), credentials.secret_key.get_value()]
    return {"preview": preview_record, "_secrets": secrets}


def _assert_no_secret_material(text: str, secrets: Sequence[str]) -> None:
    """Fail closed: refuse to emit an artefact carrying any 4-char window of a secret."""
    for secret in secrets:
        if not secret:
            continue
        windows = {secret[i : i + 4] for i in range(max(1, len(secret) - 3))}
        if any(w in text for w in windows):
            raise RuntimeError("refusing to write evidence: secret-derived material detected")


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.close:
        order_body = build_close_order_body(
            slug=args.slug, price=args.price, outcome=args.outcome, quantity=args.quantity
        )
    else:
        order_body = build_preview_order_body(
            slug=args.slug, price=args.price, outcome_side=args.outcome_side
        )
    envelope = build_preview_envelope(order_body, unwrapped=args.unwrapped)
    stamp = utc_stamp()

    dry: dict[str, Any] = {
        "mode": "DRY_RUN" if not args.execute else "EXECUTE",
        "captured_at": stamp,
        "slug": args.slug,
        "preview_request": request_record(
            method=WRITE_METHOD,
            base_url="<api_base_url from config>",
            path=PREVIEW_PATH,
            headers={
                "X-PM-Access-Key": REDACTED,
                "X-PM-Timestamp": REDACTED,
                "X-PM-Signature": REDACTED,
                "Content-Type": "application/json",
            },
            body=encode_body(envelope),
        ),
        "writes_possible": ["POST " + PREVIEW_PATH],
        "creates_orders": False,
    }
    if args.close:
        dry["close"] = True
        dry["outcome"] = args.outcome
        dry["quantity"] = args.quantity
    else:
        dry["book_request"] = {
            "method": READ_METHOD,
            "path": BOOK_PATH_TEMPLATE.format(slug=args.slug),
        }
    print(json.dumps(dry, indent=2, sort_keys=True))
    if not args.execute:
        print("dry run: no network call was made; pass --execute to capture.", file=sys.stderr)
        return 0

    import asyncio

    if args.close:
        captured = asyncio.run(_capture_close_live(args, envelope))
        secrets = captured.pop("_secrets")
        order = extract_order_echo(captured["preview"])
        document: dict[str, Any] = {
            "schema": "breezy.close_preview_capture.v1",
            "captured_at": stamp,
            "slug": args.slug,
            "outcome": args.outcome,
            "quantity": args.quantity,
            "envelope": "unwrapped" if args.unwrapped else "sdk_request_wrapper",
            "echo": {
                "intent": order.get("intent"),
                "side": order.get("side"),
                "outcomeSide": order_body["outcomeSide"],
                "price": order.get("price"),
                "state": order.get("state"),
                "id": order.get("id"),
            },
            **captured,
        }
        path = close_evidence_path(args.outcome, stamp)
    else:
        captured = asyncio.run(_capture_live(args, envelope))
        secrets = captured.pop("_secrets")
        document = {
            "schema": "breezy.no_side_preview_capture.v1",
            "captured_at": stamp,
            "slug": args.slug,
            "outcome_side": args.outcome_side,
            "envelope": "unwrapped" if args.unwrapped else "sdk_request_wrapper",
            **captured,
        }
        path = evidence_path(stamp)

    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    _assert_no_secret_material(text, secrets)
    write_evidence_excl(path, text)
    print(f"evidence written: {path}", file=sys.stderr)
    preview_status = document["preview"].get("response", {}).get("status")
    print(f"preview status: {preview_status}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
