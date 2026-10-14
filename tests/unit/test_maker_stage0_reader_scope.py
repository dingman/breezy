"""MAKER-S2 S-5 reader fix: the Stage-0 reader converts only the rungs it will query.

The 15 GB live instance made the whole-instance conversion OOM at 4 GiB. A station-day read must
convert depth/print/gap/truncation streams for ``plan.instruments`` only, a first-print pass must
convert prints for licensed rungs only, and what a station-day sees must not change.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from nautilus_trader.model.data import OrderBookDepth10, TradeTick
from nautilus_trader.persistence.catalog.parquet import ParquetDataCatalog

from breezy.persistence.feather_preflight import DEFAULT_SUBDIRECTORY, PreflightError, scan_instance
from breezy.runtime import quote_tape_ingest_core as ingest_core
from scripts.analysis import maker_stage0_catalog_read as catalog_read
from scripts.analysis import maker_stage0_probe as probe
from scripts.analysis import maker_stage0_scoped_convert as scoped
from scripts.analysis.maker_stage0_catalog_read import CatalogSession, query_window_ns
from tests.fixtures.maker_stage0 import replay_world as rw
from tests.unit.test_maker_stage0_probe import _slug

OUT_OF_PLAN = _slug("sfo", "gte60lt61f", rw.DIRECTION_DAY.isoformat())


def _spy(monkeypatch: pytest.MonkeyPatch, module: Any) -> list[tuple[type, Any]]:
    calls: list[tuple[type, Any]] = []
    real = module.default_convert

    def spy(source: Any, instance: str, data_cls: Any, *a: Any, **k: Any) -> Any:
        calls.append((data_cls, k.get("identifiers")))
        return real(source, instance, data_cls, *a, **k)

    monkeypatch.setattr(module, "default_convert", spy)
    return calls


def _whole_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reference behaviour: drop the scoping so every rung of the instance is converted."""
    real = ingest_core.default_convert

    def whole(source: Any, instance: str, data_cls: Any, *a: Any, **k: Any) -> Any:
        k.pop("identifiers", None)
        return real(source, instance, data_cls, *a, **k)

    monkeypatch.setattr(catalog_read, "default_convert", whole)


def test_a_station_day_read_converts_only_the_planned_rungs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = rw.build_capture(tmp_path / "w")
    session = CatalogSession(capture, tmp_path / "scratch")
    plan = session.plan([rw.DAY], ["SFO"])[("SFO", rw.DAY)]
    calls = _spy(monkeypatch, catalog_read)
    session.read(plan, query_window_ns("SFO", rw.DAY))
    scoped = {cls: ids for cls, ids in calls if ids is not None}
    assert {TradeTick, OrderBookDepth10} <= set(scoped)
    for ids in scoped.values():
        assert sorted(ids) == sorted(plan.instruments)
        assert OUT_OF_PLAN not in ids
    work = ParquetDataCatalog(str(tmp_path / "scratch" / "replay" / "inst-a"))
    assert work.query(data_cls=OrderBookDepth10, identifiers=[OUT_OF_PLAN]) == []
    assert work.query(data_cls=TradeTick, identifiers=[OUT_OF_PLAN]) == []
    assert work.query(data_cls=OrderBookDepth10, identifiers=[plan.instruments[0]])
    session.close()


def test_the_scoped_slice_equals_the_whole_instance_slice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = rw.build_capture(tmp_path / "w", second_instance=True)
    scoped = CatalogSession(capture, tmp_path / "s1")
    plan = scoped.plan([rw.DAY], ["SFO"])[("SFO", rw.DAY)]
    window = query_window_ns("SFO", rw.DAY)
    got = scoped.read(plan, window)
    scoped.close()
    _whole_instance(monkeypatch)
    reference = CatalogSession(capture, tmp_path / "s2")
    want = reference.read(plan, window)
    reference.close()
    assert got == want
    assert any(s.frames and s.prints for s in got) and any(s.truncations for s in got)
    assert any(g.end_ns is None for s in got for g in s.gaps)  # an unresolved gap survives
    seen = {f.rung for s in got for f in s.frames} | {p.rung for s in got for p in s.prints}
    assert seen <= set(plan.instruments)  # no NO leg, direction rung or substring rung leaks
    assert not [r for r in seen if r.endswith(("^no", "fx"))]


def test_a_cached_instance_is_reconverted_for_a_wider_rung_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = rw.build_capture(tmp_path / "w")
    session = CatalogSession(capture, tmp_path / "scratch")
    plan = session.plan([rw.DAY], ["SFO"])[("SFO", rw.DAY)]
    window = query_window_ns("SFO", rw.DAY)
    narrow = session._read_instance("inst-a", plan.instruments[:1], window)
    wide = session._read_instance("inst-a", plan.instruments, window)
    assert {f.rung for f in narrow.frames} == set(plan.instruments[:1])
    assert {f.rung for f in wide.frames} == set(plan.instruments)
    session.close()


def test_first_print_converts_prints_of_licensed_rungs_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = rw.build_capture(tmp_path / "w")
    calls = _spy(monkeypatch, probe)
    first = probe.first_print_instant(capture, [rw.DAY], work_root=tmp_path / "fp")
    ids = [i for cls, i in calls if cls is TradeTick]
    assert ids and all(i is not None and OUT_OF_PLAN not in i and i for i in ids)
    assert first == rw._t("2026-09-28T21:00:00")


