"""AUD-15 §7 step 7c(ii) -- the regression pin for the r6 review defect:
the freshness check must still run, and the `asos_cache_stale` WARN must
still fire, on a night the shared studies flock is held by another study.

The retired `mb-daily-run.sh`/`offer-gate-daily-run.sh` idiom `exit 0`d
immediately on lock contention, so nothing after the lock line ever ran on
that path. `asos-refresh-run.sh` captures the lock result instead of
acting on it with an early `exit`, so the freshness check runs
unconditionally. This test holds the real fd-9 lock (mirrors the working
fixture at `tests/unit/test_analysis_units_serialized.py:752-779`) and
spawns the wrapper against it.

**AUD-15 amendment (2026-09-22), folded review finding D-vi.** The original
version of this test asserted `"asos_cache_stale" in (stdout + log)`, which
passed ONLY because `LoggingAlertSink.emit` -> `logger.warning` hits
Python's `lastResort` handler on stderr in a bare subprocess with no
logging config, and the wrapper redirects stderr into the log -- i.e. it
was GREEN because delivery was accidentally logging, the exact false-
positive shape AUD-15 exists to close. This version points
`BREEZY_ALERT_WEBHOOK_URL` at a REAL loopback HTTPS receiver
(`tests/support/loopback_https.py`, already shipped by `f97c26f`) and
asserts on the captured request BODY, an out-of-process artefact, never
log text. The subprocess's own `resolve_alert_sink()` (production code,
unmodified) is made to trust the receiver's throwaway self-signed CA via
`SSL_CERT_FILE` -- `ssl.create_default_context()` (inside
`health._build_webhook_ssl_context`) honours that env var when building its
default trust store, so this needs zero source changes to make the real
webhook path testable end to end.

**AUD-18 amendment (2026-09-25), round-2 review finding B1 (blocking).**
`_WRAPPER` (the file under `deploy/systemd/`) hard-codes `REPO=/home/jon/
breezy`. Spawning that file directly means every invocation resolves the
FOUR python steps under the PRIMARY tree, never this worktree's own edits
-- a change to `iem_mos_backfill.py` or `iem_mos_freshness_check.py` in a
worktree would silently go unexercised by this file's tests. Every test
below now spawns a COPY of the wrapper, in tmp, with its `REPO=` line
rewritten to `_REPO_ROOT` -- the repo root this test file itself resolves
from -- so the wrapper's own bash control flow is exercised unmodified
while the python scripts it invokes are the ones actually under test.
"""

from __future__ import annotations

import fcntl
import os
import subprocess
from pathlib import Path
from typing import Final

import pytest

from tests.support.loopback_https import (
    TlsMaterial,
    generate_loopback_tls_material,
    loopback_https_receiver,
)

pytestmark = pytest.mark.allow_socket

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_DEPLOY_DIR: Final[Path] = _REPO_ROOT / "deploy" / "systemd"
_WRAPPER: Final[Path] = _DEPLOY_DIR / "asos-refresh-run.sh"
_LOCK_FILENAME: Final[str] = "breezy-studies.lock"
_ORIGINAL_REPO_LINE: Final[str] = "REPO=/home/jon/breezy\n"


def _wrapper_for_repo_under_test(tmp_path: Path, repo_root: Path = _REPO_ROOT) -> Path:
    """Copy `_WRAPPER` to tmp with its `REPO=` line rewritten to `repo_root`
    (B1). The wrapper's own bash logic (lock handling, step sequencing, exit
    code) is exercised byte-for-byte; only WHICH tree the python steps
    resolve under changes."""
    original = _WRAPPER.read_text()
    rewritten = original.replace(_ORIGINAL_REPO_LINE, f"REPO={repo_root}\n", 1)
    assert rewritten != original, "REPO= line not found in the wrapper to rewrite"
    target = tmp_path / "asos-refresh-run.sh"
    target.write_text(rewritten)
    target.chmod(0o755)
    return target


def _build_env(
    tmp_path: Path, *, webhook_url: str, ca_path: Path
) -> tuple[dict[str, str], Path, Path]:
    home = tmp_path / "home"
    home.mkdir()
    xdg_runtime_dir = tmp_path / "xdg-runtime"
    xdg_runtime_dir.mkdir()
    out_dir = tmp_path / "out"
    env = {
        "HOME": str(home),
        "XDG_RUNTIME_DIR": str(xdg_runtime_dir),
        "BREEZY_ASOS_REFRESH_OUTPUT_DIR": str(out_dir),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        # Simulates the unit's declared `EnvironmentFile=-%h/.config/breezy/
        # alerts.env` having been loaded by systemd -- this test spawns the
        # wrapper directly via bash, so the env is built here instead.
        "BREEZY_ALERT_WEBHOOK_URL": webhook_url,
        # Makes the SAME `ssl.create_default_context()` production code
        # (`health._build_webhook_ssl_context`) trust the loopback
        # receiver's throwaway CA -- see module docstring.
        "SSL_CERT_FILE": str(ca_path),
    }
    return env, xdg_runtime_dir, out_dir


