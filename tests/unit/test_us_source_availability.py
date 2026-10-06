"""F13-C1 S1: the pure availability-interval rule."""

from __future__ import annotations

import datetime as dt

import pytest

from breezy.domain.forecast_point import MINIMUM_PUBLICATION_LAG_NS
from breezy.ingest.us_source_availability import (
    AvailabilityBasis,
    AvailabilityConfigError,
    LagPrereg,
    LagSample,
    Observation,
    available_at,
    freeze_lag,
    parse_last_modified_ns,
)

NS = 1_000_000_000
MIN = 60 * NS
HOUR = 60 * MIN
RUN = int(dt.datetime(2026, 10, 6, 0, 30, tzinfo=dt.UTC).timestamp()) * NS
PREREG = LagPrereg(
    sanity_floors_ns={"us-lamp-live": 20 * MIN, "us-pfm-afos": 0, "us-lav-iem": 20 * MIN},
    conservative_lags_ns={"us-lamp-live": 60 * MIN, "GFS_MOS": 5 * HOUR, "us-lav-iem": 60 * MIN},
)


def _http(offset_ns: int) -> str:
    moment = dt.datetime.fromtimestamp((RUN + offset_ns) / NS, tz=dt.UTC)
    return moment.strftime("%a, %d %b %Y %H:%M:%S GMT")


def test_measured_header_beyond_floor_is_the_anchor() -> None:
    ts, basis, miss = available_at(
        "us-lamp-live",
        "v1",
        RUN,
        Observation(last_modified=_http(25 * MIN), last_miss_ns=RUN + 20 * MIN),
        prereg=PREREG,
    )
    assert (ts, basis, miss) == (RUN + 25 * MIN, "measured_header", RUN + 20 * MIN)


def test_measured_header_below_floor_is_clamped_to_run_plus_floor() -> None:
    ts, basis, _ = available_at(
        "us-lamp-live", "v1", RUN, Observation(last_modified=_http(5 * MIN)), prereg=PREREG
    )
    assert ts == RUN + 20 * MIN
    assert basis == "measured_header"


@pytest.mark.parametrize("lm_offset_min", [10, 30, 61, 62, 120, 400])
def test_floor_rule_matches_nbp_available_at_ns_on_shared_fixtures(lm_offset_min: int) -> None:
    from breezy.persistence.nbp_derived_store import available_at_ns

    lm = _http(lm_offset_min * MIN)
    lm_ns = parse_last_modified_ns(lm)
    expected = available_at_ns(cycle_runtime_ns=RUN, last_modified_ns=lm_ns)

    ts, _, _ = available_at("NBM_NBP", "v5.0", RUN, Observation(last_modified=lm), prereg=PREREG)

    assert ts == expected
    assert MINIMUM_PUBLICATION_LAG_NS["NBM_NBP"] == 60 * MIN


def test_nbp_floor_comes_from_minimum_publication_lag_not_a_literal() -> None:
    ts, _, _ = available_at(
        "NBM_NBP", "v5.0", RUN, Observation(last_modified=_http(1)), prereg=PREREG
    )
    assert ts == RUN + MINIMUM_PUBLICATION_LAG_NS["NBM_NBP"]


def test_unmeasured_row_uses_conservative_lag_not_minimum_floor() -> None:
    ts, basis, miss = available_at("GFS_MOS", "v16", RUN, None, prereg=PREREG)

    assert ts == RUN + 5 * HOUR
    assert ts != RUN + MINIMUM_PUBLICATION_LAG_NS["GFS_MOS"]
    assert basis == AvailabilityBasis.NOMINAL_PLUS_CONSERVATIVE_LAG.value
    assert miss is None


def test_unmeasured_lamp_uses_prereg_conservative_lag() -> None:
    ts, basis, _ = available_at("us-lamp-live", "v1", RUN, Observation(), prereg=PREREG)
    assert (ts, basis) == (RUN + 60 * MIN, "nominal_plus_conservative_lag")


def test_no_key_is_added_to_minimum_publication_lag_ns() -> None:
    assert set(MINIMUM_PUBLICATION_LAG_NS) == {"NBM_NBS", "GFS_MOS", "NBM_NBP"}


