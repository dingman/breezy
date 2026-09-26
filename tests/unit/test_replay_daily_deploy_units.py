"""AUD-09 plan §7 step 10 / B18: `breezy-replay-daily.service`/`.timer` and
`deploy/systemd/replay-daily-run.sh`'s own invocation-set property.

Text-only parsing, never `systemctl`/`daemon-reload` -- mirrors
`test_analysis_units_memory_capped.py` and `test_deploy_timer_hours.py`'s
own posture.
"""

from __future__ import annotations

import re
from pathlib import Path

_DEPLOY_DIR = Path(__file__).resolve().parents[2] / "deploy" / "systemd"
_SERVICE = _DEPLOY_DIR / "breezy-replay-daily.service"
_TIMER = _DEPLOY_DIR / "breezy-replay-daily.timer"
_WRAPPER = _DEPLOY_DIR / "replay-daily-run.sh"

#: B18: the ONLY scripts the wrapper may invoke via `"$PY" ...`.
_SANCTIONED_SCRIPTS = frozenset(
    {"replay_sufficiency_census.py", "replay_daily_runner.py", "promotion_proposal.py"}
)


def test_service_declares_its_own_memory_ceiling_and_studies_slice() -> None:
    text = _SERVICE.read_text()
    assert re.search(r"^MemoryHigh=\d+[KMGT]$", text, re.MULTILINE)
    assert re.search(r"^MemoryMax=\d+[KMGT]$", text, re.MULTILINE)
    assert "Slice=breezy-studies.slice" in text
    assert "Type=oneshot" in text


def _code_lines(text: str) -> list[str]:
    """Non-comment, non-blank lines only -- so a prose comment MENTIONING a
    forbidden token (e.g. explaining why the wrapper has none) never trips
    an assertion meant for actual unit/shell syntax."""
    return [
        line for line in text.splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def test_service_has_no_install_section() -> None:
    # Only the timer is ever enabled -- mirrors every sibling study unit.
    assert "[Install]" not in "\n".join(_code_lines(_SERVICE.read_text()))


def test_service_has_an_onfailure_notifier() -> None:
    assert "OnFailure=breezy-study-failed@%n.service" in _SERVICE.read_text()


def test_timer_fires_at_1550_utc_and_is_persistent() -> None:
    text = _TIMER.read_text()
    assert "OnCalendar=*-*-* 15:50:00 UTC" in text
    assert "Persistent=true" in text
    assert "Unit=breezy-replay-daily.service" in text


def test_wrapper_unsets_posixly_correct() -> None:
    assert "unset POSIXLY_CORRECT" in _WRAPPER.read_text()


def test_wrapper_takes_the_host_wide_studies_lock() -> None:
    text = _WRAPPER.read_text()
    assert "breezy-studies.lock" in text
    assert re.search(r"flock -n 9", text)


def test_wrapper_contains_no_record_blocked_and_no_jsonl_parsing() -> None:
    code = "\n".join(_code_lines(_WRAPPER.read_text()))
    assert "record_blocked" not in code
    assert ".jsonl" not in code
    assert "json.load" not in code


def test_every_py_invocation_is_one_of_the_named_scripts() -> None:
    """B18: a PROPERTY over the invoked script SET, never a count -- the
    sanctioned third invocation (AUD-10b's `promotion_proposal.py`) must
    never fail this test once it lands."""
    text = _WRAPPER.read_text()
    invoked = set(re.findall(r'"\$PY"\s+"\$REPO/scripts/analysis/([A-Za-z0-9_]+\.py)"', text))
    assert invoked, "expected at least one \"$PY\" invocation in the wrapper"
    unsanctioned = invoked - _SANCTIONED_SCRIPTS
    assert not unsanctioned, f"unsanctioned invocation(s): {unsanctioned}"


def test_wrapper_invokes_both_the_census_and_the_runner() -> None:
    text = _WRAPPER.read_text()
    assert "replay_sufficiency_census.py" in text
    assert "replay_daily_runner.py" in text


#: FU-10 / AUD-10b: the non-secret sqlite path literal
#: `promotion_proposal.py`'s `--tally-output-dir` run resolves
#: `POLYMARKET_US_EXEC_STATE_DB` from, byte-identical to the same line in
#: `breezy-live-tally.service` (and `breezy-score-live-trials.service` /
#: `breezy-family-tally@.service` -- see
#: `tests/unit/test_score_live_trials_deploy.py`'s own
#: `_PINNED_STATE_DB_LITERAL`).
_PINNED_STATE_DB_LITERAL = (
    "Environment=POLYMARKET_US_EXEC_STATE_DB="
    "/home/jon/.local/share/breezy/state/exec_polymarket_us.sqlite"
)

_LIVE_TALLY_SERVICE = _DEPLOY_DIR / "breezy-live-tally.service"


def test_service_carries_the_pinned_exec_state_db_env_line() -> None:
    """FU-10: without this line, promotion_proposal.py's `_fill_count`
    resolves `os.environ["POLYMARKET_US_EXEC_STATE_DB"]` to None and the
    whole scheduled unit fails with KILL_CLOCK_NOT_EVALUABLE (observed
    2026-09-26 14:33Z)."""
    text = _SERVICE.read_text()
    matching = [
        line
        for line in text.splitlines()
        if line.startswith("Environment=POLYMARKET_US_EXEC_STATE_DB=")
    ]
    assert len(matching) == 1
    assert matching[0] == _PINNED_STATE_DB_LITERAL

    live_tally_matching = [
        line
        for line in _LIVE_TALLY_SERVICE.read_text().splitlines()
        if line.startswith("Environment=POLYMARKET_US_EXEC_STATE_DB=")
    ]
    assert len(live_tally_matching) == 1
    assert matching[0] == live_tally_matching[0]


def test_service_carries_no_environment_file_other_than_alerts_env() -> None:
    env_file_lines = [
        line.strip()
        for line in _SERVICE.read_text().splitlines()
        if line.strip().startswith("EnvironmentFile=")
    ]
    assert env_file_lines == ["EnvironmentFile=-%h/.config/breezy/alerts.env"]
