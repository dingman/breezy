"""C7 stat-only instance pre-filter.

An instance whose newest feather is strictly older than the licensed block is not
converted. A tie is kept. An empty or unreadable signature fails open (scan).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import pyarrow as pa
import pytest
from nautilus_trader.model.enums import AggressorSide

from breezy.persistence.feather_preflight import DEFAULT_SUBDIRECTORY
from scripts.analysis import maker_stage0_catalog_read as catalog
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

    monkeypatch.setattr(p, "_prefilter_reason", keep, raising=False)


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


def _write_licensed_old(capture: Path) -> tuple[int, int]:
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


def _raise_on_definition_read(monkeypatch: pytest.MonkeyPatch, error: BaseException) -> None:
    def boom(*_args: object, **_kwargs: object) -> object:
        raise error

    mod = sys.modules[p._prefilter_reason.__module__]
    monkeypatch.setattr(mod, "_read_definition_instrument_ids", boom, raising=False)


def _probe_lax(capture: Path, work: Path) -> tuple[int | None, p.ProbeReport]:
    first = p.first_print_instant(capture, [_DAY], work_root=work / "fp", stations=_LAX)
    report = p.probe(capture, [_DAY], _LAX, work_root=work / "probe", first_print_ns=first)
    return first, report


def _without_skipped(report: p.ProbeReport) -> dict[str, Any]:
    body = report.to_dict()
    del body["skipped_instances"]
    return body


def test_prefilter_cutoff_none_on_empty_inputs() -> None:
    assert p.prefilter_cutoff_ns([], ["LAX"]) is None
    assert p.prefilter_cutoff_ns([_DAY], []) is None
    assert p.prefilter_cutoff_ns((), ()) is None


def test_prefilter_skips_only_instances_last_written_before_the_block(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cutoff = p.prefilter_cutoff_ns([_DAY], _LAX)
    assert cutoff == _ns("2026-09-20T12:00:00")
    capture = _capture(tmp_path)
    _minimal(capture, "tie")
    _minimal(capture, "old", city="nyc")
    _touch(capture / "live" / "tie", cutoff)
    _touch(capture / "live" / "old", cutoff - 1)
    (capture / "live" / "bad-inst").mkdir()
    foreign = tmp_path / "work" / "probe" / "old"
    foreign.mkdir(parents=True)
    (foreign / "marker").write_text("keep")
    seen = _spy(monkeypatch)

    _first, report = _probe_lax(capture, tmp_path / "work")

    assert report.skipped["old"] == (
        f"prefilter: last_written_ns {cutoff - 1} < cutoff_ns {cutoff}"
    )
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
    """One feather at or after the cutoff keeps the instance (newest mtime, not oldest)."""
    cutoff = _ns("2026-09-20T12:00:00")  # D-1 12:00Z minus one day; no call into the new seam
    capture = _capture(tmp_path)
    files = sorted((capture / "live" / "inst-a").rglob("*.feather"))
    assert len(files) >= 2
    for path in files:
        os.utime(path, ns=(cutoff - 1, cutoff - 1))
    os.utime(files[-1], ns=(cutoff, cutoff))

    kept_first, kept = _probe_lax(capture, tmp_path / "on")
    _disable(monkeypatch)
    off_first, off = _probe_lax(capture, tmp_path / "off")

    listed = _ns("2026-09-21T11:00:00")
    assert kept.coverage[0].listing_ns == listed
    assert off.coverage[0].listing_ns == listed
    assert kept.coverage == off.coverage
    assert kept.delta_instance_days == off.delta_instance_days
    assert kept_first == off_first
    assert "inst-a" not in kept.skipped


def test_prefilter_tie_keeps(tmp_path: Path) -> None:
    cutoff = p.prefilter_cutoff_ns([_DAY], _LAX)
    assert cutoff is not None
    capture = _capture(tmp_path)
    _touch(capture / "live" / "inst-a", cutoff)

    assert p._prefilter_reason(capture / "live" / "inst-a", cutoff) is None
    _first, report = _probe_lax(capture, tmp_path / "work")
    assert "inst-a" not in report.skipped
    assert report.depth_frames == 3
    assert report.coverage[0].listing_ns == _ns("2026-09-21T11:00:00")


def test_prefilter_future_mtime_keeps(tmp_path: Path) -> None:
    cutoff = p.prefilter_cutoff_ns([_DAY], _LAX)
    assert cutoff is not None
    capture = _capture(tmp_path)
    _touch(capture / "live" / "inst-a", cutoff + 86_400 * 1_000_000_000)

    assert p._prefilter_reason(capture / "live" / "inst-a", cutoff) is None
    _first, report = _probe_lax(capture, tmp_path / "work")
    assert "inst-a" not in report.skipped
    assert report.depth_frames == 3


def test_prefilter_oserror_keeps(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cutoff = p.prefilter_cutoff_ns([_DAY], _LAX)
    assert cutoff is not None
    capture = _capture(tmp_path)
    real = sc._signature

    def always_raise(_directory: Path) -> tuple[tuple[str, int, int], ...]:
        raise OSError("stat failed")

    monkeypatch.setattr(sc, "_signature", always_raise)
    assert p._prefilter_reason(capture / "live" / "inst-a", cutoff) is None

    calls = {"n": 0}

    def one_shot(directory: Path) -> tuple[tuple[str, int, int], ...]:
        if calls["n"] == 0:
            calls["n"] = 1
            raise OSError("stat failed")
        return real(directory)

    monkeypatch.setattr(sc, "_signature", one_shot)
    seen = _spy(monkeypatch)
    _first, report = _probe_lax(capture, tmp_path / "work")
    assert calls["n"] == 1
    assert "inst-a" in seen
    assert "inst-a" not in report.skipped
    assert report.depth_frames == 3


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
    assert on.skipped["old"] == f"prefilter: last_written_ns {cutoff - 1} < cutoff_ns {cutoff}"
    assert on_plan.keys() == off_plan.keys()
    for key, row in on_plan.items():
        assert row.instruments == off_plan[key].instruments
        assert row.instances == off_plan[key].instances
        assert row.catalog_bytes == off_plan[key].catalog_bytes
    assert set(on_skipped) - set(off_skipped) == {"old"}
    assert set(off_skipped) - set(on_skipped) == set()
    assert on_skipped["old"].startswith("prefilter:")


def test_prefilter_keeps_old_instance_that_holds_a_licensed_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ts_init = _ns("2026-09-19T00:00:00")
    print_ts = _ns("2026-09-22T05:40:00")
    cutoff = p.prefilter_cutoff_ns([_DAY], _LAX)
    assert cutoff == _ns("2026-09-20T12:00:00")
    capture = tmp_path / "capture"
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


def test_prefilter_keeps_licensed_instance_when_definitions_read_raises_oserror(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = tmp_path / "capture"
    _write_licensed_old(capture)
    _raise_on_definition_read(monkeypatch, OSError("read failed"))

    _first, report = _probe_lax(capture, tmp_path / "work")

    assert "licensed" not in report.skipped
    assert report.coverage[0].listing_ns is not None


def test_prefilter_keeps_licensed_instance_when_definitions_read_raises_arrow_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    capture = tmp_path / "capture"
    _write_licensed_old(capture)
    _raise_on_definition_read(monkeypatch, pa.ArrowInvalid("bad schema"))

    _first, report = _probe_lax(capture, tmp_path / "work")

    assert "licensed" not in report.skipped
    assert report.coverage[0].listing_ns is not None


def test_plan_pass_skips_and_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Imported for plan(), not re-exported (mypy no-implicit-reexport).
    assert catalog.__dict__["prefilter_cutoff_ns"] is p.prefilter_cutoff_ns
    cutoff = p.prefilter_cutoff_ns([_DAY], _LAX)
    assert cutoff is not None
    capture = _capture(tmp_path)
    _minimal(capture, "old", city="nyc")
    _touch(capture / "live" / "old", cutoff - 1)
    seen = _spy(monkeypatch)
    work = tmp_path / "plan-work"
    session = catalog.CatalogSession(capture, work)

    plan = session.plan([_DAY], _LAX)

    assert session.skipped["old"] == (
        f"prefilter: last_written_ns {cutoff - 1} < cutoff_ns {cutoff}"
    )
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
    _write_licensed_old(capture)
    session = catalog.CatalogSession(capture, tmp_path / "plan-on")

    plan = session.plan([_DAY], _LAX)

    assert "licensed" not in session.skipped
    key = ("LAX", _DAY)
    assert key in plan
    assert "licensed" in plan[key].instances
    _disable(monkeypatch)
    control = catalog.CatalogSession(capture, tmp_path / "plan-off")
    control_plan = control.plan([_DAY], _LAX)
    assert plan.keys() == control_plan.keys()
    for plan_key, row in plan.items():
        assert row.instruments == control_plan[plan_key].instruments
        assert row.instances == control_plan[plan_key].instances
        assert row.catalog_bytes == control_plan[plan_key].catalog_bytes