@pytest.fixture(scope="module")
def tls_material(tmp_path_factory: pytest.TempPathFactory) -> TlsMaterial:
    directory: Path = tmp_path_factory.mktemp("asos-refresh-contention-tls")
    return generate_loopback_tls_material(directory)


def test_the_staleness_check_still_runs_when_the_studies_flock_is_held(
    tmp_path: Path, tls_material: TlsMaterial
) -> None:
    assert _WRAPPER.is_file(), "asos-refresh-run.sh does not exist"
    wrapper = _wrapper_for_repo_under_test(tmp_path)

    with loopback_https_receiver(tls_material) as receiver:
        env, xdg_runtime_dir, out_dir = _build_env(
            tmp_path, webhook_url=receiver.url, ca_path=tls_material.ca_path
        )
        lock_path = xdg_runtime_dir / _LOCK_FILENAME
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            result = subprocess.run(
                ["bash", str(wrapper)], env=env, capture_output=True, text=True,
                timeout=30, check=False,
            )

            log_path = out_dir / "asos_refresh.log"
            log_text = log_path.read_text() if log_path.is_file() else ""
            combined = result.stdout + log_text

            assert result.returncode == 0, combined
            assert "SKIPPED-LOCK" in combined, combined
            assert "another study holds the studies lock" in combined
            # Neither the ASOS nor the MOS refresh subprocess may have run.
            assert "asos refresh ok" not in combined
            assert "asos refresh reported a shortfall" not in combined
            assert "iem-mos refresh" not in combined
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

        # The real, out-of-process delivery artefact -- not log text.
        # AUD-18: replaces the pre-AUD-18 `len(receiver.received) == 1` with
        # an assertion at least as strict -- exactly 2 bodies now that BOTH
        # freshness checks (ASOS and MOS) run unconditionally: one
        # `asos_cache_stale` WARN (the consumer cache key is absent in this
        # fresh scratch HOME) and one `iem_mos_archive_stale` WARN with
        # `MANIFEST_MISSING` (the scratch HOME has no MOS manifest either).
        assert len(receiver.received) == 2, "expected exactly one ASOS WARN and one MOS WARN"
        bodies = [request.json_body() for request in receiver.received]

    asos_bodies = [body for body in bodies if body["event"] == "asos_cache_stale"]
    mos_bodies = [body for body in bodies if body["event"] == "iem_mos_archive_stale"]
    assert len(asos_bodies) == 1
    assert len(mos_bodies) == 1
    assert asos_bodies[0]["severity"] == "WARN"
    assert mos_bodies[0]["severity"] == "WARN"
    assert mos_bodies[0]["detail"] == "manifest_missing"


def test_the_wrapper_is_executable() -> None:
    assert os.access(_WRAPPER, os.X_OK), f"{_WRAPPER.name} is not executable"


# ---------------------------------------------------------------------------
# AUD-18 behavioural wrapper tests: step independence and the exit contract.
#
# These use a DIFFERENT `REPO=` target -- a throwaway stub tree containing a
# fake `.venv/bin/python` that dumps its own env and exits with a scripted
# code, keyed by which script path it was asked to "run". This adds NO test
# seam to production: the wrapper itself is unmodified, only what `REPO`
# resolves to differs from a real invocation.
# ---------------------------------------------------------------------------

_STUB_PYTHON: Final[str] = """#!/usr/bin/env bash
# Test stub standing in for .venv/bin/python: records its own env, keyed by
# the basename of the script path it was asked to run, then exits with a
# scripted code for that step (default 0).
set -uo pipefail
script="$1"
name="$(basename "$script" .py)"
: "${STUB_ENV_DUMP_DIR:?STUB_ENV_DUMP_DIR must be set}"
env > "$STUB_ENV_DUMP_DIR/$name.env"
case "$name" in
  asos_recent_refresh) exit "${STUB_ASOS_REFRESH_EXIT:-0}" ;;
  asos_cache_freshness_check) exit "${STUB_ASOS_FRESHNESS_EXIT:-0}" ;;
  iem_mos_backfill) exit "${STUB_MOS_REFRESH_EXIT:-0}" ;;
  iem_mos_freshness_check) exit "${STUB_MOS_FRESHNESS_EXIT:-0}" ;;
  *) exit 1 ;;
esac
"""


def _build_stub_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "stub-repo"
    venv_bin = repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    stub = venv_bin / "python"
    stub.write_text(_STUB_PYTHON)
    stub.chmod(0o755)
    return repo


