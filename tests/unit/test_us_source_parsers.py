"""F13-C1-S3: LAMP and PFM text parsers (pure) -- H3 refusal posture (RED first).

Fixtures under `tests/fixtures/us_sources/` are SYNTHETIC (see their headers).
"""

from __future__ import annotations

import datetime as dt
import gzip
from collections.abc import Iterator
from pathlib import Path

import pytest

from breezy.ingest import lamp_parse
from breezy.ingest.http import TransportError
from breezy.ingest.lamp_parse import (
    LAMP_STATIONS,
    LampParseError,
    iter_gzip_lines,
    iter_lamp_blocks,
    iter_plain_lines,
    lamp_daily_max_f,
)
from breezy.ingest.pfm_parse import (
    PFM_POINT_MAP,
    PfmParseError,
    _issuance,
    parse_pfm_product,
    resolve_pfm_station,
)
from breezy.normalize.cli_parse import CliParseError
from breezy.normalize.sanity import CliSanityError

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "us_sources"
UTC = dt.UTC
PFM_REF = dt.datetime(2026, 10, 5, 19, 5, tzinfo=UTC)


def _fixture_text(name: str) -> str:
    raw = (FIXTURES / name).read_text(encoding="utf-8")
    return "".join(ln for ln in raw.splitlines(keepends=True) if not ln.startswith("#"))


def _lamp_lines(text: str | None = None) -> list[str]:
    body = text if text is not None else _fixture_text("lamp_lavtxt_synthetic_edge.txt")
    return body.splitlines()


def _lamp_blocks(text: str | None = None, **kw: int) -> dict[str, lamp_parse.LampBlock]:
    return {b.station: b for b in iter_lamp_blocks(_lamp_lines(text), **kw)}


def _knyc_block(tmp_row: str, utc_row: str | None = None) -> str:
    utc = utc_row or " UTC  02 03 04"
    return f" KNYC   GFS LAMP GUIDANCE   10/06/2026  0130 UTC\n{utc}\n{tmp_row}\n"


def _chunks(data: bytes, size: int = 4096) -> Iterator[bytes]:
    for i in range(0, len(data), size):
        yield data[i : i + size]


# --------------------------------------------------------------------- LAMP


def test_lamp_blocks_cover_closed_station_set_and_skip_others() -> None:
    blocks = _lamp_blocks()
    assert set(blocks) == set(LAMP_STATIONS) == {"KLAX", "KMDW", "KMIA", "KSFO", "KNYC"}
    knyc = blocks["KNYC"]
    assert knyc.issued_at == dt.datetime(2026, 10, 6, 1, 30, tzinfo=UTC)
    assert knyc.valid_times[0] == dt.datetime(2026, 10, 6, 2, 0, tzinfo=UTC)
    assert knyc.valid_times[-1] == dt.datetime(2026, 10, 7, 7, 0, tzinfo=UTC)
    assert len(knyc.tmp_f) == len(knyc.valid_times) == 30


def test_lamp_daily_max_uses_climate_day_lst_window() -> None:
    knyc = _lamp_blocks()["KNYC"]
    # KNYC LST (-5h) climate day 2026-10-06 = 05Z Oct 6 .. 04Z Oct 7 inclusive.
    assert lamp_daily_max_f(knyc, dt.date(2026, 10, 6), -5.0) == 70
    # Hours of the next LST day (05Z..07Z) must not leak into 10-06: shifting the
    # window to the LAX offset (-8h: 08Z Oct 6 .. 07Z Oct 7) changes membership.
    values = dict(zip(knyc.valid_times, knyc.tmp_f, strict=True))
    window = [
        v
        for t, v in values.items()
        if v is not None
        and dt.datetime(2026, 10, 6, 5, tzinfo=UTC) <= t <= dt.datetime(2026, 10, 7, 4, tzinfo=UTC)
    ]
    assert len(window) == 24
    assert lamp_daily_max_f(knyc, dt.date(2026, 10, 6), -5.0) == max(window)


