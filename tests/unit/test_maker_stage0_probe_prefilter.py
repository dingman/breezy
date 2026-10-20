"""C7 instance pre-filter (verdict-blind: file stat plus definitions-name and rung-directory-name).

An old instance is skipped (never converted) only when ALL of these hold: its newest feather is
strictly older than the licensed block (a tie is kept), it holds no readable licensed YES
definition, it holds no licensed per-rung stream directory, and it holds no flat per-rung stream
file. Any read error keeps it (fail open: WARNING with traceback, counted in the single per-pass
log line, as is every instance kept by content).

Every boundary case uses an UNLICENSED instance (NYC, or a station outside the requested ones)
with real ``days``/``stations``: a licensed instance is rescued by the definitions or rung-directory
check whatever its mtimes say, so it cannot probe the stat boundary (L-33).
"""

from __future__ import annotations

import ast
import datetime as dt
import inspect
import logging
import os
import shutil
from collections.abc import Collection
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from nautilus_trader.model.data import TradeTick
from nautilus_trader.model.enums import AggressorSide
from nautilus_trader.persistence.funcs import class_to_filename

from breezy.persistence.feather_preflight import DEFAULT_SUBDIRECTORY
from breezy.registry.sites import SiteNotFoundError
from scripts.analysis import maker_stage0_catalog_read as catalog
from scripts.analysis import maker_stage0_prefilter as pf
from scripts.analysis import maker_stage0_probe as p
from scripts.analysis import maker_stage0_scoped_convert as sc
from tests.fixtures.maker_stage0 import replay_world as rw
from tests.unit.test_maker_stage0_probe import (
    _DAY,
    _capture,
    _depth,
    _instrument,
    _ns,
    _slug,
    _trade,
    _write_instance,
)

_LAX = ("LAX",)
_SFO = ("SFO",)
_DAYS = frozenset({_DAY})
_ONE_DAY_NS = 86_400 * 1_000_000_000
_PF_LOG = pf.__name__


def _touch(instance_dir: Path, mtime_ns: int) -> None:
    files = list(instance_dir.rglob("*.feather"))
    assert files, instance_dir
    for path in files:
        os.utime(path, ns=(mtime_ns, mtime_ns))


