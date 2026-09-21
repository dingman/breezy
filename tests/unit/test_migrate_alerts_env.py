"""AUD-15 amendment (2026-09-22), Set B -- `deploy/systemd/migrate-alerts-env.sh`.

Every test runs the REAL script as a subprocess against a throwaway `HOME`
(never the real `~/.config/breezy`) with a FAKE `systemctl` placed first on
`PATH`. No test ever asserts on, prints, or constructs the VALUE of
`BREEZY_ALERT_WEBHOOK_URL` beyond a fixture literal used only to prove the
migrated line is byte-identical -- names, counts and modes are what the
script itself promises never to leak.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_SCRIPT: Final[Path] = _REPO_ROOT / "deploy" / "systemd" / "migrate-alerts-env.sh"

#: A fixture value, never asserted to reach any log/stdout capture -- only
#: byte-equality between the two files' matching line is checked.
_FIXTURE_URL_LINE: Final[str] = "BREEZY_ALERT_WEBHOOK_URL=https://ntfy.sh/fixture-topic-token\n"

_FAKE_SYSTEMCTL_NOT_YET_RELOADED: Final[str] = """#!/usr/bin/env bash
if [ "$1" = "--user" ] && [ "$2" = "cat" ]; then
  echo "[Unit]"
  echo "Description=fake"
  echo "[Service]"
  echo "EnvironmentFile=-%h/.config/breezy/breezy-trade.env"
  exit 0
fi
exit 1
"""

_FAKE_SYSTEMCTL_RELOADED: Final[str] = """#!/usr/bin/env bash
if [ "$1" = "--user" ] && [ "$2" = "cat" ]; then
  echo "[Unit]"
  echo "Description=fake"
  echo "[Service]"
  echo "EnvironmentFile=-%h/.config/breezy/alerts.env"
  echo "EnvironmentFile=-%h/.config/breezy/breezy-trade.env"
  exit 0
