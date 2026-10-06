"""F13-C1-S3: LAMP and PFM text parsers (pure) -- H3 refusal posture (RED first).

Fixtures under `tests/fixtures/us_sources/` are SYNTHETIC (see their headers).
"""

from __future__ import annotations

import datetime as dt
import gzip
import zlib
from collections.abc import Iterator
from pathlib import Path

import pytest

from breezy.ingest import lamp_parse, pfm_parse
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


def _tmp_block(values: list[int]) -> str:
    """A KNYC block of 30 hourly columns starting 02Z Oct 6 with the given TMP values."""
    hours = [(2 + i) % 24 for i in range(len(values))]
    utc = " UTC " + "".join(f"{h:3d}".replace(" ", " ") for h in hours)
    tmp = " TMP " + "".join(f"{v:3d}" for v in values)
    return f" KNYC   GFS LAMP GUIDANCE   10/06/2026  0130 UTC\n{utc}\n{tmp}\n"


def test_lamp_daily_max_uses_climate_day_lst_window() -> None:
    # Index i is valid at 02Z Oct 6 + i h. Decoys sit where only a WRONG offset looks:
    #   02Z Oct 6 (i=0)  99: before both the -5h and -8h windows
    #   06Z Oct 6 (i=4)  77: inside the -5h window (05Z..04Z), outside the -8h one (08Z..07Z)
    #   15Z Oct 6 (i=13) 70: inside both
    #   07Z Oct 7 (i=29) 95: inside the -8h window only (-5h ends 04Z Oct 7)
    values = [50] * 30
    values[0], values[4], values[13], values[29] = 99, 77, 70, 95
    block = _lamp_blocks(_tmp_block(values))["KNYC"]
    assert lamp_daily_max_f(block, dt.date(2026, 10, 6), -5.0) == 77
    assert lamp_daily_max_f(block, dt.date(2026, 10, 6), -8.0) == 95
    # The real-offset result must not equal what a -8h (wrong for KNYC) window gives.
    assert lamp_daily_max_f(block, dt.date(2026, 10, 6), -5.0) != lamp_daily_max_f(
        block, dt.date(2026, 10, 6), -8.0
    )


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
    for bad in (" TMP  50 51400", " TMP  50 51-99"):
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
    # A real bad value (out of the physical range), after five valid closed-set blocks.
    poisoned = good + _knyc_block(" TMP  50 51400", " UTC  03 04 05").replace("0130", "0230")
    with pytest.raises(LampParseError) as err:
        lamp_parse.parse_lamp_blocks(_lamp_lines(poisoned))
    assert err.value.reason == "tmp_out_of_range"
    # All-or-nothing: the collecting API returns nothing, so nothing valid is committed.
    result: list[lamp_parse.LampBlock] = []
    with pytest.raises(LampParseError):
        result.extend(lamp_parse.parse_lamp_blocks(_lamp_lines(poisoned)))
    assert result == []


def test_lazy_stream_yields_valid_blocks_before_the_bad_one_so_callers_must_drain() -> None:
    """Pins the documented contract: `iter_lamp_blocks` is lazy; persist only after a full drain."""
    good = _fixture_text("lamp_lavtxt_synthetic_edge.txt")
    poisoned = good + _knyc_block(" TMP  50 51400", " UTC  03 04 05").replace("0130", "0230")
    seen: list[str] = []
    with pytest.raises(LampParseError):
        for block in iter_lamp_blocks(_lamp_lines(poisoned)):
            seen.append(block.station)
    assert seen == ["KNYC", "KMIA", "KMDW", "KLAX", "KSFO"]


def test_lamp_refuses_header_minute_other_than_30() -> None:
    for minute in ("0100", "0115", "0145"):
        with pytest.raises(LampParseError) as err:
            _lamp_blocks(_knyc_block(" TMP  50 51 52").replace("0130", minute))
        assert err.value.reason == "run_minute_not_30"


def test_lamp_refuses_duplicate_station_run_in_one_stream() -> None:
    text = _knyc_block(" TMP  50 51 52") * 2
    with pytest.raises(LampParseError) as err:
        lamp_parse.parse_lamp_blocks(_lamp_lines(text))
    assert err.value.reason == "duplicate_block"
    # A different run of the same station is not a duplicate.
    other = (
        _knyc_block(" TMP  50 51 52")
        .replace("0130", "0230")
        .replace("UTC  02", "UTC  03")
        .replace("03 04", "04 05")
    )
    assert (
        len(lamp_parse.parse_lamp_blocks(_lamp_lines(_knyc_block(" TMP  50 51 52") + other))) == 2
    )


