"""Derive Polymarket.us's tradeable weather-city universe from venue payloads.

G-19 item B3/B4. The bot must learn which cities the venue trades from the
venue's own responses, never from a human reciting a list into an environment
variable. This module is the derivation; it holds **no** city table.

The two payload shapes it reads, both already captured under
``docs/evidence/venue/polymarket_us/raw/``:

* the **series list** (``{"series": [{"id", "slug", "title"}, ...]}``) --
  establishes which weather series exist. The weather family is
  ``weather-daily-<measure>-<city_token>``; the umbrella series ``weather``
  carries no city and is structurally excluded.
* an **events list** (``{"events": [{"seriesSlug", "markets": [...]}, ...]}``)
  -- establishes the join. Each event names its ``seriesSlug`` and nests the
  markets, whose ``description`` names the settlement station in parentheses:
  *"the highest temperature recorded at Chicago Midway Airport (KMDW) in
  Chicago ..."*.

That parenthesised ICAO is the ONLY thing this module treats as a station
identity. It is then bound to `breezy.registry.sites` by matching the stored
``icao`` field -- a lookup against settlement truth, never a derivation of it.

THE CITY-TOKEN GAP (read before extending this module)
------------------------------------------------------
The city token in a series slug (``chicago``, ``los-angeles``) is NOT the code
used elsewhere in Breezy (``MDW``, ``LAX``). Recovering that correspondence
needs the series->event->market join above.

As of the 2026-08 captures the join is established for the five
``weather-daily-high-*`` series ONLY. The five ``weather-daily-low-*`` series
(ids 36, 38, 40, 42, 44) are **UNRESOLVED**: no captured payload carries an
event whose ``seriesSlug`` is a low series -- ``events_seriesId_36_active.json``
came back ``{"events": []}`` -- so nothing observed binds
``weather-daily-low-nyc`` to a station.

Their city tokens are textually identical to the resolved high series' tokens,
and it is very likely they settle on the same stations. This module does NOT
act on that likelihood. Extending an observed token->station binding across the
measure axis is a grammar inference, not an observation, and the point of this
module is that the bot only believes what the venue actually told it. The low
series are reported in :attr:`SeriesUniverse.unresolved`, and
:func:`derive_site_pairs` refuses -- loudly -- if any unresolved series names a
city no resolved series independently established, so a city can never vanish
quietly. Closing the gap needs one capture: the events list for any low series.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from breezy.adapters.polymarket_us.errors import PolymarketUSError
from breezy.registry.sites import SiteRegistry

__all__ = [
    "DEFAULT_VENUE",
    "ResolvedSeries",
    "SeriesDerivationError",
    "SeriesUniverse",
    "WeatherSeries",
    "derive_series_universe",
    "derive_site_pairs",
    "index_series_stations",
    "parse_weather_series",
]

#: The venue key these payloads belong to, matching `sites.toml`'s
#: `[sites.polymarket_us.*]` tables. A parameter everywhere below rather than a
#: constant reached for directly, so Kalshi needs no restructuring.
DEFAULT_VENUE: Final[str] = "polymarket_us"

#: Membership test for the daily weather family. Deliberately a PREFIX and not
#: the full grammar: anything inside the family that fails the full pattern is
#: drift and must raise, while the umbrella `weather` series and every sports
#: series simply are not members.
_WEATHER_DAILY_PREFIX: Final[str] = "weather-daily-"

#: `weather-daily-high-san-francisco` -> measure `high`, token `san-francisco`.
_SERIES_SLUG_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"^weather-daily-(?P<measure>high|low)-(?P<city_token>[a-z0-9]+(?:-[a-z0-9]+)*)$"
)

#: The station as the venue writes it in a market description: a parenthesised
#: four-letter uppercase ICAO, e.g. `(KMDW)`. Prose parentheses in these
#: descriptions ("(Daily)") are mixed case and do not match.
_STATION_PATTERN: Final[re.Pattern[str]] = re.compile(r"\(([A-Z]{4})\)")


class SeriesDerivationError(PolymarketUSError, ValueError):
    """Raised when venue series/event payloads cannot be interpreted.

    Every message names the offending slug, station or key. There is no
    fallback branch anywhere in this module: an uninterpretable payload stops
    the derivation rather than yielding a smaller, plausible-looking universe.
    """


@dataclass(frozen=True, slots=True)
class WeatherSeries:
    """One `weather-daily-<measure>-<city_token>` series, as the venue lists it."""

    series_id: str
    slug: str
    title: str
    #: `high` or `low`, from the slug.
    measure: str
    #: The venue's own city token (`nyc`, `los-angeles`). NOT a Breezy city
    #: code; see the module docstring.
    city_token: str


@dataclass(frozen=True, slots=True)
class ResolvedSeries:
    """A series whose settlement station was OBSERVED in a market description."""

    series: WeatherSeries
    #: ICAO exactly as the venue printed it, e.g. `KMDW`.
    icao: str
    #: The market slug whose description established the binding, kept so a
    #: reviewer can re-read the evidence rather than trust this object.
    evidence_market_slug: str


@dataclass(frozen=True, slots=True)
class SeriesUniverse:
    """The weather series the venue publishes, split by what was observed."""

    resolved: tuple[ResolvedSeries, ...]
    #: Series with no captured event to join against. Never silently dropped;
    #: see :func:`derive_site_pairs`.
    unresolved: tuple[WeatherSeries, ...]

    @property
    def icaos(self) -> tuple[str, ...]:
        """Distinct observed stations, sorted."""
        return tuple(sorted({entry.icao for entry in self.resolved}))


def _series_entries(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = payload.get("series")
    if not isinstance(raw, list):
        raise SeriesDerivationError(
            "series payload has no list under the 'series' key; "
            f"got keys {sorted(payload)}"
        )
    return [entry for entry in raw if isinstance(entry, Mapping)]


def parse_weather_series(payload: Mapping[str, Any]) -> tuple[WeatherSeries, ...]:
    """Return every `weather-daily-*` series in a venue series-list payload.

    Non-weather series and the umbrella `weather` series are not members of
    the family and are skipped. A slug that IS in the family but does not match
    the grammar raises: a new measure or a renamed token must fail loudly here
    rather than shrink the universe by one city without anybody noticing.
    """
    parsed: list[WeatherSeries] = []
    seen: set[str] = set()

    for entry in _series_entries(payload):
        slug = entry.get("slug")
        if slug is None:
            raise SeriesDerivationError(
                f"series entry has no 'slug': id={entry.get('id')!r}"
            )
        if not isinstance(slug, str):
            raise SeriesDerivationError(f"series 'slug' is not a string: {slug!r}")
        if not slug.startswith(_WEATHER_DAILY_PREFIX):
            continue

        match = _SERIES_SLUG_PATTERN.match(slug)
        if match is None:
            raise SeriesDerivationError(
                f"weather series slug {slug!r} does not match the known grammar "
                "'weather-daily-<high|low>-<city-token>'; refusing to guess which "
                "city or measure it denotes"
            )
        if slug in seen:
            raise SeriesDerivationError(f"duplicate weather series slug {slug!r}")
        seen.add(slug)

        parsed.append(
            WeatherSeries(
                series_id=str(entry.get("id", "")),
                slug=slug,
                title=str(entry.get("title", "")),
                measure=match.group("measure"),
                city_token=match.group("city_token"),
            )
        )

    return tuple(parsed)


def _event_entries(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    raw = payload.get("events")
    if not isinstance(raw, list):
        raise SeriesDerivationError(
            "events payload has no list under the 'events' key; "
            f"got keys {sorted(payload)}"
        )
    return [entry for entry in raw if isinstance(entry, Mapping)]


def index_series_stations(
    *payloads: Mapping[str, Any],
) -> dict[str, tuple[str, str]]:
    """Join `seriesSlug` to an observed station across events payloads.

    Returns ``{series_slug: (icao, evidence_market_slug)}``. A series whose
    markets name no station simply does not appear -- the April-2026 market
    descriptions carry no parenthesised ICAO, and absence of evidence is
    reported as absence, not as an error.

    Two DIFFERENT stations under one series raises: an ambiguous join must
    never be settled by taking the first.
    """
    index: dict[str, tuple[str, str]] = {}

    for payload in payloads:
        for event in _event_entries(payload):
            series_slug = event.get("seriesSlug")
            if not isinstance(series_slug, str) or not series_slug:
                raise SeriesDerivationError(
                    "event carries no 'seriesSlug', so it cannot be joined to a "
                    f"series: slug={event.get('slug')!r}"
                )
            if not series_slug.startswith(_WEATHER_DAILY_PREFIX):
                continue

            for market in _markets(event):
                icao, market_slug = _station_from_market(market)
                if icao is None:
                    continue
                existing = index.get(series_slug)
                if existing is None:
                    index[series_slug] = (icao, market_slug)
                elif existing[0] != icao:
                    raise SeriesDerivationError(
                        f"series {series_slug!r} names two different stations: "
                        f"{existing[0]} (market {existing[1]!r}) and {icao} "
                        f"(market {market_slug!r}); refusing to pick one"
                    )

    return index


def _markets(event: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    raw = event.get("markets")
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise SeriesDerivationError(
            f"event {event.get('slug')!r} has a non-list 'markets' value"
        )
    return [entry for entry in raw if isinstance(entry, Mapping)]


def _station_from_market(market: Mapping[str, Any]) -> tuple[str | None, str]:
    market_slug = str(market.get("slug", ""))
    description = market.get("description")
    if not isinstance(description, str):
        return None, market_slug

    found = set(_STATION_PATTERN.findall(description))
    if not found:
        return None, market_slug
    if len(found) > 1:
        raise SeriesDerivationError(
            f"market {market_slug!r} names more than one station {sorted(found)}; "
            "refusing to pick one"
        )
    return found.pop(), market_slug


def derive_series_universe(
    series_payload: Mapping[str, Any],
    *event_payloads: Mapping[str, Any],
) -> SeriesUniverse:
    """Split the venue's weather series into observed-station and unresolved."""
    series = parse_weather_series(series_payload)
    index = index_series_stations(*event_payloads)

    resolved: list[ResolvedSeries] = []
    unresolved: list[WeatherSeries] = []
    for entry in series:
        joined = index.get(entry.slug)
        if joined is None:
            unresolved.append(entry)
            continue
        icao, market_slug = joined
        resolved.append(
            ResolvedSeries(series=entry, icao=icao, evidence_market_slug=market_slug)
        )

    return SeriesUniverse(resolved=tuple(resolved), unresolved=tuple(unresolved))


