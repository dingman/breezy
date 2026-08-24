"""Contract test pinning `Actor.publish_signal`'s per-name type coercion trap.

Every assertion here was observed by execution against the pinned install
(nautilus-trader 1.231.0), not inferred from documentation. Run this FIRST on
any version bump: a failure means the platform moved, not that Breezy is
wrong.

`generate_signal_class` (`common/signal.py:25`) is called lazily, the FIRST
time a given signal `name` is published, and its result is cached per-Actor
keyed only by `name` (`common/actor.pyx:2854-2858`). The generated
`SignalData` subclass's pyarrow schema (used for catalog persistence) is
fixed at that moment from `type(value)` of whichever value happened to be
published first. Every subsequent `publish_signal(name, ...)` call for that
same `name` reuses the SAME class regardless of the new value's type --
`Actor.publish_signal` never re-checks the value against the schema that
generated the class, and the generated `SignalData.__init__` stores
`self.value = value` verbatim with no cast. So a signal named `"temp"` first
published as an `int` and later published as a `str` is accepted both times,
delivered both times, and BOTH are wrapped in a class whose Arrow schema was
fixed to `int64` on the first call -- the second value is silently accepted
under a schema that does not describe it, not rejected and not converted to
match it.

The one type check that does exist runs before any of this: `Condition.is_in`
(`common/actor.pyx:2851`) restricts a published `value` to `(int, float,
str)` -- notably NARROWER than the four Python types `generate_signal_class`'s
pyarrow schema table supports (`int`, `float`, `str`, `bool`, `bytes`,
`common/signal.py:120-127`), so `bool`/`bytes` never reach the per-name-typed
class at all, regardless of what published first.

Scope: `common/actor.pyx` `Actor.publish_signal` (`:2832-2864`) and
`common/signal.py` `generate_signal_class` (`:25`). No network access, no
catalog, no disk.
"""

from __future__ import annotations

import pytest
from nautilus_trader.common.component import MessageBus
from nautilus_trader.model.identifiers import TraderId
from nautilus_trader.test_kit.mocks.actors import MockActor, MockActorConfig
from nautilus_trader.test_kit.stubs.component import TestComponentStubs

pytestmark = pytest.mark.contract


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


def test_the_signal_class_is_generated_once_and_reused_across_different_value_types(
    bus: MessageBus,
) -> None:
    """`common/actor.pyx:2854-2858` -- three `publish_signal("temp", ...)`
    calls with an `int`, then a `str`, then a `float` all deliver, and all
    three delivered records are instances of the exact SAME class object
    (`type(...) is type(...)`, not merely same name) -- proving the class was
    generated once, off the FIRST value, and never regenerated or checked
    again for the later two.
    """
    publisher = _running_actor(bus, "PUBLISHER")
    subscriber = _running_actor(bus, "SUBSCRIBER")
    subscriber.subscribe_signal("temp")

    publisher.publish_signal("temp", 42)
    publisher.publish_signal("temp", "not-a-number")
    publisher.publish_signal("temp", 3.14)

    assert len(subscriber.store) == 3
    first, second, third = subscriber.store
    assert type(first) is type(second) is type(third)
    assert type(first).__name__ == "SignalTemp"


def test_a_later_value_of_a_different_type_is_accepted_verbatim_not_rejected(
    bus: MessageBus,
) -> None:
    """The coercion hazard, stated as data: the SECOND published value keeps
    its own real Python type (a `str`, unchanged) even though the class it is
    wrapped in was typed off the FIRST value (an `int`). Nothing rejects the
    mismatch and nothing casts the `str` to look like the `int` schema either
    -- it passes through `SignalData.__init__` untouched. This is why
    "coerced" is really "silently accepted under a stale schema": the value
    itself is not coerced to anything, only the class's Arrow typing becomes
    a lie about what it now contains.
    """
    publisher = _running_actor(bus, "PUBLISHER")
    subscriber = _running_actor(bus, "SUBSCRIBER")
    subscriber.subscribe_signal("mixed")

    publisher.publish_signal("mixed", 7)
    publisher.publish_signal("mixed", "seven")

    first, second = subscriber.store
    assert first.value == 7
    assert type(first.value) is int
    assert second.value == "seven"
    assert type(second.value) is str


def test_publish_signal_rejects_bool_and_bytes_before_any_class_is_generated(
    bus: MessageBus,
) -> None:
    """`common/actor.pyx:2851` -- `Condition.is_in(type(value), (int, float,
    str), ...)` runs BEFORE `generate_signal_class` is ever reached, and it
    is narrower than the four value types `generate_signal_class`'s own
    pyarrow schema table supports (`bool` and `bytes` included there,
    `common/signal.py:120-127`). A `bool` or `bytes` value is refused with
    `KeyError` (the exception type `Condition.is_in` raises, `core/
    correctness.pyx`), not `TypeError` and not silently coerced to `int`
    (which is notable since `bool` is an `int` subclass in Python and would
    otherwise pass a naive `isinstance` check).
    """
    publisher = _running_actor(bus, "PUBLISHER")

    with pytest.raises(KeyError):
        publisher.publish_signal("flag", True)

    with pytest.raises(KeyError):
        publisher.publish_signal("blob", b"raw-bytes")


def test_each_actor_generates_and_caches_its_own_signal_class_independently() -> None:
    """Two separate Actors publishing the same signal `name` with different
    FIRST value types end up with two DIFFERENT generated classes -- the
    per-name cache (`common/actor.pyx:2854`) is an Actor instance attribute,
    not global, so this per-Actor divergence is possible and is not itself a
    bug, just the surface the previous tests' hazard lives on.
    """
    bus_a = MessageBus(trader_id=TraderId("BREEZY-001"), clock=TestComponentStubs.clock())
    bus_b = MessageBus(trader_id=TraderId("BREEZY-001"), clock=TestComponentStubs.clock())
    actor_a = _running_actor(bus_a, "A")
    actor_b = _running_actor(bus_b, "B")
    sub_a = _running_actor(bus_a, "SUB-A")
    sub_b = _running_actor(bus_b, "SUB-B")
    sub_a.subscribe_signal("shared-name")
    sub_b.subscribe_signal("shared-name")

    actor_a.publish_signal("shared-name", 1)
    actor_b.publish_signal("shared-name", "one")

    assert type(sub_a.store[0]).__name__ == "SignalShared-Name"
    assert type(sub_b.store[0]).__name__ == "SignalShared-Name"
    # Same generated NAME, but independently generated class objects.
    assert type(sub_a.store[0]) is not type(sub_b.store[0])
    assert sub_a.store[0].value == 1
    assert sub_b.store[0].value == "one"
