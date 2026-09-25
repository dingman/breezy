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
