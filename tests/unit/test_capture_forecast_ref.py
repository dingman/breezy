"""AUT-1 WP1 part B: ``resolve_forecast_ref`` (plan r12 section 3.3.1; R-B; WP0-R6, WP0-R8).

The oracle is the REAL ``ForecastQuantileStateActor``, fed the same ``ForecastPoint`` objects FQ
consumes. The resolver rebuilds the vector from the boot's STREAMED points, written by the real
``CaptureStreamWriter`` and read back from disk, and must equal what FQ held at the decision.
"""

import ast
from pathlib import Path
from typing import Any

import pytest

from breezy.analysis import capture_forecast_ref
from breezy.analysis.capture_forecast_ref import ForecastRefStatus, resolve_forecast_ref
from breezy.domain.forecast_point import ForecastPoint
from breezy.persistence.autonomy.capture_reader import read_capture_stream
from breezy.strategy.ladder_ev import forecast_subscriber
from breezy.strategy.ladder_ev.forecast_subscriber import ForecastQuantileStateActor
from tests.unit.capture_reader_support import (
    HOUR_NS,
    STATION,
    STD_OFFSET_HOURS,
    boot_dir,
    forecast_point,
    full_cycle,
    open_stream,
    write_all,
)

CYCLE = 100 * HOUR_NS
V0 = CYCLE + 2 * HOUR_NS  # the full cycle's vintage
V1 = CYCLE + 3 * HOUR_NS  # a reissue's vintage


def _fq_state() -> ForecastQuantileStateActor:
    return ForecastQuantileStateActor(
        stations=(STATION,), std_utc_offset_hours={STATION: STD_OFFSET_HOURS}
    )


def _stream_of(tmp_path: Path, points: list[ForecastPoint]) -> Any:
    stream = open_stream(tmp_path)
    write_all(stream, list(points))
    stream.close()
    return read_capture_stream(boot_dir(tmp_path))


def _resolve(stream: Any, available_at_ns: int, *, cycle_ns: int = CYCLE) -> Any:
    return resolve_forecast_ref(
        stream,
        STATION,
        cycle_ns,
        available_at_ns,
        std_utc_offset_hours=STD_OFFSET_HOURS,
    )


def test_forecast_ref_resolves_to_vector_equal_to_strategy_state(tmp_path: Path) -> None:
    """WP0-R8 unit check: the replayed vector equals FQ's own, including noise FQ ignores."""
    noise = [
        forecast_point("TXN_Q10", 1.0, station="KSFO"),  # a station this FQ does not serve
        forecast_point("TXN_Q10", 2.0, model="NBM_NBS"),  # a foreign model
        forecast_point("TMP", 3.0),  # a foreign variable
    ]
    points = [*noise, *full_cycle()]
    fq = _fq_state()
    for point in points:
        fq.on_data(point)
    held = fq.state_for(STATION).value_at(V0)
    assert held is not None
    stream = _stream_of(tmp_path, points)

    resolved = _resolve(stream, held.available_at_ns)

    assert resolved.status is ForecastRefStatus.RESOLVED
    assert resolved.vector == held  # every field, including climate_day and model_version
    assert resolved.reason == ""


def test_reissue_replays_as_fq_pushed_it(tmp_path: Path) -> None:
    """A reissue overwrites exactly as it did live, and a ref to the earlier vintage still gets the
    earlier vector (the later reissue is filtered by ``available_at_ns``).

    MUTATION (red): ignoring the ``available_at_ns <= ref`` filter returns the reissued vector for
    the early ref; replaying out of stream order changes which value wins.
    """
    reissue = forecast_point("TXN_Q50", 99.5, issuance_seq=1, lag_ns=3 * HOUR_NS)
    points = [*full_cycle(), reissue]
    fq = _fq_state()
    for point in full_cycle():
        fq.on_data(point)
    before = fq.state_for(STATION).value_at(V0)
    fq.on_data(reissue)
    after = fq.state_for(STATION).value_at(V1)
    assert before is not None and after is not None and before != after
    assert (before.q50, after.q50) == (72.0, 99.5)
    stream = _stream_of(tmp_path, points)

    assert _resolve(stream, V0).vector == before
    assert _resolve(stream, V1).vector == after


def test_vintage_mismatch_is_unresolved(tmp_path: Path) -> None:
    """The complete vector's own vintage must equal the cited one.

    MUTATION (red): accepting the vector without comparing vintages resolves both off-by-one refs.
    """
    stream = _stream_of(tmp_path, full_cycle())
    assert _resolve(stream, V0).status is ForecastRefStatus.RESOLVED
    for cited in (V0 + 1, V0 - 1):
        resolved = _resolve(stream, cited)
        assert resolved.status is ForecastRefStatus.UNRESOLVED, cited
        assert resolved.vector is None
    assert _resolve(stream, V0 + 1).reason == "vintage_mismatch"


def test_unresolved_when_the_stream_cannot_rebuild_a_complete_vector(tmp_path: Path) -> None:
    partial = full_cycle()[:-1]  # TXN_SD never streamed
    stream = _stream_of(tmp_path, partial)
    incomplete = _resolve(stream, V0)
    assert (incomplete.status, incomplete.reason) == (
        ForecastRefStatus.UNRESOLVED,
        "incomplete_vector",
    )
    (tmp_path / "empty").mkdir()
    empty = _stream_of(tmp_path / "empty", [])
    no_points = _resolve(empty, V0)
    assert (no_points.status, no_points.reason) == (ForecastRefStatus.UNRESOLVED, "no_points")