def test_lamp_peak_window_not_covered_is_missing_not_imputed() -> None:
    knyc = _lamp_blocks()["KNYC"]
    # Oct 7 LST day needs through 04Z Oct 8, but the bulletin ends at 07Z Oct 7.
    assert lamp_daily_max_f(knyc, dt.date(2026, 10, 7), -5.0) is None
    # Oct 5 LST day starts 05Z Oct 5, before the first valid hour.
    assert lamp_daily_max_f(knyc, dt.date(2026, 10, 5), -5.0) is None


def test_lamp_one_missing_hour_in_window_is_missing() -> None:
    knyc = _lamp_blocks()["KNYC"]
    # Drop one interior hour: no imputation across the hole.
    keep = [i for i, t in enumerate(knyc.valid_times) if t.hour != 12 or t.day != 6]
    holed = lamp_parse.LampBlock(
        station=knyc.station,
        issued_at=knyc.issued_at,
        valid_times=tuple(knyc.valid_times[i] for i in keep),
        tmp_f=tuple(knyc.tmp_f[i] for i in keep),
    )
    assert lamp_daily_max_f(holed, dt.date(2026, 10, 6), -5.0) is None


REAL_LAMP = "lamp_lavtxt_real_20261005_2330z.txt"
LAMP_REAL_RUN = dt.datetime(2026, 10, 5, 23, 30, tzinfo=UTC)
#: station -> (TMP row as printed, fixture line of that row). Read by eye from the fixture.
REAL_LAMP_TMP = {
    "KNYC": [
        63,
        61,
        60,
        58,
        56,
        55,
        54,
        53,
        53,
        51,
        50,
        50,
        50,
        50,
        53,
        55,
        57,
        59,
        61,
        62,
        62,
        62,
        61,
        60,
        59,
    ],
    "KMIA": [
        83,
        83,
        83,
        82,
        82,
        82,
        81,
        81,
        80,
        79,
        79,
        80,
        81,
        83,
        84,
        86,
        87,
        88,
        89,
        88,
        85,
        84,
        83,
        82,
        81,
    ],
}


def test_lamp_real_fixture_blocks_hours_and_tmp_values() -> None:
    blocks = _lamp_blocks(_fixture_text(REAL_LAMP))
    assert set(blocks) == {"KLAX", "KMDW", "KMIA", "KSFO", "KNYC"}  # KNYG block skipped
    for station, expected in REAL_LAMP_TMP.items():
        block = blocks[station]
        assert block.issued_at == LAMP_REAL_RUN
        # UTC row `00 01 ... 23 00` (25 hourly columns) starts the hour after the 2330 run.
        assert block.valid_times[0] == dt.datetime(2026, 10, 6, 0, tzinfo=UTC)
        assert block.valid_times[-1] == dt.datetime(2026, 10, 7, 0, tzinfo=UTC)
        assert list(block.tmp_f) == expected  # KNYC: TMP row of the KNYC block; KMIA likewise


def test_lamp_real_fixture_has_no_fully_covered_climate_day() -> None:
    knyc = _lamp_blocks(_fixture_text(REAL_LAMP))["KNYC"]
    # 25 hourly columns, 00Z Oct 6 .. 00Z Oct 7: no 24-hour LST day (05Z..04Z) fits.
    assert lamp_daily_max_f(knyc, dt.date(2026, 10, 6), -5.0) is None


def test_lamp_missing_marker_999_is_missing_hour_not_refusal() -> None:
    text = _fixture_text(REAL_LAMP)
    row = " TMP  63 61 60 58 56 55 54 53 53 51 50 50 50 50 53 55 57 59 61 62 62 62 61 60 59"
    assert row in text
    holed = text.replace(row, row.replace(" 55 54", "999 54", 1))
    knyc = _lamp_blocks(holed)["KNYC"]
    assert knyc.tmp_f[5] is None  # the hour printed as 999
    assert knyc.tmp_f[4] == 56 and knyc.tmp_f[6] == 54
    # Needed hour missing -> day MISSING (not a refusal): extended-run edge block.
    edge = _fixture_text("lamp_lavtxt_synthetic_edge.txt")
    knyc_edge = _lamp_blocks(
        edge.replace(
            " TMP  50 50 50 51 53 55 57 60 63 65 67", " TMP  50 50 50 51 53 55 57 60999 65 67"
        )
    )["KNYC"]
    assert knyc_edge.tmp_f[8] is None
    assert lamp_daily_max_f(knyc_edge, dt.date(2026, 10, 6), -5.0) is None


