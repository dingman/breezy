"""AUD-02 A0 follow-up (2026-09-25): the fee-drift evidence pull unit used to
hardcode a personal email address in its ``--user-agent`` literal, committed
to the repo and sent to the venue on every request. Fixed by sourcing the
contact string from the operator's own non-credential env file
(``%h/.config/breezy/breezy.env``, holding ``BREEZY_USER_AGENT``) rather than
a literal in the unit. Shape mirrors the other ``deploy/systemd`` hermetic
text-parsing tests (e.g. ``test_portfolio_roi_deploy.py``): this module never
runs ``systemctl``/``daemon-reload``, it only reads unit text.
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SYSTEMD_DIR = _REPO_ROOT / "deploy" / "systemd"
_SERVICE = _SYSTEMD_DIR / "breezy-fee-evidence-pull.service"
_TIMER = _SYSTEMD_DIR / "breezy-fee-evidence-pull.timer"

_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9-]+)+"
)


def _directive_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if not line.strip().startswith("#")]


def test_unit_and_timer_exist() -> None:
    assert _SERVICE.is_file()
    assert _TIMER.is_file()


def test_unit_file_contains_no_email_address_on_any_line() -> None:
    text = _SERVICE.read_text()
    offending = [line for line in text.splitlines() if _EMAIL_RE.search(line)]
    assert offending == [], f"unit file still hardcodes an email address: {offending!r}"


def test_exec_start_substitutes_the_user_agent_from_the_environment() -> None:
    lines = _directive_lines(_SERVICE.read_text())
    exec_start_lines = [line for line in lines if line.startswith("ExecStart=")]
    assert len(exec_start_lines) == 1
    assert '--user-agent "${BREEZY_USER_AGENT}"' in exec_start_lines[0]
    # No leftover literal contact string alongside the substitution.
    assert "contact" not in exec_start_lines[0]


def test_service_declares_the_breezy_env_and_alerts_env_environment_files(
) -> None:
    lines = _directive_lines(_SERVICE.read_text())
    env_files = [line for line in lines if line.startswith("EnvironmentFile=")]
    assert "EnvironmentFile=%h/.config/breezy/breezy.env" in env_files
    assert "EnvironmentFile=-%h/.config/breezy/alerts.env" in env_files
    # breezy.env is required (no leading `-`): a missing file must fail
    # loudly rather than silently substituting an empty user agent.
    assert not any(
        line.startswith("EnvironmentFile=-") and "breezy.env" in line for line in env_files
    )


def test_no_credential_env_file_is_referenced() -> None:
    # Scoped to actual EnvironmentFile= directives, not comment prose: the
    # unit's own comment explains this exclusion by NAMING the forbidden
    # files, which would otherwise trip a raw substring-of-the-whole-file
    # check.
    lines = _directive_lines(_SERVICE.read_text())
    env_files = [line for line in lines if line.startswith("EnvironmentFile=")]
    for forbidden in ("polymarket.env", "breezy-trade.env", "operator.env"):
        assert not any(forbidden in env_file for env_file in env_files)
