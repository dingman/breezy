"""AUT-2 r7 WP6 / section 3.10 (L2, V1): the score-live-trials catch-up guard."""

from __future__ import annotations

import datetime as dt
import os
import subprocess
import sys
from pathlib import Path

import pytest

from breezy.analysis.labeling.constants import CATCHUP_DENY_UTC, SLOT_GUARD_REFUSED_RC
from breezy.analysis.labeling.slot_guard import (
    SlotDecision,
    catch_up_permitted,
    main,
    parse_systemd_span_s,
)

_REPO = Path(__file__).resolve().parents[2]
_DEPLOY_DIR = _REPO / "deploy" / "systemd"
#: the guard reads the STAGED WP6 unit pair: the deployed pair is symlink-installed and untouched
_UNIT_DIR = _REPO / "tests" / "fixtures" / "aut2_units" / "promote"
_TIMER = (_UNIT_DIR / "breezy-score-live-trials.timer").read_text()
_SERVICE = (_UNIT_DIR / "breezy-score-live-trials.service").read_text()
_WRAPPER = _DEPLOY_DIR / "slot-guard-run.sh"


def _at(hh: int, mm: int, ss: int = 0) -> dt.datetime:
    return dt.datetime(2026, 10, 7, hh, mm, ss, tzinfo=dt.UTC)


def _decide(now: dt.datetime, timer: str = _TIMER, service: str = _SERVICE) -> SlotDecision:
    return catch_up_permitted(now, timer, service)


def test_score_live_trials_catch_up_deferred_in_launch_window_and_night() -> None:
    for refused, reason in (
        (_at(16, 7, 30), "launch_window"),
        (_at(16, 35), "launch_window"),
        (_at(2, 0), "heavy_night"),
        (_at(1, 0), "heavy_night"),
        (_at(4, 29, 59), "heavy_night"),
    ):
        decision = _decide(refused)
        assert (decision.permitted, decision.reason) == (False, reason), refused
    for permitted in (_at(16, 7, 29), _at(13, 55), _at(5, 0), _at(4, 30), _at(17, 10), _at(14, 40)):
        assert _decide(permitted).permitted is True, permitted


def test_the_scheduled_start_is_always_permitted_even_inside_its_own_accuracy_term() -> None:
    assert _decide(_at(13, 55, 40)).permitted is True  # a timer may fire up to AccuracySec late
    assert _decide(_at(13, 57, 0)).permitted is True  # outside every deny window anyway


def test_bounds_are_read_from_the_unit_files_with_the_stop_term_included() -> None:
    longer = _SERVICE.replace("TimeoutStartSec=1200", "TimeoutStartSec=1300")

    # +100 s of start budget moves the first refused start 100 s earlier: 16:05:50
    assert _decide(_at(16, 5, 55), service=longer).permitted is False
    assert _decide(_at(16, 5, 55)).permitted is True
    with_stop = _SERVICE.replace("TimeoutStartSec=1200", "TimeoutStartSec=1200\nTimeoutStopSec=5")
    assert _decide(_at(16, 7, 30), service=with_stop).permitted is True  # 5 s stop, not 90 s


def test_deny_constants_match_the_derived_windows_for_the_current_units() -> None:
    (launch_from, launch_until), (night_from, night_until) = CATCHUP_DENY_UTC

    assert (launch_from, launch_until) == (dt.time(16, 7, 30), dt.time(17, 10))
    assert (night_from, night_until) == (dt.time(1, 0), dt.time(4, 30))
    assert _decide(_at(16, 7, 30)).permitted is False and _decide(_at(16, 7, 29)).permitted is True


def test_slot_guard_flags_planted_timeout_that_reaches_window() -> None:
    """Positive control: a planted TimeoutStartSec that carries a 13:55 start into the window is
    refused as a scheduled start's bound would be, so the guard is not vacuous."""
    huge = _SERVICE.replace("TimeoutStartSec=1200", "TimeoutStartSec=14400")

    assert _decide(_at(12, 30), service=huge).permitted is False
    assert _decide(_at(12, 30)).permitted is True


@pytest.mark.parametrize(
    ("text", "seconds"),
    [("1200", 1200.0), ("1min", 60.0), ("5s", 5.0), ("1h", 3600.0), ("2m", 120.0), ("90", 90.0)],
)
def test_systemd_spans_parse(text: str, seconds: float) -> None:
    assert parse_systemd_span_s(text) == seconds


@pytest.mark.parametrize("bad", ["", "soon", "-5", "1x"])
def test_a_malformed_span_is_an_error(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_systemd_span_s(bad)


def test_main_exit_codes_permit_refuse_and_internal_error(
    capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    assert main(["--unit", "breezy-score-live-trials"], now=_at(5, 0), unit_dir=_UNIT_DIR) == 0
    rc = main(["--unit", "breezy-score-live-trials"], now=_at(2, 0), unit_dir=_UNIT_DIR)
    assert rc == SLOT_GUARD_REFUSED_RC == 10
    assert "SCORE_LIVE_TRIALS CATCHUP_DEFERRED reason=heavy_night" in capsys.readouterr().out
    assert main(["--unit", "breezy-score-live-trials"], now=_at(5, 0), unit_dir=tmp_path) == 255


def test_main_rejects_a_unit_name_that_is_not_a_plain_name() -> None:
    assert main(["--unit", "../x"], now=_at(5, 0), unit_dir=_UNIT_DIR) == 255


def _run_wrapper(*args: str, **env: str) -> subprocess.CompletedProcess[str]:
    full = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            filter(None, [str(_REPO / "src"), os.environ.get("PYTHONPATH", "")])
        ),
        "BREEZY_PYTHON": sys.executable,
        **env,
    }
    return subprocess.run(
        ["/bin/bash", str(_WRAPPER), *args],
        capture_output=True,
        text=True,
        env=full,
        timeout=60,
        check=False,
    )