def test_lamp_glued_negative_values_parse_by_fixed_width() -> None:
    block = _lamp_blocks(_knyc_block(" TMP  -5-12 -3"))["KNYC"]
    assert block.tmp_f == (-5, -12, -3)


def test_parser_refuses_row_out_of_physical_range() -> None:
    for bad in (" TMP  50 51 400", " TMP  50 51 -120"):
        with pytest.raises(LampParseError):
            _lamp_blocks(_knyc_block(bad))


def test_lamp_refuses_bad_token_missing_rows_and_count_mismatch() -> None:
    for text in (
        _knyc_block(" TMP  50 5x 52"),
        _knyc_block(" TMP  50 51"),
        " KNYC   GFS LAMP GUIDANCE   10/06/2026  0130 UTC\n UTC  02 03 04\n",
        " KNYC   GFS LAMP GUIDANCE   10/06/2026  0130 UTC\n TMP  50 51 52\n",
        _knyc_block(" TMP  50 51 52", utc_row=" UTC  02 04 05"),
        _knyc_block(" TMP  50 51 52", utc_row=" UTC  05 06 07"),
        _knyc_block(" TMP  50 51 52").replace("10/06/2026", "13/06/2026"),
    ):
        with pytest.raises(LampParseError):
            _lamp_blocks(text)


def test_bad_row_refuses_whole_run_never_skips() -> None:
    good = _fixture_text("lamp_lavtxt_synthetic_edge.txt")
    poisoned = good + _knyc_block(" TMP  50 51 999")
    with pytest.raises(LampParseError) as err:
        list(iter_lamp_blocks(_lamp_lines(poisoned)))
    assert err.value.reason  # carries a machine-readable reason for the alert path


def test_parser_refuses_non_utf8() -> None:
    with pytest.raises(LampParseError):
        list(iter_plain_lines([b" KNYC \xff\xfe GFS LAMP\n"]))
    with pytest.raises(PfmParseError):
        parse_pfm_product(b"FOUS51 KOKX 051901\n\xff\xfe\n", station="KNYC", reference_time=PFM_REF)


def test_parser_refuses_line_and_field_count_over_bound() -> None:
    text = _fixture_text("lamp_lavtxt_synthetic_edge.txt")
    with pytest.raises(LampParseError):
        _lamp_blocks(text, max_lines=10)
    wide = _knyc_block(" TMP  " + " ".join(["50"] * 200), " UTC  " + " ".join(["02"] * 200))
    with pytest.raises(LampParseError):
        _lamp_blocks(wide, max_fields=64)
    with pytest.raises(LampParseError):
        list(iter_plain_lines([b"x" * 5000], max_line_bytes=1024))
    with pytest.raises(PfmParseError):
        parse_pfm_product(
            b"FOUS51 KOKX 051901\n" + b"x" * 5000 + b"\n",
            station="KNYC",
            reference_time=PFM_REF,
        )
    many = b"FOUS51 KOKX 051901\n" + b"a\n" * 5000
    with pytest.raises(PfmParseError):
        parse_pfm_product(many, station="KNYC", reference_time=PFM_REF, max_lines=100)


def test_plain_line_reader_handles_crlf_and_unterminated_tail() -> None:
    assert list(iter_plain_lines([b"ab\r\ncd\n", b"ef"])) == ["ab", "cd", "ef"]


def test_gzip_line_reader_streams_concatenated_members() -> None:
    raw = gzip.compress(b"one\ntwo\n") + gzip.compress(b"three\n") + gzip.compress(b"four")
    got = list(
        iter_gzip_lines(
            _chunks(raw, 7),
            max_compressed_bytes=len(raw),
            max_decompressed_bytes=1024,
        )
    )
    assert got == ["one", "two", "three", "four"]


