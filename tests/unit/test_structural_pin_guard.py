"""RED-first suite for ``breezy.runtime.structural_pin_guard``.

The v2 tally's structural-dead pin is READY only when the node-env pre-flight
token is exactly ``MATCH`` and UTC wall time is at or after
``LAUNCH_WINDOW_END_UTC``. Pre-launch MATCH is PRE_LAUNCH, not READY. Kalshi is
NOT_APPLICABLE. The module is a pure predicate plus a ``main(argv) -> int``
CLI the wrapper invokes; it has no default HOME path (L-27).
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Self

import pytest

from breezy.runtime.trade_supervisor_core import LAUNCH_WINDOW_END_UTC

_REAL_HOME = Path.home()
_REAL_TALLY_LOG = _REAL_HOME / ".local" / "share" / "breezy" / "derived" / "family_tally_v2.log"

_PM_FAMILY = "pm_us_crh_v2"
_KALSHI_FAMILY = "kalshi_crh_v1"
_POST_LAUNCH = dt.time(17, 15)
_PRE_LAUNCH = dt.time(15, 30)


def _stat_or_none(path: Path) -> tuple[int, float] | None:
    try:
        stat_result = path.stat()
    except FileNotFoundError:
        return None
    return (stat_result.st_size, stat_result.st_mtime)


@pytest.fixture(scope="module", autouse=True)
def _guard_real_tally_log_untouched() -> Iterator[None]:
    """L-27: this suite must not write the operator's real tally log."""
    before = _stat_or_none(_REAL_TALLY_LOG)
    yield
    after = _stat_or_none(_REAL_TALLY_LOG)
    assert after == before, (
        "a test in tests/unit/test_structural_pin_guard.py modified the REAL "
        f"tally log at {_REAL_TALLY_LOG} -- (size, mtime) changed from "
        f"{before} to {after}"
    )


def _load_guard() -> ModuleType:
    import breezy.runtime.structural_pin_guard as guard

    return guard


def test_pre_launch_non_match_is_pre_launch_not_ready() -> None:
    guard = _load_guard()
    for token in ("NO_NODE", "refused"):
        assert (
            guard.evaluate_pin_gate(_PM_FAMILY, token, _PRE_LAUNCH) == "PRE_LAUNCH"
        ), token


def test_pre_launch_match_is_pre_launch_not_ready() -> None:
    guard = _load_guard()
    assert guard.evaluate_pin_gate(_PM_FAMILY, "MATCH", _PRE_LAUNCH) == "PRE_LAUNCH"


def test_match_just_before_launch_utc_is_pre_launch() -> None:
    """16:49 UTC is still before the day's first Take is legal."""
    guard = _load_guard()
    assert guard.evaluate_pin_gate(_PM_FAMILY, "MATCH", dt.time(16, 49)) == "PRE_LAUNCH"


def test_match_inside_launch_window_is_pre_launch_not_ready() -> None:
    """Persistent=true catch-up at 16:55 must not write a binding report."""
    guard = _load_guard()
    assert guard.evaluate_pin_gate(_PM_FAMILY, "MATCH", dt.time(16, 55)) == "PRE_LAUNCH"


def test_post_launch_non_match_is_unavailable() -> None:
    guard = _load_guard()
    assert guard.evaluate_pin_gate(_PM_FAMILY, "NO_NODE", _POST_LAUNCH) == "UNAVAILABLE"


def test_post_launch_match_is_ready() -> None:
    guard = _load_guard()
    assert guard.evaluate_pin_gate(_PM_FAMILY, "MATCH", _POST_LAUNCH) == "READY"
    assert guard.evaluate_pin_gate(_PM_FAMILY, "MATCH", LAUNCH_WINDOW_END_UTC) == "READY"


def test_match_is_exact_not_a_set() -> None:
    guard = _load_guard()
    assert guard.REQUIRED_TOKEN == "MATCH"
    assert guard.evaluate_pin_gate(_PM_FAMILY, "MATCH", _POST_LAUNCH) == "READY"
    for token in ("NO_NODE", "MISMATCH", "DISCOVERY_FAILED", "refused", "match", "MATCH "):
        assert guard.evaluate_pin_gate(_PM_FAMILY, token, _POST_LAUNCH) == "UNAVAILABLE", token


def test_kalshi_is_not_applicable() -> None:
    guard = _load_guard()
    assert guard.evaluate_pin_gate(_KALSHI_FAMILY, "MATCH", _POST_LAUNCH) == "NOT_APPLICABLE"
    assert guard.evaluate_pin_gate(_KALSHI_FAMILY, "NO_NODE", _PRE_LAUNCH) == "NOT_APPLICABLE"


@pytest.mark.parametrize(
    ("argv", "expected_rc", "stderr_token"),
    [
        (["--family", _PM_FAMILY, "--token", "MATCH", "--now", "17:15"], 0, None),
        (["--family", _KALSHI_FAMILY, "--token", "MATCH", "--now", "17:15"], 0, None),
        (["--family", _PM_FAMILY, "--token", "MATCH", "--now", "15:30"], 1, "MATCH"),
        (["--family", _PM_FAMILY, "--token", "NO_NODE", "--now", "17:15"], 1, "NO_NODE"),
        (["--family", _PM_FAMILY, "--token", "refused", "--now", "17:15"], 1, "refused"),
        ([], 2, None),
        (["--family", _PM_FAMILY], 2, None),
        (["--token", "MATCH"], 2, None),
        (["--family", _PM_FAMILY, "--token", "MATCH", "--now", "not-a-time"], 2, None),
    ],
)
def test_main_exit_codes_per_label(
    argv: list[str],
    expected_rc: int,
    stderr_token: str | None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    guard = _load_guard()
    rc = guard.main(argv)
    captured = capsys.readouterr()
    assert rc == expected_rc
    if expected_rc == 1:
        assert stderr_token is not None
        assert stderr_token in captured.err
        assert "PRE_LAUNCH" in captured.err or "UNAVAILABLE" in captured.err
    if expected_rc == 2:
        assert "usage" in captured.err.lower() or "--family" in captured.err


def test_main_missing_now_reads_utc_not_host_local(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing ``--now`` must call ``datetime.now(UTC)``, never host local."""
    guard = _load_guard()

    class _FrozenDateTime(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> Self:
            if tz is dt.UTC:
                return cls(2026, 9, 6, 17, 15, tzinfo=dt.UTC)
            return cls(2026, 9, 6, 15, 0)

    monkeypatch.setattr(guard.dt, "datetime", _FrozenDateTime)
    rc = guard.main(["--family", _PM_FAMILY, "--token", "MATCH"])
    assert rc == 0
    capsys.readouterr()