def test_slot_guard_internal_error_exits_255_not_1() -> None:
    done = _run_wrapper("--unit", "x", SLOT_GUARD_MODULE="breezy.analysis.labeling.no_such_module")

    assert done.returncode == 255  # python's own exit 1 for a failed import must not leak as 1


def test_slot_guard_deliberate_refusal_exits_1(tmp_path: Path) -> None:
    (tmp_path / "refuser.py").write_text("import sys\nsys.exit(10)\n")

    done = _run_wrapper("--unit", "x", SLOT_GUARD_MODULE="refuser", PYTHONPATH=str(tmp_path))

    assert done.returncode == 1


def test_slot_guard_permit_exits_0(tmp_path: Path) -> None:
    (tmp_path / "permitter.py").write_text("")

    done = _run_wrapper("--unit", "x", SLOT_GUARD_MODULE="permitter", PYTHONPATH=str(tmp_path))

    assert done.returncode == 0


def test_any_other_status_maps_to_255(tmp_path: Path) -> None:
    (tmp_path / "odd.py").write_text("import sys\nsys.exit(7)\n")

    done = _run_wrapper("--unit", "x", SLOT_GUARD_MODULE="odd", PYTHONPATH=str(tmp_path))

    assert done.returncode == 255


def test_score_live_trials_service_carries_slot_guard_exec_condition() -> None:
    lines = [ln for ln in _SERVICE.splitlines() if ln.startswith("ExecCondition=")]

    expected = (
        "ExecCondition=/home/jon/breezy/deploy/systemd/slot-guard-run.sh "
        "--unit breezy-score-live-trials"
    )
    assert lines == [expected]
    assert "OnFailure=breezy-study-failed@%n.service" in _SERVICE


def test_score_live_trials_timer_moves_to_1355_and_keeps_its_other_settings() -> None:
    assert "OnCalendar=*-*-* 13:55:00 UTC" in _TIMER
    assert "14:15:00" not in "\n".join(ln for ln in _TIMER.splitlines() if not ln.startswith("#"))
    assert "AccuracySec=1min" in _TIMER and "Persistent=true" in _TIMER


def test_the_wrapper_is_executable_and_names_no_shell_hazard() -> None:
    assert os.access(_WRAPPER, os.X_OK)
    assert "set -u" in _WRAPPER.read_text() or "set -eu" in _WRAPPER.read_text()


# -- review fold-in: the module's windows are derived from the shared constants -----------------


def test_slot_guard_windows_are_the_shared_constants() -> None:
    from breezy.analysis.labeling import slot_guard

    (launch_from, launch_until), (night_from, night_until) = CATCHUP_DENY_UTC

    assert slot_guard._LAUNCH_FROM == dt.time(16, 30)  # the ARCH launch window opens at 16:30Z
    assert slot_guard._LAUNCH_UNTIL == launch_until == dt.time(17, 10)
    assert (slot_guard._NIGHT_FROM, slot_guard._NIGHT_UNTIL) == (night_from, night_until)
    # CATCHUP_DENY_UTC's launch start is the 16:30Z window minus the worst-case span of the
    # current unit pair (AccuracySec 60 + TimeoutStartSec 1200 + default stop 90 = 1350 s)
    span = dt.timedelta(seconds=60 + 1200 + 90)
    opened = dt.datetime.combine(dt.date(2026, 10, 7), dt.time(16, 30)) - span
    assert launch_from == opened.time()


def test_a_drift_between_the_constants_and_the_guard_would_be_caught() -> None:
    from breezy.analysis.labeling import slot_guard

    assert slot_guard.LAUNCH_WINDOW == (dt.time(16, 30), CATCHUP_DENY_UTC[0][1])
    assert slot_guard.NIGHT_WINDOW == CATCHUP_DENY_UTC[1]


def test_the_wrapper_runs_python_in_isolated_mode_unless_a_test_seam_is_set() -> None:
    text = _WRAPPER.read_text()

    assert '"$PYTHON" -I -m' in text
    assert "SLOT_GUARD_MODULE" in text  # the seam is the only path that drops -I


def test_the_unit_context_cgroup_check_fails_closed_under_a_cgroup_namespace() -> None:
    from breezy.analysis.labeling.label_run import UnitContext

    # inside a cgroup namespace /proc/self/cgroup shows a path relative to the namespace root
    # ("0::/"), whose leaf is empty: it can never equal breezy-label-outcomes.service
    assert UnitContext.from_environment({"INVOCATION_ID": "i"}, "0::/\n").is_label_unit() is False
    assert (
        UnitContext.from_environment({"INVOCATION_ID": "i"}, "0::/../..\n").is_label_unit() is False
    )
    assert UnitContext.from_environment({"INVOCATION_ID": "i"}, "").is_label_unit() is False
