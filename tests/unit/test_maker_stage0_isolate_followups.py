"""MAKER-S2 S-5 follow-ups (test-only): differing ladder parity across days, a real S-6 violation.

Fixture world only. (a) one station carries two replayable days whose ladders have different lower
edge parity: the isolated run (default) and the in-process run must agree in every output and the
earlier day must win the parity. (d) ``assert_before_local_midnight`` really fails inside a spawned
child, through the real ``_run_in_child`` path, and voids the run with the violation's own type.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.analysis import maker_stage0_driver as drv
from scripts.analysis import maker_stage0_events_build as eb
from scripts.analysis import maker_stage0_isolate as iso
from tests.fixtures.maker_stage0 import replay_world as rw
from tests.fixtures.maker_stage0 import two_parity_world as tpw
from tests.unit import test_maker_stage0_driver as drv_fx
from tests.unit import test_maker_stage0_isolate as iso_t
from tests.unit import test_maker_stage0_pno as pno_fx


@pytest.fixture(autouse=True)
def _calibration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(drv, "load_calibration", lambda _model: pno_fx._calibration())


# --- module-level so the spawned child can import it (patched over ``_child_main``) -------------

EARLY_LIMIT_NS = int(dt.datetime(2026, 9, 28, tzinfo=dt.UTC).timestamp()) * 10**9


def child_with_premise_broken(conn: Any, ctx: Any, key: Any, work_dir: Path, *rest: Any) -> None:
    """The real child body, with this child's idea of local midnight moved before every episode.

    Every real ``assert_before_local_midnight`` call and every real episode are untouched; only the
    midnight the episode is compared with is earlier than the process window (the S-6 premise).
    """
    eb._local_midnight_ns = lambda _station, _day: EARLY_LIMIT_NS  # type: ignore[assignment]
    iso._child_main(conn, ctx, key, work_dir, *rest)


def _days_with_books(out: Any) -> set[str]:
    """Climate days whose replay saw at least one depth frame (a ladder that really ran)."""
    rows = next(iter(out.rows.values()))
    return {r.climate_day for r in rows if r.n_depth_frames}


def test_first_day_parity_wins_and_isolated_equals_in_process_for_differing_ladders(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "world"
    built = rw.build_world(root, capture=tpw.build_two_parity_capture(root))
    seen = iso_t._capture_out(monkeypatch)
    child = iso_t._run(built, tmp_path / "child", isolate=True)
    local = iso_t._run(built, tmp_path / "local", isolate=False)
    assert iso_t._comparable(seen[0]) == iso_t._comparable(seen[1])
    names = {p.name for p in child.out_dir.iterdir()}
    assert names == {p.name for p in local.out_dir.iterdir()}
    for name in sorted(names - iso_t.VOLATILE):
        assert iso_t._normalised(child, name) == iso_t._normalised(local, name), name
    replayed = _days_with_books(seen[0])
    assert {rw.DAY.isoformat(), tpw.ODD_DAY.isoformat()} <= replayed  # both ladders really ran
    assert max(replayed) == tpw.ODD_DAY.isoformat()  # the odd ladder is the LAST replayed day
    assert tpw.FIRST_DAY_PARITY != tpw.LATER_DAY_PARITY
    assert seen[0].parity == {"SFO": tpw.FIRST_DAY_PARITY} == seen[1].parity
    manifest = json.loads((child.out_dir / "run_manifest.json").read_text())
    assert manifest["ladder_lower_parity"] == {"SFO": tpw.FIRST_DAY_PARITY}


def test_a_real_local_midnight_violation_in_the_child_voids_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    built = rw.build_world(tmp_path / "world")
    monkeypatch.setattr(iso, "_child_main", child_with_premise_broken)
    cfg = drv_fx._fresh(built, tmp_path / "run")
    with pytest.raises(drv.RunVoided, match="LocalDayViolation") as info:
        drv.run(cfg)
    assert type(info.value.cause) is eb.LocalDayViolation
    assert "S-6" in str(info.value.cause) and "observation-cancel premise" in str(info.value.cause)
    assert drv_fx._void_dir(cfg).is_dir() and not cfg.out_dir.exists()
    assert [e["kind"] for e in drv_fx._ledger(cfg)] == ["verdict_run_start", "void"]