fi
exit 1
"""


def _config_dir(home: Path) -> Path:
    d = home / ".config" / "breezy"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write_trade_env(config_dir: Path, lines: list[str]) -> Path:
    path = config_dir / "breezy-trade.env"
    path.write_text("".join(lines))
    path.chmod(0o600)
    return path


def _fake_systemctl_path(tmp_path: Path, script_text: str) -> Path:
    bin_dir = tmp_path / "fakebin"
    bin_dir.mkdir(exist_ok=True)
    systemctl = bin_dir / "systemctl"
    systemctl.write_text(script_text)
    systemctl.chmod(0o755)
    return bin_dir


def _fake_failing_mv_path(tmp_path: Path) -> Path:
    """A `PATH` entry whose `mv` always fails -- forces the script's own
    `mv -f "$tmp_file" "$ALERTS_ENV"` to fail deterministically, so the
    temp-file cleanup trap can be proven on a REAL failure rather than only
    on the happy path."""
    bin_dir = tmp_path / "fake-failing-mv-bin"
    bin_dir.mkdir(exist_ok=True)
    fake_mv = bin_dir / "mv"
    fake_mv.write_text("#!/usr/bin/env bash\nexit 1\n")
    fake_mv.chmod(0o755)
    return bin_dir


def _stray_temp_files(config_dir: Path) -> list[Path]:
    return sorted(config_dir.glob(".alerts.env.*"))


def _run(
    tmp_path: Path, *args: str, home: Path | None = None, fake_bin_dir: Path | None = None
) -> subprocess.CompletedProcess[str]:
    env = {
        "HOME": str(home if home is not None else tmp_path / "home"),
        "PATH": f"{fake_bin_dir}:{os.environ.get('PATH', '/usr/bin:/bin')}"
        if fake_bin_dir is not None
        else os.environ.get("PATH", "/usr/bin:/bin"),
    }
    return subprocess.run(
        ["bash", str(_SCRIPT), *args], env=env, capture_output=True, text=True,
        timeout=15, check=False,
    )


def test_bash_syntax_is_valid() -> None:
    result = subprocess.run(
        ["bash", "-n", str(_SCRIPT)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_fresh_migrate_creates_alerts_env_mode_600_and_leaves_trade_env_unchanged(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    config_dir = _config_dir(home)
    trade_env = _write_trade_env(config_dir, [_FIXTURE_URL_LINE])
    trade_env_before = trade_env.read_text()

    result = _run(tmp_path, home=home)

    assert result.returncode == 0, result.stderr
    alerts_env = config_dir / "alerts.env"
    assert alerts_env.is_file()
    assert alerts_env.read_text() == _FIXTURE_URL_LINE
    assert stat.S_IMODE(alerts_env.stat().st_mode) == 0o600
    # breezy-trade.env is UNCHANGED in the base migration mode.
    assert trade_env.read_text() == trade_env_before
    assert stat.S_IMODE(config_dir.stat().st_mode) == 0o700


def test_idempotent_re_run_does_not_duplicate_or_change_the_line(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    config_dir = _config_dir(home)
    _write_trade_env(config_dir, [_FIXTURE_URL_LINE])

    first = _run(tmp_path, home=home)
    assert first.returncode == 0, first.stderr
    alerts_env = config_dir / "alerts.env"
    after_first = alerts_env.read_text()

    second = _run(tmp_path, home=home)

    assert second.returncode == 0, second.stderr
    assert alerts_env.read_text() == after_first == _FIXTURE_URL_LINE
    assert stat.S_IMODE(alerts_env.stat().st_mode) == 0o600


def test_zero_key_aborts_and_creates_nothing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    config_dir = _config_dir(home)
    _write_trade_env(config_dir, ["POLYMARKET_US_ACCOUNT_NUMBER=irrelevant\n"])

    result = _run(tmp_path, home=home)

    assert result.returncode != 0
    assert not (config_dir / "alerts.env").exists()


def test_two_keys_in_trade_env_aborts(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    config_dir = _config_dir(home)
    _write_trade_env(config_dir, [_FIXTURE_URL_LINE, _FIXTURE_URL_LINE])

    result = _run(tmp_path, home=home)

    assert result.returncode != 0
    assert not (config_dir / "alerts.env").exists()


def test_finalize_refused_before_the_installed_unit_shows_the_reload(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    config_dir = _config_dir(home)
    trade_env = _write_trade_env(config_dir, [_FIXTURE_URL_LINE])
    migrate = _run(tmp_path, home=home)
    assert migrate.returncode == 0, migrate.stderr

    fake_bin = _fake_systemctl_path(tmp_path, _FAKE_SYSTEMCTL_NOT_YET_RELOADED)
    result = _run(tmp_path, "--finalize", "--delivery-confirmed", home=home, fake_bin_dir=fake_bin)

    assert result.returncode != 0
    # Refused: the key must still be present in breezy-trade.env.
    assert "BREEZY_ALERT_WEBHOOK_URL=" in trade_env.read_text()


def test_finalize_refused_without_delivery_confirmed_even_after_reload(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    config_dir = _config_dir(home)
    trade_env = _write_trade_env(config_dir, [_FIXTURE_URL_LINE])
    migrate = _run(tmp_path, home=home)
    assert migrate.returncode == 0, migrate.stderr

    fake_bin = _fake_systemctl_path(tmp_path, _FAKE_SYSTEMCTL_RELOADED)
    result = _run(tmp_path, "--finalize", home=home, fake_bin_dir=fake_bin)

    assert result.returncode != 0
    assert "BREEZY_ALERT_WEBHOOK_URL=" in trade_env.read_text()


def test_finalize_ok_removes_the_key_from_trade_env_and_reasserts_mode_600(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    config_dir = _config_dir(home)
    trade_env = _write_trade_env(
        config_dir, ["BREEZY_USER_AGENT=x\n", _FIXTURE_URL_LINE, "BREEZY_TRADE_TRADER_ID=y\n"]
    )
    migrate = _run(tmp_path, home=home)
    assert migrate.returncode == 0, migrate.stderr

    fake_bin = _fake_systemctl_path(tmp_path, _FAKE_SYSTEMCTL_RELOADED)
    result = _run(tmp_path, "--finalize", "--delivery-confirmed", home=home, fake_bin_dir=fake_bin)

    assert result.returncode == 0, result.stderr
    trade_text = trade_env.read_text()
    assert "BREEZY_ALERT_WEBHOOK_URL=" not in trade_text
    assert "BREEZY_USER_AGENT=x" in trade_text
    assert "BREEZY_TRADE_TRADER_ID=y" in trade_text
    assert stat.S_IMODE(trade_env.stat().st_mode) == 0o600
    alerts_env = config_dir / "alerts.env"
    assert alerts_env.read_text() == _FIXTURE_URL_LINE
    assert stat.S_IMODE(alerts_env.stat().st_mode) == 0o600


def test_the_script_never_prints_the_webhook_value(tmp_path: Path) -> None:
    """The one property every other test assumes: neither stdout nor
    stderr, in any mode, ever contains the fixture URL's actual value."""
    home = tmp_path / "home"
    home.mkdir()
    config_dir = _config_dir(home)
    _write_trade_env(config_dir, [_FIXTURE_URL_LINE])

    migrate = _run(tmp_path, home=home)
    fake_bin = _fake_systemctl_path(tmp_path, _FAKE_SYSTEMCTL_RELOADED)
    finalize = _run(
        tmp_path, "--finalize", "--delivery-confirmed", home=home, fake_bin_dir=fake_bin
    )

    secret = "ntfy.sh/fixture-topic-token"
    assert secret not in migrate.stdout
    assert secret not in migrate.stderr
    assert secret not in finalize.stdout
    assert secret not in finalize.stderr


