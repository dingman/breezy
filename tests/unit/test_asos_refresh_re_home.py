"""AUD-15b/15c -- retire `breezy-offer-gate-daily` + `breezy-mb-daily`, and
re-home exactly the `--since <ASOS_FETCH_START anchor>` ASOS refresh onto a
surviving enabled timer, in the same commit.

Ruled (`docs/evidence/RULING_study_units_order_ceiling_exit_prereq_2026-09-21.md`
RULING 1 + Revision 2 addendum §A1): both units retire; the fixed-window
(`--since`) invocation is the ONLY one re-homed, never the offer-gate rolling
3-day invocation; the anchor is never forked into a third copy.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import sys
from pathlib import Path
from typing import Final

_REPO_ROOT_FOR_PATH: Final[Path] = Path(__file__).resolve().parents[2]
_SCRIPTS_ANALYSIS_DIR: Final[Path] = _REPO_ROOT_FOR_PATH / "scripts" / "analysis"
if str(_SCRIPTS_ANALYSIS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ANALYSIS_DIR))

from asos_cache_freshness_check import (
    check_and_alert,
    resolve_consumer_cache_paths,
)
from ma_prelock_winner_ask_study import ASOS_FETCH_START
from settlement_alignment_study import SiteSpec

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_DEPLOY_DIR: Final[Path] = _REPO_ROOT / "deploy" / "systemd"

_RETIRED_NAMES: Final[tuple[str, ...]] = (
    "breezy-offer-gate-daily.service",
    "breezy-offer-gate-daily.timer",
    "offer-gate-daily-run.sh",
    "breezy-mb-daily.service",
    "breezy-mb-daily.timer",
    "mb-daily-run.sh",
)

_NEW_UNIT_NAMES: Final[tuple[str, ...]] = (
    "breezy-asos-refresh.service",
    "breezy-asos-refresh.timer",
    "asos-refresh-run.sh",
)


def _unit_target(timer_path: Path) -> str:
    target = timer_path.stem + ".service"
    for line in timer_path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("Unit="):
            target = stripped[len("Unit=") :].strip()
            break
    if "%i" in target:
        # A template timer's own on-disk definition carries an empty
        # instance (e.g. `breezy-family-tally@.timer`'s `%i` resolves to
        # the template file `breezy-family-tally@.service` itself, not to
        # any one runtime instantiation).
        instance = timer_path.stem.split("@", 1)[1] if "@" in timer_path.stem else ""
        target = target.replace("%i", instance)
    return target


def _has_enabled_install_section(timer_path: Path) -> bool:
    text = timer_path.read_text()
    return "[Install]" in text and "WantedBy=timers.target" in text


def _execstart_wrapper_path(service_path: Path) -> Path | None:
    for line in service_path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("ExecStart="):
            value = stripped[len("ExecStart=") :]
            for token in value.split():
                if token.endswith(".sh"):
                    return _DEPLOY_DIR / Path(token).name
    return None


def _wrappers_reachable_from_an_enabled_timer() -> tuple[Path, ...]:
    """Resolved from the `.timer`/`.service`/`ExecStart` chain in
    `deploy/systemd/`, never from a hard-coded unit name -- so a wrapper
    that moves or is renamed is still found, and a retired one is not."""
    wrappers = []
    for timer_path in sorted(_DEPLOY_DIR.glob("*.timer")):
        if not _has_enabled_install_section(timer_path):
            continue
        service_path = _DEPLOY_DIR / _unit_target(timer_path)
        if not service_path.is_file():
            continue
        wrapper = _execstart_wrapper_path(service_path)
        if wrapper is not None and wrapper.is_file():
            wrappers.append(wrapper)
    return tuple(wrappers)


_SINCE_ANCHORED_RE = re.compile(
    r"asos_recent_refresh\.py.*--since\s+\"?\$?ASOS_FETCH_START_ANCHOR\"?"
)
_ANCHOR_LITERAL_RE = re.compile(r"^ASOS_FETCH_START_ANCHOR=(\S+)$", re.MULTILINE)


def _logical_lines(text: str) -> list[str]:
    """Collapse each `... \\\n  ...` shell line continuation into ONE
    logical line (never spanning further than that), so a regex over one
    command's arguments does not stop at the first physical newline but
    also never spans two unrelated commands."""
    return re.sub(r"\\\s*\n\s*", " ", text).splitlines()


def _since_anchored_wrappers() -> tuple[Path, ...]:
    return tuple(
        wrapper
        for wrapper in _wrappers_reachable_from_an_enabled_timer()
        if any(
            _SINCE_ANCHORED_RE.search(line)
            for line in _logical_lines(wrapper.read_text())
        )
    )


def test_an_enabled_timer_invokes_the_since_anchored_asos_refresh_and_the_consumer_cache_key_is_fresh(  # noqa: E501 -- exact name pinned by the plan
    tmp_path: Path,
) -> None:
    # (a) exactly one wrapper, reachable from an enabled timer, invokes the
    # since-anchored refresh.
    matches = _since_anchored_wrappers()
    assert len(matches) == 1, f"expected exactly one since-anchored wrapper, found {matches}"
    wrapper_text = matches[0].read_text()

    # (b) that --since value equals ma_prelock_winner_ask_study.ASOS_FETCH_START,
    # imported -- so a forked anchor fails this suite.
    anchor_match = _ANCHOR_LITERAL_RE.search(wrapper_text)
    assert anchor_match is not None, "wrapper does not declare ASOS_FETCH_START_ANCHOR="
    assert dt.date.fromisoformat(anchor_match.group(1)) == ASOS_FETCH_START

    # (c) a freshness check on the consumer's OWN resolved cache path, by
    # epoch-mtime comparison, never existence alone.
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    sites = (
        SiteSpec(  # type: ignore[arg-type]
            city="Testville", site=object(), std_utc_offset_hours=-6.0, iem_asos_id="TST"
        ),
    )
    fetch_start = ASOS_FETCH_START
    fetch_end = dt.date(2026, 9, 22)
    now = dt.datetime(2026, 9, 22, 13, 30, tzinfo=dt.UTC)

    paths = resolve_consumer_cache_paths(
        cache_dir=cache_dir, sites=sites, fetch_start=fetch_start, fetch_end=fetch_end
    )
    assert len(paths) == 1

    class _RecordingSink:
        def __init__(self) -> None:
            self.emitted: list[object] = []

        def emit(self, payload: object) -> None:
            self.emitted.append(payload)

    # Missing path -> stale (existence leg).
    missing_sink = _RecordingSink()
    stale = check_and_alert(
        cache_dir=cache_dir, sites=sites, fetch_start=fetch_start, fetch_end=fetch_end,
        now=now, sink=missing_sink,
    )
    assert stale is True
    assert len(missing_sink.emitted) == 1

    # Present but written BEFORE today 00:00Z -> stale by epoch-mtime, not
    # by existence (this is the leg existence-only checks cannot express).
    stale_path = paths[0]
    stale_path.write_bytes(b"old")
    yesterday_evening = (now - dt.timedelta(hours=20)).timestamp()

    os.utime(stale_path, (yesterday_evening, yesterday_evening))
    stale_mtime_sink = _RecordingSink()
    stale2 = check_and_alert(
        cache_dir=cache_dir, sites=sites, fetch_start=fetch_start, fetch_end=fetch_end,
        now=now, sink=stale_mtime_sink,
    )
    assert stale2 is True
    assert len(stale_mtime_sink.emitted) == 1

    # Written today, before `now` -> fresh, no alert.
    today_start = now.replace(hour=1, minute=0, second=0, microsecond=0).timestamp()
    os.utime(stale_path, (today_start, today_start))
    fresh_sink = _RecordingSink()
    stale3 = check_and_alert(
        cache_dir=cache_dir, sites=sites, fetch_start=fetch_start, fetch_end=fetch_end,
        now=now, sink=fresh_sink,
    )
    assert stale3 is False
    assert fresh_sink.emitted == []


def test_no_retired_study_unit_timer_or_wrapper_remains() -> None:
    present = [name for name in _RETIRED_NAMES if (_DEPLOY_DIR / name).is_file()]
    assert present == [], f"retired unit(s)/wrapper(s) still present: {present}"

    for timer_path in sorted(_DEPLOY_DIR.glob("*.timer")):
        target = _DEPLOY_DIR / _unit_target(timer_path)
        assert target.is_file(), (
            f"{timer_path.name} references missing unit {target.name}"
        )

    for name in _NEW_UNIT_NAMES:
        assert (_DEPLOY_DIR / name).is_file(), f"expected re-homed file {name} to exist"


def test_the_offer_gate_rolling_asos_invocation_is_not_re_homed() -> None:
    """Ruling §A1(ii): the offer-gate rolling 3-day (`--since`-less)
    invocation is retired WITH its wrapper, never re-homed -- no consumer of
    that cache key was found, and re-homing it would suppress the loud
    cache-miss that would otherwise surface a wrong re-home."""
    for path in _DEPLOY_DIR.glob("*.sh"):
        for line in _logical_lines(path.read_text()):
            stripped = line.strip()
            if stripped.startswith("#") or "asos_recent_refresh.py" not in stripped:
                continue
            if not stripped.startswith(('"$PY"', "$PY")):
                continue  # an actual invocation line, not a comment mentioning the script
            assert "--since" in line, (
                f"{path.name} invokes asos_recent_refresh.py without --since "
                "-- this is the rolling 3-day form, which ruling §A1(ii) "
                "requires to be retired, never re-homed"
            )


_ASOS_REFRESH_WRAPPER: Final[Path] = _DEPLOY_DIR / "asos-refresh-run.sh"


def test_the_refresh_subprocess_never_sees_the_alert_webhook_url() -> None:
    """AUD-15 amendment, least privilege (A-5): only the freshness check
    needs BREEZY_ALERT_WEBHOOK_URL; the fetch is an outbound HTTP GET to a
    public endpoint and has no use for a credential-shaped value."""
    text = _ASOS_REFRESH_WRAPPER.read_text()
    for line in _logical_lines(text):
        if "asos_recent_refresh.py" in line and ('"$PY"' in line or "$PY" in line):
            assert 'env -u BREEZY_ALERT_WEBHOOK_URL "$PY"' in line, (
                f"asos_recent_refresh.py invocation does not strip the webhook "
                f"env var: {line!r}"
            )
            break
    else:
        raise AssertionError("no asos_recent_refresh.py invocation found in the wrapper")


def test_both_python_steps_route_stdout_to_the_log_not_devnull() -> None:
    """Folded review finding D-v: `>/dev/null` on the refresh and freshness
    steps discarded their own outcome text. Routing it to `$LOG` instead
    (`>>"$LOG" 2>>"$LOG"`) puts the per-site outcome and the `stale=`
    verdict in the wrapper's own log FILE, where an operator or a later
    debugging session can actually read them. This does NOT reach the
    journal: `StandardOutput=journal` only captures what the unit's own
    ExecStart process (the wrapper shell) writes to ITS stdout/stderr --
    the two Python steps are separate subprocesses redirected straight to
    the file, so the journal only ever sees the wrapper's own `say()`
    summary lines (`asos refresh ok`, `asos cache freshness check ok`,
    etc.), never the Python steps' own output."""
    text = _ASOS_REFRESH_WRAPPER.read_text()
    assert ">/dev/null" not in text, "a python step still discards its own stdout"
    invocation_count = sum(
        1
        for line in _logical_lines(text)
        if ("asos_recent_refresh.py" in line or "asos_cache_freshness_check.py" in line)
        and ('"$PY"' in line or "$PY" in line)
    )
    assert invocation_count == 2
    for line in _logical_lines(text):
        if ("asos_recent_refresh.py" in line or "asos_cache_freshness_check.py" in line) and (
            '"$PY"' in line or "$PY" in line
        ):
            assert '>>"$LOG" 2>>"$LOG"' in line, f"stdout not routed to $LOG: {line!r}"


