"""Contract tests pinning the NautilusTrader 1.231.0 `DataType` topic behaviour.

Every assertion here was observed by execution against the pinned install, not
inferred from documentation. Run these FIRST on any version bump: a failure means
the platform moved, not that Breezy is wrong.

These are the facts `breezy.domain.data_types` exists to work around. If any of
them changes, the factory's rationale changes with it -- which is precisely why
they are pinned rather than described in a comment.

Scope: `model/data.pyx` `DataType`, `common/data_topics.pyx` `TopicCache`, and
`common/actor.pyx` `publish_data`. No network access, no catalog, no disk.
"""

from __future__ import annotations

import pytest
from nautilus_trader.common.component import MessageBus, is_matching_py
from nautilus_trader.common.data_topics import TopicCache
from nautilus_trader.core.data import Data
from nautilus_trader.model.data import CustomData, DataType
from nautilus_trader.model.identifiers import ClientId, TraderId
from nautilus_trader.test_kit.mocks.actors import MockActor, MockActorConfig
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

pytestmark = pytest.mark.contract


class _Probe(Data):
    """A minimal `Data` contract implementation, kept out of `breezy.domain`.

    Deliberately not a Breezy record type: these tests pin framework behaviour, so
    they must keep passing even if every Breezy record class is renamed.
    """

    def __init__(self, ts: int = 0) -> None:
        self._ts = ts

    @property
    def ts_event(self) -> int:
        return self._ts

    @property
    def ts_init(self) -> int:
        return self._ts


_FORWARD = {"venue": "polymarket_us", "city": "NYC"}
_REVERSE = {"city": "NYC", "venue": "polymarket_us"}


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
    actor.start()
    return actor


# ---------------------------------------------------------------------------
# `DataType.topic` grammar
# ---------------------------------------------------------------------------


def test_topic_is_dot_separated_key_equals_value_in_insertion_order() -> None:
    """`model/data.pyx:2102-2104`.

    The separator is a dot and the pairs are `k=v` -- NOT a query string. A
    metadata key or value containing `.` or `=` would therefore restructure the
    topic, which is why `canonical_metadata` rejects those characters.
    """
    assert DataType(_Probe, _FORWARD).topic == "_Probe.venue=polymarket_us.city=NYC"
    assert DataType(_Probe, _REVERSE).topic == "_Probe.city=NYC.venue=polymarket_us"


def test_metadata_less_topic_is_a_trailing_glob() -> None:
    """`model/data.pyx:2104` -- no metadata yields `<ClassName>*`, a wildcard."""
    assert DataType(_Probe).topic == "_Probe*"


def test_equal_data_types_can_carry_different_topics() -> None:
    """The whole hazard in four assertions.

    `__eq__` and `__hash__` key on `frozenset(metadata.items())`
    (`model/data.pyx:2106-2107`, `:2109-2112`, `:2126-2127`) while `topic` keys on
    insertion order. Equality-based tests pass while production delivers nothing.
    """
    forward = DataType(_Probe, _FORWARD)
    reverse = DataType(_Probe, _REVERSE)

    assert forward == reverse
    assert hash(forward) == hash(reverse)
    assert forward.topic != reverse.topic


def test_sorting_the_metadata_keys_removes_the_divergence() -> None:
    """The fix, pinned against the framework rather than against Breezy code."""
    forward = DataType(_Probe, dict(sorted(_FORWARD.items())))
    reverse = DataType(_Probe, dict(sorted(_REVERSE.items())))

    assert forward.topic == reverse.topic


# ---------------------------------------------------------------------------
# `TopicCache` resolves by `__eq__`/`__hash__`, so the first construction wins
# ---------------------------------------------------------------------------


def test_topic_cache_returns_whichever_ordering_was_cached_first() -> None:
    """`common/data_topics.pyx:189-209` caches on `(data_type, historical)` in a
    plain dict. Because the two orderings are equal and hash equal, the SECOND
    lookup returns the FIRST one's topic string -- so which string a component
    uses depends on construction order, not on which instance it holds.
    """
    forward = DataType(_Probe, _FORWARD)
    reverse = DataType(_Probe, _REVERSE)

    forward_first = TopicCache()
    assert forward_first.get_custom_data_topic(forward) == "data._Probe.venue=polymarket_us.city=NYC"
    assert forward_first.get_custom_data_topic(reverse) == "data._Probe.venue=polymarket_us.city=NYC"

    reverse_first = TopicCache()
    assert reverse_first.get_custom_data_topic(reverse) == "data._Probe.city=NYC.venue=polymarket_us"
    assert reverse_first.get_custom_data_topic(forward) == "data._Probe.city=NYC.venue=polymarket_us"


def test_topic_cache_agrees_across_instances_when_metadata_is_sorted() -> None:
    """With sorted keys the construction order stops mattering -- both caches
    resolve to the same string whichever instance primed them first.
    """
    forward = DataType(_Probe, dict(sorted(_FORWARD.items())))
    reverse = DataType(_Probe, dict(sorted(_REVERSE.items())))

    forward_first = TopicCache()
    reverse_first = TopicCache()

    assert forward_first.get_custom_data_topic(forward) == reverse_first.get_custom_data_topic(
        reverse,
    )