def test_source_without_a_floor_in_the_prereg_is_refused() -> None:
    with pytest.raises(AvailabilityConfigError, match="no sanity floor"):
        available_at("us-lamp-mdl", "v1", RUN, None, prereg=PREREG)


def test_source_without_a_conservative_lag_is_refused_not_floored() -> None:
    prereg = LagPrereg(sanity_floors_ns={"us-pfm-afos": 0}, conservative_lags_ns={})
    with pytest.raises(AvailabilityConfigError, match="no conservative lag"):
        available_at("us-pfm-afos", "v1", RUN, None, prereg=prereg)


def test_conservative_lag_below_floor_is_refused() -> None:
    with pytest.raises(AvailabilityConfigError, match="below its sanity floor"):
        LagPrereg(sanity_floors_ns={"x": 30 * MIN}, conservative_lags_ns={"x": 10 * MIN})


def test_conservative_lag_below_measured_maximum_is_refused() -> None:
    with pytest.raises(AvailabilityConfigError, match="measured maximum"):
        LagPrereg(
            sanity_floors_ns={"x": 0},
            conservative_lags_ns={"x": 10 * MIN},
            measured_max_lag_ns={"x": 11 * MIN},
        )


def test_conservative_lag_at_or_above_gfs_mos_floor_is_accepted() -> None:
    LagPrereg(sanity_floors_ns={}, conservative_lags_ns={"GFS_MOS": 5 * HOUR})
    with pytest.raises(AvailabilityConfigError, match="below its sanity floor"):
        LagPrereg(sanity_floors_ns={}, conservative_lags_ns={"GFS_MOS": 30 * MIN})


def test_version_keyed_prereg_overrides_source_keyed() -> None:
    prereg = LagPrereg(
        sanity_floors_ns={"us-lamp-live": 20 * MIN},
        conservative_lags_ns={"us-lamp-live": 60 * MIN, ("us-lamp-live", "v2"): 90 * MIN},
    )
    assert available_at("us-lamp-live", "v2", RUN, None, prereg=prereg).ts == RUN + 90 * MIN
    assert available_at("us-lamp-live", "v1", RUN, None, prereg=prereg).ts == RUN + 60 * MIN


def test_pfm_wmo_header_time_is_exact_and_labelled_wmo_header() -> None:
    wmo = RUN + 3 * MIN
    ts, basis, _ = available_at(
        "us-pfm-afos", "v1", RUN, Observation(wmo_header_ns=wmo, host_tag="iem"), prereg=PREREG
    )
    assert ts == wmo
    assert basis == "wmo_header"


def test_mirror_host_tagged_in_basis() -> None:
    _, basis, _ = available_at(
        "us-lav-iem",
        "v1",
        RUN,
        Observation(last_modified=_http(30 * MIN), host_tag="iem"),
        prereg=PREREG,
    )
    assert basis == "measured_header@iem"
    assert "wmo_header" not in basis


def test_mirror_last_modified_is_never_labelled_wmo_header() -> None:
    for host in ("iem", "mdl", "s3", "nomads"):
        _, basis, _ = available_at(
            "us-lamp-mdl" if host == "mdl" else "us-lav-iem",
            "v1",
            RUN,
            Observation(last_modified=_http(30 * MIN), host_tag=host),
            prereg=LagPrereg(
                sanity_floors_ns={"us-lamp-mdl": 0, "us-lav-iem": 0}, conservative_lags_ns={}
            ),
        )
        assert basis == f"measured_header@{host}"


def test_first_seen_basis_and_miss_interval_recorded() -> None:
    first_seen = RUN + 36 * MIN
    miss = RUN + 30 * MIN
    ts, basis, got_miss = available_at(
        "us-lamp-live",
        "v1",
        RUN,
        Observation(first_seen_ns=first_seen, last_miss_ns=miss),
        prereg=PREREG,
    )
    assert (ts, basis, got_miss) == (first_seen, "first_seen", miss)
    assert got_miss is not None and got_miss < ts


