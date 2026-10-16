"""Text-format AFOS CLI windows shared by the C6b producer and the truth-dataset reader.

MAKER-S2 second look, unit C6b (``S2_second_look_plan_r3_delta_coordinator.md`` section 1).
The IEM transport is text-only, so the s2b cross-check window is fetched as ``fmt=text``
and cached as a URL-hashed ``.txt``. Producer (``scripts/archive/iem_cli_window_text.py``)
and reader (``settlement_truth_dataset.read_window_issuances``) must agree on the URL, so
the one definition lives here. Pure: no I/O, no network, no dataset imports.
"""

from __future__ import annotations

import datetime as dt
from typing import Final
from urllib.parse import parse_qsl, urlencode, urlsplit

from settlement_alignment_study import (  # type: ignore[import-not-found]
    afos_url,
    parse_issued_at,
    split_iem_afos_products,
)

#: The only stations the s2b cross-check window is ever fetched or emitted for.
MAKER_S2B_CITIES: Final[tuple[str, ...]] = ("LAX", "MDW", "MIA", "SFO")
MAKER_S2B_WINDOW_START: Final[dt.date] = dt.date(2026, 9, 29)
MAKER_S2B_WINDOW_END: Final[dt.date] = dt.date(2026, 11, 15)
MAKER_S2B_LIMIT: Final[int] = 3_000

_UNSTAMPED_MEMBER: Final[str] = "CLI{loc}_unstamped_{index:05d}.txt"


def text_window_url(cli_location: str, start: dt.date, end: dt.date, limit: int) -> str:
    """The shared ``afos_url`` grammar (limit bound enforced there) with ``fmt=text``."""
    parts = urlsplit(afos_url(cli_location, start, end, limit=limit))
    query = [(key, "text" if key == "fmt" else value) for key, value in parse_qsl(parts.query)]
    return f"{parts.scheme}://{parts.netloc}{parts.path}?{urlencode(query)}"


def text_window_members(raw_text: str, cli_location: str) -> tuple[tuple[str, bytes], ...]:
    """Split a ``fmt=text`` body into ``(member_name, member_bytes)`` pairs.

    Built on ``split_iem_afos_products`` (which rewrites the WMO sequence to ``000`` -- a
    documented limit of the text path; the zip path preserves it). Each pair is shaped like
    a zip member so the existing ``issuance_from_member`` parses it unchanged: the member
    name carries the ``_YYYYMMDDHHMM.txt`` issuance stamp, derived from the product's own
    ISSUED line, and the bytes drop the leading framing newline the splitter adds (the
    reader re-prepends exactly one). An unstampable product keeps a stamp-less name so the
    reader records it as a refusal instead of dropping it.
    """
    members: list[tuple[str, bytes]] = []
    for index, product in enumerate(split_iem_afos_products(raw_text)):
        issued = parse_issued_at(product)
        if issued is None:
            name = _UNSTAMPED_MEMBER.format(loc=cli_location, index=index)
        else:
            name = f"CLI{cli_location}_{issued.strftime('%Y%m%d%H%M')}.txt"
        members.append((name, product[1:].encode("utf-8")))
    return tuple(members)
