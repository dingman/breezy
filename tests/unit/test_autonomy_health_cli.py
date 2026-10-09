"""The ``breezy-autonomy-health`` entry (plan r15 sections 3.9 and 3.11; WP3 S6)."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.persistence.autonomy import pins
from breezy.persistence.autonomy.closure import ClosureUnavailable
from breezy.runtime import autonomy_health_cli as cli
from breezy.runtime.autonomy_sandbox.bus_handoff import BusSnapshotError
from breezy.runtime.unit_health_store import HealthStore, health_root
from breezy.runtime.unit_health_types import PassEnv
from tests.support.unit_health_fixtures import AlertRecorder, FakeClock

SHA: Final = "cd" * 32
SRC: Final = Path(cli.__file__).resolve().parents[2]
MARKER_ARGV: Final = [
    "--mark-buildside-restart",
    "breezy-trade-supervisor.service",
    "--reason",
    "merge",
    "--commit",
    "abcdef1",
]


class _NoJournal:
    def __getattr__(self, name: str) -> Any:  # a blind pass must never reach the journal
        raise AssertionError(f"journal.{name} used on a pass with no snapshot")


class _Wiring:
    """A ``production_env`` stand-in: records the data root and builds a blind (no-snapshot) env."""

    def __init__(self) -> None:
        self.roots: list[Path] = []
        self.alerts = AlertRecorder()
        self.seen_at_call: list[dict[str, Any] | None] = []
        self.clock = FakeClock()

    def __call__(
        self, *, environ: Any = None, data_root: Path | None = None, **_kw: Any
    ) -> PassEnv:
        assert data_root is not None
        self.roots.append(data_root)
        store = HealthStore(health_root(data_root))
        self.seen_at_call.append(store.read_heartbeat())

        def snapshot() -> Any:
            raise BusSnapshotError("snapshot_missing")

        return PassEnv(
            store=store,
            read_snapshot=snapshot,
            journal=_NoJournal(),
            alert=self.alerts,
            delivered=lambda event, site: False,
            now_ns=self.clock.wall,
            monotonic=self.clock.monotonic,
            worktrees=lambda timeout_s: (),
            meminfo=lambda: (8_000_000, 16_000_000),
            invocation_id="f" * 32,
        )


@pytest.fixture
def wiring(monkeypatch: pytest.MonkeyPatch) -> _Wiring:
    fake = _Wiring()
    monkeypatch.setattr(cli, "production_env", fake)
    monkeypatch.setattr(cli, "producer_pin_state", lambda: (True, SHA))
    return fake


def _tree(root: Path) -> dict[str, bytes]:
    return {
        str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()
    }


# --------------------------------------------------------------------------- routing


def test_main_routes_the_mark_flag_to_the_marker_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Sequence[str]] = []

    def marker(argv: Sequence[str]) -> int:
        seen.append(list(argv))
        return 7

    monkeypatch.setattr(cli, "run_mark_buildside", marker)
    assert cli.main(MARKER_ARGV) == 7
    assert seen == [MARKER_ARGV]


def test_main_runs_the_pass_by_default_and_a_dry_run_on_the_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bool] = []

    def run_pass(*, dry_run: bool = False) -> int:
        calls.append(dry_run)
        return 0

    monkeypatch.setattr(cli, "run_pass", run_pass)
    assert cli.main([]) == 0 and cli.main(["--dry-run"]) == 0
    assert calls == [False, True]


@pytest.mark.parametrize("argv", [["--bogus"], ["--dry-run", "extra"], ["breezy-x.service"]])
def test_main_rejects_unknown_arguments_without_running_anything(
    argv: list[str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(cli, "run_pass", lambda **_k: pytest.fail("the pass must not run"))
    assert cli.main(argv) == cli.EXIT_USAGE == 2
    assert "usage" in capsys.readouterr().err


def test_main_defaults_to_the_process_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["autonomy_health_cli", "--dry-run"])
    calls: list[bool] = []

    def run_pass(*, dry_run: bool = False) -> int:
        calls.append(dry_run)
        return 0

    monkeypatch.setattr(cli, "run_pass", run_pass)
    assert cli.main() == 0 and calls == [True]


# --------------------------------------------------------------------------- the pass


def test_pass_prints_one_summary_line_and_exits_zero_even_when_unknown(
    wiring: _Wiring, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "data"
    root.mkdir()
    assert cli.run_pass(data_root=root) == 0
    (line,) = capsys.readouterr().out.splitlines()
    assert line.startswith("AUTONOMY_HEALTH pass_result=UNKNOWN failed_units=unknown ")
    assert "snapshot_missing" in line and "fold_unreadable" in line and "dry_run=0" in line
    beat = HealthStore(health_root(root)).read_heartbeat()
    assert (
        beat is not None and beat["pass_result"] == "UNKNOWN" and beat["passes_unknown_streak"] == 1
    )


def test_the_fold_failure_is_paged_and_written_as_a_host_verdict(
    wiring: _Wiring, tmp_path: Path
) -> None:
    """F4: an unreadable fold pages directly and writes #26 FAIL under ``_host/``."""
    root = tmp_path / "data"
    root.mkdir()
    cli.run_pass(data_root=root)
    assert wiring.alerts.events == ["fold_unreadable"]
    (verdict,) = sorted((root / "derived" / "verdicts" / "_host").rglob("*.json"))
    text = verdict.read_text()
    assert '"detector":"aut6.producer_stale"' in text and SHA in text
    assert '"outcome":"FAIL"' in text and '"fold_reason":"unreadable"' in text


