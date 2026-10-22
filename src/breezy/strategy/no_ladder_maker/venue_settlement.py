"""ARM D1: the ``maker_venue_settlement/v1`` file -- the venue's own YES resolutions.

``scripts/venue/maker_settlement_collect.py`` WRITES it (the only writer, from the account activity
feed); ``scripts/analysis/maker_loss_stop_producer.py`` READS it (no network). A slug that is
absent from ``yes_resolved`` is simply unresolved: the harm stop treats it as PENDING and, past
the settlement deadline, as a LOSS. Unknown or ambiguous is therefore always omitted, never guessed.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

from breezy.strategy.no_ladder_maker.harm_stop_artefact import write_json_atomic

__all__ = [
    "SETTLEMENT_MAX_AGE",
    "SOURCE_ACTIVITIES",
    "VENUE_SCHEMA",
    "VENUE_SETTLEMENTS_NAME",
    "VenueSettlementFile",
    "read_venue_settlement",
    "read_venue_yes",
    "render_venue_settlement",
    "untrusted_reason",
    "write_venue_settlement",
]

VENUE_SCHEMA: Final[str] = "maker_venue_settlement/v1"
#: the file's name beside ``latest.json``
VENUE_SETTLEMENTS_NAME: Final[str] = "venue_settlements.json"
SOURCE_ACTIVITIES: Final[str] = "activities"
#: the producer HOLDs when the file's ``fetched_at`` is older than this (it runs daily, so one
#: missed collector run is tolerated and a second is not)
SETTLEMENT_MAX_AGE: Final[timedelta] = timedelta(hours=24)


@dataclass(frozen=True, slots=True)
class VenueSettlementFile:
    """What the producer needs of the file: the resolutions, whether the feed was read to its end,
    and when. ``fetched_at`` is ``None`` when the file is absent, unreadable or carries no valid
    timestamp."""

    yes_resolved: dict[str, bool]
    complete: bool
    fetched_at: datetime | None


def read_venue_yes(path: Path | None) -> dict[str, bool]:
    """``{base slug: venue resolved YES}``; absent/unreadable/malformed -> ``{}`` (unresolved)."""
    if path is None:
        return {}
    try:
        body = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(body, dict) or body.get("schema") != VENUE_SCHEMA:
        return {}
    raw = body.get("yes_resolved")
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, bool)}


def read_venue_settlement(path: Path | None) -> VenueSettlementFile:
    """The whole file; absent/unreadable/malformed -> empty, incomplete, no timestamp."""
    empty = VenueSettlementFile({}, False, None)
    if path is None:
        return empty
    try:
        body = json.loads(path.read_text())
    except (OSError, ValueError):
        return empty
    if not isinstance(body, dict) or body.get("schema") != VENUE_SCHEMA:
        return empty
    fetched_at: datetime | None = None
    raw_at = body.get("fetched_at")
    if isinstance(raw_at, str):
        try:
            parsed = datetime.fromisoformat(raw_at)
        except ValueError:
            parsed = None
        if parsed is not None and parsed.tzinfo is not None:
            fetched_at = parsed.astimezone(UTC)
    return VenueSettlementFile(
        yes_resolved=read_venue_yes(path),
        complete=body.get("complete") is True,
        fetched_at=fetched_at,
    )


def untrusted_reason(settlement: VenueSettlementFile, *, now: datetime) -> str | None:
    """Why the file cannot back a verdict (a HOLD reason), or ``None`` when it can.

    Missing (no readable file / no valid ``fetched_at``), incomplete (the collector did not reach
    the feed's end) or stale (``fetched_at`` more than :data:`SETTLEMENT_MAX_AGE` before ``now``).
    A partial or old file proves nothing about the slugs it lacks."""
    if settlement.fetched_at is None:
        return "venue_settlement_missing"
    if not settlement.complete:
        return "venue_settlement_incomplete"
    if now - settlement.fetched_at > SETTLEMENT_MAX_AGE:
        return "venue_settlement_stale"
    return None


def render_venue_settlement(
    yes_resolved: Mapping[str, bool], *, fetched_at: datetime, complete: bool
) -> dict[str, Any]:
    """The file body. ``complete`` says the feed was read to its end (``eof``); the producer HOLDs
    on ``False``."""
    return {
        "schema": VENUE_SCHEMA,
        "source": SOURCE_ACTIVITIES,
        "fetched_at": fetched_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        "complete": complete,
        "yes_resolved": dict(sorted(yes_resolved.items())),
    }


def write_venue_settlement(
    path: Path, yes_resolved: Mapping[str, bool], *, fetched_at: datetime, complete: bool
) -> None:
    """Atomic, 0600, fsynced; the directory is created 0755."""
    body = render_venue_settlement(yes_resolved, fetched_at=fetched_at, complete=complete)
    write_json_atomic(path, body, when=fetched_at)
