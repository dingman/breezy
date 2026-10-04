"""AUT-1 WP5 stage 3, S2: the ``breezy-capture-live-proof`` entry point (design r3 D8).

The CLI publishes the roll-up (``live_proof_<family>_<asof>.json``, 0444, through
``replace_atomic``) and runs the two duties the audit's watchdog used to run: the audit dead-man
(``CAPTURE_AUDIT_DEADMAN``) and the missing-audit-file check (``CAPTURE_AUDIT_FILE_MISSING``). Each
is its own ``try``, each is sent at most once per ``asof`` (a write-once marker written only after
the offer was accepted), and a failed delivery exits 1. The alert offer and the clock are injected;
files are real.
"""

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Final

import pytest

from breezy.analysis import capture_live_proof_cli as cli
from breezy.analysis.capture_audit_model import LIVE_PROOF_NAME_RE, DayStatus
from tests.support.capture_audit_run_support import Offers
from tests.unit.test_capture_live_proof import (
    ASOF,
    FAMILY,
    NS,
    day,
    proven_world,
    put_audit,
    put_pass_days,
)

#: 14:40Z on ``ASOF``: clear of the launch window even with the unit's worst-case span.
NOW: Final = int(dt.datetime(2026, 10, 20, 14, 40, tzinfo=dt.UTC).timestamp()) * NS
HOUR: Final = 3600 * NS
DEADMAN: Final = "CAPTURE_AUDIT_DEADMAN"
MISSING: Final = "CAPTURE_AUDIT_FILE_MISSING"
LIVE_PROOF_DIR: Final = ("evidence", "capture", "live_proof")
REPO_ROOT: Final = Path(__file__).resolve().parents[2]


def run(
    root: Path,
    *families: str,
    offer: Offers | None = None,
    now: int = NOW,
    extra: tuple[str, ...] = (),
) -> tuple[int, Offers]:
    outbox = offer or Offers()
    argv = ["--data-root", str(root), *(f"--family-id={f}" for f in families), *extra]
    return cli._main(argv, offer=outbox, clock=lambda: now), outbox


def age_audit_files(root: Path, *, hours_old: float, now: int = NOW) -> None:
    stamp = now - int(hours_old * HOUR)
    for path in (root / "evidence" / "capture" / "audit" / FAMILY).glob("*.json"):
        os.utime(path, ns=(stamp, stamp))


def fresh_audits(root: Path, *, backs: range = range(1, 9)) -> None:
    put_pass_days(root, backs, real=1)
    age_audit_files(root, hours_old=2)


def rollup_path(root: Path, asof: dt.date = ASOF) -> Path:
    return root.joinpath(*LIVE_PROOF_DIR) / f"live_proof_{FAMILY}_{asof.isoformat()}.json"


def sent_marker(root: Path, event: str, asof: dt.date = ASOF) -> Path:
    return root.joinpath(*LIVE_PROOF_DIR, "sent", asof.isoformat(), f"{event}_{FAMILY}.json")


# -- the launch window -----------------------------------------------------------------------------


@pytest.mark.parametrize("hh_mm", [(16, 30), (16, 45), (17, 9), (16, 25)])
def test_live_proof_cli_defers_inside_launch_window(tmp_path: Path, hh_mm: tuple[int, int]) -> None:
    """The unit's worst case (``flock -w 30`` plus ``TimeoutStartSec=300``) must not meet
    [16:30Z, 17:10Z): a run that would, defers (exit 0, no work, no write)."""
    moment = int(dt.datetime(2026, 10, 20, *hh_mm, tzinfo=dt.UTC).timestamp()) * NS
    code, offers = run(tmp_path, FAMILY, now=moment)
    assert code == 0 and offers.calls == []
    assert list(tmp_path.iterdir()) == []


def test_a_run_outside_the_window_does_not_defer(tmp_path: Path) -> None:
    moment = int(dt.datetime(2026, 10, 20, 17, 10, tzinfo=dt.UTC).timestamp()) * NS
    _code, offers = run(tmp_path, FAMILY, now=moment)
    assert offers.events  # an empty root: the dead-man fires, so the run did its work


# -- the roll-up file ------------------------------------------------------------------------------