def test_an_unpinned_producer_refuses_to_run_and_touches_nothing(
    wiring: _Wiring,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "producer_pin_state", lambda: (False, SHA))
    root = tmp_path / "data"
    root.mkdir()
    assert cli.run_pass(data_root=root) == cli.EXIT_UNPINNED == 3
    assert "pass_result=REFUSED reason=producer_unpinned" in capsys.readouterr().out
    assert wiring.roots == [] and list(root.iterdir()) == []


# --------------------------------------------------------------------------- --dry-run


def test_dry_run_writes_nothing_to_the_live_root_and_removes_its_scratch(
    wiring: _Wiring, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "data"
    live = HealthStore(health_root(root))
    live.write_heartbeat({"schema": "health_heartbeat/v1", "ts_ns": 5, "passes_unknown_streak": 2})
    before = _tree(root)
    assert cli.run_pass(dry_run=True, data_root=root) == 0
    assert _tree(root) == before
    assert not (root / "derived").exists() and not (root / "evidence" / "alerts").exists()
    (scratch,) = wiring.roots
    assert scratch != root and not scratch.exists()
    out = capsys.readouterr().out
    assert "dry_run=1" in out
    assert "AUTONOMY_HEALTH_DRYRUN_FINDING finding=fold_unreadable unit=_host" in out
    assert wiring.alerts.events == ["fold_unreadable"]  # enqueued to the scratch outbox seam


def test_dry_run_starts_from_the_live_state_so_the_cursor_and_markers_apply(
    wiring: _Wiring, tmp_path: Path
) -> None:
    root = tmp_path / "data"
    live = HealthStore(health_root(root))
    live.write_heartbeat({"schema": "health_heartbeat/v1", "ts_ns": 99, "passes_unknown_streak": 4})
    marker = health_root(root) / "buildside_restart" / "2026-10-09" / "1_x.json"
    marker.parent.mkdir(parents=True)
    marker.write_text("{}")
    cli.run_pass(dry_run=True, data_root=root)
    assert wiring.seen_at_call[0] is not None and wiring.seen_at_call[0]["ts_ns"] == 99


def test_dry_run_does_not_need_the_pin(
    wiring: _Wiring, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(cli, "producer_pin_state", lambda: (False, "0" * 64))
    root = tmp_path / "data"
    root.mkdir()
    assert cli.run_pass(dry_run=True, data_root=root) == 0


def test_dry_run_copies_a_missing_health_tree_as_empty(wiring: _Wiring, tmp_path: Path) -> None:
    root = tmp_path / "data"
    root.mkdir()
    assert cli.run_pass(dry_run=True, data_root=root) == 0
    assert list(root.iterdir()) == []


# --------------------------------------------------------------------------- seams


def test_production_wiring_installs_the_fold_verdict_and_dropin_seams(
    wiring: _Wiring, tmp_path: Path
) -> None:
    """L-55: the production default of each seam the core leaves open is installed."""
    base = wiring(data_root=tmp_path)
    assert base.fold_probe is None and base.host_verdict is None and base.committed_dropins is None
    env = cli._wire(base, tmp_path, tmp_path, SHA)
    assert callable(env.fold_probe) and callable(env.host_verdict)
    assert env.committed_dropins is not None
    assert env.committed_dropins["us-source-collector@lav.service"] == frozenset({"runtime.conf"})


def test_committed_dropins_lists_each_unit_directory(tmp_path: Path) -> None:
    for unit, names in {
        "a.service.d": ["x.conf", "y.conf", "note.txt"],
        "b.timer.d": ["z.conf"],
    }.items():
        (tmp_path / unit).mkdir()
        for name in names:
            (tmp_path / unit / name).write_text("")
    (tmp_path / "plain.service").write_text("")
    assert cli.committed_dropins(tmp_path) == {
        "a.service": frozenset({"x.conf", "y.conf"}),
        "b.timer": frozenset({"z.conf"}),
    }


def test_committed_dropins_is_none_when_nothing_is_readable(tmp_path: Path) -> None:
    assert cli.committed_dropins(tmp_path) is None
    assert cli.committed_dropins(tmp_path / "missing") is None


def test_the_repository_drop_ins_are_the_committed_baseline() -> None:
    found = cli.committed_dropins()
    assert found is not None and "breezy.slice" in found


# --------------------------------------------------------------------------- the pin


def test_pin_state_is_unpinned_when_the_closure_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def gone(_component: str) -> str:
        raise ClosureUnavailable("planted")

    monkeypatch.setattr(cli, "closure_sha256", gone)
    assert cli.producer_pin_state() == (False, "0" * 64)


def test_pin_state_requires_the_pin_to_equal_the_closure_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "closure_sha256", lambda _component: SHA)
    assert cli.producer_pin_state() == (False, SHA)
    monkeypatch.setattr(pins, "PRODUCER_SOURCE_SHA256", {"aut6.health": "ee" * 32})
    assert cli.producer_pin_state() == (False, SHA)
    monkeypatch.setattr(pins, "PRODUCER_SOURCE_SHA256", {"aut6.health": SHA})
    assert cli.producer_pin_state() == (True, SHA)


# --------------------------------------------------------------------------- as a program


def _run_module(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "PYTHONPATH": str(SRC),
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    return subprocess.run(
        [sys.executable, "-m", "breezy.runtime.autonomy_health_cli", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=60,
    )


def test_the_module_runs_the_marker_subcommand_as_a_program(tmp_path: Path) -> None:
    done = _run_module(tmp_path, *MARKER_ARGV)
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith("BUILDSIDE_MARKER written=")
    markers = list((tmp_path / ".local/share/breezy/evidence/unit_health").rglob("*_breezy-*.json"))
    assert len(markers) == 1 and oct(markers[0].stat().st_mode & 0o777) == "0o444"


def test_the_module_exits_with_usage_status_on_a_bad_flag(tmp_path: Path) -> None:
    done = _run_module(tmp_path, "--nope")
    assert done.returncode == 2 and "usage" in done.stderr
    assert not (tmp_path / ".local").exists()
