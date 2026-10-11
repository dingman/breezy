"""The legacy CRH fill -> latch trial id -> frozen ``ScoredTrial`` join (TE-1 WP-A).

A durable fill of a retired CRH family has no C1 attribution and no FQ latch key. Its identity is
the trial the CRH latch recorded for it: the stored key ``<prefix><STATION>/<day>[/<instrument>]``
under a legacy composition kind's latch namespace. The join is made on the latch key, built from
the fill's own station, climate day and instrument, and NEVER on ``venueOrderId``: a latch row can
carry a null one (the 2026-09-11 SFO row does). A non-null ``venueOrderId`` is only compared, and a
disagreement refuses.

The family-manifest attribution is the manifest of a legacy kind whose venue, station and date
window name the fill and whose kind's latch namespace holds that key. The latch trial id and that
attribution must agree on exactly one trial and one family, or the join raises
:class:`LegacyAttributionDisagreement` (a CRITICAL, exit 1 through the planner's refusal path).
The join adds no attribution rule of its own: a fill with no legacy latch key returns ``None``.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from breezy.adapters.polymarket_us.exec.client import DurableFillRecord
from breezy.analysis.labeling.instrument_facts import bucket_facts_from_instrument_id
from breezy.analysis.labeling.legacy_crh_scorer import LegacyFillInput
from breezy.persistence.family_manifest import FamilyManifest
from breezy.settlement.trial_scorer import ScoredTrial
from breezy.strategy.current_rung_hold.trial_day_latch import (
    CONTINUOUS_TRIAL_KEY_PREFIX,
    DEFAULT_TRIAL_KEY_PREFIX,
    TAKEN_FROM_FILL_WALK_REASON,
    TrialDayRecord,
    trial_id_for,
)

__all__ = ["LegacyAttributionDisagreement", "LegacyJoin", "legacy_join"]

#: The latch key namespace of each retired composition kind. A manifest's own prefix field is never
#: read (G35): two families can share a prefix, and the stored latch key is not derived from it.
_PREFIX_OF_KIND: Final = {
    "current_rung_hold": DEFAULT_TRIAL_KEY_PREFIX,
    "continuous_rung_hold": CONTINUOUS_TRIAL_KEY_PREFIX,
}
_TAKEN_REASONS: Final = frozenset({"taken", TAKEN_FROM_FILL_WALK_REASON})


class LegacyAttributionDisagreement(Exception):
    """The latch trial id of a legacy fill disagrees with its family-manifest attribution."""


@dataclass(frozen=True)
class LegacyJoin:
    """A joined legacy fill: the composition kind it is planned under, and the scorer input."""

    kind: str
    fill_input: LegacyFillInput


def _read_latches(exec_db: Path, keys: Sequence[str]) -> dict[str, TrialDayRecord]:
    """The taken latch records among ``keys``, read through a ``mode=ro`` URI."""
    conn = sqlite3.connect(f"file:{exec_db.as_posix()}?mode=ro", uri=True)
    try:
        conn.execute("PRAGMA query_only=ON")
        found: dict[str, TrialDayRecord] = {}
        for key in keys:
            row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
            if row is None:
                continue
            record = TrialDayRecord.from_bytes(row[0])
            if record.reason in _TAKEN_REASONS:
                found[key] = record
        return found
    finally:
        conn.close()


def _window_covers(manifest: FamilyManifest, station: str, climate_day: str) -> bool:
    return (
        station in manifest.stations
        and manifest.d0_climate_day <= climate_day
        and (manifest.terminal_climate_day is None or climate_day <= manifest.terminal_climate_day)
    )


def legacy_join(
    fill: DurableFillRecord,
    manifests: Sequence[FamilyManifest],
    *,
    exec_db: Path,
    venue: str,
    scored_by_trial_id: Mapping[str, ScoredTrial],
) -> LegacyJoin | None:
    """Join one fill to its legacy latch trial, or ``None`` when it holds no legacy latch key."""
    facts = bucket_facts_from_instrument_id(fill.instrument_id)
    if facts is None:
        return None
    station, day = facts.settlement_station, facts.climate_day.isoformat()
    legacy = [m for m in manifests if m.composition_kind in _PREFIX_OF_KIND and m.venue == venue]
    prefixes = sorted({_PREFIX_OF_KIND[m.composition_kind] for m in legacy})
    instrument_key = {p: trial_id_for(p, station, day, fill.instrument_id) for p in prefixes}
    station_day_key = {p: f"{p}{station}/{day}" for p in prefixes}
    records = _read_latches(exec_db, [*instrument_key.values(), *station_day_key.values()])
    held: dict[str, str] = {}  # stored key -> its prefix
    for prefix in prefixes:
        if instrument_key[prefix] in records:
            held[instrument_key[prefix]] = prefix
        record = records.get(station_day_key[prefix])
        # a station-day row is this fill's only when its own instrument is this fill's (read-compat
        # shim of the latch: a stranger's row is never joined)
        if record is not None and (
            trial_id_for(prefix, station, day, record.instrument_id) == instrument_key[prefix]
        ):
            held[station_day_key[prefix]] = prefix
    if not held:
        return None
    if len(held) != 1:
        raise LegacyAttributionDisagreement("the fill holds more than one legacy latch key")
    ((trial_id, prefix),) = held.items()
    named = {
        m.family_id: m
        for m in legacy
        if _PREFIX_OF_KIND[m.composition_kind] == prefix and _window_covers(m, station, day)
    }
    if len(named) != 1:
        raise LegacyAttributionDisagreement(
            "the latch trial id is not named by exactly one family manifest"
        )
    ((_, manifest),) = named.items()
    latch_vo = records[trial_id].venue_order_id
    if latch_vo is not None and latch_vo != fill.venue_order_id:
        raise LegacyAttributionDisagreement("the latch venueOrderId differs from the fill's")
    return LegacyJoin(
        kind=manifest.composition_kind,
        fill_input=LegacyFillInput(
            fill=fill,
            label_family=manifest.family_id,
            trial_id=trial_id,
            scored=scored_by_trial_id.get(trial_id),
        ),
    )