def _spy(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []
    real = sc.scan_instance_memoized

    def counting(
        catalog_root: Path, instance_id: str, subdirectory: str = DEFAULT_SUBDIRECTORY
    ) -> Any:
        seen.append(instance_id)
        return real(catalog_root, instance_id, subdirectory)

    monkeypatch.setattr(sc, "scan_instance_memoized", counting)
    return seen


def _disable(monkeypatch: pytest.MonkeyPatch) -> None:
    def keep(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr(p, "_prefilter_reason", keep)


def _cutoff() -> int:
    cutoff = p.prefilter_cutoff_ns([_DAY], _LAX)
    assert cutoff is not None
    return cutoff


def _reason(
    instance_dir: Path,
    cutoff: int,
    *,
    fail_open: list[str] | None = None,
    kept_by_content: list[str] | None = None,
) -> str | None:
    """The real decision for LAX x ``_DAY`` (real ``days``/``stations``, never the empty guard)."""
    return pf._prefilter_reason(
        instance_dir,
        cutoff,
        days=_DAYS,
        stations=frozenset(_LAX),
        fail_open=fail_open,
        kept_by_content=kept_by_content,
    )


def _skip_reason(newest: int, cutoff: int) -> str:
    return f"prefilter: last_written_ns {newest} < cutoff_ns {cutoff}"


def _minimal(capture: Path, instance_id: str, *, city: str = "lax") -> None:
    instrument = _instrument(_slug(city), _ns("2026-09-21T11:00:00"))
    _write_instance(
        capture,
        instance_id,
        instruments=[instrument],
        records=[
            _trade(
                instrument,
                f"{instance_id}-t",
                "0.500",
                AggressorSide.BUYER,
                _ns("2026-09-22T05:40:00"),
            )
        ],
        offsets=[(_ns("2026-09-22T01:00:00"), 0)],
    )


def _unlicensed(capture: Path, name: str, mtime_ns: int, *, city: str = "nyc") -> Path:
    """An instance holding no LAX x ``_DAY`` data at all, every feather stamped ``mtime_ns``."""
    _minimal(capture, name, city=city)
    instance_dir = capture / "live" / name
    _touch(instance_dir, mtime_ns)
    return instance_dir


def _write_licensed_old(capture: Path) -> tuple[int, int]:
    """LAX definitions plus licensed depth/print rung directories, all feathers before the block."""
    ts_init = _ns("2026-09-19T00:00:00")
    print_ts = _ns("2026-09-22T05:40:00")
    lax = _instrument(_slug("lax"), ts_init)
    _write_instance(
        capture,
        "licensed",
        instruments=[lax],
        records=[
            _depth(lax, "0.390", "0.410", print_ts),
            _trade(lax, "lic", "0.500", AggressorSide.BUYER, print_ts),
        ],
        offsets=[(_ns("2026-09-22T01:00:00"), -5 * 1_000_000_000)],
    )
    _touch(capture / "live" / "licensed", ts_init)
    return ts_init, print_ts


def _write_defs_only_old(capture: Path) -> int:
    """A licensed LAX definition and NO per-rung stream directory: only the definitions keep it."""
    ts_init = _ns("2026-09-19T00:00:00")
    lax = _instrument(_slug("lax"), ts_init)
    _write_instance(
        capture,
        "defs-only",
        instruments=[lax],
        records=[],
        offsets=[(_ns("2026-09-22T01:00:00"), -5 * 1_000_000_000)],
    )
    instance_dir = capture / "live" / "defs-only"
    assert not (instance_dir / "trade_tick").exists()
    assert not (instance_dir / "order_book_depths").exists()
    _touch(instance_dir, ts_init)
    return ts_init


def _blank_definitions(instance_dir: Path) -> None:
    """Rewrite the definitions feather as a schema-only (zero-row) stream: no licensed row."""
    path = next(instance_dir.glob("binary_option_*.feather"))
    with pa.OSFile(str(path), "rb") as source:
        schema = pa.ipc.open_stream(source).schema
    with pa.OSFile(str(path), "wb") as sink, pa.ipc.new_stream(sink, schema):
        pass
    with pa.OSFile(str(path), "rb") as source:
        assert pa.ipc.open_stream(source).read_all().num_rows == 0


def _write_rungs_without_definitions(
    capture: Path, mtime_ns: int | None = None
) -> tuple[Path, int]:
    """Old instance: licensed ``trade_tick/<rung>/`` + depth directories, zero-row definitions."""
    _ts_init, print_ts = _write_licensed_old(capture)
    instance_dir = capture / "live" / "licensed"
    _blank_definitions(instance_dir)
    assert any((instance_dir / "trade_tick").iterdir())
    _touch(instance_dir, _ns("2026-09-19T00:00:00") if mtime_ns is None else mtime_ns)
    return instance_dir, print_ts


def _write_flat_per_rung_old(capture: Path) -> tuple[Path, int]:
    """Old instance, zero-row definitions, licensed prints held ONLY as a flat per-rung file.

    The recorder's per-instrument directories are moved to the flat ``<table>_<ts>.feather`` name
    ``StreamingFeatherWriter._create_writer`` gives a flat file (it carries no instrument id).
    """
    instance_dir, print_ts = _write_rungs_without_definitions(capture)
    (rung_file,) = (instance_dir / class_to_filename(TradeTick)).rglob("*.feather")
    flat = instance_dir / f"{class_to_filename(TradeTick)}_{print_ts}.feather"
    rung_file.rename(flat)
    shutil.rmtree(instance_dir / class_to_filename(TradeTick))
    shutil.rmtree(instance_dir / "order_book_depths")
    _touch(instance_dir, _ns("2026-09-19T00:00:00"))
    assert flat.parent == instance_dir
    return instance_dir, print_ts


def _read_calls(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> list[str]:
    """Make the definitions reader raise ``error``; returns the list of paths it was asked for."""
    calls: list[str] = []

    def boom(path: Path) -> object:
        calls.append(str(path))
        raise error

    monkeypatch.setattr(pf, "_read_definition_instrument_ids", boom)
    return calls


def _definition_reads(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Spy on the definitions reader (the real one still runs); returns the paths it was given."""
    calls: list[str] = []
    real = pf._read_definition_instrument_ids

    def spy(path: Path) -> Any:
        calls.append(str(path))
        return real(path)

    monkeypatch.setattr(pf, "_read_definition_instrument_ids", spy)
    return calls


def _probe_lax(capture: Path, work: Path) -> tuple[int | None, p.ProbeReport]:
    first = p.first_print_instant(capture, [_DAY], work_root=work / "fp", stations=_LAX)
    report = p.probe(capture, [_DAY], _LAX, work_root=work / "probe", first_print_ns=first)
    return first, report


def _without_skipped(report: p.ProbeReport) -> dict[str, Any]:
    body = report.to_dict()
    del body["skipped_instances"]
    return body


def _summary_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage().startswith("prefilter: skipped")]


def _summary_lines(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [record.getMessage() for record in _summary_records(caplog)]


# --- structure ----------------------------------------------------------------------------


def test_prefilter_cutoff_none_on_empty_inputs() -> None:
    assert p.prefilter_cutoff_ns([], ["LAX"]) is None
    assert p.prefilter_cutoff_ns([_DAY], []) is None
    assert p.prefilter_cutoff_ns((), ()) is None


def test_cutoff_helper_is_defined_in_probe_beside_query_bounds() -> None:
    assert p.prefilter_cutoff_ns.__module__ == p.__name__
    assert list(inspect.signature(p.prefilter_cutoff_ns).parameters) == ["days", "stations"]
    assert not hasattr(pf, "prefilter_cutoff_ns")


def test_prefilter_module_never_imports_the_probe() -> None:
    tree = ast.parse(Path(pf.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported |= {node.module or "", *(alias.name for alias in node.names)}
        elif isinstance(node, ast.Import):
            imported |= {alias.name for alias in node.names}
    assert not {name for name in imported if name.rsplit(".", 1)[-1] == "maker_stage0_probe"}


def test_prefilter_reason_scope_arguments_are_required_keyword_only() -> None:
    params = inspect.signature(pf._prefilter_reason).parameters
    for name in ("days", "stations"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert params[name].default is inspect.Parameter.empty


# --- the stat boundary, on UNLICENSED instances -----------------------------------------


def test_prefilter_reason_keeps_an_unlicensed_instance_at_the_cutoff(tmp_path: Path) -> None:
    cutoff = _cutoff()
    instance_dir = _unlicensed(tmp_path / "capture", "nyc-tie", cutoff)

    assert _reason(instance_dir, cutoff) is None


def test_prefilter_reason_skips_an_unlicensed_instance_one_ns_below_the_cutoff(
    tmp_path: Path,
) -> None:
    cutoff = _cutoff()
    instance_dir = _unlicensed(tmp_path / "capture", "nyc-old", cutoff - 1)

    assert _reason(instance_dir, cutoff) == _skip_reason(cutoff - 1, cutoff)


def test_prefilter_reason_keeps_an_unlicensed_instance_stamped_in_the_future(
    tmp_path: Path,
) -> None:
    cutoff = _cutoff()
    instance_dir = _unlicensed(tmp_path / "capture", "nyc-future", cutoff + _ONE_DAY_NS)

    assert _reason(instance_dir, cutoff) is None


@pytest.mark.parametrize("fresh_index", [0, 1, -1])
def test_one_feather_at_the_cutoff_keeps_an_otherwise_older_instance(
    tmp_path: Path, fresh_index: int
) -> None:
    """The NEWEST mtime decides, wherever that file sorts."""
    cutoff = _cutoff()
    instance_dir = _unlicensed(tmp_path / "capture", "nyc-mixed", cutoff - 1)
    files = sorted(instance_dir.rglob("*.feather"))
    assert len(files) >= 3
    os.utime(files[fresh_index], ns=(cutoff, cutoff))

    assert _reason(instance_dir, cutoff) is None


def test_prefilter_reason_names_the_newest_mtime_not_the_oldest(tmp_path: Path) -> None:
    cutoff = _cutoff()
    instance_dir = _unlicensed(tmp_path / "capture", "nyc-spread", cutoff - 1)
    files = sorted(instance_dir.rglob("*.feather"))
    assert len(files) >= 3
    os.utime(files[0], ns=(cutoff - 9 * _ONE_DAY_NS, cutoff - 9 * _ONE_DAY_NS))
    os.utime(files[1], ns=(cutoff - 5 * _ONE_DAY_NS, cutoff - 5 * _ONE_DAY_NS))

    assert _reason(instance_dir, cutoff) == _skip_reason(cutoff - 1, cutoff)


@pytest.mark.parametrize(
    ("days", "stations"),
    [((), frozenset(_LAX)), (_DAYS, ()), ((), ())],
    ids=["no-days", "no-stations", "neither"],
)
def test_prefilter_reason_keeps_when_the_licensed_block_is_empty(
    tmp_path: Path, days: Collection[dt.date], stations: Collection[str]
) -> None:
    cutoff = _cutoff()
    instance_dir = _unlicensed(tmp_path / "capture", "nyc-old", cutoff - 1)

    assert pf._prefilter_reason(instance_dir, cutoff, days=days, stations=stations) is None


def test_prefilter_reason_keeps_a_directory_with_no_feather_files(tmp_path: Path) -> None:
    empty = tmp_path / "capture" / "live" / "empty"
    empty.mkdir(parents=True)
    fail_open: list[str] = []

    assert _reason(empty, _cutoff(), fail_open=fail_open) is None
    assert fail_open == []  # an empty signature is a keep, not a read error


# --- the stat boundary through the probe passes -----------------------------------------


def test_prefilter_skips_only_instances_last_written_before_the_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cutoff = p.prefilter_cutoff_ns([_DAY], _LAX)
    assert cutoff == _ns("2026-09-20T12:00:00")
    capture = _capture(tmp_path)
    _minimal(capture, "tie", city="nyc")
    _minimal(capture, "old", city="nyc")
    _touch(capture / "live" / "tie", cutoff)
    _touch(capture / "live" / "old", cutoff - 1)
    (capture / "live" / "bad-inst").mkdir()
    foreign = tmp_path / "work" / "probe" / "old"
    foreign.mkdir(parents=True)
    (foreign / "marker").write_text("keep")
    seen = _spy(monkeypatch)

    _first, report = _probe_lax(capture, tmp_path / "work")

    assert report.skipped["old"] == _skip_reason(cutoff - 1, cutoff)
    assert "tie" not in report.skipped
    assert "inst-a" not in report.skipped
    assert report.skipped["bad-inst"].startswith("PreflightError")
    assert set(report.skipped) == {"old", "bad-inst"}
    assert "old" not in seen
    assert {"inst-a", "tie"} <= set(seen)
    assert (foreign / "marker").read_text() == "keep"


def test_prefilter_keeps_an_instance_whose_start_ends_an_earlier_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One feather at or after the cutoff keeps an unlicensed instance (newest mtime)."""
    cutoff = _cutoff()
    capture = tmp_path / "capture"
    instance_dir = _unlicensed(capture, "nyc-mixed", cutoff - 1)
    os.utime(max(instance_dir.rglob("*.feather")), ns=(cutoff, cutoff))
    seen = _spy(monkeypatch)

    _first, report = _probe_lax(capture, tmp_path / "work")

    assert "nyc-mixed" in seen
    assert "nyc-mixed" not in report.skipped


def test_prefilter_tie_keeps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cutoff = _cutoff()
    capture = tmp_path / "capture"
    instance_dir = _unlicensed(capture, "nyc-tie", cutoff)
    seen = _spy(monkeypatch)

    assert _reason(instance_dir, cutoff) is None
    _first, report = _probe_lax(capture, tmp_path / "work")
    assert "nyc-tie" in seen
    assert "nyc-tie" not in report.skipped


def test_prefilter_future_mtime_keeps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cutoff = _cutoff()
    capture = tmp_path / "capture"
    instance_dir = _unlicensed(capture, "nyc-future", cutoff + _ONE_DAY_NS)
    seen = _spy(monkeypatch)

    assert _reason(instance_dir, cutoff) is None
    _first, report = _probe_lax(capture, tmp_path / "work")
    assert "nyc-future" in seen
    assert "nyc-future" not in report.skipped


def test_prefilter_keeps_a_fresh_unlicensed_instance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = tmp_path / "capture"
    _minimal(capture, "nyc-fresh", city="nyc")  # written just now: far above the cutoff
    seen = _spy(monkeypatch)

    _first, report = _probe_lax(capture, tmp_path / "work")

    assert "nyc-fresh" in seen
    assert "nyc-fresh" not in report.skipped


# --- fail open: read errors keep, warn, and are counted ---------------------------------


def test_prefilter_oserror_keeps_warns_and_counts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    capture = tmp_path / "capture"
    instance_dir = _unlicensed(capture, "nyc-old", _cutoff() - 1)

    def always_raise(_directory: Path) -> tuple[tuple[str, int, int], ...]:
        raise OSError("stat failed")

    monkeypatch.setattr(sc, "_signature", always_raise)
    fail_open: list[str] = []
    with caplog.at_level(logging.WARNING, logger=_PF_LOG):
        assert _reason(instance_dir, _cutoff(), fail_open=fail_open) is None

    assert fail_open == ["nyc-old"]
    (record,) = [r for r in caplog.records if r.name == _PF_LOG]
    assert record.levelno == logging.WARNING
    assert "nyc-old" in record.getMessage()
    assert record.exc_info is not None
    assert record.exc_info[0] is OSError


def test_prefilter_oserror_in_a_pass_keeps_the_instance_and_counts_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    capture = _capture(tmp_path)
    real = sc._signature
    calls = {"n": 0}

    def one_shot(directory: Path) -> tuple[tuple[str, int, int], ...]:
        if calls["n"] == 0:
            calls["n"] = 1
            raise OSError("stat failed")
        return real(directory)

    monkeypatch.setattr(sc, "_signature", one_shot)
    seen = _spy(monkeypatch)

    with caplog.at_level(logging.INFO):
        _first, report = _probe_lax(capture, tmp_path / "work")

    assert calls["n"] == 1
    assert "inst-a" in seen
    assert "inst-a" not in report.skipped
    assert report.depth_frames == 3
    first_print_pass, probe_pass = (
        "prefilter: skipped 0 of 1 instances (kept_by_fail_open 1, kept_by_content 0)",
        "prefilter: skipped 0 of 1 instances (kept_by_fail_open 0, kept_by_content 0)",
    )
    assert _summary_lines(caplog) == [first_print_pass, probe_pass]


@pytest.mark.parametrize("payload", ["zero-byte", "truncated"])
def test_prefilter_keeps_an_old_instance_whose_real_definitions_file_is_unreadable(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, payload: str
) -> None:
    """A REAL damaged ``binary_option_*.feather`` (no monkeypatch) fails open, never skips."""
    cutoff = _cutoff()
    capture = tmp_path / "capture"
    instance_dir = _unlicensed(capture, "nyc-damaged", cutoff - 1)
    definitions = next(instance_dir.glob("binary_option_*.feather"))
    data = definitions.read_bytes()
    definitions.write_bytes(b"" if payload == "zero-byte" else data[: len(data) // 2])
    os.utime(definitions, ns=(cutoff - 1, cutoff - 1))
    fail_open: list[str] = []

    with caplog.at_level(logging.WARNING, logger=_PF_LOG):
        assert _reason(instance_dir, cutoff, fail_open=fail_open) is None

    assert fail_open == ["nyc-damaged"]
    (record,) = [r for r in caplog.records if r.name == _PF_LOG]
    assert record.levelno == logging.WARNING
    assert "nyc-damaged" in record.getMessage()
    assert record.exc_info is not None
    assert record.exc_info[0] is pa.ArrowInvalid


def test_pass_over_a_damaged_old_instance_is_not_a_prefilter_skip_and_is_counted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cutoff = _cutoff()
    capture = _capture(tmp_path)
    instance_dir = _unlicensed(capture, "nyc-damaged", cutoff - 1)
    definitions = next(instance_dir.glob("binary_option_*.feather"))
    definitions.write_bytes(b"")
    os.utime(definitions, ns=(cutoff - 1, cutoff - 1))

    with caplog.at_level(logging.INFO):
        _first, report = _probe_lax(capture, tmp_path / "work")

    # Kept by the prefilter; the later classify stage owns the verdict on the damaged file.
    assert not report.skipped.get("nyc-damaged", "").startswith("prefilter:")
    assert _summary_lines(caplog)[-1].endswith("(kept_by_fail_open 1, kept_by_content 0)")


def test_prefilter_keeps_licensed_instance_when_definitions_read_raises_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = tmp_path / "capture"
    _write_defs_only_old(capture)
    calls = _read_calls(monkeypatch, OSError("read failed"))

    _first, report = _probe_lax(capture, tmp_path / "work")

    assert calls  # the definitions reader really was reached
    assert "defs-only" not in report.skipped
    assert report.coverage[0].listing_ns is not None


def test_prefilter_keeps_licensed_instance_when_definitions_read_raises_arrow_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = tmp_path / "capture"
    _write_defs_only_old(capture)
    calls = _read_calls(monkeypatch, pa.ArrowInvalid("bad schema"))

    _first, report = _probe_lax(capture, tmp_path / "work")

    assert calls
    assert "defs-only" not in report.skipped
    assert report.coverage[0].listing_ns is not None


# --- the three KEEP conditions beyond the stat gate -------------------------------------


def test_prefilter_keeps_old_instance_whose_only_licensed_evidence_is_a_definition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cutoff = _cutoff()
    capture = tmp_path / "capture"
    ts_init = _write_defs_only_old(capture)
    assert ts_init < cutoff

    assert _reason(capture / "live" / "defs-only", cutoff) is None
    kept_first, kept = _probe_lax(capture, tmp_path / "on")
    _disable(monkeypatch)
    off_first, off = _probe_lax(capture, tmp_path / "off")

    assert "defs-only" not in kept.skipped
    assert kept_first == off_first
    assert kept.coverage[0].listing_ns == off.coverage[0].listing_ns == ts_init
    assert kept.coverage == off.coverage
    assert _without_skipped(kept) == _without_skipped(off)


def test_prefilter_keeps_old_instance_that_holds_a_licensed_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = tmp_path / "capture"
    ts_init, print_ts = _write_licensed_old(capture)
    cutoff = p.prefilter_cutoff_ns([_DAY], _LAX)
    assert cutoff == _ns("2026-09-20T12:00:00")
    assert ts_init < cutoff

    kept_first, kept = _probe_lax(capture, tmp_path / "on")
    _disable(monkeypatch)
    off_first, off = _probe_lax(capture, tmp_path / "off")

    assert "licensed" not in kept.skipped
    assert all(not reason.startswith("prefilter:") for reason in kept.skipped.values())
    assert kept_first == off_first == print_ts
    assert kept.first_print_ns == off.first_print_ns == print_ts == kept_first
    assert kept.coverage[0].listing_ns == off.coverage[0].listing_ns == ts_init
    assert kept.coverage == off.coverage
    assert kept.census == off.census
    assert kept.direction == off.direction
    assert _without_skipped(kept) == _without_skipped(off)


def test_prefilter_keeps_old_instance_with_licensed_rung_dirs_and_no_licensed_definitions(
    tmp_path: Path,
) -> None:
    cutoff = _cutoff()
    instance_dir, _print_ts = _write_rungs_without_definitions(tmp_path / "capture")
    fail_open: list[str] = []

    assert _reason(instance_dir, cutoff, fail_open=fail_open) is None
    assert fail_open == []  # kept on the evidence, not by a read error


def test_prefilter_keeps_the_fresh_twin_of_the_rungs_without_definitions_instance(
    tmp_path: Path,
) -> None:
    cutoff = _cutoff()
    instance_dir, _print_ts = _write_rungs_without_definitions(tmp_path / "capture", cutoff + 1)

    assert _reason(instance_dir, cutoff) is None


@pytest.mark.parametrize("payload", ["zero-byte", "truncated"])
def test_rung_directory_check_precedes_the_definitions_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: str
) -> None:
    """Licensed rung directories keep the instance BEFORE the definitions file is opened.

    The definitions file here is damaged: were it read first it would fail open (counted in
    ``fail_open``); read second-or-never it cannot. Pins the cheap directory listing ahead of the
    file read, so a damaged definitions file never turns into a read error the rungs already settle.
    """
    cutoff = _cutoff()
    instance_dir, _print_ts = _write_rungs_without_definitions(tmp_path / "capture")
    definitions = next(instance_dir.glob("binary_option_*.feather"))
    data = definitions.read_bytes()
    definitions.write_bytes(b"" if payload == "zero-byte" else data[: len(data) // 2])
    _touch(instance_dir, _ns("2026-09-19T00:00:00"))
    reads = _definition_reads(monkeypatch)
    fail_open: list[str] = []

    assert _reason(instance_dir, cutoff, fail_open=fail_open) is None

    assert fail_open == []
    assert reads == []  # the definitions reader was never reached


def test_prefilter_keeps_old_instance_whose_only_licensed_evidence_is_a_flat_per_rung_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A flat ``trade_tick_<ts>.feather`` names no instrument: any such file keeps (names only)."""
    cutoff = _cutoff()
    capture = tmp_path / "capture"
    instance_dir, print_ts = _write_flat_per_rung_old(capture)
    assert not (instance_dir / "trade_tick").exists()
    assert not (instance_dir / "order_book_depths").exists()
    (definitions,) = instance_dir.glob("binary_option_*.feather")
    assert pf._read_definition_instrument_ids(definitions) == ()  # no licensed definition row
    fail_open: list[str] = []
    reads = _definition_reads(monkeypatch)

    assert _reason(instance_dir, cutoff, fail_open=fail_open) is None
    assert fail_open == []
    assert reads == []  # names only: the flat file keeps it before any definitions read
    kept_first, kept = _probe_lax(capture, tmp_path / "on")
    _disable(monkeypatch)
    off_first, off = _probe_lax(capture, tmp_path / "off")

    assert "licensed" not in kept.skipped
    assert kept_first == off_first == print_ts
    assert kept.first_print_ns == off.first_print_ns == print_ts
    assert _without_skipped(kept) == _without_skipped(off)


def test_a_flat_non_per_rung_file_does_not_keep_an_old_unlicensed_instance(
    tmp_path: Path,
) -> None:
    """Definitions and the venue clock are flat too; only per-rung stream names keep."""
    cutoff = _cutoff()
    instance_dir = _unlicensed(tmp_path / "capture", "nyc-flat", cutoff - 1, city="nyc")
    flat = [p for p in instance_dir.glob("*.feather")]
    assert flat  # binary_option_*.feather and the venue clock offsets
    assert not any(f.name.startswith(class_to_filename(TradeTick) + "_") for f in flat)

    assert _reason(instance_dir, cutoff) == _skip_reason(cutoff - 1, cutoff)


@pytest.mark.parametrize("stream", ["trade_tick", "order_book_depths"])
def test_any_per_rung_stream_directory_keeps_the_instance(tmp_path: Path, stream: str) -> None:
    cutoff = _cutoff()
    instance_dir, _print_ts = _write_rungs_without_definitions(tmp_path / "capture")
    for other in {"trade_tick", "order_book_depths"} - {stream}:
        shutil.rmtree(instance_dir / other)
    _touch(instance_dir, cutoff - 1)

    assert _reason(instance_dir, cutoff) is None


@pytest.mark.parametrize("city", ["nyc", "sfo"])
def test_prefilter_skips_old_zero_row_instance_whose_rung_dirs_are_not_licensed(
    tmp_path: Path, city: str
) -> None:
    """NYC, or SFO when only LAX is requested: rung directories of another scope do not keep it."""
    cutoff = _cutoff()
    instance_dir = _unlicensed(tmp_path / "capture", "other-scope", cutoff - 1, city=city)
    _blank_definitions(instance_dir)
    _touch(instance_dir, cutoff - 1)
    assert any((instance_dir / "trade_tick").iterdir())

    assert _reason(instance_dir, cutoff) == _skip_reason(cutoff - 1, cutoff)


def test_rungs_without_definitions_gives_the_same_first_print_with_the_prefilter_on_and_off(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = tmp_path / "capture"
    _instance_dir, print_ts = _write_rungs_without_definitions(capture)

    on_first, on = _probe_lax(capture, tmp_path / "on")
    _disable(monkeypatch)
    off_first, off = _probe_lax(capture, tmp_path / "off")

    assert on_first == off_first == print_ts
    assert on.first_print_ns == off.first_print_ns == print_ts
    assert on.first_replayable_day == off.first_replayable_day
    assert "licensed" not in on.skipped
    assert _without_skipped(on) == _without_skipped(off)


# --- kept_by_content: the empirical premise-P violation signal -----------------------------


def test_kept_by_content_counts_an_old_instance_kept_by_a_licensed_rung_directory(
    tmp_path: Path,
) -> None:
    cutoff = _cutoff()
    instance_dir, _print_ts = _write_rungs_without_definitions(tmp_path / "capture")
    kept_by_content: list[str] = []

    assert _reason(instance_dir, cutoff, kept_by_content=kept_by_content) is None
    assert kept_by_content == ["licensed"]


def test_kept_by_content_counts_an_old_instance_kept_by_a_licensed_definition(
    tmp_path: Path,
) -> None:
    cutoff = _cutoff()
    _write_defs_only_old(tmp_path / "capture")
    kept_by_content: list[str] = []

    assert (
        _reason(
            tmp_path / "capture" / "live" / "defs-only", cutoff, kept_by_content=kept_by_content
        )
        is None
    )
    assert kept_by_content == ["defs-only"]


def test_kept_by_content_counts_an_old_instance_kept_by_a_flat_per_rung_file(
    tmp_path: Path,
) -> None:
    instance_dir, _print_ts = _write_flat_per_rung_old(tmp_path / "capture")
    kept_by_content: list[str] = []

    assert _reason(instance_dir, _cutoff(), kept_by_content=kept_by_content) is None
    assert kept_by_content == ["licensed"]


def test_kept_by_content_is_zero_for_an_old_unlicensed_instance_that_is_skipped(
    tmp_path: Path,
) -> None:
    cutoff = _cutoff()
    instance_dir = _unlicensed(tmp_path / "capture", "nyc-old", cutoff - 1)
    kept_by_content: list[str] = []

    assert _reason(instance_dir, cutoff, kept_by_content=kept_by_content) == _skip_reason(
        cutoff - 1, cutoff
    )
    assert kept_by_content == []


def test_kept_by_content_is_zero_for_a_fresh_instance(tmp_path: Path) -> None:
    cutoff = _cutoff()
    instance_dir = _unlicensed(tmp_path / "capture", "nyc-fresh", cutoff + 1)
    kept_by_content: list[str] = []

    assert _reason(instance_dir, cutoff, kept_by_content=kept_by_content) is None
    assert kept_by_content == []


def test_kept_by_content_is_zero_when_a_read_error_kept_the_instance(tmp_path: Path) -> None:
    """A read error is counted in ``fail_open``, never also as a content keep."""
    cutoff = _cutoff()
    instance_dir = _unlicensed(tmp_path / "capture", "nyc-damaged", cutoff - 1)
    definitions = next(instance_dir.glob("binary_option_*.feather"))
    definitions.write_bytes(b"")
    os.utime(definitions, ns=(cutoff - 1, cutoff - 1))
    fail_open: list[str] = []
    kept_by_content: list[str] = []

    assert (
        _reason(instance_dir, cutoff, fail_open=fail_open, kept_by_content=kept_by_content) is None
    )
    assert fail_open == ["nyc-damaged"]
    assert kept_by_content == []


def test_the_pass_summary_counts_the_instance_kept_by_content(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    capture = tmp_path / "capture"
    _write_rungs_without_definitions(capture)

    with caplog.at_level(logging.INFO):
        _probe_lax(capture, tmp_path / "work")

    assert (
        _summary_lines(caplog)
        == ["prefilter: skipped 0 of 1 instances (kept_by_fail_open 0, kept_by_content 1)"] * 2
    )


# --- on/off equivalence of the licensed outputs -----------------------------------------


def test_licensed_outputs_identical_with_and_without_prefilter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    days = [rw.DAY]
    cutoff = p.prefilter_cutoff_ns(days, _SFO)
    assert cutoff == _ns("2026-09-27T12:00:00")
    capture = rw.build_capture(tmp_path / "world")
    _touch(capture / "live" / "inst-a", cutoff)
    nyc = _instrument(_slug("nyc", day=rw.DAY.isoformat()), _ns("2026-09-19T00:00:00"))
    _write_instance(
        capture,
        "old",
        instruments=[nyc],
        records=[_trade(nyc, "old-t", "0.500", AggressorSide.BUYER, _ns("2026-09-28T21:00:00"))],
        offsets=[(_ns("2026-09-29T01:00:00"), 0)],
    )
    _touch(capture / "live" / "old", cutoff - 1)

    def run(
        root: Path,
    ) -> tuple[int | None, p.ProbeReport, dict[Any, catalog.StationDayPlan], dict[str, str]]:
        session = catalog.CatalogSession(capture, root / "plan-work")
        plan = session.plan(days, _SFO)
        first = p.first_print_instant(capture, days, work_root=root / "fp", stations=_SFO)
        report = p.probe(capture, days, _SFO, work_root=root / "probe", first_print_ns=first)
        return first, report, dict(plan), dict(session.skipped)

    on_first, on, on_plan, on_skipped = run(tmp_path / "on")
    _disable(monkeypatch)
    off_first, off, off_plan, off_skipped = run(tmp_path / "off")

    assert on_first == off_first
    assert on.first_print_ns == on_first == off.first_print_ns
    assert [row.listing_ns for row in on.coverage] == [row.listing_ns for row in off.coverage]
    assert all(row.listing_ns is not None for row in on.coverage)
    assert on.ladder_parity == off.ladder_parity
    assert on.delta_instance_days == off.delta_instance_days
    assert on.census == off.census
    assert on.direction == off.direction
    assert on.control == off.control
    assert _without_skipped(on) == _without_skipped(off)
    assert set(on.skipped) - set(off.skipped) == {"old"}
    assert set(off.skipped) - set(on.skipped) == set()
    assert on.skipped["old"] == _skip_reason(cutoff - 1, cutoff)
    assert on_plan.keys() == off_plan.keys()
    for key, row in on_plan.items():
        assert row.instruments == off_plan[key].instruments
        assert row.instances == off_plan[key].instances
        assert row.catalog_bytes == off_plan[key].catalog_bytes
    assert set(on_skipped) - set(off_skipped) == {"old"}
    assert set(off_skipped) - set(on_skipped) == set()
    assert on_skipped["old"].startswith("prefilter:")


# --- the plan pass --------------------------------------------------------------------


def test_plan_pass_skips_and_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cutoff = _cutoff()
    capture = _capture(tmp_path)
    _minimal(capture, "old", city="nyc")
    _touch(capture / "live" / "old", cutoff - 1)
    seen = _spy(monkeypatch)
    work = tmp_path / "plan-work"
    session = catalog.CatalogSession(capture, work)

    plan = session.plan([_DAY], _LAX)

    assert session.skipped["old"] == _skip_reason(cutoff - 1, cutoff)
    assert not (work / "plan" / "old").exists()
    assert "old" not in seen
    assert "inst-a" in seen
    _disable(monkeypatch)
    control = catalog.CatalogSession(capture, tmp_path / "plan-off")
    control_plan = control.plan([_DAY], _LAX)
    assert "old" not in control.skipped
    assert plan.keys() == control_plan.keys()
    for key, row in plan.items():
        assert row.instruments == control_plan[key].instruments
        assert row.instances == control_plan[key].instances
        assert row.catalog_bytes == control_plan[key].catalog_bytes


def test_plan_pass_keeps_old_instance_that_holds_a_licensed_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = tmp_path / "capture"
    _write_defs_only_old(capture)
    session = catalog.CatalogSession(capture, tmp_path / "plan-on")

    plan = session.plan([_DAY], _LAX)

    assert "defs-only" not in session.skipped
    key = ("LAX", _DAY)
    assert key in plan
    assert "defs-only" in plan[key].instances
    _disable(monkeypatch)
    control = catalog.CatalogSession(capture, tmp_path / "plan-off")
    control_plan = control.plan([_DAY], _LAX)
    assert plan.keys() == control_plan.keys()
    for plan_key, row in plan.items():
        assert row.instruments == control_plan[plan_key].instruments
        assert row.instances == control_plan[plan_key].instances
        assert row.catalog_bytes == control_plan[plan_key].catalog_bytes


def test_plan_pass_keeps_old_instance_with_licensed_rung_dirs_and_no_licensed_definitions(
    tmp_path: Path,
) -> None:
    capture = tmp_path / "capture"
    _write_rungs_without_definitions(capture)
    session = catalog.CatalogSession(capture, tmp_path / "plan-on")

    session.plan([_DAY], _LAX)

    assert "licensed" not in session.skipped


# --- one summary line per pass; no frame-store leak on a bad station --------------------


def test_each_pass_logs_one_prefilter_summary_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    capture = _capture(tmp_path)
    _unlicensed(capture, "nyc-old", _cutoff() - 1)

    with caplog.at_level(logging.INFO):
        p.first_print_instant(capture, [_DAY], work_root=tmp_path / "fp", stations=_LAX)
        p.probe(capture, [_DAY], _LAX, work_root=tmp_path / "probe")
        catalog.CatalogSession(capture, tmp_path / "plan").plan([_DAY], _LAX)

    assert (
        _summary_lines(caplog)
        == ["prefilter: skipped 1 of 2 instances (kept_by_fail_open 0, kept_by_content 0)"] * 3
    )


def test_summary_line_is_info_when_nothing_was_kept_by_error_or_content(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    capture = _capture(tmp_path)
    _unlicensed(capture, "nyc-old", _cutoff() - 1)

    with caplog.at_level(logging.INFO, logger=_PF_LOG):
        p.probe(capture, [_DAY], _LAX, work_root=tmp_path / "probe")

    (record,) = _summary_records(caplog)
    assert record.levelno == logging.INFO
    assert record.getMessage() == (
        "prefilter: skipped 1 of 2 instances (kept_by_fail_open 0, kept_by_content 0)"
    )


def test_summary_line_is_a_warning_when_a_read_error_kept_an_instance(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """No maker_stage0 script configures logging: only WARNING+ reaches stderr unconfigured."""
    cutoff = _cutoff()
    capture = _capture(tmp_path)
    instance_dir = _unlicensed(capture, "nyc-damaged", cutoff - 1)
    definitions = next(instance_dir.glob("binary_option_*.feather"))
    definitions.write_bytes(b"")
    os.utime(definitions, ns=(cutoff - 1, cutoff - 1))

    with caplog.at_level(logging.INFO, logger=_PF_LOG):
        p.probe(capture, [_DAY], _LAX, work_root=tmp_path / "probe")

    (record,) = _summary_records(caplog)
    assert record.levelno == logging.WARNING
    assert record.getMessage() == (
        "prefilter: skipped 0 of 2 instances (kept_by_fail_open 1, kept_by_content 0)"
    )


def test_summary_line_is_a_warning_when_an_old_instance_was_kept_by_content(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Under premise P the count is 0: a non-zero one must be visible without logging config."""
    capture = tmp_path / "capture"
    _write_rungs_without_definitions(capture)

    with caplog.at_level(logging.INFO, logger=_PF_LOG):
        p.probe(capture, [_DAY], _LAX, work_root=tmp_path / "probe")

    (record,) = _summary_records(caplog)
    assert record.levelno == logging.WARNING
    assert record.getMessage() == (
        "prefilter: skipped 0 of 1 instances (kept_by_fail_open 0, kept_by_content 1)"
    )


def test_probe_with_an_unknown_station_leaves_no_frame_store(tmp_path: Path) -> None:
    capture = _capture(tmp_path)
    work = tmp_path / "work"

    with pytest.raises(SiteNotFoundError):
        p.probe(capture, [_DAY], ("ZZZ",), work_root=work)

    assert not (work / "_frames").exists()
