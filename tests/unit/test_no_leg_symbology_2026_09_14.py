"""S2 NO-leg composite instrument id (plan `docs/plans/NO_SIDE_EDGE_2026-09-14.md`
section 4 S2, R3-1, N2-1).

R3-1: ``~`` is withdrawn -- Nautilus's Rust-session Parquet SQL sanitiser
(``_sanitize_sql_identifier``) does not escape it, so a ``QuoteTick`` written
under a ``~``-composite id cannot be read back through
``ParquetDataCatalog.quote_ticks``. The replacement separator must pass all
three of: (a) refused inside a base slug by ``assert_valid_slug``; (b)
accepted by Nautilus ``Symbol``/``InstrumentId``; (c) a ``QuoteTick`` written
under the composite id round-trips through ``catalog.quote_ticks``. ``^`` is
tried first; this file is the test that proves it.
"""

from __future__ import annotations

import shutil
import tempfile

import pytest
from nautilus_trader.model.data import QuoteTick
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.model.objects import Price, Quantity
from nautilus_trader.persistence.catalog import ParquetDataCatalog

from breezy.adapters.polymarket_us.errors import VenuePayloadError
from breezy.adapters.polymarket_us.symbology import (
    INSTRUMENT_SEPARATOR,
    POLYMARKET_US_VENUE,
    assert_catalog_aliases_are_unique,
    assert_valid_slug,
    base_slug_of,
    catalog_sql_alias,
    leg_of,
    no_leg_instrument_id,
    sibling_instrument_id,
    slug_to_instrument_id,
)

SLUG = "tc-temp-nychigh-2026-08-25-lt79f"


def test_chosen_separator_is_caret() -> None:
    # R3-1: ~ is withdrawn (Rust-session SQL parser rejects it); ^ passed the
    # empirical probe (Symbol round-trip + catalog write/read) and is chosen.
    assert INSTRUMENT_SEPARATOR == "^"


def test_separator_is_refused_inside_a_base_slug() -> None:
    with pytest.raises(VenuePayloadError):
        assert_valid_slug(f"tc{INSTRUMENT_SEPARATOR}temp-nychigh")


def test_no_leg_symbol_round_trips_through_nautilus_instrument_id() -> None:
    no_id = no_leg_instrument_id(SLUG)
    assert no_id.venue == POLYMARKET_US_VENUE
    assert InstrumentId.from_str(str(no_id)) == no_id
    assert str(no_id.symbol) == f"{SLUG}{INSTRUMENT_SEPARATOR}no"


def test_a_quote_tick_written_under_the_no_leg_id_reads_back_through_the_catalog() -> None:
    no_id = no_leg_instrument_id(SLUG)
    tick = QuoteTick(
        instrument_id=no_id,
        bid_price=Price.from_str("0.10"),
        ask_price=Price.from_str("0.20"),
        bid_size=Quantity.from_str("1"),
        ask_size=Quantity.from_str("1"),
        ts_event=0,
        ts_init=0,
    )
    tmpdir = tempfile.mkdtemp()
    try:
        catalog = ParquetDataCatalog(tmpdir)
        catalog.write_data([tick])
        read_back = catalog.quote_ticks(instrument_ids=[no_id.value])
        assert len(read_back) == 1
        assert read_back[0].instrument_id == no_id
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_leg_of_distinguishes_yes_and_no() -> None:
    yes_id = slug_to_instrument_id(SLUG)
    no_id = no_leg_instrument_id(SLUG)
    assert leg_of(yes_id) == "yes"
    assert leg_of(no_id) == "no"


def test_base_slug_of_recovers_the_slug_from_either_leg() -> None:
    yes_id = slug_to_instrument_id(SLUG)
    no_id = no_leg_instrument_id(SLUG)
    assert base_slug_of(yes_id) == SLUG
    assert base_slug_of(no_id) == SLUG


def test_sibling_instrument_id_is_an_involution() -> None:
    yes_id = slug_to_instrument_id(SLUG)
    no_id = no_leg_instrument_id(SLUG)
    assert sibling_instrument_id(yes_id) == no_id
    assert sibling_instrument_id(no_id) == yes_id


def test_instrument_id_to_slug_refuses_a_no_leg_id() -> None:
    # N2-1: the existing bijection is untouched -- it is a hard error for a
    # NO id, never a silent "same slug" answer, so every one of its 20+
    # existing callers stays exactly as blind to the NO leg as before.
    from breezy.adapters.polymarket_us.symbology import instrument_id_to_slug

    no_id = no_leg_instrument_id(SLUG)
    with pytest.raises(VenuePayloadError):
        instrument_id_to_slug(no_id)


# ---------------------------------------------------------------------------
# Catalog SQL alias collision guard
# ---------------------------------------------------------------------------


def test_catalog_sql_alias_mirrors_the_nautilus_sanitiser() -> None:
    no_id = no_leg_instrument_id("ab")
    # ``^`` -> ``_``, ``-``/``_`` already ``_``, then lower(); matches
    # ``parquet.py:_sanitize_sql_identifier`` (verified empirically against
    # the installed Nautilus catalog).
    assert catalog_sql_alias(no_id) == "ab_no_polymarket_us"
    assert catalog_sql_alias(slug_to_instrument_id("ab-no")) == "ab_no_polymarket_us"
    assert catalog_sql_alias(slug_to_instrument_id("ab_no")) == "ab_no_polymarket_us"


def test_distinct_ids_that_alias_to_the_same_catalog_table_are_refused() -> None:
    colliding = (
        no_leg_instrument_id("ab"),
        slug_to_instrument_id("ab-no"),
        slug_to_instrument_id("ab_no"),
    )
    with pytest.raises(VenuePayloadError):
        assert_catalog_aliases_are_unique(colliding)


def test_distinct_non_colliding_ids_are_accepted() -> None:
    non_colliding = (
        slug_to_instrument_id(SLUG),
        no_leg_instrument_id(SLUG),
        slug_to_instrument_id("tc-temp-laxhigh-2026-08-25-lt79f"),
    )
    assert_catalog_aliases_are_unique(non_colliding)  # must not raise


def test_the_same_id_repeated_is_not_a_collision() -> None:
    same = (slug_to_instrument_id(SLUG), slug_to_instrument_id(SLUG))
    assert_catalog_aliases_are_unique(same)  # must not raise
