"""Decision D2: three independent unlocks for a credentialed pytest session.

Authority: ``docs/plans/POLYMARKET_US_READONLY_AUTH_PLAN.md`` (revision 2)
D2, and control S9 in section 11.

Before this change, ``pytest_sessionstart`` aborted unconditionally when any
``POLYMARKET_CREDENTIAL_ENV_VARS`` name was set. Revision 1 of the plan
proposed lifting that abort on ``BREEZY_VENUE_LIVE=1``, which was rejected on
review: that one variable would both silence the credential kill-switch AND
unlock ``venue_live`` execution, so a single stray line in a shell profile
would fire real signed requests where that had been structurally impossible.

The gate therefore requires THREE independently-named factors, no one of
which both silences the abort and unlocks execution:

1. ``BREEZY_VENUE_LIVE=1``            -- also the marker-run gate;
2. ``BREEZY_ALLOW_CREDENTIALED_PYTEST=1`` -- unlocks nothing on its own,
   because the marker gate still deselects/skips ``venue_live``;
3. the explicit ``--venue-live`` command-line flag, which no environment
   variable can supply.

The tests below assert each factor ALONE still aborts, that the full set
lifts the abort, and that the autouse scrub keeps credentials out of every
non-``venue_live`` test even inside an exempted session.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.conftest import (
    ALLOW_CREDENTIALED_PYTEST_ENV_VAR,
    POLYMARKET_CREDENTIAL_ENV_VARS,
    VENUE_LIVE_CLI_FLAG,
    VENUE_LIVE_ENV_VAR,
    missing_venue_live_unlocks,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Not a credential. A syntactically-shaped placeholder used only to prove the
#: tripwire fires and that its value is never echoed.
FAKE_SECRET = "not_a_real_secret_only_a_tripwire_probe"

_ALL_UNLOCKS = (VENUE_LIVE_ENV_VAR, ALLOW_CREDENTIALED_PYTEST_ENV_VAR, VENUE_LIVE_CLI_FLAG)


# --------------------------------------------------------------------------
# Pure gate logic -- fast, exhaustive over the 2^3 lattice
# --------------------------------------------------------------------------


def test_no_unlocks_reports_all_three_missing() -> None:
    assert missing_venue_live_unlocks(env={}, venue_live_flag=False) == _ALL_UNLOCKS


@pytest.mark.parametrize(
    ("env", "flag"),
    [
        ({VENUE_LIVE_ENV_VAR: "1"}, False),
        ({ALLOW_CREDENTIALED_PYTEST_ENV_VAR: "1"}, False),
        ({}, True),
    ],
    ids=["venue_live_only", "allow_credentialed_only", "cli_flag_only"],
)
def test_any_single_unlock_alone_is_insufficient(env: dict[str, str], flag: bool) -> None:
    assert missing_venue_live_unlocks(env=env, venue_live_flag=flag) != ()


@pytest.mark.parametrize(
    ("env", "flag"),
    [
        ({VENUE_LIVE_ENV_VAR: "1", ALLOW_CREDENTIALED_PYTEST_ENV_VAR: "1"}, False),
        ({VENUE_LIVE_ENV_VAR: "1"}, True),
        ({ALLOW_CREDENTIALED_PYTEST_ENV_VAR: "1"}, True),
    ],
    ids=["both_env_no_flag", "venue_live_and_flag", "allow_and_flag"],
)
def test_any_pair_of_unlocks_is_still_insufficient(env: dict[str, str], flag: bool) -> None:
    assert missing_venue_live_unlocks(env=env, venue_live_flag=flag) != ()


def test_all_three_unlocks_together_lift_the_gate() -> None:
    env = {VENUE_LIVE_ENV_VAR: "1", ALLOW_CREDENTIALED_PYTEST_ENV_VAR: "1"}
    assert missing_venue_live_unlocks(env=env, venue_live_flag=True) == ()


def test_a_truthy_but_non_one_value_does_not_unlock() -> None:
    """Only the exact string ``"1"`` counts; ``true``/``yes`` must not."""
    env = {VENUE_LIVE_ENV_VAR: "true", ALLOW_CREDENTIALED_PYTEST_ENV_VAR: "yes"}
    assert missing_venue_live_unlocks(env=env, venue_live_flag=True) == (
        VENUE_LIVE_ENV_VAR,
        ALLOW_CREDENTIALED_PYTEST_ENV_VAR,
    )


def test_endpoint_variables_are_not_treated_as_credentials() -> None:
    """Plan D2 point 4: endpoints are configuration, not secrets.

    Listing them would abort the live suite on non-secret configuration and
    teach the tripwire to cry wolf.
    """
    for name in ("POLYMARKET_US_API_BASE", "POLYMARKET_US_GATEWAY_BASE", "POLYMARKET_US_WS_URL"):
        assert name not in POLYMARKET_CREDENTIAL_ENV_VARS


# --------------------------------------------------------------------------
# End-to-end: a real subprocess pytest session
# --------------------------------------------------------------------------


def _run_pytest(
    extra_env: dict[str, str], *args: str, disable_autoload: bool = True
) -> subprocess.CompletedProcess[str]:
    """Run a nested pytest session holding a placeholder credential.

    ``disable_autoload`` mirrors the shipped tripwire test, which sets
    ``PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`` for isolation. That is fine when the
    expected outcome is a non-zero exit, but it makes ``asyncio_mode`` in
    ``pyproject.toml`` an unknown config option and yields exit code 4 --
    so any assertion that the session *succeeds* must let plugins load.
    """
    env = {
        **os.environ,
        "POLYMARKET_US_SECRET_KEY": FAKE_SECRET,
        **({"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"} if disable_autoload else {}),
        **extra_env,
    }
    return subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", *args],
        cwd=REPO_ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


_TARGET = "tests/unit/test_domain_strict_arrow.py"


@pytest.mark.parametrize(
    ("extra_env", "args"),
    [
        ({}, ()),
        ({VENUE_LIVE_ENV_VAR: "1"}, ()),
        ({ALLOW_CREDENTIALED_PYTEST_ENV_VAR: "1"}, ()),
        ({}, (VENUE_LIVE_CLI_FLAG,)),
        ({VENUE_LIVE_ENV_VAR: "1", ALLOW_CREDENTIALED_PYTEST_ENV_VAR: "1"}, ()),
        ({VENUE_LIVE_ENV_VAR: "1"}, (VENUE_LIVE_CLI_FLAG,)),
        ({ALLOW_CREDENTIALED_PYTEST_ENV_VAR: "1"}, (VENUE_LIVE_CLI_FLAG,)),
    ],
    ids=[
        "none",
        "env_venue_live_only",
        "env_allow_only",
        "flag_only",
        "both_env_no_flag",
        "venue_live_and_flag",
        "allow_and_flag",
    ],
)
def test_incomplete_unlocks_still_abort_a_credentialed_session(
    extra_env: dict[str, str], args: tuple[str, ...]
) -> None:
    result = _run_pytest(extra_env, *args, _TARGET)
    combined = result.stdout + result.stderr

    assert result.returncode != 0, combined
    assert "Polymarket credential environment variable(s) present" in combined
    assert "POLYMARKET_US_SECRET_KEY" in combined
    assert FAKE_SECRET not in combined


def test_all_three_unlocks_allow_the_session_to_start() -> None:
    result = _run_pytest(
        {VENUE_LIVE_ENV_VAR: "1", ALLOW_CREDENTIALED_PYTEST_ENV_VAR: "1"},
        VENUE_LIVE_CLI_FLAG,
        _TARGET,
        disable_autoload=False,
    )
    combined = result.stdout + result.stderr

    assert result.returncode == 0, combined
    assert "Polymarket credential environment variable(s) present" not in combined


def test_the_exemption_notice_names_variables_but_never_values() -> None:
    result = _run_pytest(
        {VENUE_LIVE_ENV_VAR: "1", ALLOW_CREDENTIALED_PYTEST_ENV_VAR: "1"},
        VENUE_LIVE_CLI_FLAG,
        "-s",
        _TARGET,
    )
    combined = result.stdout + result.stderr

    assert "POLYMARKET_US_SECRET_KEY" in combined
    assert FAKE_SECRET not in combined


def test_credentials_are_scrubbed_from_an_ordinary_test_inside_an_exempt_session() -> None:
    """Plan D2 point 3: the autouse scrub, proven end to end.

    Even in a session that legitimately carries credentials, a unit test not
    marked ``venue_live``/``real_money`` must observe an empty environment, so
    a call to the credential loader raises rather than picking up a real key.
    """
    probe = REPO_ROOT / "tests" / "unit" / "_scrub_probe_generated.py"
    probe.write_text(
        "import os\n"
        "\n"
        "\n"
        "def test_credentials_are_absent() -> None:\n"
        "    leaked = [n for n in os.environ if n.startswith('POLYMARKET')]\n"
        "    assert leaked == []\n",
        encoding="utf-8",
    )
    try:
        env = {
            **os.environ,
            "POLYMARKET_US_SECRET_KEY": FAKE_SECRET,
            VENUE_LIVE_ENV_VAR: "1",
            ALLOW_CREDENTIALED_PYTEST_ENV_VAR: "1",
        }
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                VENUE_LIVE_CLI_FLAG,
                "-p",
                "no:randomly",
                str(probe.relative_to(REPO_ROOT)),
            ],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )
    finally:
        probe.unlink(missing_ok=True)

    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert FAKE_SECRET not in combined


def test_the_scrub_fixture_is_active_in_this_very_test() -> None:
    """The in-process half of the same guarantee."""
    assert [name for name in POLYMARKET_CREDENTIAL_ENV_VARS if name in os.environ] == []
