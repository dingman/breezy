"""Tape-instrument selection helpers for analysis scripts.

This module owns the Nautilus-typed tape seam used by paper replay, whole-tape
replay and the replay-sufficiency census. It imports none of the removed
weather strategy packages (BC-3; they resolve at git tag
``bc3-pre-removal-2026-10-02``), and it uses only the strategy-free selection
functions of ``weather_strategy_backtest_lib``.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from nautilus_trader.model.data import InstrumentClose, OrderBookDepth10, QuoteTick
from nautilus_trader.model.enums import InstrumentCloseType
from nautilus_trader.model.instruments import BinaryOption, Instrument
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from weather_strategy_backtest_lib import (  # type: ignore[import-not-found]
    select_book_backed_instrument_ids,
    select_tradable_instrument_ids,
)

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.weather_bucket_facts import WeatherBucketFacts, read_weather_bucket_facts
from breezy.persistence.catalog import open_station_catalog, read_climate_days
from breezy.runtime.quote_tape_ingest_cli import default_convert

DEFAULT_WEATHER_CATALOG_ROOT: Final[Path] = Path("/home/jon/.local/share/breezy/catalog")
WEATHER_VENUE: Final[str] = "polymarket_us"
CLIMATE_DAY: Final[dt.date] = dt.date(2026, 8, 30)
_ONE_SECOND_NS: Final[int] = 1_000_000_000


@dataclass(frozen=True, slots=True)
class TapeInstrument:
    """One tradable instrument plus the REAL data selected for it.

    ``closes`` is empty by default: ``_select_tape_instruments``'s source tape
    carries ZERO real ``InstrumentClose`` records, so that path leaves it empty
    and synthesizes a close separately via ``_synthesize_close``.
    ``_select_capture_instruments`` populates it from the capture's OWN
    recorded closes -- never synthesized -- so a paper-replay caller can feed
    them straight into ``market_data``.
    """

    instrument: BinaryOption
    facts: WeatherBucketFacts
    depths: list[OrderBookDepth10]
    quotes: list[QuoteTick]
    closes: list[InstrumentClose] = field(default_factory=list)

    @property
    def last_market_data_ts_init(self) -> int:
        return int(
            max(
                [d.ts_init for d in self.depths] + [q.ts_init for q in self.quotes],
            ),
        )


def _select_tape_instruments(
    catalog: ParquetDataCatalog,
    *,
    climate_day: dt.date = CLIMATE_DAY,
) -> list[TapeInstrument]:
    """Every ``climate_day`` instrument on the tape with depth and quote coverage."""
    by_id = _capture_instruments_by_id(catalog, climate_day=climate_day)
    depth_counts: dict[str, int] = {}
    quote_counts: dict[str, int] = {}
    depths_by_id: dict[str, list[OrderBookDepth10]] = {}
    quotes_by_id: dict[str, list[QuoteTick]] = {}
    for instrument_id in by_id:
        depths = catalog.order_book_depth10(instrument_ids=[instrument_id])
        quotes = catalog.quote_ticks(instrument_ids=[instrument_id])
        depth_counts[instrument_id] = len(depths)
        quote_counts[instrument_id] = len(quotes)
        depths_by_id[instrument_id] = depths
        quotes_by_id[instrument_id] = quotes

    tradable_ids = set(select_tradable_instrument_ids(depth_counts, quote_counts))

    result: list[TapeInstrument] = []
    for instrument_id in sorted(tradable_ids):
        instrument = by_id[instrument_id]
        if not isinstance(instrument, BinaryOption):
            raise TypeError(
                f"{instrument_id} is a {type(instrument).__name__}, not a "
                f"BinaryOption; every Breezy weather instrument on this venue "
                f"is a BinaryOption",
            )
        facts = read_weather_bucket_facts(instrument.info)
        result.append(
            TapeInstrument(
                instrument=instrument,
                facts=facts,
                depths=depths_by_id[instrument_id],
                quotes=quotes_by_id[instrument_id],
            ),
        )
    return result


def _synthesize_close(tape_instrument: TapeInstrument) -> InstrumentClose:
    """One CONSTRUCTED ``CONTRACT_EXPIRED`` close, strictly after the real tape."""
    ts = tape_instrument.last_market_data_ts_init + _ONE_SECOND_NS
    instrument = tape_instrument.instrument
    return InstrumentClose(
        instrument.id,
        instrument.make_price(0.5),
        InstrumentCloseType.CONTRACT_EXPIRED,
        ts,
        ts,
    )


def _convert_live_capture(
    *,
    quote_catalog: Path,
    instance_id: str,
    subdirectory: str,
    work_catalog: Path,
) -> ParquetDataCatalog:
    """Convert one live-recorder run into a SEPARATE work catalog, natively."""
    if work_catalog.resolve() == quote_catalog.resolve() or quote_catalog.resolve() in (
        work_catalog.resolve().parents
    ):
        raise ValueError(
            f"--work-catalog {work_catalog} is inside the capture root {quote_catalog}. "
            "The capture is read-only evidence; converted rows must go somewhere else.",
        )
    if work_catalog.exists() and any(work_catalog.iterdir()):
        raise ValueError(
            f"--work-catalog {work_catalog} is not empty. `convert_stream_to_data` "
            "silently SKIPS a write whose filename already exists (parquet.py:2680, a "
            "bare print), so converting into a populated root can produce a partial "
            "tape with no error. Point it at a fresh directory.",
        )
    work_catalog.mkdir(parents=True, exist_ok=True)
    source = ParquetDataCatalog(str(quote_catalog))
    work = ParquetDataCatalog(str(work_catalog))
    for data_cls in (BinaryOption, InstrumentClose, QuoteTick, OrderBookDepth10):
        default_convert(source, instance_id, data_cls, subdirectory, target=work)
    return work


def _capture_instruments_by_id(
    catalog: object,
    *,
    climate_day: dt.date,
    station: str | None = None,
) -> dict[str, Instrument]:
    """Every recorded instrument for ``climate_day``, de-duplicated on id."""
    by_id: dict[str, Instrument] = {}
    for instrument in catalog.instruments():  # type: ignore[attr-defined]
        by_id.setdefault(instrument.id.value, instrument)

    return {
        instrument_id: instrument
        for instrument_id, instrument in by_id.items()
        if (
            read_weather_bucket_facts(instrument.info).applies_to(station, climate_day)
            if station is not None
            else read_weather_bucket_facts(instrument.info).climate_day == climate_day
        )
    }


def _select_capture_instruments(
    catalog: ParquetDataCatalog,
    *,
    climate_day: dt.date,
    station: str | None = None,
    start: int | None = None,
    end: int | None = None,
) -> list[TapeInstrument]:
    """Every captured instrument for ``climate_day`` that carries book depth."""
    by_id = _capture_instruments_by_id(catalog, climate_day=climate_day, station=station)
    facts_by_id: dict[str, WeatherBucketFacts] = {
        instrument_id: read_weather_bucket_facts(instrument.info)
        for instrument_id, instrument in by_id.items()
    }

    depth_counts: dict[str, int] = {}
    depths_by_id: dict[str, list[OrderBookDepth10]] = {}
    quotes_by_id: dict[str, list[QuoteTick]] = {}
    closes_by_id: dict[str, list[InstrumentClose]] = {}
    for instrument_id in facts_by_id:
        depths = catalog.order_book_depth10(
            instrument_ids=[instrument_id],
            start=start,
            end=end,
        )
        depths_by_id[instrument_id] = depths
        depth_counts[instrument_id] = len(depths)
        quotes_by_id[instrument_id] = catalog.quote_ticks(
            instrument_ids=[instrument_id],
            start=start,
            end=end,
        )
        closes_by_id[instrument_id] = catalog.instrument_closes(
            instrument_ids=[instrument_id],
        )

    result: list[TapeInstrument] = []
    for instrument_id in select_book_backed_instrument_ids(depth_counts):
        instrument = by_id[instrument_id]
        if not isinstance(instrument, BinaryOption):
            raise TypeError(
                f"{instrument_id} is a {type(instrument).__name__}, not a BinaryOption",
            )
        result.append(
            TapeInstrument(
                instrument=instrument,
                facts=facts_by_id[instrument_id],
                depths=depths_by_id[instrument_id],
                quotes=quotes_by_id[instrument_id],
                closes=closes_by_id[instrument_id],
            ),
        )
    return result


def _load_climate_day_records(
    weather_catalog_root: Path,
    *,
    stations: Sequence[str],
    climate_day: dt.date,
) -> list[NwsClimateDay]:
    """Every non-superseded ``NwsClimateDay`` for ``climate_day`` at real ts_init."""
    records: list[NwsClimateDay] = []
    for station in stations:
        station_catalog = open_station_catalog(weather_catalog_root, WEATHER_VENUE, station)
        records.extend(
            record
            for record in read_climate_days(station_catalog)
            if record.climate_day == climate_day and not record.is_superseded
        )
    return sorted(records, key=lambda r: r.ts_init)