def test_fresh_migrate_leaves_no_stray_temp_file_behind(tmp_path: Path) -> None:
    """Atomic-write regression pin: the final artefact must land exactly at
    `alerts.env`, never beside it at its `mktemp` staging name."""
    home = tmp_path / "home"
    home.mkdir()
    config_dir = _config_dir(home)
    _write_trade_env(config_dir, [_FIXTURE_URL_LINE])

    result = _run(tmp_path, home=home)

    assert result.returncode == 0, result.stderr
    assert _stray_temp_files(config_dir) == []
    assert (config_dir / "alerts.env").is_file()


def test_zero_key_abort_never_touches_a_pre_existing_alerts_env(tmp_path: Path) -> None:
    """A pre-existing `alerts.env` (e.g. holding an unrelated line while
    mid-migration) must never be truncated or replaced on an abort path --
    the abort must happen strictly BEFORE any write to it."""
    home = tmp_path / "home"
    home.mkdir()
    config_dir = _config_dir(home)
    _write_trade_env(config_dir, ["POLYMARKET_US_ACCOUNT_NUMBER=irrelevant\n"])
    alerts_env = config_dir / "alerts.env"
    pre_existing_content = "# not yet migrated, unrelated placeholder\n"
    alerts_env.write_text(pre_existing_content)
    alerts_env.chmod(0o600)

    result = _run(tmp_path, home=home)

    assert result.returncode != 0
    assert alerts_env.read_text() == pre_existing_content
    assert _stray_temp_files(config_dir) == []


def test_two_key_abort_never_touches_a_pre_existing_alerts_env(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    config_dir = _config_dir(home)
    _write_trade_env(config_dir, [_FIXTURE_URL_LINE, _FIXTURE_URL_LINE])
    alerts_env = config_dir / "alerts.env"
    pre_existing_content = "# not yet migrated, unrelated placeholder\n"
    alerts_env.write_text(pre_existing_content)
    alerts_env.chmod(0o600)

    result = _run(tmp_path, home=home)

    assert result.returncode != 0
    assert alerts_env.read_text() == pre_existing_content
    assert _stray_temp_files(config_dir) == []


def test_a_forced_write_failure_cleans_up_the_temp_file_via_trap(tmp_path: Path) -> None:
    """A REAL mid-write failure (here: `mv` itself fails), not just the
    happy path -- proves the `trap 'rm -f "$tmp_file"' EXIT` actually runs
    rather than merely being unreachable dead code."""
    home = tmp_path / "home"
    home.mkdir()
    config_dir = _config_dir(home)
    _write_trade_env(config_dir, [_FIXTURE_URL_LINE])
    fake_mv_bin = _fake_failing_mv_path(tmp_path)

    result = _run(tmp_path, home=home, fake_bin_dir=fake_mv_bin)

    assert result.returncode != 0
    assert _stray_temp_files(config_dir) == []
    assert not (config_dir / "alerts.env").exists()