def _behavioural_env(
    tmp_path: Path, *, dump_dir: Path, exit_codes: dict[str, int]
) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    xdg_runtime_dir = tmp_path / "xdg-runtime"
    xdg_runtime_dir.mkdir(exist_ok=True)
    out_dir = tmp_path / "out"
    env = {
        "HOME": str(home),
        "XDG_RUNTIME_DIR": str(xdg_runtime_dir),
        "BREEZY_ASOS_REFRESH_OUTPUT_DIR": str(out_dir),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "STUB_ENV_DUMP_DIR": str(dump_dir),
        "BREEZY_USER_AGENT": "breezy-mos-refresh-behavioural-test-ua-TESTONLY",
    }
    _EXIT_VAR = {
        "asos_recent_refresh": "STUB_ASOS_REFRESH_EXIT",
        "asos_cache_freshness_check": "STUB_ASOS_FRESHNESS_EXIT",
        "iem_mos_backfill": "STUB_MOS_REFRESH_EXIT",
        "iem_mos_freshness_check": "STUB_MOS_FRESHNESS_EXIT",
    }
    for step, code in exit_codes.items():
        env[_EXIT_VAR[step]] = str(code)
    return env


def test_all_steps_ok_exits_zero(tmp_path: Path) -> None:
    repo = _build_stub_repo(tmp_path)
    wrapper = _wrapper_for_repo_under_test(tmp_path, repo)
    dump_dir = tmp_path / "dumps"
    dump_dir.mkdir()
    env = _behavioural_env(tmp_path, dump_dir=dump_dir, exit_codes={})

    result = subprocess.run(
        ["bash", str(wrapper)], env=env, capture_output=True, text=True,
        timeout=30, check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    for name in (
        "asos_recent_refresh", "asos_cache_freshness_check",
        "iem_mos_backfill", "iem_mos_freshness_check",
    ):
        assert (dump_dir / f"{name}.env").is_file(), f"{name} did not run"


def test_mos_failure_does_not_skip_asos_and_exits_nonzero(tmp_path: Path) -> None:
    repo = _build_stub_repo(tmp_path)
    wrapper = _wrapper_for_repo_under_test(tmp_path, repo)
    dump_dir = tmp_path / "dumps"
    dump_dir.mkdir()
    env = _behavioural_env(
        tmp_path, dump_dir=dump_dir, exit_codes={"iem_mos_backfill": 1}
    )

    result = subprocess.run(
        ["bash", str(wrapper)], env=env, capture_output=True, text=True,
        timeout=30, check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert (dump_dir / "asos_recent_refresh.env").is_file(), "the ASOS refresh must still run"
    assert (dump_dir / "asos_cache_freshness_check.env").is_file(), (
        "the ASOS freshness check must still run"
    )
    assert (dump_dir / "iem_mos_freshness_check.env").is_file(), (
        "the MOS freshness check must still run despite the MOS refresh failing"
    )


def test_asos_failure_does_not_skip_mos_and_exits_nonzero(tmp_path: Path) -> None:
    repo = _build_stub_repo(tmp_path)
    wrapper = _wrapper_for_repo_under_test(tmp_path, repo)
    dump_dir = tmp_path / "dumps"
    dump_dir.mkdir()
    env = _behavioural_env(
        tmp_path, dump_dir=dump_dir, exit_codes={"asos_recent_refresh": 1}
    )

    result = subprocess.run(
        ["bash", str(wrapper)], env=env, capture_output=True, text=True,
        timeout=30, check=False,
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert (dump_dir / "iem_mos_backfill.env").is_file(), "the MOS refresh must still run"
    assert (dump_dir / "iem_mos_freshness_check.env").is_file(), (
        "the MOS freshness check must still run"
    )


def test_webhook_url_stripped_from_refresh_env(tmp_path: Path) -> None:
    """Behavioural half (the static half lives in
    `test_asos_refresh_re_home.py`): the fetch-step env dumps lack
    `BREEZY_ALERT_WEBHOOK_URL`, the freshness-step dumps have it, and the
    MOS fetch sees `BREEZY_LIVE=1` and the inherited `BREEZY_USER_AGENT`."""
    repo = _build_stub_repo(tmp_path)
    wrapper = _wrapper_for_repo_under_test(tmp_path, repo)
    dump_dir = tmp_path / "dumps"
    dump_dir.mkdir()
    env = _behavioural_env(tmp_path, dump_dir=dump_dir, exit_codes={})
    env["BREEZY_ALERT_WEBHOOK_URL"] = "https://example.invalid/alerts"

    result = subprocess.run(
        ["bash", str(wrapper)], env=env, capture_output=True, text=True,
        timeout=30, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    def _dump(name: str) -> str:
        return (dump_dir / f"{name}.env").read_text()

    assert "BREEZY_ALERT_WEBHOOK_URL=" not in _dump("asos_recent_refresh")
    assert "BREEZY_ALERT_WEBHOOK_URL=" not in _dump("iem_mos_backfill")
    assert "BREEZY_ALERT_WEBHOOK_URL=" in _dump("asos_cache_freshness_check")
    assert "BREEZY_ALERT_WEBHOOK_URL=" in _dump("iem_mos_freshness_check")

    mos_refresh_env = _dump("iem_mos_backfill")
    assert "BREEZY_LIVE=1" in mos_refresh_env
    assert f"BREEZY_USER_AGENT={env['BREEZY_USER_AGENT']}" in mos_refresh_env
