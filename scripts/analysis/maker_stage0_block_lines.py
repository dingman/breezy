"""MAKER-S2 second look C5r (D7): the holdout and D5 report lines, driven by the frozen block.

Block 1 (v1) returns the two ``maker_stage0_render`` constants byte-for-byte. Block 2 (v2) states
the block's own days, read from ``frozen.dates``; the ``block`` field is read defensively so this
module works whether or not the frozen set carries it (default 1).
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Final

from scripts.analysis import maker_stage0_render as render

__all__ = ["block_lines"]

_V2: Final[int] = 2
_D14: Final[dt.timedelta] = dt.timedelta(days=14)


def _span(days: list[dt.date]) -> str:
    return f"{days[0].isoformat()}..{days[-1].isoformat()}"


def _holdout_v2(span: str) -> str:
    return (
        f"Holdout touch: block days {span} are forward data under the holdout ruling 2026-10-03 "
        "(clause 3, descriptive evidence only); there is no tail-day read and the sealed "
        f"holdout day stays unread. Statistics for {span} are disclosed contamination for "
        "AUT-4 forward windows. "
        "This run fits nothing and never calls open_holdout."
    )


def _d5_v2(span: str, not_past: int, total: int) -> str:
    return (
        "- D5 the truth is the CLI FINAL as a proxy for venue resolution; there is no VOID or "
        f"UNRESOLVED handling ({not_past} of {total} block days {span} are not yet past D+14 at "
        "run time); band edges are inclusive (`bucket_facts_from_instrument_id`)."
    )


def block_lines(frozen: Any, *, now: dt.datetime | None = None) -> tuple[str, str]:
    """``(holdout_line, d5_line)`` for the frozen set's block; ``now`` is injectable (UTC)."""
    days = sorted(getattr(frozen, "dates", ()))
    if getattr(frozen, "block", 1) != _V2 or not days:
        return render.HOLDOUT_LINE, render._D5
    today = (now or dt.datetime.now(dt.UTC)).date()
    not_past = sum(1 for d in days if d + _D14 >= today)
    span = _span(days)
    return _holdout_v2(span), _d5_v2(span, not_past, len(days))
