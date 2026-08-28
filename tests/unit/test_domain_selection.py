"""Unit tests for the supersession selector.

§4.3: corrections are new records with a strictly later `ts_init`, never a rewrite.
The reader therefore selects max `(is_final, ts_init, revision_seq)` per
`(station, climate_day)`: only the final CLI is settlement-grade, so a final
outranks a preliminary however late the preliminary arrives, while arrival still
orders within a finality class. The `as_of_ts_init` bound is applied first, so
finality precedence decides only among what was known at that instant.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any

import pytest

from breezy.domain.nws_climate_day import CLIMATE_DAY_SCHEMA_VERSION, NwsClimateDay
from breezy.domain.selection import climate_day_key, latest_by_climate_day, select_climate_day

_DAY_END_NS = int(dt.datetime(2026, 8, 23, 5, 0, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_BASE_NS = int(dt.datetime(2026, 8, 23, 6, 31, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
_SHA = hashlib.sha256(b"seed").hexdigest()


def make_climate_day(**overrides: Any) -> NwsClimateDay:
    kwargs: dict[str, Any] = {
        "station": "NYC",
        "climate_day": dt.date(2026, 8, 22),
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
        "issuance_time_ns": _BASE_NS - 240_000_000_000,
        "retrieved_at_ns": _BASE_NS,
        "parser_version": "pyiem==1.27.0",
        "registry_version": "sites.toml@1",
        "raw_sha256": _SHA,
        "source_channel": "api.weather.gov",
        "schema_version": CLIMATE_DAY_SCHEMA_VERSION,
        "ts_event": _DAY_END_NS,
    }
    kwargs.update(overrides)
    return NwsClimateDay(**kwargs)


def test_key_is_station_and_climate_day() -> None:
    assert climate_day_key(make_climate_day()) == ("NYC", dt.date(2026, 8, 22))


def test_latest_wins_regardless_of_input_order() -> None:
    first = make_climate_day(tmax_f=84)
    correction = make_climate_day(
        tmax_f=85,
        revision_seq=2,
        correction_flag=True,
        retrieved_at_ns=_BASE_NS + 86_400_000_000_000,
    )

    for records in ([first, correction], [correction, first]):
        selected = latest_by_climate_day(records)
        assert selected[("NYC", dt.date(2026, 8, 22))].tmax_f == 85


def test_stations_are_selected_independently() -> None:
    nyc = make_climate_day(station="NYC", tmax_f=84)
    mdw = make_climate_day(station="MDW", issuing_office="KLOT", tmax_f=91)

    selected = latest_by_climate_day([nyc, mdw])
    assert selected[("NYC", dt.date(2026, 8, 22))].tmax_f == 84
    assert selected[("MDW", dt.date(2026, 8, 22))].tmax_f == 91


def test_days_are_selected_independently() -> None:
    day22 = make_climate_day(climate_day=dt.date(2026, 8, 22), tmax_f=84)
    day23 = make_climate_day(
        climate_day=dt.date(2026, 8, 23),
        tmax_f=88,
        retrieved_at_ns=_BASE_NS + 86_400_000_000_000,
    )

    selected = latest_by_climate_day([day22, day23])
    assert selected[("NYC", dt.date(2026, 8, 22))].tmax_f == 84
    assert selected[("NYC", dt.date(2026, 8, 23))].tmax_f == 88


def test_equal_ts_init_breaks_the_tie_on_revision_seq() -> None:
    original = make_climate_day(tmax_f=84, revision_seq=1)
    same_instant = make_climate_day(tmax_f=85, revision_seq=2)

    selected = latest_by_climate_day([same_instant, original])
    assert selected[("NYC", dt.date(2026, 8, 22))].tmax_f == 85


def test_as_of_bound_reproduces_the_pre_correction_answer() -> None:
    """§4.4: post-hoc audit needs 'what would the resolver have said at time T'."""
    first = make_climate_day(tmax_f=84)
    correction = make_climate_day(
        tmax_f=85,
        revision_seq=2,
        correction_flag=True,
        retrieved_at_ns=_BASE_NS + 86_400_000_000_000,
    )
    records = [first, correction]

    current = select_climate_day(records, "NYC", dt.date(2026, 8, 22))
    assert current is not None
    assert current.tmax_f == 85
    as_of = select_climate_day(
        records,
        "NYC",
        dt.date(2026, 8, 22),
        as_of_ts_init=_BASE_NS + 3_600_000_000_000,
    )
    assert as_of is not None
    assert as_of.tmax_f == 84


def test_as_of_bound_is_inclusive() -> None:
    record = make_climate_day()
    assert (
        select_climate_day(
            [record],
            "NYC",
            dt.date(2026, 8, 22),
            as_of_ts_init=_BASE_NS,
        )
        is record
    )


def test_as_of_before_any_arrival_selects_nothing() -> None:
    record = make_climate_day()
    assert (
        select_climate_day([record], "NYC", dt.date(2026, 8, 22), as_of_ts_init=_BASE_NS - 1)
        is None
    )


def test_unknown_key_selects_nothing() -> None:
    assert select_climate_day([make_climate_day()], "LAX", dt.date(2026, 8, 22)) is None


def test_empty_input_selects_nothing() -> None:
    assert latest_by_climate_day([]) == {}


def test_custom_data_wrappers_are_rejected_with_a_pointed_message() -> None:
    """`catalog.query`/`custom_data` return `CustomData`; callers must unwrap `.data`."""
    from nautilus_trader.model.data import CustomData, DataType

    wrapped = CustomData(DataType(NwsClimateDay), make_climate_day())
    with pytest.raises(TypeError, match="CustomData"):
        latest_by_climate_day([wrapped])


# -- finality precedence --------------------------------------------------------------------


_PRELIM_NS = int(dt.datetime(2026, 8, 22, 20, 50, tzinfo=dt.UTC).timestamp() * 1_000_000_000)
"""~4:50 PM EDT on the climate day: when the preliminary CLI is actually polled."""

_BACKFILL_NS = _BASE_NS + 7 * 86_400_000_000_000
"""A Phase-2 IEM/AFOS backfill re-fetches ~7 days of products and stamps `now`."""


def make_preliminary(**overrides: Any) -> NwsClimateDay:
    """A preliminary CLI: the ~4:44 PM issuance, never settlement-grade."""
    kwargs: dict[str, Any] = {
        "is_final": False,
        "tmax_f": 82,
        "issuance_time_ns": _PRELIM_NS - 360_000_000_000,
        "retrieved_at_ns": _PRELIM_NS,
        "ts_event": _PRELIM_NS - 360_000_000_000,
    }
    kwargs.update(overrides)
    return make_climate_day(**kwargs)


def test_backfilled_preliminary_never_supersedes_a_final() -> None:
    """A final outranks a preliminary regardless of arrival order.

    The Phase-2 backfill scenario: the final for the climate day is already on
    disk, then a re-fetch of the same day's preliminary lands with
    ``ts_init = retrieved_at_ns = now``, strictly later than the final's. Ordering
    on arrival alone would settle on a value NWS never finalized.
    """
    final = make_climate_day(tmax_f=84, is_final=True, retrieved_at_ns=_BASE_NS)
    backfilled_preliminary = make_preliminary(tmax_f=82, retrieved_at_ns=_BACKFILL_NS)

    assert backfilled_preliminary.ts_init > final.ts_init

    for records in ([final, backfilled_preliminary], [backfilled_preliminary, final]):
        current = select_climate_day(records, "NYC", dt.date(2026, 8, 22))
        assert current is not None
        assert current.is_final is True
        assert current.tmax_f == 84


def test_backfilled_preliminary_never_supersedes_a_final_even_with_higher_revision_seq() -> None:
    """`revision_seq` is per `(station, climate_day)`, so a preliminary can carry a high one."""
    final = make_climate_day(tmax_f=84, is_final=True, revision_seq=2, retrieved_at_ns=_BASE_NS)
    preliminary = make_preliminary(tmax_f=82, revision_seq=9, retrieved_at_ns=_BACKFILL_NS)

    current = select_climate_day([final, preliminary], "NYC", dt.date(2026, 8, 22))
    assert current is not None
    assert current.is_final is True
    assert current.tmax_f == 84


def test_correction_to_a_final_still_supersedes() -> None:
    """The correction path is why max-`ts_init` exists; finality must not break it."""
    final = make_climate_day(tmax_f=84, is_final=True, retrieved_at_ns=_BASE_NS)
    corrected_final = make_climate_day(
        tmax_f=85,
        is_final=True,
        revision_seq=2,
        correction_flag=True,
        retrieved_at_ns=_BASE_NS + 86_400_000_000_000,
    )

    for records in ([final, corrected_final], [corrected_final, final]):
        current = select_climate_day(records, "NYC", dt.date(2026, 8, 22))
        assert current is not None
        assert current.tmax_f == 85
        assert current.revision_seq == 2


def test_as_of_before_the_final_still_returns_the_preliminary() -> None:
    """Point-in-time correctness: bound FIRST, then choose within what was known.

    At 17:00 local on the climate day the preliminary is genuinely all Breezy
    knew, so it is the correct answer for that instant. "A final always wins" is
    a statement about the candidate set *after* the ``as_of_ts_init`` filter, not
    about the whole record set.
    """
    preliminary = make_preliminary(tmax_f=82, retrieved_at_ns=_PRELIM_NS)
    final = make_climate_day(tmax_f=84, is_final=True, retrieved_at_ns=_BASE_NS)
    records = [preliminary, final]

    as_of_that_afternoon = select_climate_day(
        records,
        "NYC",
        dt.date(2026, 8, 22),
        as_of_ts_init=_PRELIM_NS + 600_000_000_000,
    )
    assert as_of_that_afternoon is not None
    assert as_of_that_afternoon.is_final is False
    assert as_of_that_afternoon.tmax_f == 82

    # Unbounded, and as of any instant at or after the final's arrival, the final wins.
    for as_of in (None, _BASE_NS, _BACKFILL_NS):
        current = select_climate_day(records, "NYC", dt.date(2026, 8, 22), as_of_ts_init=as_of)
        assert current is not None
        assert current.is_final is True
        assert current.tmax_f == 84


def test_as_of_before_the_final_still_returns_the_preliminary_with_backfill_present() -> None:
    """The as-of answer must not be perturbed by records that arrived later.

    A backfilled preliminary stamped a week after the fact is excluded by the
    bound, so an audit of the afternoon still sees the original preliminary.
    """
    preliminary = make_preliminary(tmax_f=82, retrieved_at_ns=_PRELIM_NS)
    final = make_climate_day(tmax_f=84, is_final=True, retrieved_at_ns=_BASE_NS)
    backfilled_preliminary = make_preliminary(tmax_f=83, retrieved_at_ns=_BACKFILL_NS)

    as_of_that_afternoon = select_climate_day(
        [preliminary, final, backfilled_preliminary],
        "NYC",
        dt.date(2026, 8, 22),
        as_of_ts_init=_PRELIM_NS + 600_000_000_000,
    )
    assert as_of_that_afternoon is not None
    assert as_of_that_afternoon.is_final is False
    assert as_of_that_afternoon.tmax_f == 82


def test_later_preliminary_wins_when_no_final_exists() -> None:
    """Before any final arrives, the preliminaries order among themselves by arrival."""
    first = make_preliminary(tmax_f=82, retrieved_at_ns=_PRELIM_NS)
    reissued = make_preliminary(
        tmax_f=83,
        revision_seq=2,
        correction_flag=True,
        retrieved_at_ns=_PRELIM_NS + 1_800_000_000_000,
    )

    for records in ([first, reissued], [reissued, first]):
        current = select_climate_day(records, "NYC", dt.date(2026, 8, 22))
        assert current is not None
        assert current.is_final is False
        assert current.tmax_f == 83


def test_equal_ts_init_prefers_the_final_over_the_preliminary() -> None:
    """One poll can return the preliminary and the final together."""
    preliminary = make_preliminary(tmax_f=82, revision_seq=2, retrieved_at_ns=_BASE_NS)
    final = make_climate_day(tmax_f=84, is_final=True, revision_seq=1, retrieved_at_ns=_BASE_NS)

    for records in ([preliminary, final], [final, preliminary]):
        current = select_climate_day(records, "NYC", dt.date(2026, 8, 22))
        assert current is not None
        assert current.is_final is True


def test_finality_precedence_is_scoped_to_one_climate_day() -> None:
    """A final for one day must not shadow the only record another day has."""
    final_22 = make_climate_day(
        climate_day=dt.date(2026, 8, 22),
        tmax_f=84,
        is_final=True,
        retrieved_at_ns=_BASE_NS,
    )
    preliminary_23 = make_preliminary(
        climate_day=dt.date(2026, 8, 23),
        tmax_f=88,
        retrieved_at_ns=_BASE_NS + 50_400_000_000_000,
    )

    selected = latest_by_climate_day([final_22, preliminary_23])
    assert selected[("NYC", dt.date(2026, 8, 22))].tmax_f == 84
    assert selected[("NYC", dt.date(2026, 8, 23))].tmax_f == 88
    assert selected[("NYC", dt.date(2026, 8, 23))].is_final is False
