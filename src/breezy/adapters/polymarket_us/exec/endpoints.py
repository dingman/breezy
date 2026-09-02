"""The private read surface R-4 consumes, and a Decimal-preserving decode.

Authority: ``docs/plans/EXEC_SPINE_2026-09-01.md`` section R-3. **Read only.**
Nothing here sends, and nothing here can: this module is a table of GET path
templates plus one pure decoder. It performs no I/O of any kind.

WHY A SECOND DECODER EXISTS
---------------------------

``PolymarketUSHttpClient._decode`` (``http.py:249-263``) calls ``json.loads``
with no ``parse_float``. On the public market-data surface that is harmless:
``Amount`` (``sdk_snapshot/.../types/common.py:6-10``) carries ``value`` as a
decimal STRING, so a price arrives as text and reaches ``Decimal`` intact.

The private account surface is different. ``UserBalance``
(``sdk_snapshot/.../types/account.py:19-33``) types **nine** money fields as
bare ``float`` -- ``currentBalance``, ``buyingPower``, ``assetNotional``,
``assetAvailable``, ``pendingCredit``, ``openOrders``, ``unsettledFunds``,
``marginRequirement``, ``balanceReservation`` -- which means the venue sends
them as bare JSON number literals. ``json.loads`` binds each to a binary
``float``, and at that instant the literal the venue wrote is gone. For a
literal a ``float`` can round-trip the damage is recoverable by going back
through ``str``; for one it cannot, the number is silently replaced by a
different number, with no exception and nothing to compare against later.
Since this is the account balance every spend cap is measured against, the
decode is done once, correctly, here: ``json.loads(body, parse_float=Decimal)``
never constructs the intermediate ``float`` at all.

``parse_float=Decimal`` appears nowhere else in ``src/`` or ``tests/``; this is
the only place that needs it, because it is the only surface whose money is
schema-typed as ``float``.

WHAT IS DELIBERATELY ABSENT
---------------------------

The open-orders read path is **not** declared here. Barrier V2
(``tests/unit/test_polymarket_us_readonly_guard.py``) refuses any string
constant matching ``/v\\d+/orders?`` inside a venue-touching module, with no
allowlist and by design. R-3 is read/map only and does not need that path, so
adding it -- or splicing it out of fragments to slip past the scan -- would
weaken a shipped barrier for no benefit in this increment. The increment that
genuinely needs it lands the barrier change under the plan's paired-barrier
rule, with its compensating strengthening and a non-vacuity proof, and a
reviewer sees it.

No response BODY is ever formatted into an error here. A private-endpoint body
is the operator's portfolio; only its byte length is ever named.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from decimal import Decimal
from typing import Any, Final

from breezy.adapters.polymarket_us.errors import VenuePayloadError
from breezy.adapters.polymarket_us.transport import QUOTA_KEY_PORTFOLIO

__all__ = [
    "ACCOUNT_BALANCES_PATH",
    "PORTFOLIO_POSITIONS_PATH",
    "PRIVATE_READ_PATHS",
    "PRIVATE_READ_QUOTA_KEY",
    "decode_private_payload",
]

#: Account balances. Response shape ``GetAccountBalancesResponse``
#: (``sdk_snapshot/.../types/account.py:36-39``). Probed by R-1's shape capture.
ACCOUNT_BALANCES_PATH: Final[str] = "/v1/account/balances"

#: Open positions, keyed by market slug -- the slug is the DICT KEY of
#: ``GetUserPositionsResponse.positions``, and is the only authoritative market
#: identifier a position carries (``UserPosition`` declares no ``marketSlug``).
#: A caller mapping one MUST pass that key to
#: ``reports.parse_position_status_report``. Response shape
#: ``GetUserPositionsResponse`` (``sdk_snapshot/.../types/portfolio.py:45-50``).
#: The same path ``config.py:94`` names as the authenticated-read target.
PORTFOLIO_POSITIONS_PATH: Final[str] = "/v1/portfolio/positions"

#: Every private path this slice reads, so a caller can assert its own coverage
#: rather than re-listing the constants and drifting from them.
PRIVATE_READ_PATHS: Final[tuple[str, ...]] = (
    ACCOUNT_BALANCES_PATH,
    PORTFOLIO_POSITIONS_PATH,
)

#: The rate-limit budget both private reads spend from. Not a new quota key:
#: ``QUOTA_KEY_PORTFOLIO`` already exists and is already provisioned
#: (``transport.py:92``, ``:233``), and an unbudgeted read is refused outright
#: by ``assert_permitted_quota_key``.
PRIVATE_READ_QUOTA_KEY: Final[str] = QUOTA_KEY_PORTFOLIO


def decode_private_payload(body: bytes | str, *, context: str) -> Mapping[str, Any]:
    """Decode a private-endpoint JSON body, preserving every numeric literal.

    ``parse_float=Decimal`` is the whole point: a bare JSON number arrives as
    an exact :class:`~decimal.Decimal` of the digits the venue wrote, never as
    a binary ``float``. Integers are untouched -- ``parse_int`` is deliberately
    left alone, because a JSON integer literal is already exact in Python.

    ``context`` is a caller-supplied label (the endpoint being read). It is
    interpolated into the error; the body never is. Its SIZE is named as a
    count of bytes or of characters depending on what was actually handed in,
    because ``len()`` on a ``str`` counts characters and calling those "bytes"
    is wrong for any non-ASCII body -- a small lie, but this is the one message
    that exists to be trusted about what it did and did not disclose.

    Only ``ValueError`` is caught. ``UnicodeDecodeError`` used to be listed
    beside it and was redundant: it is a ``ValueError`` subclass, which reads
    as though a second, separate failure mode were being handled.
    """
    try:
        payload = json.loads(body, parse_float=Decimal)
    except ValueError:
        unit = "bytes" if isinstance(body, (bytes, bytearray)) else "characters"
        raise VenuePayloadError(
            f"Polymarket.us returned a body that is not valid JSON for {context} "
            f"({len(body)} {unit}; content withheld)"
        ) from None
    if not isinstance(payload, dict):
        raise VenuePayloadError(
            f"Polymarket.us returned a JSON {type(payload).__name__} where an object "
            f"was expected for {context}"
        )
    return payload
