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

    with loopback_https_receiver(tls_material) as receiver:
        env, xdg_runtime_dir, out_dir = _build_env(
            tmp_path, webhook_url=receiver.url, ca_path=tls_material.ca_path
        )
        lock_path = xdg_runtime_dir / _LOCK_FILENAME
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            result = subprocess.run(
                ["bash", str(_WRAPPER)], env=env, capture_output=True, text=True,
                timeout=30, check=False,
            )

            log_path = out_dir / "asos_refresh.log"
            log_text = log_path.read_text() if log_path.is_file() else ""
            combined = result.stdout + log_text

            assert result.returncode == 0, combined
            assert "SKIPPED-LOCK" in combined, combined
            assert "another study holds the studies lock" in combined
            # The refresh subprocess must NOT have run on this path.
            assert "asos refresh ok" not in combined
            assert "asos refresh reported a shortfall" not in combined
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            os.close(lock_fd)

        # The real, out-of-process delivery artefact -- not log text. The
        # consumer's cache key is absent in this fresh scratch HOME, so
        # exactly one WARN reaches the receiver.
        assert len(receiver.received) == 1, "the alert never left the process"
        body = receiver.received[0].json_body()

    assert body["event"] == "asos_cache_stale"
    assert body["severity"] == "WARN"


def test_the_wrapper_is_executable() -> None:
    assert os.access(_WRAPPER, os.X_OK), f"{_WRAPPER.name} is not executable"
