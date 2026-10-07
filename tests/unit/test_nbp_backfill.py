"""SL-4: the NBM NBP historical backfill script.

No test here opens a real socket -- every fetch is a `_FakeTransport` (never
`NbmQuantileTransport` itself, whose own transport behaviour is already
covered by `test_nbm_quantile_transport.py`). Real fixture bodies from
`tests/fixtures/nbm/` are used as the bulletin TEXT a fake fetch returns, so
the parser and the derived-row construction run against real captures.
"""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path

import pyarrow.parquet as pq
import pytest

from breezy.ingest.nbm_quantile_parse import NbpBulletinDriftError
from breezy.ingest.nbm_quantile_transport import (
    BothHostsFailedError,
    NbmQuantileFetchError,
    NbmQuantileFetchResult,
)
from breezy.persistence.nbp_derived_store import (
    NBP_DERIVED_SCHEMA,
    DerivedNbpRow,
    available_at_ns,
    dedupe_rows,
    load_failure_ledger,
    load_manifest,
    manifest_key,
    read_partition,
    write_partition,
)
from scripts.analysis.nbp_backfill import (
    BackfillPlanItem,
    build_plan,
    derive_rows_for_bulletin,
    main,
    run_backfill,
)

_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "nbm"


def _fixture_text(name: str) -> str:
    return (_FIXTURE_DIR / name).read_text(encoding="utf-8")


class _AsyncResultOrRaise:
    """Awaitable that returns a canned result or raises a canned exception."""

    def __init__(self, *, result: NbmQuantileFetchResult | None, error: Exception | None) -> None:
        self._result = result
        self._error = error

    def __await__(self):  # type: ignore[no-untyped-def]
        async def _run() -> NbmQuantileFetchResult:
            if self._error is not None:
                raise self._error
            assert self._result is not None
            return self._result

        return _run().__await__()


class _FakeTransport:
    """Keyed by (date, hour); raises `AssertionError` for any un-programmed
    call -- so a resumed (skipped) item that reaches the network is caught."""

    def __init__(self) -> None:
        self._by_key: dict[tuple[dt.date, int], NbmQuantileFetchResult] = {}
        self._errors: dict[tuple[dt.date, int], Exception] = {}
        self.calls: list[tuple[dt.date, int]] = []

    def program_result(
        self, cycle_date: dt.date, cycle_hour: int, result: NbmQuantileFetchResult
    ) -> None:
        self._by_key[(cycle_date, cycle_hour)] = result

    def program_error(self, cycle_date: dt.date, cycle_hour: int, error: Exception) -> None:
        self._errors[(cycle_date, cycle_hour)] = error

    def fetch_nbp_bulletin(self, *, cycle_date: dt.date, cycle_hour: int) -> _AsyncResultOrRaise:
        self.calls.append((cycle_date, cycle_hour))
        key = (cycle_date, cycle_hour)
        if key in self._errors:
            return _AsyncResultOrRaise(result=None, error=self._errors[key])
        if key not in self._by_key:
            raise AssertionError(f"un-programmed fetch for {key}")
        return _AsyncResultOrRaise(result=self._by_key[key], error=None)


class _FakeRunner:
    """Mirrors the `asyncio.Runner.run` surface `run_backfill` calls."""

    def run(self, awaitable):  # type: ignore[no-untyped-def]
        coro = awaitable.__await__()
        try:
            coro.send(None)
        except StopIteration as exc:
            return exc.value
        raise AssertionError("fake awaitable did not complete synchronously")


def _clock() -> Callable[[], int]:
    counter = {"n": 1_700_000_000_000_000_000}

    def _tick() -> int:
        counter["n"] += 1
        return counter["n"]

    return _tick