def test_gzip_bomb_trips_decompressed_cap_before_buffering() -> None:
    bomb = gzip.compress(b"0" * (64 * 1024 * 1024), compresslevel=9)
    assert len(bomb) < 200_000
    produced = 0
    with pytest.raises(LampParseError):
        for _ in iter_gzip_lines(
            iter([bomb]),
            max_compressed_bytes=len(bomb),
            max_decompressed_bytes=1_000_000,
            max_line_bytes=1_000_000_000,
        ):
            produced += 1
    assert produced == 0


def test_gzip_decompressed_cap_counts_across_many_lines() -> None:
    payload = gzip.compress(b"abcdefghi\n" * 1000)  # 10_000 bytes decompressed
    with pytest.raises(LampParseError):
        list(
            iter_gzip_lines(
                iter([payload]),
                max_compressed_bytes=len(payload),
                max_decompressed_bytes=5_000,
            )
        )
    ok = list(
        iter_gzip_lines(
            iter([payload]),
            max_compressed_bytes=len(payload),
            max_decompressed_bytes=10_000,
        )
    )
    assert len(ok) == 1000


def test_gzip_compressed_cap_refuses_oversize_input_without_reading_on() -> None:
    payload = gzip.compress(b"x\n" * 10)
    pulled = 0

    def source() -> Iterator[bytes]:
        nonlocal pulled
        for chunk in _chunks(payload * 50, 16):
            pulled += 1
            yield chunk

    with pytest.raises(LampParseError):
        list(
            iter_gzip_lines(
                source(),
                max_compressed_bytes=64,
                max_decompressed_bytes=10_000,
            )
        )
    assert pulled <= 6


def test_gzip_truncated_or_garbage_refused() -> None:
    good = gzip.compress(b"hello\nworld\n" * 100)
    for bad in (good[:-10], good + b"garbage", b"not gzip at all"):
        with pytest.raises(LampParseError):
            list(
                iter_gzip_lines(
                    iter([bad]),
                    max_compressed_bytes=len(bad),
                    max_decompressed_bytes=100_000,
                )
            )


def test_gzip_lamp_archive_end_to_end_matches_plain() -> None:
    text = _fixture_text("lamp_lavtxt_synthetic_edge.txt")
    raw = gzip.compress(text.encode()[:1000]) + gzip.compress(text.encode()[1000:])
    plain = [b.station for b in iter_lamp_blocks(iter_plain_lines([text.encode()]))]
    zipped = [
        b.station
        for b in iter_lamp_blocks(
            iter_gzip_lines(
                iter([raw]),
                max_compressed_bytes=len(raw),
                max_decompressed_bytes=10_000_000,
            )
        )
    ]
    assert plain == zipped and plain


# ---------------------------------------------------------------------- PFM

