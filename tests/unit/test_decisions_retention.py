"""F-3 (STALL_FOLLOWUPS_F1_F4_2026-09-24.md): `scripts/ops/decisions_retention.py`.

Gzip-only, atomic, verified before rename; pruning ships disabled behind an
explicit opt-in flag. Every test builds its own throwaway `decisions/`
directory -- never the real `~/.local/share/breezy` state.
"""

from __future__ import annotations

import datetime as dt
import gzip
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, (REPO_ROOT / "scripts" / "ops").as_posix())

from decisions_retention import (
    DEFAULT_GZIP_OLDER_THAN_DAYS,
    gzip_eligible_files,
    prune_old_gz_files,
    run_retention,
)

_NOW = dt.datetime(2026, 9, 25, 12, 0, 0, tzinfo=dt.UTC)

_DEPLOY_DIR = REPO_ROOT / "deploy" / "systemd"
_WRAPPER = _DEPLOY_DIR / "decisions-retention-run.sh"
_SERVICE = _DEPLOY_DIR / "breezy-decisions-retention.service"
_TIMER = _DEPLOY_DIR / "breezy-decisions-retention.timer"


def _touch_with_mtime(path: Path, *, age_hours: float, content: str = "line1\nline2\n") -> None:
    path.write_text(content, encoding="utf-8")
    mtime = (_NOW - dt.timedelta(hours=age_hours)).timestamp()
    os.utime(path, (mtime, mtime))


def _decompress_text(path: Path) -> str:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return handle.read()


class TestGzipsOlderThanN:
    def test_default_gzip_older_than_days_is_seven(self) -> None:
        assert DEFAULT_GZIP_OLDER_THAN_DAYS == 7

    def test_gzips_older_than_n(self, tmp_path: Path) -> None:
        old = tmp_path / "offer_tape_2026-09-01.jsonl"
        _touch_with_mtime(old, age_hours=24 * 10)

        outcome = gzip_eligible_files(tmp_path, older_than_days=7, now=_NOW)

        assert outcome.gzipped == ("offer_tape_2026-09-01.jsonl",)
        assert not old.exists()
        gz = tmp_path / "offer_tape_2026-09-01.jsonl.gz"
        assert gz.is_file()
        assert _decompress_text(gz) == "line1\nline2\n"
        assert outcome.failed == ()

    def test_diagnostics_summary_files_are_also_eligible(self, tmp_path: Path) -> None:
        old = tmp_path / "diagnostics_summary_2026-09-01.jsonl"
        _touch_with_mtime(old, age_hours=24 * 10)

        outcome = gzip_eligible_files(tmp_path, older_than_days=7, now=_NOW)

        assert outcome.gzipped == ("diagnostics_summary_2026-09-01.jsonl",)

    def test_older_than_days_below_2_is_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(ValueError):
            gzip_eligible_files(tmp_path, older_than_days=1, now=_NOW)


class TestRecentMtimeUntouchedEvenIfNamedOld:
    def test_recent_mtime_file_untouched_even_if_named_old(self, tmp_path: Path) -> None:
        """A file NAMED with an old climate day but touched recently (a
        backdated reprocessing run) must be left alone -- age is judged by
        `stat().st_mtime`, never by the filename."""
        path = tmp_path / "offer_tape_2020-01-01.jsonl"
        _touch_with_mtime(path, age_hours=1)

        outcome = gzip_eligible_files(tmp_path, older_than_days=7, now=_NOW)

        assert outcome.gzipped == ()
        assert outcome.skipped_recent == ("offer_tape_2020-01-01.jsonl",)
        assert path.is_file()
        assert not (tmp_path / "offer_tape_2020-01-01.jsonl.gz").exists()

    def test_36h_floor_binds_even_when_older_than_days_would_allow(self, tmp_path: Path) -> None:
        path = tmp_path / "offer_tape_2026-09-24.jsonl"
        _touch_with_mtime(path, age_hours=24)  # < 36h, but older_than_days=1 not allowed anyway

        outcome = gzip_eligible_files(tmp_path, older_than_days=2, now=_NOW)

        assert outcome.gzipped == ()
        assert outcome.skipped_recent == ("offer_tape_2026-09-24.jsonl",)