def test_each_actor_owns_a_private_topic_cache() -> None:
    """`common/actor.pyx:165` -- `self._topic_cache = TopicCache()` per instance.

    This is why the cache cannot be relied on to reconcile the two orderings: five
    per-city Actors hold five independent caches, each primed by whatever that
    Actor happened to construct first. `_topic_cache` is a cdef attribute and
    unreachable from Python, so the privacy is observed through its consequence --
    prime two Actors in opposite orders and their subscription topics diverge.
    """
    bus_a = MessageBus(trader_id=TraderId("BREEZY-001"), clock=TestComponentStubs.clock())
    bus_b = MessageBus(trader_id=TraderId("BREEZY-001"), clock=TestComponentStubs.clock())
    a = _running_actor(bus_a, "A")
    b = _running_actor(bus_b, "B")

    a.subscribe_data(DataType(_Probe, _FORWARD), client_id=ClientId("WEATHER"))
    b.subscribe_data(DataType(_Probe, _REVERSE), client_id=ClientId("WEATHER"))

    topics_a = {sub.topic for sub in bus_a.subscriptions()}
    topics_b = {sub.topic for sub in bus_b.subscriptions()}
    assert "data._Probe.venue=polymarket_us.city=NYC" in topics_a
    assert "data._Probe.city=NYC.venue=polymarket_us" in topics_b


# ---------------------------------------------------------------------------
# msgbus glob matching
# ---------------------------------------------------------------------------


def test_orderings_do_not_match_each_other() -> None:
    assert not is_matching_py(f"data.{DataType(_Probe, _REVERSE).topic}", f"data.{DataType(_Probe, _FORWARD).topic}")


def test_metadata_bearing_subscription_does_not_match_a_metadata_less_publish() -> None:
    """PHASE1_ACTOR_BRIEF F1: `catalog.custom_data(...)` drops `metadata`, so a
    `request_data` warm start answers on `historical.data.<Class>*`.
    """
    assert not is_matching_py(
        f"data.{DataType(_Probe).topic}",
        f"data.{DataType(_Probe, _FORWARD).topic}",
    )


def test_the_reverse_direction_does_match_and_that_asymmetry_is_the_trap() -> None:
    """A metadata-LESS subscriber receives a metadata-bearing publish, because
    `<Class>*` is a glob. So a smoke test written against a bare `DataType(X)`
    subscriber passes while the production subscriber receives nothing.
    """
    assert is_matching_py(
        f"data.{DataType(_Probe, _FORWARD).topic}",
        f"data.{DataType(_Probe).topic}",
    )


# ---------------------------------------------------------------------------
# `Actor.publish_data` type enforcement
# ---------------------------------------------------------------------------


def test_publish_data_rejects_a_custom_data_wrapper_with_type_error(bus: MessageBus) -> None:
    """`common/actor.pyx:2827` runs `Condition.type(data, data_type.type, ...)`, and
    `Condition.type` raises **TypeError** (`core/correctness.pyx:179-183`) -- not
    `ValueError`. The raw record is published; the wrapper belongs to the catalog
    and `BacktestEngine.add_data` paths only.
    """
    publisher = _running_actor(bus, "PUBLISHER")
    data_type = DataType(_Probe, _FORWARD)

    with pytest.raises(TypeError):
        publisher.publish_data(data_type, CustomData(data_type, _Probe()))


def test_publish_data_accepts_the_raw_record(bus: MessageBus) -> None:
    publisher = _running_actor(bus, "PUBLISHER")
    subscriber = _running_actor(bus, "SUBSCRIBER")
    data_type = DataType(_Probe, dict(sorted(_FORWARD.items())))
    record = _Probe()

    subscriber.subscribe_data(data_type, client_id=ClientId("WEATHER"))
    publisher.publish_data(data_type, record)

    assert subscriber.store == [record]


def test_data_published_before_running_is_dropped(bus: MessageBus) -> None:
    """`actor.pyx:4716` -- `handle_data` forwards only while RUNNING. Pinned here so
    the delivery tests' `actor.start()` is understood as load-bearing, not ritual.
    """
    publisher = _running_actor(bus, "PUBLISHER")
    subscriber = MockActor(MockActorConfig(component_id="SUBSCRIBER"))
    subscriber.register_base(
        portfolio=TestComponentStubs.portfolio(),
        msgbus=bus,
        cache=TestComponentStubs.cache(),
        clock=TestComponentStubs.clock(),
    )
    data_type = DataType(_Probe, dict(sorted(_FORWARD.items())))

    subscriber.subscribe_data(data_type, client_id=ClientId("WEATHER"))  # not started
    publisher.publish_data(data_type, _Probe())

    assert subscriber.store == []


def test_data_type_type_attribute_is_the_class_object() -> None:
    """1.231.0's Cython `DataType` takes a class object; the PyO3 surface takes a
    string. Pinned so a docs-driven change to a string cannot land quietly.
    """
    assert DataType(_Probe, _FORWARD).type is _Probe

    with pytest.raises(TypeError):
        DataType("_Probe", _FORWARD)  # type: ignore[arg-type]