def test_the_rollup_is_published_read_only_under_its_audit_visible_name(tmp_path: Path) -> None:
    fresh_audits(tmp_path)
    code, offers = run(tmp_path, FAMILY)
    path = rollup_path(tmp_path)
    assert code == 0 and offers.calls == []
    assert LIVE_PROOF_NAME_RE.fullmatch(path.name) is not None
    assert path.stat().st_mode & 0o777 == 0o444
    doc = json.loads(path.read_text())
    assert doc["family_id"] == FAMILY and doc["asof"] == ASOF.isoformat()
    assert doc["status"] == "NOT_PROVEN"


def test_a_rerun_replaces_the_rollup_and_refreshes_its_mtime(tmp_path: Path) -> None:
    fresh_audits(tmp_path)
    run(tmp_path, FAMILY)
    path = rollup_path(tmp_path)
    os.utime(path, ns=(1, 1))
    proven_world(tmp_path)
    age_audit_files(tmp_path, hours_old=2)
    run(tmp_path, FAMILY)
    assert json.loads(path.read_text())["status"] == "PROVEN"
    assert path.stat().st_mtime_ns > 1  # the audit's ``CAPTURE_LIVE_PROOF_STALE`` reads this


def test_each_family_gets_its_own_rollup(tmp_path: Path) -> None:
    fresh_audits(tmp_path)
    run(tmp_path, FAMILY, "other_fam")
    names = sorted(p.name for p in tmp_path.joinpath(*LIVE_PROOF_DIR).glob("live_proof_*"))
    assert names == [
        f"live_proof_other_fam_{ASOF.isoformat()}.json",
        f"live_proof_{FAMILY}_{ASOF.isoformat()}.json",
    ]


# -- the dead-man ---------------------------------------------------------------------------------


def test_a_fresh_audit_file_sends_no_deadman(tmp_path: Path) -> None:
    fresh_audits(tmp_path)
    _code, offers = run(tmp_path, FAMILY)
    assert DEADMAN not in offers.events


def test_deadman_reads_audit_file_not_c4_verdict(tmp_path: Path) -> None:
    """The dead-man reads the newest AUDIT file's age. The C4 HEALTH verdict is skipped while the
    producer is unpinned (F17), so it can be absent or fresh without telling anything about it."""
    fresh_audits(tmp_path)
    verdicts = tmp_path / "derived" / "verdicts" / FAMILY / day(1).isoformat()
    verdicts.mkdir(parents=True)
    stale_verdict = verdicts / "verdict.json"
    stale_verdict.write_text("{}")
    os.utime(stale_verdict, ns=(1, 1))
    _code, offers = run(tmp_path, FAMILY)
    assert DEADMAN not in offers.events  # a fresh audit file and a stale verdict: alive

    other = tmp_path / "other"
    other.mkdir(mode=0o700)
    fresh_audits(other)
    age_audit_files(other, hours_old=30)
    fresh_verdict = other / "derived" / "verdicts" / FAMILY
    fresh_verdict.mkdir(parents=True)
    (fresh_verdict / "verdict.json").write_text("{}")
    _code, offers = run(other, FAMILY)
    assert DEADMAN in offers.events  # a stale audit file and a fresh verdict: dead


def test_the_deadman_boundary_is_26_hours(tmp_path: Path) -> None:
    fresh_audits(tmp_path)
    age_audit_files(tmp_path, hours_old=26)
    assert DEADMAN not in run(tmp_path, FAMILY)[1].events  # exactly 26 h is not older than 26 h
    age_audit_files(tmp_path, hours_old=26.01)
    assert DEADMAN in run(tmp_path, FAMILY)[1].events


def test_no_audit_directory_sends_the_deadman(tmp_path: Path) -> None:
    code, offers = run(tmp_path, FAMILY)
    assert DEADMAN in offers.events and code == 0


def test_the_deadman_carries_the_family_and_a_critical_severity(tmp_path: Path) -> None:
    _code, offers = run(tmp_path, FAMILY)
    sent = {event: (severity, detail) for event, severity, detail in offers.calls}
    assert sent[DEADMAN][0] == "CRITICAL" and f"family={FAMILY}" in sent[DEADMAN][1]
    assert sent[MISSING][0] == "CRITICAL" and f"family={FAMILY}" in sent[MISSING][1]