@pytest.mark.parametrize("header", [None, "", "not a date", "Thu, 99 Foo 2026 25:61:61 GMT"])
def test_first_seen_fallback_when_last_modified_none_or_unparsable(header: str | None) -> None:
    first_seen = RUN + 40 * MIN
    ts, basis, _ = available_at(
        "us-lamp-live",
        "v1",
        RUN,
        Observation(first_seen_ns=first_seen, last_modified=header, host_tag="nomads"),
        prereg=PREREG,
    )
    assert ts == first_seen
    assert basis == "first_seen@nomads"


def test_first_seen_below_floor_is_clamped() -> None:
    ts, _, _ = available_at(
        "us-lamp-live", "v1", RUN, Observation(first_seen_ns=RUN + MIN), prereg=PREREG
    )
    assert ts == RUN + 20 * MIN


def test_available_at_never_precedes_run_ts_when_observed_is_earlier() -> None:
    ts, _, _ = available_at(
        "us-lamp-live", "v1", RUN, Observation(last_modified=_http(-3 * HOUR)), prereg=PREREG
    )
    assert ts >= RUN


@pytest.mark.parametrize("bad", [True, 1.5, "1"])
def test_non_int_timestamps_are_refused(bad: object) -> None:
    with pytest.raises(TypeError):
        available_at("us-lamp-live", "v1", RUN, Observation(first_seen_ns=bad), prereg=PREREG)  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        available_at("us-lamp-live", "v1", bad, None, prereg=PREREG)  # type: ignore[arg-type]


def test_empty_source_or_version_refused() -> None:
    with pytest.raises(ValueError, match="non-empty"):
        available_at("", "v1", RUN, None, prereg=PREREG)
    with pytest.raises(ValueError, match="non-empty"):
        available_at("us-lamp-live", "", RUN, None, prereg=PREREG)


def test_available_at_is_observed_header_never_assumed() -> None:
    measured, basis_m, _ = available_at(
        "us-lamp-live", "v1", RUN, Observation(last_modified=_http(26 * MIN)), prereg=PREREG
    )
    assumed, basis_a, _ = available_at("us-lamp-live", "v1", RUN, None, prereg=PREREG)
    assert measured == RUN + 26 * MIN
    assert assumed == RUN + 60 * MIN
    assert basis_m != basis_a


def test_parse_last_modified_ns_none_and_garbage() -> None:
    assert parse_last_modified_ns(None) is None
    assert parse_last_modified_ns("garbage") is None
    assert (
        parse_last_modified_ns("Tue, 06 Oct 2026 00:40:04 GMT")
        == int(dt.datetime(2026, 10, 6, 0, 40, 4, tzinfo=dt.UTC).timestamp()) * NS
    )


def test_late_rows_excluded_from_lag_freeze_maximum() -> None:
    samples = [
        LagSample("us-lamp-live", 8 * MIN, late=False),
        LagSample("us-lamp-live", 11 * MIN, late=False),
        LagSample("us-lamp-live", 95 * MIN, late=True),
        LagSample("us-pfm-afos", 500 * MIN, late=False),
    ]
    freeze = freeze_lag(samples, "us-lamp-live")

    assert freeze.max_lag_ns == 11 * MIN
    assert (freeze.uncensored_n, freeze.late_n) == (2, 1)


def test_lag_freeze_withheld_until_minimum_uncensored_samples() -> None:
    samples = [
        LagSample("us-lamp-live", 8 * MIN, late=False),
        LagSample("us-lamp-live", 9 * MIN, late=True),
    ]
    freeze = freeze_lag(samples, "us-lamp-live", min_uncensored=2)
    assert freeze.max_lag_ns is None
    assert (freeze.uncensored_n, freeze.late_n) == (1, 1)


def test_lag_freeze_all_late_has_no_maximum() -> None:
    freeze = freeze_lag([LagSample("s", 1, late=True)], "s")
    assert freeze.max_lag_ns is None
    assert freeze.late_n == 1


def test_lag_freeze_min_uncensored_must_be_positive() -> None:
    with pytest.raises(ValueError, match=">= 1"):
        freeze_lag([], "s", min_uncensored=0)
