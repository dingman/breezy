"""FQ loss response F2 FQ-TRUTH: the two parked truth units and the offline dataset.

The units are PARKED (committed, never installed); these tests read the text under
``deploy/systemd`` and never touch an installed unit path or ``systemctl``.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest

from tests.unit.test_iem_cli_fetch import (
    WINDOW_START,
    FakeFetcher,
    cli_body,
    fetch,  # noqa: F401  (module-scoped fixture)
    nyc_spec,
    run_fetch,
    tree_digest,
)
from tests.unit.test_launch_window_table import DEPLOYED_DIR, window_overlaps

DEPLOY_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
UNITS: Final[tuple[str, ...]] = ("breezy-truth-fetch", "breezy-truth-dataset")
FORBIDDEN_ENV: Final[tuple[str, ...]] = (
    "polymarket.env",
    "breezy-trade.env",
    "operator.env",
    "breezy.env",
)


def _directives(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _single(lines: list[str], name: str) -> str:
    values = [line.removeprefix(f"{name}=") for line in lines if line.startswith(f"{name}=")]
    assert len(values) == 1, f"expected exactly one {name}=, found {values}"
    return values[0]


@pytest.mark.parametrize("unit", UNITS)
def test_truth_units_bounded_and_outside_launch_window(unit: str) -> None:
    service = _directives(DEPLOY_DIR / f"{unit}.service")
    timer = _directives(DEPLOY_DIR / f"{unit}.timer")

    # Bounded: memory ceiling, both time bounds, failure alert, no restart.
    assert re.fullmatch(r"\d+[MG]", _single(service, "MemoryMax"))
    start_s = int(_single(service, "TimeoutStartSec"))
    runtime_s = int(_single(service, "RuntimeMaxSec"))
    assert 0 < start_s <= runtime_s <= 3600
    assert _single(service, "OnFailure") == "breezy-study-failed@%n.service"
    assert not any(line.startswith("Restart=") for line in service)

    # alerts.env is the only environment file; no venue or operator env anywhere.
    env_files = [
        line.removeprefix("EnvironmentFile=") for line in service if "EnvironmentFile" in line
    ]
    assert env_files == ["-%h/.config/breezy/alerts.env"]
    assert not any(name in line for line in service for name in FORBIDDEN_ENV)

    # Parked: only the timer is installable; the service carries no [Install].
    assert "[Install]" not in service
    assert "WantedBy=timers.target" in timer

    # Scheduled outside [16:30Z, 17:10Z) including each firing's worst-case runtime.
    assert window_overlaps(DEPLOYED_DIR, only_timer=unit) == []
    assert any(line.startswith("OnCalendar=*-*-* ") and line.endswith(" UTC") for line in timer)


def test_truth_units_run_the_script_with_the_right_subcommand() -> None:
    fetch_exec = _single(_directives(DEPLOY_DIR / "breezy-truth-fetch.service"), "ExecStart")
    dataset_exec = _single(_directives(DEPLOY_DIR / "breezy-truth-dataset.service"), "ExecStart")
    assert fetch_exec.endswith("scripts/archive/iem_cli_fetch.py fetch")
    assert dataset_exec.endswith("scripts/archive/iem_cli_fetch.py dataset")
    # The offline unit asks for no network ordering.
    dataset_lines = _directives(DEPLOY_DIR / "breezy-truth-dataset.service")
    assert not any("network-online" in line for line in dataset_lines)


# ---------------------------------------------------------------------------
# Offline dataset
# ---------------------------------------------------------------------------


class _NetworkTripwire:
    """Counts every attempt to reach IEM through the transport or the fetch entry point."""

    def __init__(self) -> None:
        self.attempts = 0

    async def fetch_cli_text(self, url: str) -> Any:
        self.attempts += 1
        raise AssertionError(f"dataset reached for the network: {url}")


def test_dataset_never_fetches_cache_miss_refused(
    fetch: ModuleType,  # noqa: F811
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    tripwire = _NetworkTripwire()

    async def tripped(self: Any, url: str) -> Any:
        return await tripwire.fetch_cli_text(url)

    monkeypatch.setattr(fetch.IemCliTransport, "fetch_cli_text", tripped)
    monkeypatch.setattr(fetch.IemCliTransport, "_fetch", tripped)

    async def tripped_fetch_all(**_kwargs: Any) -> Any:
        tripwire.attempts += 1
        raise AssertionError("dataset reached fetch_all")

    monkeypatch.setattr(fetch, "fetch_all", tripped_fetch_all)

    cache = tmp_path / "cache"
    cache.mkdir()
    out = tmp_path / "out"

    # Library path: an empty cache is a refusal.
    with pytest.raises(fetch.TruthCacheMissError):
        fetch.build_dataset(
            store=fetch.RevisionStore(cache),
            sites=[nyc_spec(fetch)],
            as_of=dt.date(2026, 8, 23),
            output_dir=out,
            window_start=WINDOW_START,
        )

    # CLI path (what the unit runs): exit 2, nothing written, no request attempted.
    code = fetch.main(["dataset", "--cache-dir", str(cache), "--output-dir", str(out)])
    assert code == fetch.EXIT_REFUSED
    assert "refused" in capsys.readouterr().err
    assert tripwire.attempts == 0
    assert not out.exists()
    assert tree_digest(cache) == {}


def test_coverage_gap_reported_not_zero(fetch: ModuleType, tmp_path: Path) -> None:  # noqa: F811
    cache, out = tmp_path / "cache", tmp_path / "out"
    present = [dt.date(2026, 8, 18), dt.date(2026, 8, 19), dt.date(2026, 8, 21)]
    run_fetch(fetch, cache, FakeFetcher(fetch, cli_body(present)), dt.date(2026, 8, 22))

    # The cache ends at D-1 = 08-21 but the dataset runs for as_of 08-24 (D-1 = 08-23).
    report = fetch.build_dataset(
        store=fetch.RevisionStore(cache),
        sites=[nyc_spec(fetch)],
        as_of=dt.date(2026, 8, 24),
        output_dir=out,
        window_start=WINDOW_START,
    )

    coverage = json.loads(report.coverage_path.read_text(encoding="utf-8"))
    station = coverage["stations"]["NYC"]
    assert coverage["through_d_minus_1"] == "2026-08-23"
    assert coverage["expected_days_per_station"] == 6
    assert station["final_days"] == 3
    assert station["coverage_gap"] == ["2026-08-20", "2026-08-22", "2026-08-23"]
    assert station["coverage_gap_days"] == 3
    assert coverage["coverage_gap_days"] == 3
    assert station["last_final_day"] == "2026-08-21"
    rows = report.csv_path.read_text(encoding="utf-8").splitlines()
    assert rows[0].startswith("station,city,climate_day,tmax_f")
    assert [row.split(",")[2] for row in rows[1:]] == [d.isoformat() for d in present]
    assert all(row.split(",")[3] == "85" for row in rows[1:])

    # A complete cache reports the field explicitly as zero, never by omission.
    complete = fetch.build_dataset(
        store=fetch.RevisionStore(cache),
        sites=[nyc_spec(fetch)],
        as_of=dt.date(2026, 8, 20),
        output_dir=tmp_path / "out2",
        window_start=WINDOW_START,
    )
    assert complete.coverage["stations"]["NYC"]["coverage_gap"] == []
    assert complete.coverage["coverage_gap_days"] == 0