# -- the missing-file check -----------------------------------------------------------------------


def test_every_elapsed_day_of_the_last_eight_has_an_audit_file_or_is_reported(
    tmp_path: Path,
) -> None:
    fresh_audits(tmp_path)
    assert MISSING not in run(tmp_path, FAMILY)[1].events
    audit_dir = tmp_path / "evidence" / "capture" / "audit" / FAMILY
    for back in (3, 6):
        (audit_dir / f"{day(back).isoformat()}.json").unlink()
    _code, offers = run(tmp_path, FAMILY)
    (detail,) = [d for e, _s, d in offers.calls if e == MISSING]
    assert f"days={day(6).isoformat()},{day(3).isoformat()}" in detail


def test_a_day_older_than_eight_or_today_is_not_expected(tmp_path: Path) -> None:
    fresh_audits(tmp_path)  # day(1)..day(8) only: day(9) and ASOF itself have none
    assert MISSING not in run(tmp_path, FAMILY)[1].events


# -- once per asof --------------------------------------------------------------------------------


def test_deadman_and_missing_deduped_per_asof(tmp_path: Path) -> None:
    code, offers = run(tmp_path, FAMILY)
    assert offers.events == [DEADMAN, MISSING] and code == 0
    assert sent_marker(tmp_path, DEADMAN).is_file() and sent_marker(tmp_path, MISSING).is_file()
    code, again = run(tmp_path, FAMILY, offer=Offers())  # the fallback run of the same day
    assert again.calls == [] and code == 0
    later = NOW + 24 * HOUR
    _code, tomorrow = run(tmp_path, FAMILY, now=later)
    assert tomorrow.events == [DEADMAN, MISSING]  # a new asof sends again


def test_a_marker_is_written_only_after_the_offer_was_accepted(tmp_path: Path) -> None:
    code, offers = run(tmp_path, FAMILY, offer=Offers(accept=False))
    assert code == 1 and offers.events == [DEADMAN, MISSING]
    assert (
        not sent_marker(tmp_path, DEADMAN).exists() and not sent_marker(tmp_path, MISSING).exists()
    )
    code, retry = run(tmp_path, FAMILY)  # the next run offers them again
    assert retry.events == [DEADMAN, MISSING] and code == 0


def test_the_marker_is_write_once_evidence(tmp_path: Path) -> None:
    run(tmp_path, FAMILY)
    marker = sent_marker(tmp_path, DEADMAN)
    assert marker.stat().st_mode & 0o777 == 0o444
    body = json.loads(marker.read_text())
    assert body == {"event": DEADMAN, "family_id": FAMILY, "asof": ASOF.isoformat()}


def test_dedupe_is_per_family(tmp_path: Path) -> None:
    run(tmp_path, FAMILY)
    _code, offers = run(tmp_path, FAMILY, "other_fam")
    assert [(e, d) for e, _s, d in offers.calls if "other_fam" in d]  # the new family is offered
    assert not [d for _e, _s, d in offers.calls if f"family={FAMILY}" in d]


# -- isolation and exit status --------------------------------------------------------------------


def test_each_deadman_check_isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """r8 H7: a check that raises is counted and the others still run."""

    def broken(*_a: Any, **_k: Any) -> Any:
        raise OSError("gone")

    monkeypatch.setattr(cli, "_newest_audit_mtime_ns", broken)
    code, offers = run(tmp_path, FAMILY)
    assert code == 1 and offers.events == [MISSING]
    assert rollup_path(tmp_path).is_file()  # the roll-up was written before any check ran

    monkeypatch.undo()
    other = tmp_path / "second"
    other.mkdir(mode=0o700)
    monkeypatch.setattr(cli, "_missing_audit_days", broken)
    code, offers = run(other, FAMILY)
    assert code == 1 and offers.events == [DEADMAN]


def test_the_rollup_failing_does_not_stop_the_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_a: Any, **_k: Any) -> Any:
        raise ValueError("bad audit")

    monkeypatch.setattr(cli, "build_live_proof", broken)
    code, offers = run(tmp_path, FAMILY)
    assert code == 1 and offers.events == [DEADMAN, MISSING]
    assert not rollup_path(tmp_path).exists()