D = dt.date
#: station -> (fixture, issued_at, {forecast local date: MAX}). Expected values are read by eye
#: from the fixture; line numbers are of the fixture file as saved (comment header included).
#: Each table's `Min/Max` (3hrly) or `Max/Min` (6hrly) row holds the MAX under the UTC 00
#: column of the day's local date and the MIN under UTC 12.
REAL_PFM = {
    "KNYC": (
        "pfm_okx_real_20261006.txt",
        dt.datetime(2026, 10, 5, 19, 1, tzinfo=UTC),
        {
            D(2026, 10, 6): 63,  # line 24 (Min/Max 49 63 47 68 55): 63 under UTC 00
            D(2026, 10, 7): 68,  # line 24
            D(2026, 10, 8): 76,  # 6hrly table Max/Min line 40: 76 57 72 55 69 53 68 57 71
            D(2026, 10, 9): 72,
            D(2026, 10, 10): 69,
            D(2026, 10, 11): 68,
            D(2026, 10, 12): 71,
        },
    ),
    "KLAX": (
        "pfm_lox_real_20261006.txt",
        dt.datetime(2026, 10, 5, 21, 52, tzinfo=UTC),
        {
            D(2026, 10, 6): 97,  # line 24 (Min/Max 73 97 70 90 69)
            D(2026, 10, 7): 90,
            D(2026, 10, 8): 88,  # 6hrly Max/Min: 88 69 85 69 81 68 77 65 75
            D(2026, 10, 9): 85,
            D(2026, 10, 10): 81,
            D(2026, 10, 11): 77,
            D(2026, 10, 12): 75,
        },
    ),
    "KMDW": (
        "pfm_lot_real_20261006.txt",
        dt.datetime(2026, 10, 6, 1, 56, tzinfo=UTC),
        {
            D(2026, 10, 6): 73,  # line 24 (Min/Max 49 73 57 76 54)
            D(2026, 10, 7): 76,
            D(2026, 10, 8): 68,  # line 40 (Max/Min 68 50 67 50 72 58 75 57 69)
            D(2026, 10, 9): 67,
            D(2026, 10, 10): 72,
            D(2026, 10, 11): 75,
            D(2026, 10, 12): 69,
        },
    ),
    "KSFO": (
        "pfm_mtr_real_20261006.txt",
        dt.datetime(2026, 10, 6, 1, 0, tzinfo=UTC),
        {
            D(2026, 10, 6): 87,  # line 24 (Min/Max 61 87 61 84 59)
            D(2026, 10, 7): 84,
            D(2026, 10, 8): 82,  # line 40 (Max/Min 82 60 74 61 69 58 67 57 69)
            D(2026, 10, 9): 74,
            D(2026, 10, 10): 69,
            D(2026, 10, 11): 67,
            D(2026, 10, 12): 69,
        },
    ),
    "KMIA": (
        "pfm_mfl_real_20261006.txt",
        dt.datetime(2026, 10, 5, 18, 21, tzinfo=UTC),
        {
            D(2026, 10, 6): 89,  # line 24 (Min/Max 77 89 76 89 76)
            D(2026, 10, 7): 89,
            D(2026, 10, 8): 89,  # line 43 (Max/Min 89 76 89 78 89 78 89 78 89)
            D(2026, 10, 9): 89,
            D(2026, 10, 10): 89,
            D(2026, 10, 11): 89,
            D(2026, 10, 12): 89,
        },
    ),
}
POINT_BY_STATION = {
    "KNYC": ("OKX", "Central Park-New York NY", "NYZ072"),  # line 15-16 of the OKX fixture
    "KLAX": ("LOX", "Los Angeles Airport CA", "CAZ366"),
    "KMDW": ("LOT", "Chicago Midway Airport-Cook IL", "ILZ104"),
    "KSFO": ("MTR", "San Francisco Airport-San Mateo CA", "CAZ508"),
    "KMIA": ("MFL", "Miami-Miami Dade FL", "FLZ074"),
}


def _pfm_real(station: str) -> bytes:
    return _fixture_text(REAL_PFM[station][0]).encode()


@pytest.mark.parametrize("station", sorted(REAL_PFM))
def test_pfm_real_fixture_selects_station_point_and_max_by_day(station: str) -> None:
    _, issued, expected = REAL_PFM[station]
    point = parse_pfm_product(
        _pfm_real(station),
        station=station,
        reference_time=dt.datetime(2026, 10, 6, 2, 11, tzinfo=UTC),
    )
    wfo, name, zone = POINT_BY_STATION[station]
    assert (point.wfo, point.point_name, point.zone_code) == (wfo, name, zone)
    assert point.issued_at == issued
    assert dict(point.max_by_day) == expected


def test_pfm_parse_selects_station_point_and_max_row() -> None:
    """Edge: a decoy point shares zone NYZ072; selection is by (WFO, point name)."""
    raw = _fixture_text("pfm_okx_synthetic_edge.txt").encode()
    point = parse_pfm_product(raw, station="KNYC", reference_time=PFM_REF)
    assert point.point_name == "Central Park-New York NY"
    assert point.zone_code == "NYZ072"  # recorded, never a key
    assert dict(point.max_by_day)[D(2026, 10, 6)] == 63  # decoy block has Min 99, not this
    assert 99 not in dict(point.max_by_day).values()