class TestFailedGzipKeepsOriginal:
    @pytest.mark.parametrize("failure_point", ["write", "fsync", "verify", "rename"])
    def test_failed_gzip_keeps_original(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure_point: str
    ) -> None:
        import decisions_retention as mod

        old = tmp_path / "offer_tape_2026-09-01.jsonl"
        _touch_with_mtime(old, age_hours=24 * 10)
        original_text = old.read_text(encoding="utf-8")

        if failure_point == "write":
            def _boom_open(*args: object, **kwargs: object) -> object:
                raise OSError("simulated write failure")

            monkeypatch.setattr(mod.gzip, "open", _boom_open)
        elif failure_point == "fsync":
            def _boom_fsync(fd: int) -> None:
                raise OSError("simulated fsync failure")

            monkeypatch.setattr(mod.os, "fsync", _boom_fsync)
        elif failure_point == "verify":
            monkeypatch.setattr(mod, "_verify_gzip_matches", lambda original, gz: False)
        else:  # rename
            def _boom_replace(src: object, dst: object) -> None:
                raise OSError("simulated rename failure")

            monkeypatch.setattr(mod.os, "replace", _boom_replace)

        outcome = gzip_eligible_files(tmp_path, older_than_days=7, now=_NOW)

        assert outcome.failed == ("offer_tape_2026-09-01.jsonl",)
        assert outcome.gzipped == ()
        assert old.is_file()
        assert old.read_text(encoding="utf-8") == original_text
        assert not (tmp_path / "offer_tape_2026-09-01.jsonl.gz").exists()
        assert not (tmp_path / "offer_tape_2026-09-01.jsonl.gz.tmp").exists()


