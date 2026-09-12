"""RED/GREEN coverage for `deploy/systemd/alert-webhook-run.sh` (SP-6 A9,
row 16b). Stubs `curl` via a `PATH`-shadowing script recording argv+stdin,
so no real network is ever touched. Idiom:
`tests/unit/test_score_live_trials_deploy.py`.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER = _REPO_ROOT / "deploy" / "systemd" / "alert-webhook-run.sh"

_FAKE_HOST = "sentinel-fake-host.invalid"


def _make_curl_stub(tmp_path: Path, *, exit_code: int = 0) -> Path:
    """A fake `curl` on PATH: records its own argv and stdin to files
    under `tmp_path`, then exits `exit_code`. Never touches a real
    socket."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(exist_ok=True)
    stub = bin_dir / "curl"
    stub.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$@" > "{tmp_path}/curl_argv.txt"\n'
        f'cat > "{tmp_path}/curl_stdin.txt"\n'
        f"exit {exit_code}\n"
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _run_wrapper(
    tmp_path: Path, *, args: list[str], env_extra: dict[str, str], curl_exit: int = 0
) -> subprocess.CompletedProcess[str]:
    bin_dir = _make_curl_stub(tmp_path, exit_code=curl_exit)
    env = {"PATH": f"{bin_dir}:{os.environ.get('PATH', '')}", **env_extra}
    return subprocess.run(
        [str(_WRAPPER), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_exits_zero_and_posts_nothing_when_the_variable_is_unset(tmp_path: Path) -> None:
    result = _run_wrapper(tmp_path, args=["some.service"], env_extra={})

    assert result.returncode == 0
    assert not (tmp_path / "curl_argv.txt").exists()


def test_exits_zero_with_no_argument_under_set_u(tmp_path: Path) -> None:
    result = _run_wrapper(tmp_path, args=[], env_extra={})

    assert result.returncode == 0


def test_the_url_is_written_to_stdin_not_argv(tmp_path: Path) -> None:
    url = f"https://{_FAKE_HOST}/webhook"
    result = _run_wrapper(
        tmp_path, args=["some.service"], env_extra={"BREEZY_ALERT_WEBHOOK_URL": url}
    )

    assert result.returncode == 0
    argv_text = (tmp_path / "curl_argv.txt").read_text()
    assert _FAKE_HOST not in argv_text
    stdin_text = (tmp_path / "curl_stdin.txt").read_text()
    assert _FAKE_HOST in stdin_text


def test_stderr_is_discarded(tmp_path: Path) -> None:
    url = f"https://{_FAKE_HOST}/webhook"
    result = _run_wrapper(
        tmp_path,
        args=["some.service"],
        env_extra={"BREEZY_ALERT_WEBHOOK_URL": url},
        curl_exit=22,
    )

    assert _FAKE_HOST not in result.stderr


def test_script_is_executable_and_sets_uo_pipefail() -> None:
    assert _WRAPPER.stat().st_mode & 0o111
    text = _WRAPPER.read_text()
    assert "set -uo pipefail" in text or "set -o pipefail" in text


def test_script_contains_no_systemd_specifier() -> None:
    """No systemd UNIT specifier (`%i`/`%h`/`%n`/...) anywhere in this
    script's own body -- it is invoked as a plain argv by the template
    unit, which is where specifier expansion happens, never here. The
    ONE `%s` in this file is `printf`'s OWN format specifier (shell,
    not systemd), which the plan text itself specifies."""
    code_lines = [
        line for line in _WRAPPER.read_text().splitlines() if not line.strip().startswith("#")
    ]
    for line in code_lines:
        for spec in ("%i", "%I", "%h", "%n", "%u"):
            assert spec not in line, (spec, line)


def test_a_failing_curl_makes_the_script_exit_non_zero(tmp_path: Path) -> None:
    url = f"https://{_FAKE_HOST}/webhook"
    result = _run_wrapper(
        tmp_path,
        args=["some.service"],
        env_extra={"BREEZY_ALERT_WEBHOOK_URL": url},
        curl_exit=22,
    )

    assert result.returncode != 0


def test_a_failing_curl_prints_no_host_anywhere(tmp_path: Path) -> None:
    url = f"https://{_FAKE_HOST}/webhook"
    result = _run_wrapper(
        tmp_path,
        args=["some.service"],
        env_extra={"BREEZY_ALERT_WEBHOOK_URL": url},
        curl_exit=22,
    )

    assert _FAKE_HOST not in result.stdout
    assert _FAKE_HOST not in result.stderr
