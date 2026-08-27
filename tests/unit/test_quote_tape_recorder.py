"""The venue quote-tape recorder: does a quote survive to disk and read back?

Plan item 1.1 (``docs/plans/TRADING_ENABLEMENT_PLAN.md``). Polymarket.us
weather markets did not exist before 2026 and no historical price data can
ever be backfilled, so an uncaptured day is permanently lost. The defect this
suite closes is that ``PolymarketUSDataClient`` published ``QuoteTick`` to the
message bus and NOTHING stored them.

What these tests assert, and why they are shaped this way
--------------------------------------------------------
The repo's standing lesson (``docs/core/PROGRESS.md``) is that the suite was
fully green twice while the deployment was dead. So the load-bearing test here
is not "the config has a ``streaming`` attribute" -- it is:

    quotes go in through the writer the KERNEL constructs, from the config
    :func:`build_quote_tape_node_config` returns, and come back out of a
    SEPARATE reader that was told nothing but the catalog root.

Nothing is stubbed on the persistence path. The one thing that cannot be
exercised here is a real socket: ``tests/conftest.py`` replaces the
``nautilus_pyo3`` ``WebSocketClient`` constructor with a raising sentinel for
the whole suite, and this file never tries to defeat that.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.cache.cache import Cache
from nautilus_trader.common import Environment
from nautilus_trader.common.component import TestClock
from nautilus_trader.config import CacheConfig
from nautilus_trader.model.currencies import USD
from nautilus_trader.model.data import (
    InstrumentClose,
    InstrumentStatus,
    MarkPriceUpdate,
    OrderBookDepth10,
    QuoteTick,
    TradeTick,
)
from nautilus_trader.model.enums import AssetClass
from nautilus_trader.model.identifiers import InstrumentId, Symbol
from nautilus_trader.model.instruments import BinaryOption
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog
from nautilus_trader.persistence.writer import StreamingFeatherWriter

from breezy.adapters.polymarket_us.config import PolymarketUSDataClientConfig
from breezy.adapters.polymarket_us.factories import POLYMARKET_US_CLIENT_NAME
from breezy.adapters.polymarket_us.symbology import POLYMARKET_US_VENUE
from breezy.adapters.polymarket_us.tape_records import (
    DepthTruncation,
    QuoteTapeGap,
    VenueClockOffset,
    VenueSettlementSnapshot,
)
from breezy.runtime.node_config import (
    NodeConfigError,
    build_quote_tape_node_config,
)
from breezy.runtime.settings import (
    PolymarketUSQuoteTapeSettings,
    SettingsError,
    load_quote_tape_settings,
)

SLUG = "tc-temp-nychigh-2026-08-25-lt79f"
OTHER_SLUG = "tc-temp-mdwhigh-2026-08-25-lt91f"

#: The environment a provisioned quote-tape host carries. Venue values are
#: ``.invalid`` hosts: nothing in this file performs network I/O.
TAPE_ENV: dict[str, str] = {
    "BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG": "/srv/breezy/venue/polymarket_us",
    "BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_WARNING": str(20 * 1024**3),
    "BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_ERROR": str(10 * 1024**3),
    "BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_WARNING": str(400 * 1024**3),
    "BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_ERROR": str(500 * 1024**3),
    "POLYMARKET_US_API_BASE": "https://api.example.invalid",
    "POLYMARKET_US_GATEWAY_BASE": "https://gateway.example.invalid",
    "POLYMARKET_US_WS_URL": "wss://ws.example.invalid",
    "POLYMARKET_US_DISCOVERY_RELOAD_INTERVAL_MINS": "5",
    "POLYMARKET_US_USER_AGENT": "breezy-test/1.0 (+mailto:ops@example.invalid)",
}


def make_instrument(slug: str) -> BinaryOption:
    symbol = Symbol(slug)
    price_increment = Price.from_str("0.001")
    size_increment = Quantity.from_str("1")
    return BinaryOption(
        instrument_id=InstrumentId(symbol=symbol, venue=POLYMARKET_US_VENUE),
        raw_symbol=symbol,
        outcome="Yes",
        description="Test weather market",
        asset_class=AssetClass.ALTERNATIVE,
        currency=USD,
        price_precision=price_increment.precision,
        price_increment=price_increment,
        size_precision=size_increment.precision,
        size_increment=size_increment,
        activation_ns=0,
        expiration_ns=1_800_000_000_000_000_000,
        max_quantity=None,
        min_quantity=Quantity.from_int(1),
        maker_fee=Decimal(0),
        taker_fee=Decimal(0),
        ts_event=0,
        ts_init=0,
    )


def make_quote(instrument: BinaryOption, *, bid: str, ask: str, ts: int) -> QuoteTick:
    return QuoteTick(
        instrument_id=instrument.id,
        bid_price=Price.from_str(bid),
        ask_price=Price.from_str(ask),
        bid_size=Quantity.from_str("10"),
        ask_size=Quantity.from_str("11"),
        ts_event=ts,
        ts_init=ts,
    )


def make_tape_settings(root: Path, **overrides: object) -> PolymarketUSQuoteTapeSettings:
    base: dict[str, object] = {
        "trader_id": "BREEZY-TAPE",
        "log_level": "INFO",
        "catalog_root": root,
        "min_free_bytes_warning": 20 * 1024**3,
        "min_free_bytes_error": 10 * 1024**3,
        "max_file_bytes_warning": 400 * 1024**3,
        "max_file_bytes_error": 500 * 1024**3,
        "disk_check_interval_seconds": 30,
    }
    base.update(overrides)
    return PolymarketUSQuoteTapeSettings(**base)  # type: ignore[arg-type]


def make_data_client_config() -> PolymarketUSDataClientConfig:
    return PolymarketUSDataClientConfig(
        # Deliberate test-double origin off the venue domain.
        allow_foreign_origin=True,
        api_base_url="https://api.example.invalid",
        gateway_base_url="https://gateway.example.invalid",
        ws_url="wss://ws.example.invalid",
        instrument_reload_interval_mins=5,
        user_agent="breezy-test/1.0 (+mailto:ops@example.invalid)",
    )


def writer_from_node_config(
    config: Any, root: Path, instance_id: str, cache: Cache
) -> StreamingFeatherWriter:
    """Build the writer EXACTLY as ``NautilusKernel._setup_streaming`` does.

    ``system/kernel.py:586-602``: the path is
    ``<catalog_path>/<environment.value>/<instance_id>`` and every writer
    argument comes off the ``StreamingConfig``. Reproducing that construction
    from the config under test -- rather than hand-picking arguments -- is what
    makes these tests evidence about the shipped configuration instead of
    evidence about the test's own choices.
    """
    streaming = config.streaming
    environment = config.environment
    path = f"{streaming.catalog_path}/{environment.value}/{instance_id}"
    assert path.startswith(str(root)), "the writer must land under the configured root"
    return StreamingFeatherWriter(
        path=path,
        cache=cache,
        clock=TestClock(),
        fs_protocol=streaming.fs_protocol,
        flush_interval_ms=streaming.flush_interval_ms,
        include_types=streaming.include_types,
        replace=streaming.replace_existing,
    )


# ---------------------------------------------------------------------------
# The recorder's own settings role
# ---------------------------------------------------------------------------


class TestQuoteTapeSettings:
    def test_catalog_root_is_required_with_no_default(self) -> None:
        env = dict(TAPE_ENV)
        del env["BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG"]

        with pytest.raises(SettingsError, match="BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG"):
            load_quote_tape_settings(env)

    def test_a_blank_catalog_root_is_refused_rather_than_becoming_the_cwd(self) -> None:
        # `Path("")` is `Path(".")`, which would silently write the tape into
        # whatever directory systemd happened to start the unit in.
        with pytest.raises(SettingsError, match="BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG"):
            load_quote_tape_settings({**TAPE_ENV, "BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG": "  "})

    def test_a_relative_catalog_root_is_refused(self) -> None:
        with pytest.raises(SettingsError, match="absolute"):
            load_quote_tape_settings(
                {**TAPE_ENV, "BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG": "venue/tape"}
            )

    def test_catalog_root_is_parsed_and_trimmed(self) -> None:
        settings = load_quote_tape_settings(TAPE_ENV)

        assert settings.catalog_root == Path("/srv/breezy/venue/polymarket_us")
        assert settings.min_free_bytes_warning == 20 * 1024**3
        assert settings.min_free_bytes_error == 10 * 1024**3
        assert settings.max_file_bytes_warning == 400 * 1024**3
        assert settings.max_file_bytes_error == 500 * 1024**3
        assert settings.disk_check_interval_seconds == 30

    def test_disk_thresholds_are_derived_when_none_are_configured(self) -> None:
        """G-19 B10: only the disk SPEND is an operator ceiling.

        How much headroom a volume needs is a property of the volume, and
        `shutil.disk_usage` can see it. The recorder must start with none of
        the four set, and the derived monitor must still be able to fire.
        """
        env = {
            key: value
            for key, value in TAPE_ENV.items()
            if "BYTES" not in key
        }

        settings = load_quote_tape_settings(env)

        assert 0 < settings.min_free_bytes_error < settings.min_free_bytes_warning
        assert 0 < settings.max_file_bytes_warning < settings.max_file_bytes_error

    @pytest.mark.parametrize(
        ("name", "value"),
        [
            ("BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_WARNING", "0"),
            ("BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_ERROR", "-1"),
            ("BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_WARNING", "ten"),
            ("BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_ERROR", "1.5"),
        ],
    )
    def test_disk_thresholds_must_be_positive_integers(self, name: str, value: str) -> None:
        with pytest.raises(SettingsError, match=name):
            load_quote_tape_settings({**TAPE_ENV, name: value})

    def test_free_space_error_floor_must_be_below_warning_floor(self) -> None:
        with pytest.raises(SettingsError, match="MIN_FREE_BYTES_ERROR"):
            load_quote_tape_settings(
                {
                    **TAPE_ENV,
                    "BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_WARNING": "100",
                    "BREEZY_POLYMARKET_US_QUOTE_TAPE_MIN_FREE_BYTES_ERROR": "100",
                }
            )

    def test_file_size_error_ceiling_must_be_above_warning_ceiling(self) -> None:
        with pytest.raises(SettingsError, match="MAX_FILE_BYTES_ERROR"):
            load_quote_tape_settings(
                {
                    **TAPE_ENV,
                    "BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_WARNING": "200",
                    "BREEZY_POLYMARKET_US_QUOTE_TAPE_MAX_FILE_BYTES_ERROR": "100",
                }
            )

    def test_the_recorder_role_needs_no_nws_ingestion_configuration(self) -> None:
        """Symmetry with the ingest role: neither may require the other's env.

        ``BREEZY_SITES`` and ``BREEZY_CATALOG_BASE`` are weather-collector
        settings. A tape host that carries none of them must still start.
        """
        assert "BREEZY_SITES" not in TAPE_ENV
        assert "BREEZY_CATALOG_BASE" not in TAPE_ENV

        assert load_quote_tape_settings(TAPE_ENV).trader_id == "BREEZY-001"


# ---------------------------------------------------------------------------
# The recorder's node config
# ---------------------------------------------------------------------------


class TestQuoteTapeNodeConfig:
    def test_registers_the_read_only_data_client_and_zero_exec_clients(
        self, tmp_path: Path
    ) -> None:
        config = build_quote_tape_node_config(
            make_tape_settings(tmp_path), make_data_client_config()
        )

        assert set(config.data_clients) == {POLYMARKET_US_CLIENT_NAME}
        assert (
            config.data_clients[
                POLYMARKET_US_CLIENT_NAME
            ].instrument_reload_interval_mins
            == 5
        )
        assert config.exec_clients == {}

    def test_declares_no_actors_and_registers_no_data_engine_catalogs(
        self, tmp_path: Path
    ) -> None:
        config = build_quote_tape_node_config(
            make_tape_settings(tmp_path), make_data_client_config()
        )

        assert config.actors == []
        assert config.catalogs == []

    def test_runs_as_a_live_node_with_no_redis_backed_stores(self, tmp_path: Path) -> None:
        config = build_quote_tape_node_config(
            make_tape_settings(tmp_path), make_data_client_config()
        )

        assert config.environment == Environment.LIVE
        assert config.cache is not None
        assert config.cache.database is None
        assert config.message_bus is None

    def test_streaming_targets_the_configured_root_and_only_the_tape_types(
        self, tmp_path: Path
    ) -> None:
        config = build_quote_tape_node_config(
            make_tape_settings(tmp_path), make_data_client_config()
        )

        assert config.streaming is not None
        assert config.streaming.catalog_path == str(tmp_path)
        # Exclusive filter: without it the kernel's `"*"` bus subscription
        # writes every unrelated message into the tape directory. Every entry
        # is a record that cannot be reconstructed after the fact -- see
        # `QUOTE_TAPE_INCLUDE_TYPES` for why each one is on the list.
        assert config.streaming.include_types is not None
        assert set(config.streaming.include_types) == {
            QuoteTick,
            OrderBookDepth10,
            TradeTick,
            MarkPriceUpdate,
            InstrumentClose,
            InstrumentStatus,
            QuoteTapeGap,
            VenueClockOffset,
            VenueSettlementSnapshot,
            DepthTruncation,
            BinaryOption,
        }

    def test_no_deployment_value_is_hardcoded(self, tmp_path: Path) -> None:
        config = build_quote_tape_node_config(
            make_tape_settings(tmp_path, trader_id="BREEZY-042", log_level="DEBUG"),
            make_data_client_config(),
        )

        assert str(config.trader_id) == "BREEZY-042"
        assert config.logging is not None
        assert config.logging.log_level == "DEBUG"

    def test_a_malformed_trader_id_is_refused_before_nautilus_aborts_the_process(
        self, tmp_path: Path
    ) -> None:
        with pytest.raises(NodeConfigError, match="malformed"):
            build_quote_tape_node_config(
                make_tape_settings(tmp_path, trader_id="not a trader id"),
                make_data_client_config(),
            )


# ---------------------------------------------------------------------------
# The load-bearing test: quotes reach disk and read back
# ---------------------------------------------------------------------------


class TestQuotesReachDiskAndReadBack:
    def test_recorded_quotes_are_read_back_from_disk_by_a_separate_reader(
        self, tmp_path: Path
    ) -> None:
        """Write through the kernel's writer; read with a fresh catalog object.

        The reader is constructed from the catalog ROOT alone -- it is given no
        writer, no schema and no in-memory handle -- which is the property that
        makes the tape an archive rather than a process-lifetime buffer.
        """
        instrument = make_instrument(SLUG)
        config = build_quote_tape_node_config(
            make_tape_settings(tmp_path), make_data_client_config()
        )

        cache = Cache(database=None, config=CacheConfig())
        cache.add_instrument(instrument)
        writer = writer_from_node_config(config, tmp_path, "instance-1", cache)
        writer.write(instrument)
        writer.write(make_quote(instrument, bid="0.400", ask="0.410", ts=1_000_000_000))
        writer.write(make_quote(instrument, bid="0.415", ask="0.425", ts=2_000_000_000))
        writer.close()

        reader = ParquetDataCatalog(tmp_path)
        reader.convert_stream_to_data("instance-1", QuoteTick, subdirectory="live")
        reader.convert_stream_to_data("instance-1", BinaryOption, subdirectory="live")

        quotes = reader.query(data_cls=QuoteTick)
        assert [str(q.bid_price) for q in quotes] == ["0.400", "0.415"]
        assert [str(q.ask_price) for q in quotes] == ["0.410", "0.425"]
        assert {q.instrument_id for q in quotes} == {instrument.id}
        assert [q.ts_event for q in quotes] == [1_000_000_000, 2_000_000_000]

    def test_the_instrument_definition_is_persisted_alongside_the_quotes(
        self, tmp_path: Path
    ) -> None:
        """Without it the tape is unreadable: price precision lives on the instrument."""
        instrument = make_instrument(SLUG)
        config = build_quote_tape_node_config(
            make_tape_settings(tmp_path), make_data_client_config()
        )
        cache = Cache(database=None, config=CacheConfig())
        cache.add_instrument(instrument)
        writer = writer_from_node_config(config, tmp_path, "instance-1", cache)
        writer.write(instrument)
        writer.write(make_quote(instrument, bid="0.400", ask="0.410", ts=1_000_000_000))
        writer.close()

        reader = ParquetDataCatalog(tmp_path)
        reader.convert_stream_to_data("instance-1", BinaryOption, subdirectory="live")

        definitions = reader.query(data_cls=BinaryOption)
        assert [d.id for d in definitions] == [instrument.id]
        assert definitions[0].price_increment == Price.from_str("0.001")

    def test_two_markets_are_kept_apart_in_one_catalog_root(self, tmp_path: Path) -> None:
        """One root for the venue is correct because ``QuoteTick`` carries an id.

        The "one catalog root per station" rule applies to custom data types
        with no ``instrument_id``, which write flat and become indistinguishable
        on read. ``QuoteTick`` partitions natively, so a root per market would
        fragment the dataset for nothing. Asserted by reading both back and
        checking they did not merge.
        """
        first, second = make_instrument(SLUG), make_instrument(OTHER_SLUG)
        config = build_quote_tape_node_config(
            make_tape_settings(tmp_path), make_data_client_config()
        )
        cache = Cache(database=None, config=CacheConfig())
        cache.add_instrument(first)
        cache.add_instrument(second)
        writer = writer_from_node_config(config, tmp_path, "instance-1", cache)
        writer.write(first)
        writer.write(second)
        writer.write(make_quote(first, bid="0.400", ask="0.410", ts=1_000_000_000))
        writer.write(make_quote(second, bid="0.700", ask="0.710", ts=1_500_000_000))
        writer.close()

        reader = ParquetDataCatalog(tmp_path)
        reader.convert_stream_to_data("instance-1", QuoteTick, subdirectory="live")

        recorded = reader.query(data_cls=QuoteTick)
        by_instrument = {q.instrument_id: str(q.bid_price) for q in recorded}
        assert by_instrument == {first.id: "0.400", second.id: "0.700"}

    def test_unrelated_message_types_are_not_written_into_the_tape(
        self, tmp_path: Path
    ) -> None:
        """The exclusive ``include_types`` filter is load-bearing, not cosmetic.

        The kernel subscribes the writer to ``"*"`` on the message bus. Written
        as a behaviour: an object of a type the tape does not record leaves no
        file behind.
        """
        from nautilus_trader.model.data import TradeTick
        from nautilus_trader.model.enums import AggressorSide
        from nautilus_trader.model.identifiers import TradeId

        instrument = make_instrument(SLUG)
        config = build_quote_tape_node_config(
            make_tape_settings(tmp_path), make_data_client_config()
        )
        cache = Cache(database=None, config=CacheConfig())
        cache.add_instrument(instrument)
        writer = writer_from_node_config(config, tmp_path, "instance-1", cache)
        writer.write(instrument)
        writer.write(
            TradeTick(
                instrument_id=instrument.id,
                price=Price.from_str("0.400"),
                size=Quantity.from_str("5"),
                aggressor_side=AggressorSide.BUYER,
                trade_id=TradeId("T-1"),
                ts_event=1_000_000_000,
                ts_init=1_000_000_000,
            )
        )
        writer.close()

        written = {p.name for p in tmp_path.rglob("*.feather")}
        assert not any("trade_tick" in name for name in written), written


class TestRecorderInstanceIdentityIsNative:
    """The identity stamped on gap rows IS the node's own ``instance_id``.

    Not a second identity scheme. ``NautilusKernelConfig.instance_id``
    (``system/config.py:108``) is honoured by the kernel
    (``system/kernel.py:160``) and is the same value that names the streaming
    directory (``system/kernel.py:589``), so a gap row's
    ``recorder_instance_id`` and the directory its feathers land in agree by
    construction.

    Threading it explicitly is FORCED, not preferred: ``MessageBus`` accepts
    ``instance_id`` but stores no attribute for it (verified -- there is no
    ``cdef readonly`` entry in ``common/component.pxd:273-299`` and
    ``hasattr(bus, "instance_id")`` is ``False``), and
    ``LiveDataClientFactory.create`` (``live/factories.py:33-39``) is handed
    only loop/name/config/msgbus/cache/clock. So a data client cannot reach
    the kernel's instance id on its own; the config is the only seam.
    """

    def test_the_node_and_the_data_client_share_one_instance_identity(
        self, tmp_path: Path
    ) -> None:
        base = make_data_client_config()

        config = build_quote_tape_node_config(make_tape_settings(tmp_path), base)

        wired = config.data_clients[POLYMARKET_US_CLIENT_NAME]
        assert config.instance_id is not None
        assert wired.recorder_instance_id == config.instance_id.value

    def test_two_builds_get_different_identities(
        self, tmp_path: Path
    ) -> None:
        """A restart must be distinguishable, which is the whole point."""
        base = make_data_client_config()

        first = build_quote_tape_node_config(make_tape_settings(tmp_path), base)
        second = build_quote_tape_node_config(make_tape_settings(tmp_path), base)

        assert first.instance_id != second.instance_id
