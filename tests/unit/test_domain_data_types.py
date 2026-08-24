"""Unit tests for the shared `DataType` factory.

The factory exists to close one specific silent-delivery bug. `DataType.topic` is
built from ``metadata.items()`` in **insertion order** (`model/data.pyx:2102-2104`)
while `__eq__`/`__hash__` key on a **frozenset** (`:2106-2107`, `:2109-2112`,
`:2126-2127`). So two `DataType`s carrying the same metadata in different kwarg
orders compare **equal**, hash **equal**, and carry **different** topic strings.

For settlement data the consequence is not a crash. A metadata-bearing subscriber
whose topic string disagrees with the publisher's simply receives nothing, which is
indistinguishable from "the WFO issued no product today".

The framework-side facts these tests rest on are pinned separately in
`tests/contract/test_data_type_topic_contract.py`. This file tests Breezy's factory.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any

import pytest
from nautilus_trader.common.component import MessageBus
from nautilus_trader.model.data import CustomData, DataType
from nautilus_trader.model.identifiers import ClientId, TraderId
from nautilus_trader.test_kit.mocks.actors import MockActor, MockActorConfig
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

from breezy.domain.data_types import (
    canonical_metadata,
    climate_day_type,
    raw_product_type,
)
from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.domain.nws_raw_product import RAW_PRODUCT_SCHEMA_VERSION, NwsRawProduct

_DAY = dt.date(2026, 8, 22)
_DAY_END_NS = int(dt.datetime(2026, 8, 23, 5, 0, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_ISSUED_NS = int(dt.datetime(2026, 8, 23, 6, 27, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_RETRIEVED_NS = int(dt.datetime(2026, 8, 23, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_RAW_TEXT = "CDUS41 KOKX 230627\nCLINYC\n...THE CENTRAL PARK NY CLIMATE SUMMARY FOR AUGUST 22...\n"
_RAW_SHA = hashlib.sha256(_RAW_TEXT.encode()).hexdigest()
_RESPONSE_SHA = hashlib.sha256(_RAW_TEXT.encode()).hexdigest()


def make_climate_day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": _DAY,
        "tmax_f": 84,
        "tmin_f": 63,
        "tavg_f": 74,
        "tavg_flag": None,
        "tmax_flag": None,
        "tmin_flag": None,
        "is_final": True,
        "correction_flag": False,
        "revision_seq": 1,
        "is_superseded": False,
        "issuing_office": "KOKX",
        "issuance_time_ns": _ISSUED_NS,
        "retrieved_at_ns": _RETRIEVED_NS,
        "parser_version": "pyiem==1.27.0",
        "registry_version": "sites.toml@1",
        "raw_sha256": _RAW_SHA,
        "source_channel": "api.weather.gov",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": _DAY_END_NS,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


def make_raw_product(**overrides: Any) -> NwsRawProduct:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "product_uuid": "b6a5f0f6-0c1e-4f2a-9d3f-6b7c8d9e0f11",
        "product_code": "CLI",
        "issuing_office": "KOKX",
        "wmo_collective_id": "CDUS41",
        "awips_pil": "CLINYC",
        "wmo_bbb_token": None,
        "issuance_time_ns": _ISSUED_NS,
        "retrieved_at_ns": _RETRIEVED_NS,
        "climate_day": _DAY,
        "raw_text": _RAW_TEXT,
        "raw_sha256": _RAW_SHA,
        "response_sha256": _RESPONSE_SHA,
        "response_etag": None,
        "response_last_modified": None,
        "source_channel": "api.weather.gov/products/types/CLI/locations/NYC",
        "registry_version": "sites.toml@1",
        "schema_version": RAW_PRODUCT_SCHEMA_VERSION,
    }
    kwargs.update(overrides)
    return NwsRawProduct(**kwargs)


# ---------------------------------------------------------------------------
# A real message bus, wired the way production wires it.
#
# `Actor.__init__` builds its OWN `TopicCache` (`common/actor.pyx:165`), so five
# per-city Actors hold five independent caches. Testing publish/subscribe with a
# single shared cache would hide exactly the divergence this factory prevents:
# these helpers therefore always use two distinct Actor instances.
# ---------------------------------------------------------------------------


@pytest.fixture
def bus() -> MessageBus:
    return MessageBus(trader_id=TraderId("BREEZY-001"), clock=TestComponentStubs.clock())


def _running_actor(bus: MessageBus, component_id: str) -> MockActor:
    actor = MockActor(MockActorConfig(component_id=component_id))
    actor.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=bus,
        cache=TestComponentStubs.cache(),
        clock=TestComponentStubs.clock(),
    )
    # `handle_data` forwards to `on_data` only while RUNNING (`actor.pyx:4716`);
    # anything published before that is silently dropped.
    actor.start()
    return actor


# ---------------------------------------------------------------------------
# 1. Kwarg order must not change the topic string.
# ---------------------------------------------------------------------------


def test_canonical_metadata_is_sorted_by_key_regardless_of_kwarg_order() -> None:
    forward = canonical_metadata(venue="polymarket_us", city="NYC")
    reverse = canonical_metadata(city="NYC", venue="polymarket_us")

    assert list(forward) == ["city", "venue"]
    assert list(forward) == list(reverse)
    assert forward == reverse


@pytest.mark.parametrize("factory", [climate_day_type, raw_product_type])
def test_topic_is_byte_identical_across_kwarg_orders(factory: Any) -> None:
    """The regression: equal `DataType`s carrying different topic strings."""
    forward = factory(venue="polymarket_us", city="NYC")
    reverse = factory(city="NYC", venue="polymarket_us")

    assert forward.topic == reverse.topic
    assert forward.topic.encode() == reverse.topic.encode()


def test_metadata_insertion_order_is_what_makes_the_topics_agree() -> None:
    """Pins the *mechanism*, so a future refactor cannot drop the sorting silently.

    Equality would still hold with unsorted metadata -- that is the trap. Only the
    key ORDER of the returned mapping proves the fix is in place.
    """
    data_type = climate_day_type(city="NYC", venue="polymarket_us")

    assert list(data_type.metadata) == sorted(data_type.metadata)
    assert data_type.topic == "NwsClimateDay.city=NYC.venue=polymarket_us"


# ---------------------------------------------------------------------------
# 2. The real regression: delivery through a real msgbus.
# ---------------------------------------------------------------------------


def test_subscriber_receives_publish_when_both_sides_use_the_factory(bus: MessageBus) -> None:
    publisher = _running_actor(bus, "PUBLISHER")
    subscriber = _running_actor(bus, "SUBSCRIBER")

    subscriber.subscribe_data(
        climate_day_type(city="NYC", venue="polymarket_us"),
        client_id=ClientId("WEATHER"),
    )
    record = make_climate_day()
    publisher.publish_data(climate_day_type(venue="polymarket_us", city="NYC"), record)

    assert subscriber.store == [record]


def test_raw_product_subscriber_receives_publish_through_the_factory(bus: MessageBus) -> None:
    publisher = _running_actor(bus, "PUBLISHER")
    subscriber = _running_actor(bus, "SUBSCRIBER")

    subscriber.subscribe_data(
        raw_product_type(city="NYC", venue="polymarket_us"),
        client_id=ClientId("WEATHER"),
    )
    record = make_raw_product()
    publisher.publish_data(raw_product_type(venue="polymarket_us", city="NYC"), record)

    assert subscriber.store == [record]


def test_hand_built_data_type_in_the_wrong_kwarg_order_delivers_nothing(bus: MessageBus) -> None:
    """The bug the factory exists to prevent, demonstrated end to end.

    Not an aspiration for the factory -- a pin on the framework consequence, so the
    delivery tests above cannot be mistaken for tautologies.
    """
    publisher = _running_actor(bus, "PUBLISHER")
    subscriber = _running_actor(bus, "SUBSCRIBER")

    subscriber.subscribe_data(
        DataType(NwsClimateDay, {"venue": "polymarket_us", "city": "NYC"}),
        client_id=ClientId("WEATHER"),
    )
    publisher.publish_data(
        DataType(NwsClimateDay, {"city": "NYC", "venue": "polymarket_us"}),
        make_climate_day(),
    )

    assert subscriber.store == []


def test_warm_start_republish_reaches_the_live_subscriber(bus: MessageBus) -> None:
    """PHASE1_ACTOR_BRIEF F1 / 3.2: warm start must use this same factory.

    `catalog.custom_data(...)` drops `metadata`, so a `request_data` warm start
    answers on the metadata-less topic `historical.data.NwsClimateDay*`, which a
    metadata-bearing subscription cannot match. Reading the catalog directly and
    republishing through the factory is what makes warm start and live agree.
    """
    warm_start = _running_actor(bus, "WARM-START")
    subscriber = _running_actor(bus, "SUBSCRIBER")

    subscriber.subscribe_data(
        climate_day_type(venue="polymarket_us", city="NYC"),
        client_id=ClientId("WEATHER"),
    )
    replayed = make_climate_day()
    warm_start.publish_data(climate_day_type(venue="polymarket_us", city="NYC"), replayed)

    assert subscriber.store == [replayed]


def test_metadata_less_publish_does_not_reach_a_metadata_bearing_subscriber(
    bus: MessageBus,
) -> None:
    """Why warm start may not shortcut through a bare `DataType(NwsClimateDay)`."""
    publisher = _running_actor(bus, "PUBLISHER")
    subscriber = _running_actor(bus, "SUBSCRIBER")

    subscriber.subscribe_data(
        climate_day_type(venue="polymarket_us", city="NYC"),
        client_id=ClientId("WEATHER"),
    )
    publisher.publish_data(DataType(NwsClimateDay), make_climate_day())

    assert subscriber.store == []


# ---------------------------------------------------------------------------
# 3. Distinct sites must not collide.
# ---------------------------------------------------------------------------


def test_distinct_sites_produce_distinct_topics() -> None:
    topics = {
        climate_day_type(venue="polymarket_us", city=city).topic
        for city in ("NYC", "SFO", "MIA", "MDW", "LAX")
    }

    assert len(topics) == 5


def test_distinct_venues_produce_distinct_topics() -> None:
    a = climate_day_type(venue="polymarket_us", city="NYC")
    b = climate_day_type(venue="kalshi", city="NYC")

    assert a.topic != b.topic
    assert a != b


def test_record_types_do_not_share_a_topic() -> None:
    climate = climate_day_type(venue="polymarket_us", city="NYC")
    raw = raw_product_type(venue="polymarket_us", city="NYC")

    assert climate.topic != raw.topic
    assert climate != raw


def test_one_citys_subscriber_never_receives_another_citys_publish(bus: MessageBus) -> None:
    publisher = _running_actor(bus, "PUBLISHER")
    nyc = _running_actor(bus, "NYC")
    sfo = _running_actor(bus, "SFO")

    nyc.subscribe_data(
        climate_day_type(venue="polymarket_us", city="NYC"),
        client_id=ClientId("WEATHER"),
    )
    sfo.subscribe_data(
        climate_day_type(venue="polymarket_us", city="SFO"),
        client_id=ClientId("WEATHER"),
    )
    record = make_climate_day(station="NYC")
    publisher.publish_data(climate_day_type(venue="polymarket_us", city="NYC"), record)

    assert nyc.store == [record]
    assert sfo.store == []


# ---------------------------------------------------------------------------
# 4. `DataType.type` is the raw record class, not the wrapper.
# ---------------------------------------------------------------------------


def test_data_type_type_is_the_raw_record_class() -> None:
    assert climate_day_type(venue="polymarket_us", city="NYC").type is NwsClimateDay
    assert raw_product_type(venue="polymarket_us", city="NYC").type is NwsRawProduct


def test_publishing_a_custom_data_wrapper_raises_type_error(bus: MessageBus) -> None:
    """`Actor.publish_data` runs `Condition.type(data, data_type.type)`
    (`common/actor.pyx:2827`), and `Condition.type` raises **TypeError**
    (`core/correctness.pyx:179-183`). The raw record is published, never a wrapper.
    """
    publisher = _running_actor(bus, "PUBLISHER")
    data_type = climate_day_type(venue="polymarket_us", city="NYC")
    wrapped = CustomData(data_type, make_climate_day())

    with pytest.raises(TypeError):
        publisher.publish_data(data_type, wrapped)


def test_publishing_the_wrong_record_class_raises_type_error(bus: MessageBus) -> None:
    publisher = _running_actor(bus, "PUBLISHER")

    with pytest.raises(TypeError):
        publisher.publish_data(
            climate_day_type(venue="polymarket_us", city="NYC"),
            make_raw_product(),
        )


# ---------------------------------------------------------------------------
# 5. Metadata values may not carry topic-structural characters.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", [".", "=", "*", "?", "a.b", "a=b", "NY C", "NY\tC"])
def test_topic_structural_characters_are_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        canonical_metadata(venue="polymarket_us", city=bad)


@pytest.mark.parametrize("bad", [".", "=", "*", "?"])
def test_topic_structural_characters_are_rejected_in_keys(bad: str) -> None:
    with pytest.raises(ValueError):
        canonical_metadata(**{f"ven{bad}ue": "polymarket_us"})


def test_empty_metadata_value_is_rejected() -> None:
    with pytest.raises(ValueError):
        canonical_metadata(venue="polymarket_us", city="")


def test_non_string_metadata_value_is_rejected() -> None:
    with pytest.raises(TypeError):
        canonical_metadata(venue="polymarket_us", city=7)  # type: ignore[arg-type]


def test_factories_reject_a_structurally_unsafe_city() -> None:
    with pytest.raises(ValueError):
        climate_day_type(venue="polymarket_us", city="NY.C")
    with pytest.raises(ValueError):
        raw_product_type(venue="polymarket_us", city="NY.C")


def test_canonical_metadata_with_no_kwargs_is_empty() -> None:
    assert canonical_metadata() == {}


# ---------------------------------------------------------------------------
# 6. Correctness does not rest on object identity.
# ---------------------------------------------------------------------------


def test_delivery_survives_two_distinct_objects(bus: MessageBus) -> None:
    """The module docstring's claim, made falsifiable.

    Sorted insertion order is the fix; object identity is not load-bearing. The
    subscriber here holds a `DataType` the factory never returned -- built by hand
    from `canonical_metadata` -- and delivery still succeeds, because the topic
    strings are byte-identical. Any memoisation added later is therefore an
    allocation saving, not the correctness mechanism, and this test still passes
    with it removed.
    """
    publisher = _running_actor(bus, "PUBLISHER")
    subscriber = _running_actor(bus, "SUBSCRIBER")

    sub_type = DataType(NwsClimateDay, canonical_metadata(city="NYC", venue="polymarket_us"))
    pub_type = climate_day_type(venue="polymarket_us", city="NYC")
    assert sub_type is not pub_type

    subscriber.subscribe_data(sub_type, client_id=ClientId("WEATHER"))
    record = make_climate_day()
    publisher.publish_data(pub_type, record)

    assert subscriber.store == [record]


# ---------------------------------------------------------------------------
# 7. Package surface.
# ---------------------------------------------------------------------------


def test_factory_is_re_exported_from_the_domain_package() -> None:
    """A subscriber must reach the contract without importing `breezy.ingest`."""
    from breezy import domain

    assert domain.climate_day_type is climate_day_type
    assert domain.raw_product_type is raw_product_type
    assert domain.canonical_metadata is canonical_metadata
    for name in ("canonical_metadata", "climate_day_type", "raw_product_type"):
        assert name in domain.__all__