def test_webhook_url_stripped_from_refresh_env() -> None:
    """AUD-18: the MOS fetch step is an outbound HTTP GET to a public IEM
    endpoint, same least-privilege posture (A-5) as the ASOS fetch step --
    the webhook URL never reaches it."""
    text = _ASOS_REFRESH_WRAPPER.read_text()
    for line in _logical_lines(text):
        if "iem_mos_backfill.py" in line and ('"$PY"' in line or "$PY" in line):
            assert 'env -u BREEZY_ALERT_WEBHOOK_URL "$PY"' in line, (
                f"iem_mos_backfill.py invocation does not strip the webhook "
                f"env var: {line!r}"
            )
            break
    else:
        raise AssertionError("no iem_mos_backfill.py invocation found in the wrapper")


def test_mos_steps_route_stdout_to_the_log() -> None:
    """AUD-18: both new MOS steps must not discard their own outcome text,
    same posture as the two pre-existing ASOS steps."""
    text = _ASOS_REFRESH_WRAPPER.read_text()
    assert ">/dev/null" not in text, "a python step still discards its own stdout"
    invocation_count = sum(
        1
        for line in _logical_lines(text)
        if ("iem_mos_backfill.py" in line or "iem_mos_freshness_check.py" in line)
        and ('"$PY"' in line or "$PY" in line)
    )
    assert invocation_count == 2
    for line in _logical_lines(text):
        if ("iem_mos_backfill.py" in line or "iem_mos_freshness_check.py" in line) and (
            '"$PY"' in line or "$PY" in line
        ):
            assert '>>"$LOG" 2>>"$LOG"' in line, f"stdout not routed to $LOG: {line!r}"