def test_a_raising_offer_for_one_event_does_not_stop_the_other(tmp_path: Path) -> None:
    class Selective(Offers):
        def __call__(self, event: str, severity: str, detail: str) -> bool:
            self.calls.append((event, severity, detail))
            if event == DEADMAN:
                raise RuntimeError("outbox down")
            return True

    code, offers = run(tmp_path, FAMILY, offer=Selective())
    assert code == 1 and offers.events == [DEADMAN, MISSING]
    assert sent_marker(tmp_path, MISSING).is_file() and not sent_marker(tmp_path, DEADMAN).exists()


def test_live_proof_failed_delivery_exits_nonzero(tmp_path: Path) -> None:
    fresh_audits(tmp_path)
    age_audit_files(tmp_path, hours_old=30)
    code, offers = run(tmp_path, FAMILY, offer=Offers(accept=False))
    assert code == 1 and DEADMAN in offers.events
    assert rollup_path(tmp_path).is_file()  # every write happened before the exit code was decided


def test_a_healthy_run_exits_zero(tmp_path: Path) -> None:
    fresh_audits(tmp_path)
    code, offers = run(tmp_path, FAMILY)
    assert code == 0 and offers.calls == []


def test_the_default_offer_reports_every_alert_undelivered(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli._undeliverable_offer(DEADMAN, "CRITICAL", "family=x") is False
    assert DEADMAN in capsys.readouterr().err


# -- the families ---------------------------------------------------------------------------------


def test_families_are_the_epoch_files_plus_the_named_ones(tmp_path: Path) -> None:
    epoch_dir = tmp_path / "evidence" / "capture" / "epoch"
    epoch_dir.mkdir(parents=True)
    (epoch_dir / "fam_a.json").write_text("{}")
    (epoch_dir / "notes.txt").write_text("x")
    assert cli._families(tmp_path, ["fam_b", "fam_a"]) == ("fam_a", "fam_b")


def test_no_family_is_exit_zero_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, offers = run(tmp_path)
    assert code == 0 and offers.calls == [] and list(tmp_path.iterdir()) == []
    assert "no family" in capsys.readouterr().err


def test_a_malformed_family_id_is_refused(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as exit_info:
        run(tmp_path, "../escape")
    assert exit_info.value.code == 2


def test_an_audit_with_an_error_day_still_gets_a_rollup(tmp_path: Path) -> None:
    """The fallback timer runs after an audit ERROR (exit 1, so ``OnSuccess=`` never fired)."""
    fresh_audits(tmp_path)
    put_audit(tmp_path, day(2), DayStatus.ERROR, ts_ns=5)
    age_audit_files(tmp_path, hours_old=2)
    code, _offers = run(tmp_path, FAMILY)
    assert code == 0
    assert json.loads(rollup_path(tmp_path).read_text())["breaking_days"] == [
        {"day": day(2).isoformat(), "status": "ERROR"}
    ]


# -- closure --------------------------------------------------------------------------------------

_ENV: Final = {"PYTHONPATH": str(REPO_ROOT / "src"), "PATH": "/usr/bin:/bin"}
_BAD: Final = (
    "bad = sorted(m for m in sys.modules if m.split('.')[0] in\n"
    "    {'httpx', 'requests', 'aiohttp', 'urllib3', 'nautilus_trader'}\n"
    "    or m.startswith('breezy.adapters'))\n"
    "print(bad)\n"
)


def _probe(code: str) -> str:
    done = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, env=_ENV
    )
    return done.stdout.strip()


def test_capture_live_proof_cli_sys_modules_closure(tmp_path: Path) -> None:
    """S3-R37: a full run loads no adapter, no HTTP client and no Nautilus (the unit has 256M)."""
    code = (
        "import sys\n"
        "from breezy.analysis import capture_live_proof_cli as c\n"
        f"c._main(['--data-root', {str(tmp_path)!r}, '--family-id=fam_x'],\n"
        "        offer=lambda e, s, d: True, clock=lambda: 1_792_000_000_000_000_000)\n"
    ) + _BAD
    assert _probe(code) == "[]"


def test_the_closure_probe_is_not_vacuous() -> None:
    """Positive control: the same probe flags a program that does load an adapter."""
    code = "import sys, breezy.adapters.polymarket_us.recorder_watchdog\n" + _BAD
    assert _probe(code) != "[]"
