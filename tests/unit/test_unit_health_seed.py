"""X-14: ``--seed-cursor-now`` drops journal history only (WP3 S6)."""

from __future__ import annotations

from pathlib import Path

import pytest

from breezy.runtime import autonomy_health_cli as cli
from breezy.runtime.unit_health_seed import (
    EXIT_CURSOR_EXISTS,
    EXIT_LOCKED,
    REASON,
    run_seed_cursor,
)
from breezy.runtime.unit_health_store import NS, HealthStore, day_of_ns

NOW = 1_791_548_400 * NS


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "unit_health"
    root.mkdir()
    return root


def test_seed_writes_a_since_now_cursor_and_journals_the_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root(tmp_path)
    assert run_seed_cursor(root, now_ns=lambda: NOW) == 0
    state = HealthStore(root).read_cursor()
    assert state is not None and state.cursor is None
    assert state.since_us == NOW // 1000 and state.ts_ns == NOW
    (record,) = HealthStore(root).cursor_reset_records(day_of_ns(NOW))
    assert record["reason"] == REASON == "activation_baseline"
    assert "AUTONOMY_HEALTH_SEED" in capsys.readouterr().out


def test_seed_refuses_when_a_cursor_exists_and_writes_nothing(tmp_path: Path) -> None:
    root = _root(tmp_path)
    store = HealthStore(root)
    store.write_cursor("s=abc", NOW - NS, None)
    assert run_seed_cursor(root, now_ns=lambda: NOW) == EXIT_CURSOR_EXISTS
    state = store.read_cursor()
    assert state is not None and state.cursor == "s=abc"
    assert store.cursor_reset_records(day_of_ns(NOW)) == []


def test_seed_refuses_while_a_pass_holds_the_lock(tmp_path: Path) -> None:
    root = _root(tmp_path)
    store = HealthStore(root)
    with store.lock() as held:
        assert held
        assert run_seed_cursor(root, now_ns=lambda: NOW) == EXIT_LOCKED
    assert store.read_cursor() is None


def test_main_routes_the_flag_and_rejects_it_beside_other_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: list[int] = []

    def seed() -> int:
        seen.append(1)
        return 0

    monkeypatch.setattr(cli, "run_seed_cursor_default", seed)
    assert cli.main(["--seed-cursor-now"]) == 0 and seen == [1]
    assert cli.main(["--seed-cursor-now", "--dry-run"]) == cli.EXIT_USAGE
    assert seen == [1]