class TestVerifyMismatchKeepsOriginal:
    def test_verify_mismatch_keeps_original(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import decisions_retention as mod

        old = tmp_path / "offer_tape_2026-09-01.jsonl"
        _touch_with_mtime(old, age_hours=24 * 10)

        monkeypatch.setattr(mod, "_verify_gzip_matches", lambda original, gz: False)
        outcome = gzip_eligible_files(tmp_path, older_than_days=7, now=_NOW)

        assert outcome.failed == ("offer_tape_2026-09-01.jsonl",)
        assert old.is_file()
        assert not (tmp_path / "offer_tape_2026-09-01.jsonl.gz").exists()


class TestVerifyRunsBeforeRename:
    def test_verify_runs_before_rename(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rev 3.1: VERIFY happens before `os.replace` -- if verify is
        (correctly) never reached because it already failed, `os.replace`
        must never be called at all."""
        import decisions_retention as mod

        old = tmp_path / "offer_tape_2026-09-01.jsonl"
        _touch_with_mtime(old, age_hours=24 * 10)

        replace_calls: list[object] = []
        monkeypatch.setattr(mod, "_verify_gzip_matches", lambda original, gz: False)
        monkeypatch.setattr(
            mod.os, "replace", lambda src, dst: replace_calls.append((src, dst))
        )

        gzip_eligible_files(tmp_path, older_than_days=7, now=_NOW)

        assert replace_calls == []


class TestBothPresentIdempotent:
    def test_both_present_all_readers_count_once(self, tmp_path: Path) -> None:
        """A crash between rename and unlink leaves BOTH files. The next
        retention run re-verifies the existing `.gz` and unlinks the
        original -- it never re-writes a `.gz` that already verifies (its
        compressed CONTENT is untouched), and (review fix 2) its mtime ends
        up matching the original's, never its own earlier write-time mtime."""
        old = tmp_path / "offer_tape_2026-09-01.jsonl"
        _touch_with_mtime(old, age_hours=24 * 10, content="a\nb\nc\n")
        orig_mtime = old.stat().st_mtime
        gz = tmp_path / "offer_tape_2026-09-01.jsonl.gz"
        with gzip.open(gz, "wt", encoding="utf-8") as h:
            h.write("a\nb\nc\n")
        gz_bytes_before = gz.read_bytes()

        outcome = gzip_eligible_files(tmp_path, older_than_days=7, now=_NOW)

        assert outcome.gzipped == ("offer_tape_2026-09-01.jsonl",)
        assert not old.exists()
        assert gz.is_file()
        # The pre-existing .gz was re-verified, not re-written from scratch.
        assert gz.read_bytes() == gz_bytes_before
        # ...but its mtime is now aligned to the original's (review fix 2).
        assert gz.stat().st_mtime == orig_mtime

    def test_both_present_but_gz_does_not_verify_keeps_both(self, tmp_path: Path) -> None:
        old = tmp_path / "offer_tape_2026-09-01.jsonl"
        _touch_with_mtime(old, age_hours=24 * 10, content="a\nb\nc\n")
        with gzip.open(tmp_path / "offer_tape_2026-09-01.jsonl.gz", "wt", encoding="utf-8") as h:
            h.write("DIFFERENT CONTENT\n")

        outcome = gzip_eligible_files(tmp_path, older_than_days=7, now=_NOW)

        assert outcome.failed == ("offer_tape_2026-09-01.jsonl",)
        assert old.is_file()
        assert (tmp_path / "offer_tape_2026-09-01.jsonl.gz").is_file()

    def test_same_size_and_line_count_but_different_content_fails_verification(
        self, tmp_path: Path
    ) -> None:
        """Review fix 1: byte-count/line-count equality alone cannot catch
        bit-flip-shaped corruption -- a streamed sha256 does."""
        old = tmp_path / "offer_tape_2026-09-01.jsonl"
        _touch_with_mtime(old, age_hours=24 * 10, content="a\nb\nc\n")
        # Same byte count (6) and same line count (3) as the original, but
        # NOT the same bytes.
        with gzip.open(tmp_path / "offer_tape_2026-09-01.jsonl.gz", "wt", encoding="utf-8") as h:
            h.write("x\ny\nz\n")

        outcome = gzip_eligible_files(tmp_path, older_than_days=7, now=_NOW)

        assert outcome.failed == ("offer_tape_2026-09-01.jsonl",)
        assert old.is_file()
        assert old.read_text(encoding="utf-8") == "a\nb\nc\n"
        assert (tmp_path / "offer_tape_2026-09-01.jsonl.gz").is_file()

    def test_recovery_applies_original_mtime_before_unlinking(self, tmp_path: Path) -> None:
        """Review fix 2: the idempotent recovery branch must apply the
        ORIGINAL's mtime onto the pre-existing `.gz` -- a crash between
        `os.replace` and `os.utime` in a prior run leaves the `.gz` with its
        own write-time mtime, never the original's."""
        old = tmp_path / "offer_tape_2026-09-01.jsonl"
        _touch_with_mtime(old, age_hours=24 * 10, content="a\nb\nc\n")
        orig_mtime = old.stat().st_mtime
        gz = tmp_path / "offer_tape_2026-09-01.jsonl.gz"
        with gzip.open(gz, "wt", encoding="utf-8") as h:
            h.write("a\nb\nc\n")
        write_time_mtime = (_NOW - dt.timedelta(hours=1)).timestamp()
        os.utime(gz, (write_time_mtime, write_time_mtime))
        assert gz.stat().st_mtime != orig_mtime

        outcome = gzip_eligible_files(tmp_path, older_than_days=7, now=_NOW)

        assert outcome.gzipped == ("offer_tape_2026-09-01.jsonl",)
        assert not old.exists()
        assert gz.stat().st_mtime == orig_mtime

    def test_utime_failure_in_recovery_keeps_original(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Review fix 2: if applying the original's mtime fails, the
        original must NOT be unlinked -- utime happens strictly before
        unlink in the recovery branch too."""
        import decisions_retention as mod

        old = tmp_path / "offer_tape_2026-09-01.jsonl"
        _touch_with_mtime(old, age_hours=24 * 10, content="a\nb\nc\n")
        gz = tmp_path / "offer_tape_2026-09-01.jsonl.gz"
        with gzip.open(gz, "wt", encoding="utf-8") as h:
            h.write("a\nb\nc\n")

        def _boom_utime(target: object, times: object) -> None:
            raise OSError("simulated utime failure")

        monkeypatch.setattr(mod.os, "utime", _boom_utime)

        outcome = gzip_eligible_files(tmp_path, older_than_days=7, now=_NOW)

        assert outcome.failed == ("offer_tape_2026-09-01.jsonl",)
        assert old.is_file()
        assert gz.is_file()


class TestExactNameMatchOnlyNoRecursion:
    def test_exact_name_match_only_no_recursion(self, tmp_path: Path) -> None:
        _touch_with_mtime(tmp_path / "offer_tape_2026-09-01.jsonl", age_hours=24 * 10)
        # Not an exact match -- extra suffix, wrong prefix, already .gz.
        _touch_with_mtime(tmp_path / "offer_tape_2026-09-01.jsonl.bak", age_hours=24 * 10)
        _touch_with_mtime(tmp_path / "some_other_file_2026-09-01.jsonl", age_hours=24 * 10)
        nested = tmp_path / "subdir"
        nested.mkdir()
        _touch_with_mtime(nested / "offer_tape_2026-09-02.jsonl", age_hours=24 * 10)

        outcome = gzip_eligible_files(tmp_path, older_than_days=7, now=_NOW)

        assert outcome.gzipped == ("offer_tape_2026-09-01.jsonl",)
        assert (tmp_path / "offer_tape_2026-09-01.jsonl.bak").is_file()
        assert (tmp_path / "some_other_file_2026-09-01.jsonl").is_file()
        assert (nested / "offer_tape_2026-09-02.jsonl").is_file()  # untouched, no recursion


class TestNeverTouchesObservations:
    def test_never_touches_observations(self, tmp_path: Path) -> None:
        decisions_dir = tmp_path / "decisions"
        decisions_dir.mkdir()
        observations_dir = tmp_path / "observations"
        observations_dir.mkdir()
        _touch_with_mtime(
            observations_dir / "offer_tape_2026-09-01.jsonl", age_hours=24 * 10
        )
        _touch_with_mtime(decisions_dir / "offer_tape_2026-09-02.jsonl", age_hours=24 * 10)

        outcome = gzip_eligible_files(decisions_dir, older_than_days=7, now=_NOW)

        assert outcome.gzipped == ("offer_tape_2026-09-02.jsonl",)
        assert (observations_dir / "offer_tape_2026-09-01.jsonl").is_file()
        assert not (observations_dir / "offer_tape_2026-09-01.jsonl.gz").exists()


class TestPruneAbsentByDefault:
    def test_prune_absent_by_default(self, tmp_path: Path) -> None:
        gz = tmp_path / "offer_tape_2026-01-01.jsonl.gz"
        with gzip.open(gz, "wt", encoding="utf-8") as h:
            h.write("x\n")
        os.utime(gz, ((_NOW - dt.timedelta(days=200)).timestamp(),) * 2)

        outcome = run_retention(tmp_path, now=_NOW)

        assert outcome.pruned == ()
        assert gz.is_file()

    def test_prune_only_with_explicit_flag(self, tmp_path: Path) -> None:
        gz = tmp_path / "offer_tape_2026-01-01.jsonl.gz"
        with gzip.open(gz, "wt", encoding="utf-8") as h:
            h.write("x\n")
        os.utime(gz, ((_NOW - dt.timedelta(days=200)).timestamp(),) * 2)

        outcome = run_retention(tmp_path, prune_older_than_days=90, now=_NOW)

        assert outcome.pruned == ("offer_tape_2026-01-01.jsonl.gz",)
        assert not gz.exists()

    def test_prune_old_gz_files_never_touches_recent(self, tmp_path: Path) -> None:
        recent_gz = tmp_path / "offer_tape_2026-09-01.jsonl.gz"
        with gzip.open(recent_gz, "wt", encoding="utf-8") as h:
            h.write("x\n")
        os.utime(recent_gz, ((_NOW - dt.timedelta(days=1)).timestamp(),) * 2)

        pruned = prune_old_gz_files(tmp_path, older_than_days=90, now=_NOW)

        assert pruned == ()
        assert recent_gz.is_file()


class TestTimerExecstartHasNoPruneFlag:
    def test_timer_execstart_has_no_prune_flag(self) -> None:
        assert _WRAPPER.is_file()
        wrapper_text = _WRAPPER.read_text()
        assert "--prune-older-than" not in wrapper_text
        assert _SERVICE.is_file()
        service_text = _SERVICE.read_text()
        assert "--prune-older-than" not in service_text
        assert _TIMER.is_file()


def _run_wrapper(
    tmp_path: Path, *, xdg_runtime_dir: Path | None = None
) -> subprocess.CompletedProcess[str]:
    decisions_dir = tmp_path / "decisions"
    decisions_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["BREEZY_DECISIONS_RETENTION_DECISIONS_DIR"] = str(decisions_dir)
    env["BREEZY_DECISIONS_RETENTION_OUTPUT_DIR"] = str(tmp_path / "derived")
    # Hermetic by default (same defect class as test_portfolio_roi_deploy.py's
    # _run_wrapper): the wrapper takes the shared breezy-studies.lock via
    # `LOCK_DIR="${XDG_RUNTIME_DIR:-}"`, so leaving this unset would silently
    # inherit the host's real XDG_RUNTIME_DIR and contend with a real study.
    if xdg_runtime_dir is None:
        xdg_runtime_dir = tmp_path / "run"
        xdg_runtime_dir.mkdir(parents=True, exist_ok=True)
    env["XDG_RUNTIME_DIR"] = str(xdg_runtime_dir)
    return subprocess.run(
        ["bash", str(_WRAPPER)],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


class TestSkipsOnLockContention:
    def test_skips_on_lock_contention(self, tmp_path: Path) -> None:
        import fcntl

        xdg_runtime_dir = tmp_path / "xdg-runtime"
        xdg_runtime_dir.mkdir(parents=True)
        lock_path = xdg_runtime_dir / "breezy-studies.lock"
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            result = _run_wrapper(tmp_path, xdg_runtime_dir=xdg_runtime_dir)

            assert result.returncode == 0
            log_path = tmp_path / "derived" / "decisions_retention.log"
            assert log_path.is_file()
            assert "SKIPPED -- another study holds the studies lock" in log_path.read_text()
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)
