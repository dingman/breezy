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
    body = text if text is not None else _fixture_text("lamp_lavtxt_synthetic.txt")
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
        if dt.datetime(2026, 10, 6, 5, tzinfo=UTC) <= t <= dt.datetime(2026, 10, 7, 4, tzinfo=UTC)
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
    good = _fixture_text("lamp_lavtxt_synthetic.txt")
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
    text = _fixture_text("lamp_lavtxt_synthetic.txt")
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
    text = _fixture_text("lamp_lavtxt_synthetic.txt")
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


def _pfm_bytes() -> bytes:
    return _fixture_text("pfm_okx_synthetic.txt").encode()


def test_pfm_parse_selects_station_point_and_max_row() -> None:
    point = parse_pfm_product(_pfm_bytes(), station="KNYC", reference_time=PFM_REF)
    assert point.station == "KNYC"
    assert point.wfo == "OKX"
    assert point.point_name == "Central Park-New York NY"
    assert point.zone_code == "NYZ072"  # recorded, never a key
    assert point.issued_at == dt.datetime(2026, 10, 5, 19, 1, tzinfo=UTC)
    assert point.max_f == (74, 72, 70)  # not Newark's 81, not Brooklyn's 73, not MIN


def test_pfm_wmo_header_time_resolves_month_rollover() -> None:
    raw = _pfm_bytes().replace(b"051901", b"301901")
    ref = dt.datetime(2026, 11, 1, 3, 0, tzinfo=UTC)
    point = parse_pfm_product(raw, station="KNYC", reference_time=ref)
    assert point.issued_at == dt.datetime(2026, 10, 30, 19, 1, tzinfo=UTC)


def test_pfm_unmapped_point_refused() -> None:
    assert set(PFM_POINT_MAP) == {"KNYC", "KLAX", "KMDW", "KSFO", "KMIA"}
    with pytest.raises(PfmParseError):
        resolve_pfm_station("OKX", "Brooklyn-New York NY")
    with pytest.raises(PfmParseError):
        resolve_pfm_station("LOT", "Central Park-New York NY")  # right name, wrong WFO
    assert resolve_pfm_station("OKX", "Central Park-New York NY") == "KNYC"
    with pytest.raises(PfmParseError):
        parse_pfm_product(_pfm_bytes(), station="KJFK", reference_time=PFM_REF)
    # Mapped station, but its point is absent from the product.
    raw = _pfm_bytes().replace(b"Central Park-New York NY", b"Central Park-Elsewhere NY")
    with pytest.raises(PfmParseError):
        parse_pfm_product(raw, station="KNYC", reference_time=PFM_REF)


def test_pfm_refuses_wfo_mismatch_duplicate_point_and_bad_rows() -> None:
    raw = _pfm_bytes()
    with pytest.raises(PfmParseError):
        parse_pfm_product(raw.replace(b"KOKX", b"KLOT"), station="KNYC", reference_time=PFM_REF)
    dup = (
        raw
        + b"\nNYZ072-060800-\nCentral Park-New York NY\n"
        + b"40.78N 73.97W Elev. 154 ft\nMAX           74\n$$\n"
    )
    with pytest.raises(PfmParseError):
        parse_pfm_product(dup, station="KNYC", reference_time=PFM_REF)
    for bad in (
        b"MAX           74        7x        70",
        b"MAX           74        400       70",
        b"MAX",
    ):
        mutated = raw.replace(b"MAX           74        72        70", bad)
        with pytest.raises(PfmParseError):
            parse_pfm_product(mutated, station="KNYC", reference_time=PFM_REF)
    with pytest.raises(PfmParseError):
        parse_pfm_product(
            raw.replace(b"FOUS51 KOKX 051901", b"garbage"), station="KNYC", reference_time=PFM_REF
        )
    # Day-of-month with no instant at or before the reference in the last ~month.
    with pytest.raises(PfmParseError):
        parse_pfm_product(raw, station="KNYC", reference_time=dt.datetime(2026, 12, 25, tzinfo=UTC))


# -------------------------------------------------------- refusal taxonomy


def test_parser_and_revision_refusals_are_not_transport_error_subclasses() -> None:
    for cls in (LampParseError, PfmParseError):
        assert not issubclass(cls, TransportError)
        assert not issubclass(cls, CliParseError)
        assert not issubclass(cls, CliSanityError)
        assert cls.__module__.startswith("breezy.ingest.")
    assert not issubclass(LampParseError, PfmParseError)
    assert not issubclass(PfmParseError, LampParseError)