def test_lamp_blank_line_inside_a_block_ends_it_and_a_split_block_is_refused() -> None:
    """Pinned: a blank (or whitespace-only) line terminates the block; rows after it are
    not attached, so a TMP row cut off from its UTC row is a refusal, never a silent skip."""
    split = (
        " KNYC   GFS LAMP GUIDANCE   10/06/2026  0130 UTC\n UTC  02 03 04\n   \n TMP  50 51 52\n"
    )
    with pytest.raises(LampParseError) as err:
        _lamp_blocks(split)
    assert err.value.reason == "missing_row"
    # Extra rows after a blank belong to nothing and are ignored once both rows were seen.
    ok = _knyc_block(" TMP  50 51 52") + "   \n DPT  40 41 42\n"
    assert _lamp_blocks(ok)["KNYC"].tmp_f == (50, 51, 52)


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


class _CountingInflater:
    """Wraps a zlib decompressobj and records every byte it hands back."""

    produced = 0

    def __init__(self, real: object) -> None:
        self._real = real

    def decompress(self, data: bytes, max_length: int) -> bytes:
        out: bytes = self._real.decompress(data, max_length)  # type: ignore[attr-defined]
        type(self).produced += len(out)
        return out

    def __getattr__(self, name: str) -> object:
        return getattr(self._real, name)


def test_gzip_bomb_trips_decompressed_cap_before_buffering(monkeypatch: pytest.MonkeyPatch) -> None:
    real = zlib.decompressobj
    monkeypatch.setattr(zlib, "decompressobj", lambda *a, **k: _CountingInflater(real(*a, **k)))
    _CountingInflater.produced = 0
    bomb = gzip.compress(b"0" * (64 * 1024 * 1024), compresslevel=9)
    assert len(bomb) < 200_000
    cap, step = 10_000, 1024
    with pytest.raises(LampParseError) as err:
        list(
            iter_gzip_lines(
                iter([bomb]),
                max_compressed_bytes=len(bomb),
                max_decompressed_bytes=cap,
                max_line_bytes=1_000_000_000,
                inflate_step=step,
            )
        )
    assert err.value.reason == "decompressed_cap"
    # Inflated output never exceeds the cap by more than one step: 64 MiB never materialises.
    assert cap < _CountingInflater.produced <= cap + step


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


def test_gzip_truncated_second_member_after_complete_first_is_refused() -> None:
    first, second = gzip.compress(b"one\n" * 50), gzip.compress(b"two\n" * 5000)
    raw = first + second[:-6]
    with pytest.raises(LampParseError) as err:
        list(
            iter_gzip_lines(
                iter([raw]), max_compressed_bytes=len(raw), max_decompressed_bytes=1_000_000
            )
        )
    assert err.value.reason == "truncated_gzip"


def test_gzip_single_trailing_magic_byte_after_a_member_is_refused() -> None:
    raw = gzip.compress(b"one\n") + b"\x1f"
    with pytest.raises(LampParseError):
        list(
            iter_gzip_lines(
                iter([raw]), max_compressed_bytes=len(raw), max_decompressed_bytes=1_000_000
            )
        )


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


def _pfm_synthetic(
    wmo: str,
    first_label: str,
    local_hours: list[int],
    labels: dict[int, str],
    maxes: dict[int, int],
    offset: int = 5,
) -> bytes:
    """A minimal one-table PFM product in the real column layout (EST: UTC = local + 5)."""
    n = len(local_hours)
    width = 14 + 3 * n
    date = list("Date".ljust(width))
    date[14 : 14 + len(first_label)] = first_label
    for col, text in labels.items():
        date[14 + 3 * col : 14 + 3 * col + len(text)] = text
    extrema = list("Min/Max".ljust(width))
    for col, value in maxes.items():
        extrema[14 + 3 * col : 16 + 3 * col] = f"{value:2d}"
    rows = [
        "".join(date).rstrip(),
        "EST 3hrly".ljust(14) + " ".join(f"{h:02d}" for h in local_hours),
        "UTC 3hrly".ljust(14) + " ".join(f"{(h + offset) % 24:02d}" for h in local_hours),
        "",
        "".join(extrema).rstrip(),
    ]
    body = "\n".join(rows)
    return (
        f"\x01\n854 \n{wmo}\nPFMOKX\n\nPoint Forecast Matrices\n\n"
        f"NYZ072-060800-\nCentral Park-New York NY\n40.78N  73.97W Elev. 16 ft\n\n{body}\n$$\n"
    ).encode()


def test_pfm_yearless_label_year_is_nearest_the_issuance_across_new_year() -> None:
    # Issued 2027-01-01 01:01Z (20:01 EST Dec 31). First label has no year: Dec 31 of 2026.
    hours = [19, 22, 1, 4, 7, 10, 13, 16, 19, 22]  # UTC 00 columns at i=0 and i=8
    raw = _pfm_synthetic("FOUS51 KOKX 010101", "12/31", hours, {2: "Fri 01/01/27"}, {0: 40, 8: 38})
    point = parse_pfm_product(
        raw, station="KNYC", reference_time=dt.datetime(2027, 1, 1, 1, 30, tzinfo=UTC)
    )
    assert dict(point.max_by_day) == {D(2026, 12, 31): 40, D(2027, 1, 1): 38}


