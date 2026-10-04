"""RED-PENDING-STAGE-2C (AUT-1 WP5 stage 2b W3): not collected by the merge gate.

These end-to-end tests need the REAL W1 fill legs and W2 reconciliation legs, which land in other
worktrees. They are neither xfailed nor skipped (both hide a red test): the file name does not match
pytest's ``test_*.py`` pattern, so ``pytest tests/unit/autonomy/pending_s2c_capture_audit_e2e.py``
runs it by path. Stage 2c renames it to ``test_capture_audit_e2e.py`` after the three worktrees
merge and every test passes (the WP2-R1 precedent).
"""

import datetime as dt
from pathlib import Path

import pytest

from breezy.analysis import capture_audit as audit
from breezy.analysis.capture_audit_model import DayStatus
from tests.support import capture_audit_w3_fixtures as w3


def test_a_real_gather_over_a_real_world_runs_every_real_leg_to_a_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    result = audit.audit_day(w3.gather(root))
    assert result.status in set(DayStatus)  # every leg ran over real inputs without raising
    assert len(result.legs) == 13


def test_a_real_run_writes_a_day_file_for_each_day_it_reaches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = w3.full_world(tmp_path, monkeypatch)
    today = w3.DAY + dt.timedelta(days=1)
    code = audit.run_audit(root, w3.FAMILY, today, now_ns=w3.NOW_NS, offer=lambda e, s, d: True)
    assert code in (0, 1)
    assert (root / "evidence" / "capture" / "audit" / w3.FAMILY / f"{w3.DAY}.json").exists()


def test_the_real_replay_and_marker_sinks_feed_the_boot_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from breezy.analysis import capture_audit_inputs as inputs
    from breezy.analysis.capture_audit_log_markers import MarkerParser
    from breezy.analysis.capture_audit_replay import BootReplay

    root = w3.full_world(tmp_path, monkeypatch)
    monkeypatch.setattr(inputs, "BootReplay", BootReplay)
    monkeypatch.setattr(inputs, "MarkerParser", MarkerParser)
    (boot,) = w3.gather(root).boots
    assert boot.replay.evaluations >= 1  # the Take line of the fixture log
