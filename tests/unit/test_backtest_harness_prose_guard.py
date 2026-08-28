"""The harness's prose must describe the mechanism it actually has.

This repository's named recurring defect is a docstring that states a
plausible mechanism the code does not implement. One shipped in
``backtest_harness.py``:

    ``market_data`` ... "Order does not matter: the engine sorts by ``ts_init``."

``add_data`` does sort -- and also reads ``data[0]`` and registers **only that
record's instrument** into ``_has_data``/``_has_book_data``
(``engine.pyx:863-897``). A list beginning with a ``QuoteTick`` or an
``InstrumentClose`` raises ``InvalidConfiguration`` telling the author to set
``book_type='L1_MBP'`` -- which is the SECOND-ranked silent failure in
``docs/specs/BACKTEST_VENUE_CONFIG.md`` §7. So the sentence was false, and
following it walked the author into a worse place than the error they started
with.

The claim is now true, because the harness groups by ``(instrument_id, type)``
before calling ``add_data``. These tests pin that the prose says WHY, and pin
the three author-seat warnings that have no runtime assertion of their own.
Documentation is the only possible artifact for those three: each describes a
property of NautilusTrader that Breezy neither causes nor can change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import pytest

from breezy.runtime import backtest_harness
from breezy.strategy import harness_probe

HARNESS_SOURCE: Final[str] = Path(backtest_harness.HARNESS_SOURCE_PATH).read_text(
    encoding="utf-8",
)
PROBE_SOURCE: Final[str] = Path(harness_probe.__file__).read_text(encoding="utf-8")

MODULE_DOC: Final[str] = backtest_harness.__doc__ or ""
CONFIG_DOC: Final[str] = backtest_harness.BreezyBacktestConfig.__doc__ or ""
PROBE_DOC: Final[str] = harness_probe.__doc__ or ""


# ---------------------------------------------------------------------------
# The false claim, and its true replacement
# ---------------------------------------------------------------------------


def test_the_market_data_docstring_no_longer_claims_the_engine_alone_sorts() -> None:
    """The exact sentence that was false, pinned as absent."""
    assert "Order does not matter: the engine sorts by" not in HARNESS_SOURCE


@pytest.mark.parametrize(
    "fragment",
    [
        # WHY order-independence holds: because the harness groups first.
        # Each pin is the whole CLAIM on its source line, not just an
        # identifier that could survive a substantial rewording of the
        # sentence around it (H-2: a bare "data[0]" or "_has_book_data"
        # token could still appear if the surrounding claim changed to
        # something else true about those names but not about grouping).
        "it reads ``data[0]`` and registers **that one** instrument into",
        "``_has_data``/``_has_book_data`` (``engine.pyx:863-897``)",
        "this sequence by ``(instrument_id, type)`` and calls ``add_data`` once",
    ],
)
def test_the_market_data_docstring_names_the_mechanism(fragment: str) -> None:
    assert fragment in CONFIG_DOC


def test_the_grouping_helper_is_actually_called_by_the_builder() -> None:
    """A documented mechanism nobody invokes is the same defect one level down."""
    assert "for group in _group_market_data(config.market_data):" in HARNESS_SOURCE


# ---------------------------------------------------------------------------
# Three author-seat warnings with no possible runtime assertion
# ---------------------------------------------------------------------------


def test_the_docstring_warns_that_the_settlement_legs_client_order_id_is_random() -> None:
    """`ClientOrderId(f"EXPIRATION-LEG-{uuid.uuid4()}")`, fresh every run.

    `use_random_ids=False` does not reach it. `client_order_id` is the natural
    field to put in a decision log, so a first determinism test fails
    intermittently for a reason that has nothing to do with the strategy.
    `harness_probe` already dodged this by logging `venue_order_id`; it did not
    say why, so the next author could only rediscover it.

    H-2: the original pin was three INDEPENDENT substrings ("EXPIRATION-LEG",
    "uuid4", "venue_order_id"), individually satisfiable anywhere at all in a
    module-length docstring -- a rewrite could scatter all three without
    preserving the actual claim (that THIS specific construction is the
    non-deterministic one). The first pin below is the exact code literal, so
    it can only match the real construction; the second is the recommendation
    sentence that names what to log instead, which is the actionable half of
    the warning.
    """
    assert 'ClientOrderId(f"EXPIRATION-LEG-{uuid.uuid4()}")`` (``engine.pyx:5956``)' in MODULE_DOC
    assert (
        "Log ``venue_order_id`` instead, which the harness's fixed ``TraderId`` and"
        in MODULE_DOC
    )


def test_the_docstring_warns_that_orders_open_has_no_guaranteed_ordering() -> None:
    """`cache.pyx:4719`. A sweep that iterates it is non-deterministic BY
    CONSTRUCTION, and so is any decision log written from that loop.

    H-2: tightened from two independent substrings ("Cache.orders_open()" and
    "no ordering", satisfiable anywhere and in any order relative to each
    other) to the single sentence that actually states the claim, with its
    citation -- a docstring could still contain the words "no ordering"
    somewhere after a substantial rewrite without this specific guarantee
    surviving.
    """
    assert "**``Cache.orders_open()`` guarantees no ordering** (``cache.pyx:4719``). A" in (
        MODULE_DOC
    )


def test_the_docstring_states_that_a_strategy_must_filter_on_station() -> None:
    """Client-scoped weather delivers every city to every strategy.

    Correct platform behaviour -- one climate day settles many markets -- and
    therefore not something the harness may filter. What is owed is that the
    author is told.

    H-2: left as a substring rather than tightened further. The pinned
    phrase already IS the entire claim ("a strategy MUST filter on
    ``record.station``") rather than an incidental fragment of it -- there is
    no larger surrounding sentence to fold in, and the obvious "improvement"
    (matching the whole paragraph) would cross into brittle full-text
    equality for no added protection, since the paragraph's other sentences
    are illustrative, not the rule itself.
    """
    assert "MUST filter on ``record.station``" in MODULE_DOC


# ---------------------------------------------------------------------------
# The reference strategy teaches the filter rather than merely mentioning it
# ---------------------------------------------------------------------------


def test_the_probe_docstring_states_the_station_filtering_duty() -> None:
    """H-2: same reasoning as the module-doc filter test above -- the pinned
    phrase already is the claim itself, not an incidental fragment; left
    as-is.
    """
    assert "MUST filter on ``station``" in PROBE_DOC


def test_the_probe_source_actually_implements_the_filter() -> None:
    """`harness_probe` is what a new strategy gets copied from.

    A warning in prose that the reference implementation does not follow
    teaches the opposite of what it says.

    H-2: not a prose pin at all -- this asserts against the SOURCE CODE
    predicate itself (`data.station != self.config.station`), which is
    already exact: it is the one line that performs the filter, not a
    description of it, so there is nothing left to tighten.
    """
    assert "data.station != self.config.station" in PROBE_SOURCE