def test_pfm_yearless_label_on_dec_31_issuance_stays_in_the_issuance_year() -> None:
    hours = [19, 22, 1, 4, 7, 10, 13, 16, 19, 22]
    raw = _pfm_synthetic("FOUS51 KOKX 311901", "12/31", hours, {2: "Fri 01/01/27"}, {0: 41, 8: 37})
    point = parse_pfm_product(
        raw, station="KNYC", reference_time=dt.datetime(2026, 12, 31, 19, 30, tzinfo=UTC)
    )
    assert dict(point.max_by_day) == {D(2026, 12, 31): 41, D(2027, 1, 1): 37}


def test_pfm_refuses_a_date_label_far_from_the_issuance() -> None:
    hours = [19, 22, 1, 4, 7, 10, 13, 16, 19, 22]
    for label in ("11/30/26", "01/20/27"):  # -31 days and +20 days from 2026-12-31
        raw = _pfm_synthetic("FOUS51 KOKX 311901", label, hours, {}, {0: 41})
        with pytest.raises(PfmParseError):
            parse_pfm_product(
                raw, station="KNYC", reference_time=dt.datetime(2026, 12, 31, 19, 30, tzinfo=UTC)
            )


def test_pfm_refuses_oversize_raw_before_decoding() -> None:
    limit = pfm_parse.MAX_RAW_BYTES
    raw = _pfm_real("KNYC") + b" " * (limit + 1 - len(_pfm_real("KNYC")))
    assert len(raw) == limit + 1
    with pytest.raises(PfmParseError) as err:
        parse_pfm_product(raw, station="KNYC", reference_time=PFM_REF)
    assert err.value.reason == "raw_too_large"


def test_pfm_refuses_field_count_over_bound() -> None:
    hours = [(i * 3) % 24 for i in range(70)]
    raw = _pfm_synthetic("FOUS51 KOKX 311901", "12/31/26", hours, {}, {0: 41})
    with pytest.raises(PfmParseError) as err:
        parse_pfm_product(
            raw, station="KNYC", reference_time=dt.datetime(2026, 12, 31, 19, 30, tzinfo=UTC)
        )
    assert err.value.reason in {"too_many_fields", "hour_rows_too_wide"}


# -------------------------------------------------------- refusal taxonomy


def test_parser_and_revision_refusals_are_not_transport_error_subclasses() -> None:
    for cls in (LampParseError, PfmParseError):
        assert not issubclass(cls, TransportError)
        assert not issubclass(cls, CliParseError)
        assert not issubclass(cls, CliSanityError)
        assert cls.__module__.startswith("breezy.ingest.")
    assert not issubclass(LampParseError, PfmParseError)
    assert not issubclass(PfmParseError, LampParseError)


# ------------------------------------------- Pacific 09Z-grid cycle (B0-fix2 D2)

#: station -> (derived fixture, issued_at, {local date: MAX}). The raw refused products were never
#: retained, so these are DERIVED (see the fixture header): the Pacific 09Z-grid cycle ends its
#: 3hrly table on a Thursday 17 PDT, so the 6hrly table opens with a one-column block that has no
#: room for a date label.
PACIFIC_MORNING_PFM = {
    "KLAX": (
        "pfm_lox_derived_0900z_grid_20261006.txt",
        dt.datetime(2026, 10, 6, 11, 12, tzinfo=UTC),
        {
            D(2026, 10, 6): 88,
            D(2026, 10, 7): 90,
            D(2026, 10, 8): 84,
            D(2026, 10, 9): 82,
            D(2026, 10, 10): 80,
            D(2026, 10, 11): 79,
            D(2026, 10, 12): 77,
        },
    ),
    "KSFO": (
        "pfm_mtr_derived_0900z_grid_20261006.txt",
        dt.datetime(2026, 10, 6, 11, 10, tzinfo=UTC),
        {
            D(2026, 10, 6): 74,
            D(2026, 10, 7): 76,
            D(2026, 10, 8): 71,
            D(2026, 10, 9): 70,
            D(2026, 10, 10): 69,
            D(2026, 10, 11): 68,
            D(2026, 10, 12): 67,
        },
    ),
}


@pytest.mark.parametrize("station", sorted(PACIFIC_MORNING_PFM))
def test_pacific_evening_pfm_date_labels_parse(station: str) -> None:
    name, issued, expected = PACIFIC_MORNING_PFM[station]
    point = parse_pfm_product(
        _fixture_text(name).encode(),
        station=station,
        reference_time=issued + dt.timedelta(seconds=1),
    )
    assert point.issued_at == issued
    assert dict(point.max_by_day) == expected


def test_pacific_one_column_first_block_still_refuses_a_wrong_later_label() -> None:
    raw = _fixture_text(PACIFIC_MORNING_PFM["KLAX"][0]).encode()
    wrong = raw.replace(b"Sat 10/10/26", b"Sat 10/11/26")
    assert wrong != raw
    with pytest.raises(PfmParseError) as err:
        parse_pfm_product(wrong, station="KLAX", reference_time=PACIFIC_MORNING_PFM["KLAX"][1])
    assert err.value.reason == "date_label_mismatch"