def derive_site_pairs(
    universe: SeriesUniverse,
    registry: SiteRegistry,
    venue: str = DEFAULT_VENUE,
) -> tuple[tuple[str, str], ...]:
    """Bind observed stations to `(venue, city)` registry keys.

    Three loud refusals, each guarding a way a city could be traded blind or
    dropped silently:

    1. an observed station with **no registry entry** -- the venue trades a
       city we hold no settlement truth for, so we must not trade it and must
       not pretend it does not exist;
    2. an **unresolved series naming a city no resolved series established** --
       the city would otherwise vanish from the universe unremarked;
    3. **no resolved series at all** -- the captures established nothing, and
       an empty universe must never read as "the venue trades nothing".
    """
    if not universe.resolved:
        raise SeriesDerivationError(
            "no station was observed for any weather series; the supplied event "
            "payloads establish no series-to-station join at all"
        )

    by_icao = _registry_icao_index(registry, venue)

    pairs: set[tuple[str, str]] = set()
    for entry in universe.resolved:
        city = by_icao.get(entry.icao)
        if city is None:
            raise SeriesDerivationError(
                f"venue series {entry.series.slug!r} settles on station "
                f"{entry.icao} (market {entry.evidence_market_slug!r}), which has "
                f"no {venue} entry in the settlement registry; refusing to trade "
                "or to skip a city Breezy holds no settlement truth for"
            )
        pairs.add((venue, city))

    resolved_tokens = {entry.series.city_token for entry in universe.resolved}
    orphaned = sorted(
        entry.slug for entry in universe.unresolved if entry.city_token not in resolved_tokens
    )
    if orphaned:
        raise SeriesDerivationError(
            "these venue series name a city that no observed market binds to a "
            f"station, so the city would be dropped silently: {orphaned}"
        )

    return tuple(sorted(pairs))


def _registry_icao_index(registry: SiteRegistry, venue: str) -> dict[str, str]:
    index: dict[str, str] = {}
    for registered_venue, city in registry.pairs():
        if registered_venue != venue:
            continue
        icao = registry.settlement_site(registered_venue, city).icao
        index[icao] = city
    return index
