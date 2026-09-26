"""T5' (ING-2 S3a, AC-S3-1): the coalesced read is bounded RSS, measured.

``tracemalloc`` cannot see Arrow/IPC allocations (Stage-0: pool
``bytes_allocated`` was 0 throughout), so every memory assertion here is a
child-process ``ru_maxrss`` delta (P2: a fresh interpreter via
``subprocess.run``, never ``multiprocessing`` fork).

Runs in the DEFAULT gate by design (r3-8): this is the only standing guard
against a regression back to ``read_all()``. Serial children, one at a time,
never alongside another heavy job (a full gate run, a Phase 0 arm, or a
nightly study) -- see ``tests/unit/_bounded_rss_child.py`` for the measured
process itself.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pyarrow as pa
import pytest
from nautilus_trader.model.data import InstrumentStatus
from nautilus_trader.model.enums import MarketStatusAction
from nautilus_trader.model.identifiers import InstrumentId
from nautilus_trader.serialization.arrow.serializer import ArrowSerializer

pytestmark = pytest.mark.memory

_CHILD_SCRIPT = Path(__file__).with_name("_bounded_rss_child.py")
_IID = InstrumentId.from_str("EUR/USD.SIM")

#: Design budget (plan r3): control ΔRSS ~0.53 GB expected at N=100K.
_CONTROL_DRIFT_CEILING_KIB = int(0.8 * 1024 * 1024)
_CONTROL_FLOOR_KIB = int(0.25 * 1024 * 1024)
_TREATMENT_RATIO_CEILING = 0.25
_SCALING_K = 2
_SCALING_SLACK_KIB = 32 * 1024


def _status(index: int) -> InstrumentStatus:
    return InstrumentStatus(
        instrument_id=_IID,
        action=MarketStatusAction.TRADING,
        ts_event=1_000_000_000 + index,
        ts_init=1_000_000_000 + index,
    )


def _write_stream(path: Path, count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    first = ArrowSerializer.serialize_batch([_status(0)], data_cls=InstrumentStatus)
    schema = first.schema
    with path.open("wb") as handle:
        writer = pa.ipc.new_stream(handle, schema)
        for i in range(count):
            piece = ArrowSerializer.serialize_batch([_status(i)], data_cls=InstrumentStatus)
            writer.write_table(piece)
        writer.close()


def _run_child(path: Path, warmup_path: Path, reader: str) -> dict[str, int]:
    result = subprocess.run(
        [
            sys.executable,
            str(_CHILD_SCRIPT),
            "--path",
            str(path),
            "--warmup-path",
            str(warmup_path),
            "--reader",
            reader,
        ],
        capture_output=True,
        text=True,
        check=True,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2] / "src")},
    )
    payload: dict[str, int] = json.loads(result.stdout.strip().splitlines()[-1])
    return payload


@pytest.fixture(scope="module")
def _fixtures(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    root = tmp_path_factory.mktemp("t5prime")
    warmup_path = root / "warmup" / "live" / "instance-w" / "instrument_status_0.feather"
    _write_stream(warmup_path, 10)

    path_100k = root / "n100k" / "live" / "instance-1" / "instrument_status_0.feather"
    _write_stream(path_100k, 100_000)

    path_200k = root / "n200k" / "live" / "instance-1" / "instrument_status_0.feather"
    _write_stream(path_200k, 200_000)

    return {"warmup": warmup_path, "n100k": path_100k, "n200k": path_200k}


def test_control_scales_far_faster_than_the_coalesced_treatment(
    _fixtures: dict[str, Path],
) -> None:
    control = _run_child(_fixtures["n100k"], _fixtures["warmup"], "native")
    treatment_100k = _run_child(_fixtures["n100k"], _fixtures["warmup"], "coalesced")
    treatment_200k = _run_child(_fixtures["n200k"], _fixtures["warmup"], "coalesced")

    # A transient OSError inside the child's native read (e.g. under extreme
    # host memory/swap pressure from a concurrent sibling session) is caught
    # by native `_read_feather_file` itself and returns `None`/`nbytes=0`,
    # which would otherwise surface as the confusing "control no longer
    # shows per-message cost" message below. Fail with the real cause instead.
    assert control["nbytes"] > 0, (
        "the native control read returned no table (nbytes=0) -- likely a "
        "transient read failure under host memory pressure, not a code "
        "regression; rerun in a quiet window before treating this as real"
    )

    control_delta_kib = control["peak_kb"] - control["baseline_kb"]
    treatment_100k_delta_kib = treatment_100k["peak_kb"] - treatment_100k["baseline_kb"]
    treatment_200k_delta_kib = treatment_200k["peak_kb"] - treatment_200k["baseline_kb"]

    assert control_delta_kib <= _CONTROL_DRIFT_CEILING_KIB, (
        f"control fixture drift: control ΔRSS={control_delta_kib / (1024 * 1024):.3f} GiB "
        f"exceeds the 0.8 GiB design ceiling"
    )
    assert control_delta_kib >= _CONTROL_FLOOR_KIB, (
        f"control no longer shows per-message cost: control ΔRSS="
        f"{control_delta_kib / (1024 * 1024):.3f} GiB is below the 0.25 GiB floor"
    )

    ratio = treatment_100k_delta_kib / control_delta_kib
    assert ratio <= _TREATMENT_RATIO_CEILING, (
        f"treatment ΔRSS ({treatment_100k_delta_kib} KiB) is {ratio:.1%} of control "
        f"({control_delta_kib} KiB); must be <= {_TREATMENT_RATIO_CEILING:.0%}"
    )

    nbytes_delta = treatment_200k["nbytes"] - treatment_100k["nbytes"]
    growth_kib = treatment_200k_delta_kib - treatment_100k_delta_kib
    bound_kib = _SCALING_K * (nbytes_delta / 1024) + _SCALING_SLACK_KIB
    assert growth_kib <= bound_kib, (
        f"coalesced-read ΔRSS growth from 100K->200K ({growth_kib} KiB) exceeds "
        f"k={_SCALING_K} * Δnbytes + 32MiB ({bound_kib:.0f} KiB)"
    )
