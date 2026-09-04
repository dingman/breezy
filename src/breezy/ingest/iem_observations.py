"""Parse IEM ASOS archive CSV rows into `StationObservation` records.

The METAR ``T``-group regex, magnitude decode, and archive-timestamp parse
below are a minimal PORT of
``scripts/analysis/settlement_alignment_study.py:99-101,234-239,256-263``
(``METAR_T_RE`` / ``parse_metar_t_group`` / the ``valid`` column parse inside
``metar_temperatures``) -- not an import from ``scripts/`` into ``src/``.
The port is pinned against the original by a differential test in
``tests/unit/test_iem_observations_parse.py`` so the two copies cannot
silently drift. Drop reasons are the same two names the study module already
uses (``missing_metar_t_group_row``, ``archive_parse_error``): a row that
cannot be parsed is COUNTED and dropped, never interpolated or defaulted to
zero (L-17).
"""

from __future__ import annotations

import datetime as dt
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from functools import lru_cache
from typing import Final

from nautilus_trader.model.data import DataType

from breezy.domain.station_observation import StationObservation

#: Ported verbatim from `settlement_alignment_study.py:99-101`.
_METAR_T_RE: Final[re.Pattern[str]] = re.compile(
    r"(?:^|\s)T(?P<air_sign>[01])(?P<air_tenths>\d{3})[01]\d{3}(?:\s|$)",
)


@lru_cache(maxsize=1)
def station_observation_data_type() -> DataType:
    """The ONE `DataType` for `StationObservation`. Never construct another.

    Carries NO metadata, matching `nws_actor.py:370-389`'s Phase-1
    convention -- see that module's shared-`DataType`-factory docstring for
    why an empty metadata mapping here and an omitted
    `BacktestDataConfig(metadata=...)` elsewhere must match by construction.
    """
    return DataType(StationObservation)


def parse_metar_t_group(raw_metar: str) -> int | None:
    """Ported from `settlement_alignment_study.py:234-239`. Differentially pinned."""
    match = _METAR_T_RE.search(raw_metar)
    if match is None:
        return None
    magnitude = int(match.group("air_tenths"))
    return -magnitude if match.group("air_sign") == "1" else magnitude


def iem_asos_rows_to_station_observations(
    *,
    station: str,
    rows: Iterable[Mapping[str, str]],
    source_channel: str,
    assumed_publication_lag_ns: int,
    received_at_ns: int,
) -> tuple[tuple[StationObservation, ...], Counter[str]]:
    """Convert IEM ASOS archive CSV rows to `StationObservation` records.

    Every dropped row is counted under `missing_metar_t_group_row` (no `T`
    group found) or `archive_parse_error` (the `valid` column does not parse
    as `"%Y-%m-%d %H:%M"`) -- never silently skipped, never interpolated,
    never turned into a zero (L-17).

    `received_at_ns` is a single caller-supplied instant applied to every
    row in this call -- appropriate for a bounded archive/backfill fetch
    (amendment A8), where the whole response arrives at once. A live poller
    passes its own per-poll receipt instant.
    """
    observations: list[StationObservation] = []
    drops: Counter[str] = Counter()
    for row in rows:
        raw_metar = row.get("metar", "")
        temp_c_tenths = parse_metar_t_group(raw_metar)
        if temp_c_tenths is None:
            drops["missing_metar_t_group_row"] += 1
            continue

        raw_valid = row.get("valid", "")
        try:
            valid_utc = dt.datetime.strptime(raw_valid, "%Y-%m-%d %H:%M").replace(
                tzinfo=dt.UTC,
            )
        except ValueError:
            drops["archive_parse_error"] += 1
            continue

        observed_at_ns = int(valid_utc.timestamp() * 1_000_000_000)
        observations.append(
            StationObservation(
                station=station,
                observed_at_ns=observed_at_ns,
                received_at_ns=received_at_ns,
                temp_c_tenths=temp_c_tenths,
                source_channel=source_channel,
                assumed_publication_lag_ns=assumed_publication_lag_ns,
            ),
        )
    return tuple(observations), drops