def _result(
    *,
    text: str,
    source_host: str = "noaa-nbm-grib2-pds.s3.amazonaws.com",
    last_modified: str | None = "Mon, 28 Sep 2026 14:03:18 GMT",
    fetched_at_ns: int = 1_759_000_000_000_000_000,
    raw_sha256: str = "a" * 64,
) -> NbmQuantileFetchResult:
    return NbmQuantileFetchResult(
        text=text,
        source_host=source_host,
        last_modified=last_modified,
        fetched_at_ns=fetched_at_ns,
        raw_sha256=raw_sha256,
        raw_bytes=len(text.encode("utf-8")),
    )


def _row(**overrides: object) -> DerivedNbpRow:
    base: dict[str, object] = {
        "station": "KLAX",
        "variable": "TXN_Q50",
        "cycle_runtime_ns": 1_759_000_000_000_000_000,
        "valid_start_ns": 1_759_100_000_000_000_000,
        "valid_end_ns": 1_759_100_000_000_000_000,
        "value_f": 68.0,
        "absence_reason": None,
        "header_model_version": "5.0",
        "nbm_version_era": "v5.0",
        "version_break_mismatch": False,
        "available_at_ns": 1_759_003_600_000_000_000,
        "last_modified": "Mon, 28 Sep 2026 14:03:18 GMT",
        "source_host": "noaa-nbm-grib2-pds.s3.amazonaws.com",
        "raw_sha256": "a" * 64,
        "fetched_at_ns": 1_759_000_100_000_000_000,
    }
    base.update(overrides)
    return DerivedNbpRow(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 1. Resume skips completed (date, cycle) pairs.
# ---------------------------------------------------------------------------


def test_resume_skips_a_pair_already_in_the_manifest(tmp_path: Path) -> None:
    output_dir = tmp_path / "nbp"
    t13 = _fixture_text("nbptx_t13z_excerpt.txt")
    t19 = _fixture_text("nbptx_t19z_excerpt.txt")

    transport = _FakeTransport()
    transport.program_result(dt.date(2026, 9, 28), 13, _result(text=t13))
    transport.program_result(dt.date(2026, 9, 28), 19, _result(text=t19, raw_sha256="b" * 64))

    plan = build_plan(start=dt.date(2026, 9, 28), end=dt.date(2026, 9, 28), cycles=(13, 19))

    first = run_backfill(
        plan=plan,
        output_dir=output_dir,
        transport=transport,  # type: ignore[arg-type]
        runner=_FakeRunner(),  # type: ignore[arg-type]
        progress=lambda _m: None,
        clock=_clock(),
        dry_run=False,
    )
    assert first.written == 2
    assert transport.calls == [(dt.date(2026, 9, 28), 13), (dt.date(2026, 9, 28), 19)]

    # Second run over the SAME plan must not re-fetch either pair.
    transport.calls.clear()
    second = run_backfill(
        plan=plan,
        output_dir=output_dir,
        transport=transport,  # type: ignore[arg-type]
        runner=_FakeRunner(),  # type: ignore[arg-type]
        progress=lambda _m: None,
        clock=_clock(),
        dry_run=False,
    )
    assert second.written == 0
    assert second.skipped == 2
    assert transport.calls == []

    manifest = load_manifest(output_dir)
    assert manifest_key(dt.date(2026, 9, 28), 13) in manifest
    assert manifest_key(dt.date(2026, 9, 28), 19) in manifest


# ---------------------------------------------------------------------------
# 2. Dedupe: retransmission / identical-sha collapse / deterministic tie.
# ---------------------------------------------------------------------------


def test_dedupe_a_retransmission_with_a_newer_last_modified_wins() -> None:
    older = _row(raw_sha256="a" * 64, last_modified="Mon, 28 Sep 2026 14:00:00 GMT")
    newer = _row(raw_sha256="b" * 64, last_modified="Mon, 28 Sep 2026 15:00:00 GMT")

    kept, log = dedupe_rows([older, newer])

    assert kept == (newer,)
    assert log.kept == 1
    assert log.retransmissions_resolved == 1
    assert log.collapsed_identical_sha == 0
    assert log.ties_resolved_by_sha == 0


def test_dedupe_an_identical_sha_duplicate_collapses_without_counting_as_a_retransmission() -> None:
    first = _row(raw_sha256="c" * 64, last_modified="Mon, 28 Sep 2026 14:00:00 GMT")
    refetch = _row(raw_sha256="c" * 64, last_modified="Mon, 28 Sep 2026 14:00:00 GMT")

    kept, log = dedupe_rows([first, refetch])

    assert kept == (first,)
    assert log.kept == 1
    assert log.collapsed_identical_sha == 1
    assert log.retransmissions_resolved == 0
    assert log.ties_resolved_by_sha == 0


def test_dedupe_a_last_modified_tie_resolves_deterministically_by_sha() -> None:
    same_lm = "Mon, 28 Sep 2026 14:00:00 GMT"
    low_sha = _row(raw_sha256="1" * 64, last_modified=same_lm)
    high_sha = _row(raw_sha256="9" * 64, last_modified=same_lm)

    kept_forward, log_forward = dedupe_rows([low_sha, high_sha])
    kept_reversed, log_reversed = dedupe_rows([high_sha, low_sha])

    assert kept_forward == (high_sha,)
    assert kept_reversed == (high_sha,)
    assert log_forward.ties_resolved_by_sha == 1
    assert log_reversed.ties_resolved_by_sha == 1


def test_dedupe_two_missing_last_modified_headers_still_tie_break_by_sha() -> None:
    low = _row(raw_sha256="1" * 64, last_modified=None)
    high = _row(raw_sha256="9" * 64, last_modified=None)

    kept, log = dedupe_rows([low, high])

    assert kept == (high,)
    assert log.ties_resolved_by_sha == 1


# ---------------------------------------------------------------------------
# 3. Version tag follows the header; a break mismatch is logged.
# ---------------------------------------------------------------------------


def test_version_tag_follows_the_header_when_it_agrees_with_the_break_table() -> None:
    text = _fixture_text("nbptx_t13z_excerpt.txt")  # 2026-09-28 13Z, real V5.0 header

    messages: list[str] = []
    rows, _missing = derive_rows_for_bulletin(
        text=text,
        source_host="noaa-nbm-grib2-pds.s3.amazonaws.com",
        last_modified="Mon, 28 Sep 2026 14:03:18 GMT",
        fetched_at_ns=1_759_000_100_000_000_000,
        raw_sha256="d" * 64,
        log=messages.append,
    )

    assert rows
    assert all(row.nbm_version_era == "v5.0" for row in rows)
    assert all(not row.version_break_mismatch for row in rows)
    assert messages == []


def test_a_header_version_break_mismatch_is_logged_and_the_header_wins() -> None:
    # 2026-09-28 is in the v5.0 era (>= 2026-05-04), but the header is
    # rewritten to claim V4.2 -- a synthetic, deliberately drifted capture.
    real_text = _fixture_text("nbptx_t13z_excerpt.txt")
    drifted_text = real_text.replace(
        "KLAX    NBM V5.0 NBP GUIDANCE    9/28/2026  1300 UTC",
        "KLAX    NBM V4.2 NBP GUIDANCE    9/28/2026  1300 UTC",
    )
    assert drifted_text != real_text

    messages: list[str] = []
    rows, _missing = derive_rows_for_bulletin(
        text=drifted_text,
        source_host="noaa-nbm-grib2-pds.s3.amazonaws.com",
        last_modified="Mon, 28 Sep 2026 14:03:18 GMT",
        fetched_at_ns=1_759_000_100_000_000_000,
        raw_sha256="e" * 64,
        stations=frozenset({"KLAX"}),
        log=messages.append,
    )

    assert rows
    assert all(row.header_model_version == "4.2" for row in rows)
    # The header wins: the canonical tag stored is what the header said, not
    # what NBM_VERSION_BREAKS expected for that UTC date.
    assert all(row.nbm_version_era == "v4.2" for row in rows)
    assert all(row.version_break_mismatch for row in rows)
    assert any("mismatch" in message.lower() for message in messages)


# ---------------------------------------------------------------------------
# 4. available_at respects the 60-minute publication-lag floor.
# ---------------------------------------------------------------------------


def test_available_at_uses_the_floor_when_no_last_modified_is_present() -> None:
    cycle_ns = 1_759_000_000_000_000_000
    floor_ns = 60 * 60 * 1_000_000_000

    result = available_at_ns(cycle_runtime_ns=cycle_ns, last_modified_ns=None)

    assert result == cycle_ns + floor_ns


def test_available_at_uses_the_floor_when_last_modified_is_earlier_than_it() -> None:
    cycle_ns = 1_759_000_000_000_000_000
    floor_ns = 60 * 60 * 1_000_000_000
    # LastModified only 5 minutes after cycle -- below the 60-minute floor.
    early_last_modified_ns = cycle_ns + 5 * 60 * 1_000_000_000

    result = available_at_ns(cycle_runtime_ns=cycle_ns, last_modified_ns=early_last_modified_ns)

    assert result == cycle_ns + floor_ns


def test_available_at_uses_last_modified_when_it_is_later_than_the_floor() -> None:
    cycle_ns = 1_759_000_000_000_000_000
    # LastModified 3 hours after cycle -- above the 60-minute floor.
    late_last_modified_ns = cycle_ns + 3 * 60 * 60 * 1_000_000_000

    result = available_at_ns(cycle_runtime_ns=cycle_ns, last_modified_ns=late_last_modified_ns)

    assert result == late_last_modified_ns


# ---------------------------------------------------------------------------
# 5. Both hosts failing puts the pair on the failure ledger; no row written.
# ---------------------------------------------------------------------------


def test_both_hosts_failing_records_a_failure_and_writes_no_row(tmp_path: Path) -> None:
    output_dir = tmp_path / "nbp"
    transport = _FakeTransport()
    transport.program_error(
        dt.date(2026, 9, 28),
        13,
        BothHostsFailedError(
            "both failed",
            primary_error=RuntimeError("s3 down"),
            fallback_error=RuntimeError("nomads down"),
        ),
    )
    plan = (BackfillPlanItem(dt.date(2026, 9, 28), 13),)

    report = run_backfill(
        plan=plan,
        output_dir=output_dir,
        transport=transport,  # type: ignore[arg-type]
        runner=_FakeRunner(),  # type: ignore[arg-type]
        progress=lambda _m: None,
        clock=_clock(),
        dry_run=False,
    )

    assert report.written == 0
    assert report.failed == ("2026-09-28 13Z",)
    manifest = load_manifest(output_dir)
    assert manifest_key(dt.date(2026, 9, 28), 13) not in manifest
    ledger = load_failure_ledger(output_dir)
    entry = ledger[manifest_key(dt.date(2026, 9, 28), 13)]
    assert "s3 down" in entry.primary_error
    assert "nomads down" in entry.fallback_error
    # No parquet partition was ever created for the failed pair.
    assert not any(output_dir.rglob("*.parquet"))


def test_a_bulletin_the_parser_refuses_is_a_failure_not_a_partial_row(tmp_path: Path) -> None:
    output_dir = tmp_path / "nbp"
    transport = _FakeTransport()
    transport.program_result(dt.date(2026, 9, 28), 13, _result(text="not an NBP bulletin at all"))
    plan = (BackfillPlanItem(dt.date(2026, 9, 28), 13),)

    report = run_backfill(
        plan=plan,
        output_dir=output_dir,
        transport=transport,  # type: ignore[arg-type]
        runner=_FakeRunner(),  # type: ignore[arg-type]
        progress=lambda _m: None,
        clock=_clock(),
        dry_run=False,
    )

    assert report.written == 0
    assert report.failed == ("2026-09-28 13Z",)
    assert not any(output_dir.rglob("*.parquet"))


def test_derive_rows_for_bulletin_still_raises_the_drift_error_directly() -> None:
    with pytest.raises(NbpBulletinDriftError):
        derive_rows_for_bulletin(
            text="not an NBP bulletin at all",
            source_host="noaa-nbm-grib2-pds.s3.amazonaws.com",
            last_modified=None,
            fetched_at_ns=1,
            raw_sha256="f" * 64,
        )


# ---------------------------------------------------------------------------
# 6. --apply refuses without BREEZY_LIVE=1.
# ---------------------------------------------------------------------------


def test_apply_refuses_without_breezy_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BREEZY_LIVE", raising=False)
    monkeypatch.setenv("BREEZY_USER_AGENT", "breezy-test (contact: jon@gopoint.com)")

    exit_code = main(
        [
            "--start",
            "2026-09-28",
            "--end",
            "2026-09-28",
            "--apply",
            "--output-dir",
            str(tmp_path / "nbp"),
        ]
    )

    assert exit_code == 2


def test_apply_refuses_without_a_user_agent_even_with_breezy_live(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    monkeypatch.delenv("BREEZY_USER_AGENT", raising=False)

    exit_code = main(
        [
            "--start",
            "2026-09-28",
            "--end",
            "2026-09-28",
            "--apply",
            "--output-dir",
            str(tmp_path / "nbp"),
        ]
    )

    assert exit_code == 2


def test_no_flags_defaults_to_a_dry_run_and_touches_no_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("BREEZY_LIVE", raising=False)
    monkeypatch.delenv("BREEZY_USER_AGENT", raising=False)

    exit_code = main(
        [
            "--start",
            "2026-09-28",
            "--end",
            "2026-09-28",
            "--output-dir",
            str(tmp_path / "nbp"),
        ]
    )

    assert exit_code == 0
    assert not (tmp_path / "nbp").exists() or not any((tmp_path / "nbp").rglob("*.parquet"))


# ---------------------------------------------------------------------------
# 7. The output schema round-trips.
# ---------------------------------------------------------------------------


def test_the_output_schema_round_trips_through_parquet(tmp_path: Path) -> None:
    rows = (
        _row(variable="TXN_Q10", value_f=64.0),
        _row(variable="TXN_Q50", value_f=68.0),
        _row(variable="TXN_SD", value_f=None, absence_reason="sentinel", last_modified=None),
    )
    path = tmp_path / "nbp" / "2026" / "09" / "nbp_20260928_13z.parquet"

    write_partition(rows, path)
    table = pq.read_table(path)
    assert table.schema.equals(NBP_DERIVED_SCHEMA)

    read_back = read_partition(path)

    assert read_back == rows


# ---------------------------------------------------------------------------
# Plan construction.
# ---------------------------------------------------------------------------


def test_build_plan_is_date_major_cycle_ascending() -> None:
    plan = build_plan(start=dt.date(2026, 9, 28), end=dt.date(2026, 9, 29))

    assert plan == (
        BackfillPlanItem(dt.date(2026, 9, 28), 13),
        BackfillPlanItem(dt.date(2026, 9, 28), 19),
        BackfillPlanItem(dt.date(2026, 9, 28), 1),
        BackfillPlanItem(dt.date(2026, 9, 29), 13),
        BackfillPlanItem(dt.date(2026, 9, 29), 19),
        BackfillPlanItem(dt.date(2026, 9, 29), 1),
    )


def test_build_plan_refuses_an_end_before_start() -> None:
    with pytest.raises(ValueError):
        build_plan(start=dt.date(2026, 9, 29), end=dt.date(2026, 9, 28))


def test_manifest_json_is_valid_and_resumable_after_process_restart(tmp_path: Path) -> None:
    """A resumable checkpoint must survive a fresh `load_manifest` call --
    not merely an in-memory dict -- so a killed-and-restarted run resumes."""
    output_dir = tmp_path / "nbp"
    transport = _FakeTransport()
    text = _fixture_text("nbptx_t13z_excerpt.txt")
    transport.program_result(dt.date(2026, 9, 28), 13, _result(text=text))
    plan = (BackfillPlanItem(dt.date(2026, 9, 28), 13),)

    run_backfill(
        plan=plan,
        output_dir=output_dir,
        transport=transport,  # type: ignore[arg-type]
        runner=_FakeRunner(),  # type: ignore[arg-type]
        progress=lambda _m: None,
        clock=_clock(),
        dry_run=False,
    )

    raw = json.loads((output_dir / "_manifest.json").read_text(encoding="utf-8"))
    assert isinstance(raw, list)
    assert raw[0]["key"] == "2026-09-28:13"
    assert raw[0]["rows"] > 0

    reloaded = load_manifest(output_dir)
    assert "2026-09-28:13" in reloaded


# ---------------------------------------------------------------------------
# 8. KNYC / non-default station sets: isolation, budget, pacing, window, report.
# ---------------------------------------------------------------------------

_FIVE = frozenset({"KLAX", "KMDW", "KMIA", "KSFO", "KNYC"})
_DAY = dt.date(2026, 9, 28)


def _run(  # type: ignore[no-untyped-def]
    tmp: Path, transport, *, cycles=(13, 19), clock=None, **kwargs
):
    return run_backfill(
        plan=build_plan(start=_DAY, end=_DAY, cycles=cycles),
        output_dir=tmp,
        transport=transport,
        runner=_FakeRunner(),  # type: ignore[arg-type]
        progress=lambda _m: None,
        clock=clock or _clock(),
        dry_run=False,
        **kwargs,
    )


def _programmed() -> _FakeTransport:
    transport = _FakeTransport()
    transport.program_result(_DAY, 13, _result(text=_fixture_text("nbptx_t13z_excerpt.txt")))
    transport.program_result(
        _DAY, 19, _result(text=_fixture_text("nbptx_t19z_excerpt.txt"), raw_sha256="b" * 64)
    )
    return transport


def test_a_four_station_manifest_entry_never_skips_a_five_station_item(tmp_path: Path) -> None:
    _run(tmp_path, _programmed())  # default 4-station run
    transport = _programmed()

    report = _run(tmp_path, transport, stations=_FIVE)

    assert report.skipped == 0
    assert report.written == 2
    assert len(transport.calls) == 2


def test_a_five_station_run_is_keyed_apart_from_the_default_keys(tmp_path: Path) -> None:
    _run(tmp_path, _programmed(), stations=_FIVE)

    keys = set(load_manifest(tmp_path))
    assert manifest_key(_DAY, 13) not in keys
    assert all("KNYC" in key for key in keys)


def test_the_default_station_set_keeps_the_legacy_manifest_key(tmp_path: Path) -> None:
    _run(tmp_path, _programmed())

    assert manifest_key(_DAY, 13) in load_manifest(tmp_path)


def test_derive_rows_counts_a_missing_knyc_block() -> None:
    _rows, missing = derive_rows_for_bulletin(
        text=_fixture_text("nbptx_t13z_excerpt.txt"),
        source_host="h",
        last_modified=None,
        fetched_at_ns=1,
        raw_sha256="a" * 64,
        stations=_FIVE,
    )

    assert missing == 1


def test_budget_stops_the_run_before_the_next_worst_case_item(tmp_path: Path) -> None:
    transport = _programmed()

    report = _run(tmp_path, transport, request_budget=2)

    assert report.stop_reason == "budget_exhausted"
    assert report.written == 1
    assert len(transport.calls) == 1


def test_pacing_sleeps_between_fetches(tmp_path: Path) -> None:
    sleeps: list[float] = []

    _run(tmp_path, _programmed(), pace_s=1.5, sleeper=sleeps.append)

    assert sleeps == [1.5]


def test_a_fetch_inside_the_launch_window_is_never_started(tmp_path: Path) -> None:
    in_window = int(dt.datetime(2026, 10, 7, 16, 45, tzinfo=dt.UTC).timestamp() * 1e9)
    transport = _programmed()

    report = _run(tmp_path, transport, clock=lambda: in_window)

    assert report.stop_reason == "paused_launch_window"
    assert transport.calls == []


def _argv(tmp_path: Path, *extra: str) -> list[str]:
    return ["--start", "2026-09-28", "--end", "2026-09-28", *extra]


def test_non_default_stations_refuse_the_default_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    assert main(_argv(tmp_path, "--stations", "KLAX,KNYC")) == 2
    assert not (tmp_path / ".local").exists()


def test_non_default_stations_refuse_an_explicit_default_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    default_root = tmp_path / ".local" / "share" / "breezy" / "derived" / "nbp"

    exit_code = main(_argv(tmp_path, "--stations", "KLAX,KNYC", "--out-root", str(default_root)))

    assert exit_code == 2


def test_a_root_stamped_with_other_stations_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "nbp5"
    root.mkdir()
    (root / "_stations.json").write_text('["KLAX", "KNYC"]\n', encoding="utf-8")
    assert main(_argv(tmp_path, "--stations", "KLAX,KNYC", "--out-root", str(root))) == 0
    assert main(_argv(tmp_path, "--stations", "KLAX,KMIA", "--out-root", str(root))) == 2


def test_apply_requires_a_request_budget(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BREEZY_LIVE", "1")
    monkeypatch.setenv("BREEZY_USER_AGENT", "breezy-test (jon@gopoint.com)")

    assert main(_argv(tmp_path, "--apply", "--output-dir", str(tmp_path / "n"))) == 2


def test_apply_builds_the_transport_with_the_stations_and_always_writes_a_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.analysis.nbp_backfill as module

    seen: dict[str, object] = {}

    class _Boom:
        def __init__(self, **kwargs: object) -> None:
            seen.update(kwargs)

        async def fetch_nbp_bulletin(self, **_kw: object) -> None:
            raise NbmQuantileFetchError("boom")

    monkeypatch.setattr(module, "NbmQuantileTransport", _Boom)
    monkeypatch.setenv("BREEZY_LIVE", "1")
    monkeypatch.setenv("BREEZY_USER_AGENT", "breezy-test (jon@gopoint.com)")
    report_path = tmp_path / "report.json"

    exit_code = main(
        _argv(
            tmp_path,
            "--apply",
            "--stations",
            "KLAX,KMDW,KMIA,KSFO,KNYC",
            "--out-root",
            str(tmp_path / "nbp5"),
            "--request-budget",
            "100",
            "--pace-s",
            "0",
            "--report-json",
            str(report_path),
        ),
        clock=_clock(),
    )

    assert exit_code == 1
    assert seen["stations"] == _FIVE
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["failed"] and payload["stations"] == sorted(_FIVE)


def test_apply_inside_the_launch_window_pauses_before_any_fetch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import scripts.analysis.nbp_backfill as module

    fetched: list[object] = []

    class _Boom:
        def __init__(self, **_kwargs: object) -> None:
            pass

        async def fetch_nbp_bulletin(self, **kw: object) -> None:
            fetched.append(kw)
            raise NbmQuantileFetchError("boom")

    monkeypatch.setattr(module, "NbmQuantileTransport", _Boom)
    monkeypatch.setenv("BREEZY_LIVE", "1")
    monkeypatch.setenv("BREEZY_USER_AGENT", "breezy-test (jon@gopoint.com)")
    in_window = int(dt.datetime(2026, 10, 7, 16, 45, tzinfo=dt.UTC).timestamp() * 1e9)
    report_path = tmp_path / "report.json"

    main(
        _argv(
            tmp_path,
            "--apply",
            "--stations",
            "KLAX,KMDW,KMIA,KSFO,KNYC",
            "--out-root",
            str(tmp_path / "nbp5"),
            "--request-budget",
            "100",
            "--pace-s",
            "0",
            "--report-json",
            str(report_path),
        ),
        clock=lambda: in_window,
    )

    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert fetched == []
    assert payload["failed"] == []
    assert payload["stop_reason"] == "paused_launch_window"
