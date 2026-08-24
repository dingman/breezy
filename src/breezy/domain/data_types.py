"""The single shared `DataType` factory for Breezy's weather records.

Every publisher and every subscriber of a Breezy record builds its `DataType`
here. That is not a style preference -- it is the only thing standing between
Breezy and a silent settlement-data outage.

Why this module exists
----------------------
`DataType.topic` is built from ``metadata.items()`` in **insertion order**::

    self.topic = self.type.__name__ + '.' + '.'.join([
        f'{k}={v if v is not None else "*"}' for k, v in self.metadata.items()
    ]) if self.metadata else self.type.__name__ + "*"

(`model/data.pyx:2102-2104`), while ``__eq__``/``__hash__`` key on a
**frozenset** of the same items (`:2106-2107`, `:2109-2112`, `:2126-2127`). So::

    a = DataType(NwsClimateDay, {"venue": "polymarket_us", "city": "NYC"})
    b = DataType(NwsClimateDay, {"city": "NYC", "venue": "polymarket_us"})
    a == b                 # True
    hash(a) == hash(b)     # True
    a.topic == b.topic     # False

Two objects that every equality-based unit test calls identical, carrying two
different routing strings. The msgbus routes on the string, so a subscriber built
one way never receives a publish built the other way -- verified with
``is_matching_py``, and pinned in ``tests/contract/test_data_type_topic_contract.py``.

`TopicCache.get_custom_data_topic` does not rescue this. It caches on
``(data_type, historical)`` in a plain dict (`common/data_topics.pyx:189-209`), so
it resolves by ``__eq__``/``__hash__`` -- meaning the SECOND ordering constructed
receives the FIRST one's topic string. Which string a component uses therefore
depends on construction order. Worse, each `Actor` builds its **own** `TopicCache`
in ``__init__`` (`common/actor.pyx:165`), so Breezy's five per-city Actors hold
five independent caches, each primed by whatever that Actor happened to construct
first. Two Actors can disagree permanently.

For settlement data the failure is not a crash and not a log line. The subscriber
simply receives nothing -- which is indistinguishable from "the WFO issued no
product for this city today". That is the exact signal Breezy uses to decide
whether it may settle, so a routing typo becomes a wrong-or-absent settlement.

What actually fixes it
----------------------
**`canonical_metadata`'s sorted-key insertion order, and nothing else.** Because
the mapping's keys are always inserted in sorted order, every construction of the
same ``(venue, city)`` -- from any call site, in any kwarg order, in any process --
produces a byte-identical ``.topic``. Construction order stops mattering because
there is only one string left to construct.

Memoisation is **deliberately not used here**, and that is a correctness decision
rather than a performance one. `DataType` instances that are equal are already
fully interchangeable as `TopicCache` dict keys, so caching for object identity
would buy one avoided allocation per publish and nothing else -- while creating a
standing invitation to misread identity as the mechanism. A future reader who
believes the cache is the fix will eventually drop the sorting, keep the cache,
and reintroduce the bug in a form that passes every equality assertion. If a
profile ever justifies an ``lru_cache`` here, it must be added with the sorting
untouched and with ``test_delivery_survives_two_distinct_objects`` still passing:
that test builds the subscriber's `DataType` by hand from `canonical_metadata`, so
it proves delivery without any help from the factory's object identity.

What is published
-----------------
`DataType.type` is the **raw record class**. `Actor.publish_data` enforces
``Condition.type(data, data_type.type, "data", "data.type")``
(`common/actor.pyx:2827`), and `Condition.type` raises **`TypeError`**
(`core/correctness.pyx:179-183`). So the bus carries `NwsClimateDay` and
`NwsRawProduct` instances directly; passing a `CustomData` wrapper raises.
`CustomData` belongs to the catalog read path and `BacktestEngine.add_data`, not
to publication.

Warm start uses this module too
-------------------------------
`PHASE1_ACTOR_BRIEF.md` §2 F1: ``catalog.custom_data(...)`` silently drops
``metadata``, so a `request_data` warm start answers on the metadata-less topic
``historical.data.NwsClimateDay*``, which a metadata-bearing subscription cannot
match. §3.2's ruling is therefore to register no catalog with the `DataEngine`,
read the Actor's own catalog directly, and republish through **this** factory --
which is what makes the warm-start topic and the live topic the same string.

The asymmetry is worth stating because it makes the bug hard to catch: a
metadata-LESS subscriber DOES receive a metadata-bearing publish, since
``NwsClimateDay*`` is a glob. A smoke test written against a bare
``DataType(NwsClimateDay)`` subscriber passes while production receives nothing.

Metadata character set
----------------------
``.`` and ``=`` are the topic grammar's own separators and ``*``/``?`` are msgbus
wildcards, so a metadata key or value containing one silently restructures the
topic rather than appearing in it. `canonical_metadata` rejects them, along with
whitespace and empty strings. Today's registry values (``polymarket_us``, ``NYC``,
``SFO``, ``MIA``, ``MDW``, ``LAX``) are all safe; the guard is for the day someone
adds a city whose key is not.
"""

