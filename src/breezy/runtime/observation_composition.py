"""Composition root for the live NWS observation Actors (BL-24 Seam B, section 6).

Builds one :class:`~breezy.ingest.nws_observation_actor.NwsObservationActor`
per eligible registry site -- every site whose ICAO is not in
``EXCLUDED_ICAOS`` (KNYC: hourly-only, amendment A14, converged item 8) --
with a unique ``component_id`` (``Trader.add_actor`` rejects a collision),
the site's fixed standard-time offset from the registry, and the same
per-site stagger the ingest Actors use.

Registration is the caller's job and is NATIVE: ``node.trader.add_actor``
before ``node.build()``, exactly as ``composition.build_ingest_node`` does.
``build_trade_node_config`` keeps ``actors=[]``; nothing here touches it.

The numbers here are the measured / specified values, kept OUT of
``trade_cli.py`` (whose only numeric literals are its exit codes):

* ``NWS_API_ASSUMED_PUBLICATION_LAG_NS`` -- 21 min, the KMDW lag measured on
  2026-09-04 (``docs/evidence/observation_source_latency_2026-09-04.md``).
  Provenance only (amendment A6): stamped on every record, used nowhere.
"""

from __future__ import annotations

import datetime as dt
from functools import partial
from pathlib import Path
from typing import Final

from breezy.domain.climate_day import climate_day_for_instant
from breezy.ingest.nws_observation_actor import (
    DEFAULT_OBSERVATION_POLL_INTERVAL_SECONDS,
    DEFAULT_STALENESS_BOUND_SECONDS,
    EXCLUDED_ICAOS,
    NwsObservationActor,
    NwsObservationActorConfig,
    build_observation_transport,
)
from breezy.ingest.observation_sidecar import ObservationSidecar
from breezy.registry.sites import SettlementSite, SiteRegistry, default_registry
from breezy.runtime.composition import site_stagger_offset_seconds

__all__ = [
    "NWS_API_ASSUMED_PUBLICATION_LAG_NS",
    "build_live_observation_actors",
    "observation_actor_component_id",
]

#: 2026-09-16 GAP fix (raw-observation diagnosability): sibling of the
#: quote-tape catalog root, mirroring `current_rung_hold.composition.
#: _DECISIONS_DIRNAME` -- NEVER nested under the catalog. No env var: a
#: build-side default, never an operator control.
_OBSERVATIONS_DIRNAME: Final[str] = "observations"

_NS_PER_SECOND: Final[int] = 1_000_000_000

#: Measured 2026-09-04 ~01:36Z: KMDW newest 5-minute row 21 min behind.
NWS_API_ASSUMED_PUBLICATION_LAG_NS: Final[int] = 21 * 60 * _NS_PER_SECOND

_COMPONENT_ID_PREFIX: Final[str] = "NwsObservationActor"


def observation_actor_component_id(icao: str) -> str:
    """Unique `component_id` per station -- same reason as `actor_component_id`."""
    return f"{_COMPONENT_ID_PREFIX}-{icao}"


def _default_observation_sidecar_path(
    catalog_root: Path,
    eligible: list[tuple[str, str, SettlementSite]],
    registry: SiteRegistry,
) -> Path:
    """2026-09-16 GAP fix: the live default JSONL sidecar path.

    One file per (reference) climate day, a sibling of the quote-tape
    catalog root (never nested under it), mirroring `current_rung_hold.
    composition._default_offer_tape_path`. `min(...)` over every eligible
    site's OWN current climate day is deterministic in every real
    deployment (every registered site observes the same UTC calendar day at
    process-boot instants); a process restart at the next daily boot always
    gets a fresh file, exactly like the offer tape's own rotation.
    """
    now = dt.datetime.now(tz=dt.UTC)
    days = [
        climate_day_for_instant(now, registry.climate_day_window(venue, city).std_utc_offset_hours)
        for venue, city, _site in eligible
    ]
    day = min(days) if days else now.date()
    return catalog_root.parent / _OBSERVATIONS_DIRNAME / f"observations_{day.isoformat()}.jsonl"


def build_live_observation_actors(
    registry: SiteRegistry | None = None,
    *,
    check_proxy_env: bool = True,
    poll_interval_seconds: int = DEFAULT_OBSERVATION_POLL_INTERVAL_SECONDS,
    staleness_bound_seconds: int = DEFAULT_STALENESS_BOUND_SECONDS,
    catalog_root: Path | None = None,
    observation_sidecar_path: Path | None = None,
) -> tuple[NwsObservationActor, ...]:
    """One Actor per eligible registry site, in registry order, staggered.

    2026-09-16 GAP fix: every actor shares ONE `ObservationSidecar` (not one
    per station), mirroring `OfferTape`'s own sharing. `catalog_root` --
    `trade_cli.run`'s own `settings.catalog_root`, `Path | None` (config
    seam: it is `None` whenever no rung-hold family is on, since that is
    its only other reader today) -- resolves the live default path exactly
    like `current_rung_hold.composition._default_offer_tape_path` does. An
    explicit `observation_sidecar_path` always wins (tests keep working
    unedited). Both `None` (the pre-fix default, and the live shape when
    observations run with no rung-hold family) disables the sidecar
    entirely -- `ObservationSidecar(None)` is a no-op, never a raise, so a
    standalone-observations deployment is unaffected, not broken.
    """
    active_registry = default_registry() if registry is None else registry
    eligible = [
        (venue, city, active_registry.settlement_site(venue, city))
        for venue, city in active_registry.pairs()
    ]
    eligible = [entry for entry in eligible if entry[2].icao not in EXCLUDED_ICAOS]
    site_count = len(eligible)
    transport_factory = partial(build_observation_transport, check_proxy_env=check_proxy_env)

    resolved_sidecar_path = (
        observation_sidecar_path
        if observation_sidecar_path is not None
        else (
            _default_observation_sidecar_path(catalog_root, eligible, active_registry)
            if catalog_root is not None
            else None
        )
    )
    sidecar = ObservationSidecar(resolved_sidecar_path)

    actors: list[NwsObservationActor] = []
    for index, (venue, city, site) in enumerate(eligible):
        window = active_registry.climate_day_window(venue, city)
        config = NwsObservationActorConfig(
            component_id=observation_actor_component_id(site.icao),
            station_icao=site.icao,
            assumed_publication_lag_ns=NWS_API_ASSUMED_PUBLICATION_LAG_NS,
            poll_interval_seconds=poll_interval_seconds,
            stagger_offset_seconds=site_stagger_offset_seconds(
                index, site_count, poll_interval_seconds
            ),
            staleness_bound_seconds=staleness_bound_seconds,
        )
        actors.append(
            NwsObservationActor(
                config,
                std_utc_offset_hours=window.std_utc_offset_hours,
                transport_factory=transport_factory,
                sidecar=sidecar,
            )
        )
    return tuple(actors)
