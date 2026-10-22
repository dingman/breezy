"""ARM D1: the ``maker_venue_settlement/v1`` file -- the venue's own YES resolutions.

``scripts/venue/maker_settlement_collect.py`` WRITES it (the only writer, from the account activity
feed); ``scripts/analysis/maker_loss_stop_producer.py`` READS it (no network). A slug that is
absent from ``yes_resolved`` is simply unresolved: the harm stop treats it as PENDING and, past
the settlement deadline, as a LOSS. Unknown or ambiguous is therefore always omitted, never guessed.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from breezy.strategy.no_ladder_maker.harm_stop_artefact import write_json_atomic

__all__ = [
    "SOURCE_ACTIVITIES",
    "VENUE_SCHEMA",
    "VENUE_SETTLEMENTS_NAME",
    "read_venue_yes",
    "render_venue_settlement",
    "write_venue_settlement",
]

VENUE_SCHEMA: Final[str] = "maker_venue_settlement/v1"
#: the file's name beside ``latest.json``
VENUE_SETTLEMENTS_NAME: Final[str] = "venue_settlements.json"
SOURCE_ACTIVITIES: Final[str] = "activities"


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


def render_venue_settlement(
    yes_resolved: Mapping[str, bool], *, fetched_at: datetime, complete: bool
) -> dict[str, Any]:
    """The file body. ``complete`` says the feed was read to its end (informational)."""
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