from __future__ import annotations

from nautilus_trader.model.data import DataType

from breezy.domain.nws_climate_day import NwsClimateDay
from breezy.domain.nws_raw_product import NwsRawProduct

__all__ = ["canonical_metadata", "climate_day_type", "raw_product_type"]

# `.` separates topic segments and `=` separates a key from its value
# (`model/data.pyx:2102-2104`); `*` and `?` are msgbus glob wildcards. A metadata
# component containing any of them restructures the topic instead of appearing in it.
_TOPIC_STRUCTURAL_CHARS = frozenset(".=*?")


def _validated(part: str, *, role: str) -> str:
    """Reject a metadata key or value that would restructure the topic string."""
    if not isinstance(part, str):
        raise TypeError(f"DataType metadata {role} must be a str, was {type(part).__name__}")
    if not part:
        raise ValueError(f"DataType metadata {role} must not be empty")
    if any(char.isspace() for char in part):
        raise ValueError(f"DataType metadata {role} must not contain whitespace: {part!r}")
    illegal = sorted(set(part) & _TOPIC_STRUCTURAL_CHARS)
    if illegal:
        raise ValueError(
            f"DataType metadata {role} must not contain any of "
            f"{''.join(sorted(_TOPIC_STRUCTURAL_CHARS))!r}: {part!r} contains {illegal}",
        )
    return part


def canonical_metadata(**kwargs: str) -> dict[str, str]:
    """Build `DataType` metadata whose insertion order is sorted by key.

    This ordering is the entire mechanism by which Breezy's publishers and
    subscribers agree on a topic string -- see the module docstring. Callers may
    pass keywords in any order; the returned mapping is always sorted, so every
    `DataType` built from it carries a byte-identical ``.topic``.

    Raises
    ------
    TypeError
        If any value is not a `str`.
    ValueError
        If any key or value is empty, contains whitespace, or contains one of
        ``.``, ``=``, ``*`` or ``?``.
    """
    return {
        _validated(key, role="key"): _validated(kwargs[key], role="value")
        for key in sorted(kwargs)
    }


def _site_type(record_cls: type, *, venue: str, city: str) -> DataType:
    """Build the `(venue, city)` `DataType` for one record class."""
    return DataType(record_cls, canonical_metadata(venue=venue, city=city))


def climate_day_type(*, venue: str, city: str) -> DataType:
    """The `DataType` for `NwsClimateDay` records of one `(venue, city)` site.

    Use this for every `Actor.publish_data` and `Actor.subscribe_data` call on the
    live path AND on the warm-start republish path -- they must agree, and
    `PHASE1_ACTOR_BRIEF.md` §3.2 makes this factory the thing they agree through.

    Publish the raw `NwsClimateDay`, never a `CustomData` wrapper: `publish_data`
    checks the record against ``DataType.type`` and raises `TypeError`.
    """
    return _site_type(NwsClimateDay, venue=venue, city=city)


def raw_product_type(*, venue: str, city: str) -> DataType:
    """The `DataType` for `NwsRawProduct` records of one `(venue, city)` site.

    Structurally identical to :func:`climate_day_type` and subject to the same
    rules. The two carry distinct topics because `DataType.topic` is prefixed with
    the record class name, so a `NwsRawProduct` subscriber never sees climate days.
    """
    return _site_type(NwsRawProduct, venue=venue, city=city)