def test_the_memoized_preflight_scan_reuses_a_report_until_a_file_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = rw.build_capture(tmp_path / "w")
    scans: list[str] = []
    real = scan_instance

    def counting(root: Path, instance: str, subdirectory: str) -> Any:
        scans.append(instance)
        return real(root, instance, subdirectory)

    monkeypatch.setattr(scoped, "scan_instance", counting)
    first = scoped.scan_instance_memoized(capture, "inst-a", DEFAULT_SUBDIRECTORY)
    assert scoped.scan_instance_memoized(capture, "inst-a", DEFAULT_SUBDIRECTORY) is first
    assert first == real(capture, "inst-a", DEFAULT_SUBDIRECTORY) and scans == ["inst-a"]
    victim = next((capture / "live" / "inst-a").rglob("*.feather"))
    victim.write_bytes(victim.read_bytes() + b"\0")  # a live writer appended
    scoped.scan_instance_memoized(capture, "inst-a", DEFAULT_SUBDIRECTORY)
    assert scans == ["inst-a", "inst-a"]
    with pytest.raises(PreflightError):
        scoped.scan_instance_memoized(capture, "no-such-instance", DEFAULT_SUBDIRECTORY)


def _whole_probe(monkeypatch: pytest.MonkeyPatch) -> None:
    real = ingest_core.default_convert

    def whole(source: Any, instance: str, data_cls: Any, *a: Any, **k: Any) -> Any:
        k.pop("identifiers", None)
        return real(source, instance, data_cls, *a, **k)

    monkeypatch.setattr(probe, "default_convert", whole)


def test_first_print_and_probe_match_the_whole_instance_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = rw.build_capture(tmp_path / "w")
    days = {rw.DAY, rw.DIRECTION_DAY}
    first = probe.first_print_instant(capture, days, work_root=tmp_path / "a1")
    report = probe.probe(capture, days, ("SFO",), work_root=tmp_path / "a2", first_print_ns=first)
    _whole_probe(monkeypatch)
    want_first = probe.first_print_instant(capture, days, work_root=tmp_path / "b1")
    want = probe.probe(capture, days, ("SFO",), work_root=tmp_path / "b2", first_print_ns=first)
    assert first == want_first
    assert report.to_dict() == want.to_dict()
    only_day = probe.first_print_instant(capture, [rw.DAY], work_root=tmp_path / "c1")
    assert only_day == rw._t("2026-09-28T21:00:00")  # the earlier NO-leg print is never licensed


def test_a_flat_layout_instance_is_still_read_by_first_print(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = rw.build_capture(tmp_path / "w")
    stream = capture / "live" / "inst-a" / "trade_tick"
    for n, path in enumerate(sorted(stream.rglob("*.feather"))):
        path.rename(stream.parent / f"trade_tick_{n}.feather")
    for rung_dir in [d for d in stream.iterdir() if d.is_dir()]:
        rung_dir.rmdir()
    stream.rmdir()  # flat layout: no per-rung directory, native falls back to trade_tick_*.feather
    scoped_first = probe.first_print_instant(capture, [rw.DAY], work_root=tmp_path / "a")
    _whole_probe(monkeypatch)
    assert scoped_first == probe.first_print_instant(capture, [rw.DAY], work_root=tmp_path / "b")
    assert scoped_first == rw._t("2026-09-28T21:00:00")


def test_a_non_instrument_directory_name_is_never_licensed() -> None:
    keep = scoped.licensed_rung_filter([rw.DAY], ["SFO"])
    assert keep("not an instrument id") is False
    assert keep(OUT_OF_PLAN) is False
    assert keep(_slug("sfo", "gte86f", rw.DAY.isoformat()) + ".POLYMARKET_US") is True


def test_a_failed_conversion_removes_its_scratch_dir_and_a_retry_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = rw.build_capture(tmp_path / "w")
    scratch = tmp_path / "scratch"
    session = CatalogSession(capture, scratch)
    plan = session.plan([rw.DAY], ["SFO"])[("SFO", rw.DAY)]
    window = query_window_ns("SFO", rw.DAY)
    real = ingest_core.default_convert

    def boom(source: Any, instance: str, data_cls: Any, *a: Any, **k: Any) -> Any:
        if data_cls is TradeTick:
            raise RuntimeError("conversion failed")
        return real(source, instance, data_cls, *a, **k)

    monkeypatch.setattr(catalog_read, "default_convert", boom)
    with pytest.raises(RuntimeError, match="conversion failed"):
        session.read(plan, window)
    assert not (scratch / "replay" / "inst-a").exists()
    monkeypatch.setattr(catalog_read, "default_convert", real)
    assert session.read(plan, window)[0].frames  # not FileExistsError
    session.close()


def test_default_convert_scopes_only_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = rw.build_capture(tmp_path / "w")
    source = ParquetDataCatalog(str(capture))
    seen: list[Any] = []
    real = ParquetDataCatalog._list_feather_data_files

    def spy(self: Any, kind: str, instance_id: str, data_cls: Any, identifiers: Any = None) -> Any:
        seen.append(identifiers)
        return real(self, kind, instance_id, data_cls, identifiers)

    monkeypatch.setattr(ParquetDataCatalog, "_list_feather_data_files", spy)
    everything = ParquetDataCatalog(str(tmp_path / "all"))
    ingest_core.default_convert(source, "inst-a", TradeTick, "live", target=everything)
    assert seen == [None]  # native called exactly as before: no identifier filter
    assert everything.query(data_cls=TradeTick)
    nothing = ParquetDataCatalog(str(tmp_path / "none"))
    seen.clear()
    ingest_core.default_convert(source, "inst-a", TradeTick, "live", target=nothing, identifiers=[])
    assert seen == [] and nothing.query(data_cls=TradeTick) == []  # [] must not mean "no filter"
