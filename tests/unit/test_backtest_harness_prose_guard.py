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
        "data[0]",
        "(instrument_id, type)",
        "_has_book_data",
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
    """
    assert "EXPIRATION-LEG" in MODULE_DOC
    assert "uuid4" in MODULE_DOC
    assert "venue_order_id" in MODULE_DOC


def test_the_docstring_warns_that_orders_open_has_no_guaranteed_ordering() -> None:
    """`cache.pyx:4719`. A sweep that iterates it is non-deterministic BY
    CONSTRUCTION, and so is any decision log written from that loop.
    """
    assert "Cache.orders_open()" in MODULE_DOC
    assert "no ordering" in MODULE_DOC


def test_the_docstring_states_that_a_strategy_must_filter_on_station() -> None:
    """Client-scoped weather delivers every city to every strategy.

    Correct platform behaviour -- one climate day settles many markets -- and
    therefore not something the harness may filter. What is owed is that the
    author is told.
    """
    assert "MUST filter on ``record.station``" in MODULE_DOC


# ---------------------------------------------------------------------------
# The reference strategy teaches the filter rather than merely mentioning it
# ---------------------------------------------------------------------------


def test_the_probe_docstring_states_the_station_filtering_duty() -> None:
    assert "MUST filter on ``station``" in PROBE_DOC


def test_the_probe_source_actually_implements_the_filter() -> None:
    """`harness_probe` is what a new strategy gets copied from.

    A warning in prose that the reference implementation does not follow
    teaches the opposite of what it says.
    """
    assert "data.station != self.config.station" in PROBE_SOURCE