def test_other_cycle_and_other_station_points_never_resolve_the_cited_cycle(
    tmp_path: Path,
) -> None:
    other_cycle = full_cycle(cycle_ns=CYCLE + 6 * HOUR_NS)
    other_station = full_cycle(station="KSFO")
    stream = _stream_of(tmp_path, [*other_cycle, *other_station])
    assert _resolve(stream, V0).status is ForecastRefStatus.UNRESOLVED
    assert _resolve(stream, V0).reason == "no_points"


def test_absent_value_points_are_skipped_as_fq_skips_them(tmp_path: Path) -> None:
    """An absence never completes a vector: the cycle is incomplete until a real value arrives.

    MUTATION (red): treating ``value_f=None`` as a pushed value resolves the early ref.
    """
    absent_mean = forecast_point("TXN_MEAN", None, lag_ns=2 * HOUR_NS)
    present_mean = forecast_point("TXN_MEAN", 75.0, issuance_seq=1, lag_ns=3 * HOUR_NS)
    others = [p for p in full_cycle() if p.variable != "TXN_MEAN"]
    points = [*others, absent_mean, present_mean]
    fq = _fq_state()
    for point in points:
        fq.on_data(point)
    held = fq.state_for(STATION).value_at(V1)
    assert held is not None and held.available_at_ns == V1
    stream = _stream_of(tmp_path, points)

    early = _resolve(stream, V0)
    assert early.status is ForecastRefStatus.UNRESOLVED and early.reason == "incomplete_vector"
    assert _resolve(stream, V1).vector == held


def test_resolver_requires_the_station_offset_and_is_pure(tmp_path: Path) -> None:
    stream = _stream_of(tmp_path, full_cycle())
    with pytest.raises(TypeError):
        resolve_forecast_ref(stream, STATION, CYCLE, V0)  # type: ignore[call-arg]
    first = _resolve(stream, V0)
    second = _resolve(stream, V0)
    assert first == second


def test_module_exports_are_pinned() -> None:
    assert {"ForecastRefStatus", "ForecastRefResolution", "resolve_forecast_ref"} <= set(
        capture_forecast_ref.__all__
    )


@pytest.mark.parametrize("case", ["foreign_model", "foreign_variable", "unserved_station"])
def test_foreign_model_and_foreign_variable_points_are_skipped_as_fq_skips_them(
    tmp_path: Path, case: str
) -> None:
    """py H2: the real actor is the oracle for each filter the mirror copies. The noise point is
    pushed AFTER the real cycle and would change (or break) the vector if it were not skipped.

    MUTATION (red, M5): deleting the model filter overwrites ``TXN_Q10`` from a foreign model.
    """
    noise = {
        "foreign_model": forecast_point("TXN_Q10", 1.0, model="NBM_NBS"),
        "foreign_variable": forecast_point("TMP", 3.0),
        "unserved_station": forecast_point("TXN_Q10", 1.0, station="KSFO"),
    }[case]
    points = [*full_cycle(), noise]
    fq = _fq_state()
    for point in points:
        fq.on_data(point)
    held = fq.state_for(STATION).value_at(V0)
    assert held is not None and held.q10 == 70.0
    counters = fq.counters
    assert (
        counters[
            {
                "foreign_model": "foreign_model",
                "foreign_variable": "foreign_variable",
                "unserved_station": "unknown_station",
            }[case]
        ]
        == 1
    )
    resolved = _resolve(_stream_of(tmp_path, points), V0)
    assert resolved.status is ForecastRefStatus.RESOLVED
    assert resolved.vector == held


def test_the_model_constant_is_the_one_fq_filters_on() -> None:
    """No second copy of the literal: the module re-exports the subscriber's own constant."""
    tree = ast.parse(Path(capture_forecast_ref.__file__).read_text(encoding="utf-8"))
    defined = [
        t.id
        for node in tree.body
        if isinstance(node, ast.Assign | ast.AnnAssign)
        for t in ([node.target] if isinstance(node, ast.AnnAssign) else node.targets)
        if isinstance(t, ast.Name)
    ]
    assert "NBP_QUANTILE_MODEL" not in defined
    assert capture_forecast_ref.NBP_QUANTILE_MODEL == forecast_subscriber.NBP_QUANTILE_MODEL


def test_the_forecast_ref_module_import_closure_is_free_of_ingest_runtime_and_the_actor() -> None:
    """S2-R26: the audit CLI imports this module at module level, so its closure stays pure."""
    import subprocess
    import sys

    src = str(Path(capture_forecast_ref.__file__).parents[2])
    code = (
        "import sys\n"
        f"sys.path.insert(0, {src!r})\n"  # -I ignores PYTHONPATH
        "import breezy.analysis.capture_forecast_ref\n"
        "banned = ('httpx', 'breezy.ingest', 'breezy.runtime', 'nautilus_trader.common.actor')\n"
        "bad = sorted(m for m in sys.modules if m in banned"
        " or any(m.startswith(b + '.') for b in banned))\n"
        "print(bad)\n"
        "raise SystemExit(1 if bad else 0)\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=False
    )
    assert done.returncode == 0, done.stdout + done.stderr