def test_pfm_wmo_header_time_resolves_month_rollover() -> None:
    lines = ["FOUS51 KOKX 301901"]
    wfo, issued = _issuance(lines, dt.datetime(2026, 11, 1, 3, 0, tzinfo=UTC), dt.timedelta(days=2))
    assert (wfo, issued) == ("OKX", dt.datetime(2026, 10, 30, 19, 1, tzinfo=UTC))
    # A header whose own dates disagree with the product's date labels is refused.
    stale = _pfm_real("KNYC").replace(b"051901", b"301901")
    with pytest.raises(PfmParseError):
        parse_pfm_product(
            stale, station="KNYC", reference_time=dt.datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
        )


def test_pfm_unmapped_point_refused() -> None:
    assert set(PFM_POINT_MAP) == {"KNYC", "KLAX", "KMDW", "KSFO", "KMIA"}
    with pytest.raises(PfmParseError):
        resolve_pfm_station("OKX", "LaGuardia Airport-Queens NY")
    with pytest.raises(PfmParseError):
        resolve_pfm_station("LOT", "Central Park-New York NY")  # right name, wrong WFO
    assert resolve_pfm_station("OKX", "Central Park-New York NY") == "KNYC"
    with pytest.raises(PfmParseError):
        parse_pfm_product(_pfm_real("KNYC"), station="KJFK", reference_time=PFM_REF)
    raw = _pfm_real("KNYC").replace(b"Central Park-New York NY", b"Central Park-Elsewhere NY")
    with pytest.raises(PfmParseError):
        parse_pfm_product(raw, station="KNYC", reference_time=PFM_REF)


def _okx(mutate: tuple[bytes, bytes]) -> bytes:
    raw = _pfm_real("KNYC")
    assert mutate[0] in raw
    return raw.replace(*mutate)


def test_pfm_refuses_wfo_mismatch_duplicate_point_and_bad_rows() -> None:
    raw = _pfm_real("KNYC")
    with pytest.raises(PfmParseError):
        parse_pfm_product(raw.replace(b"KOKX", b"KLOT"), station="KNYC", reference_time=PFM_REF)
    with pytest.raises(PfmParseError):
        parse_pfm_product(raw + raw, station="KNYC", reference_time=PFM_REF)
    bad_rows = (
        (
            b"Min/Max                      49          63",
            b"Min/Max                      4x          63",
        ),
        (
            b"Min/Max                      49          63",
            b"Min/Max                     400          63",
        ),
        # a value under a column that is neither UTC 00 nor UTC 12
        (
            b"Min/Max                      49          63",
            b"Min/Max                         49       63",
        ),
        # a value with no column under it
        (
            b"Min/Max                      49          63",
            b"Min/Max                      49          63 5",
        ),
        # the table's UTC row removed
        (b"UTC 3hrly     21 00 03", b"XXX 3hrly     21 00 03"),
    )
    for mutate in bad_rows:
        with pytest.raises(PfmParseError):
            parse_pfm_product(_okx(mutate), station="KNYC", reference_time=PFM_REF)
    with pytest.raises(PfmParseError):
        parse_pfm_product(
            raw.replace(b"FOUS51 KOKX 051901", b"garbage"), station="KNYC", reference_time=PFM_REF
        )
    with pytest.raises(PfmParseError):  # no instant within max_age of the reference
        parse_pfm_product(raw, station="KNYC", reference_time=dt.datetime(2026, 12, 25, tzinfo=UTC))


def test_pfm_refuses_date_label_that_disagrees_with_its_column() -> None:
    mutate = (b"Tue 10/06/26            Wed 10/07/26", b"Tue 10/07/26            Wed 10/07/26")
    with pytest.raises(PfmParseError):
        parse_pfm_product(_okx(mutate), station="KNYC", reference_time=PFM_REF)


# -------------------------------------------------------- refusal taxonomy


def test_parser_and_revision_refusals_are_not_transport_error_subclasses() -> None:
    for cls in (LampParseError, PfmParseError):
        assert not issubclass(cls, TransportError)
        assert not issubclass(cls, CliParseError)
        assert not issubclass(cls, CliSanityError)
        assert cls.__module__.startswith("breezy.ingest.")
    assert not issubclass(LampParseError, PfmParseError)
    assert not issubclass(PfmParseError, LampParseError)
