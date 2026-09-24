"""AUD-08b §7 step 13: the nightly emitter rides ``breezy-quote-tape-rotate.service``.

Parses unit text and runs the wrapper against a stub interpreter inside
``tmp_path`` only. Never reads an INSTALLED unit, never runs ``systemctl``,
never touches the real ``$HOME`` or ``XDG_RUNTIME_DIR``.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Final

_REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
_DEPLOY_DIR: Final[Path] = _REPO_ROOT / "deploy" / "systemd"
_ROTATE_UNIT: Final[Path] = _DEPLOY_DIR / "breezy-quote-tape-rotate.service"
_WRAPPER: Final[Path] = _DEPLOY_DIR / "station-candidate-register-run.sh"
_SCORE_WRAPPER: Final[Path] = _DEPLOY_DIR / "score-live-trials-run.sh"

#: The one env-then-constant catalog resolution the scorer already uses; the
#: emitter must read the SAME root so the register and the KILL clock agree.
_CATALOG_LINE: Final[str] = (
    "CATALOG_ROOT=${BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG:-"
    "$HOME/.local/share/breezy/catalog/quote_tape/polymarket_us}"
)


def _directives(text: str, name: str) -> list[str]:
    prefix = f"{name}="
    return [
        line.strip()[len(prefix) :] for line in text.splitlines() if line.strip().startswith(prefix)
    ]


def test_the_rotate_unit_runs_the_emitter_after_the_recorder_rotation() -> None:
    exec_starts = _directives(_ROTATE_UNIT.read_text(), "ExecStart")

    assert exec_starts == [
        "/usr/bin/systemctl --user try-restart breezy-quote-tape.service",
        f"/home/jon/breezy/deploy/systemd/{_WRAPPER.name}",
    ]


def test_the_rotate_unit_carries_the_studies_slice_memory_ceiling_and_alert_egress() -> None:
    text = _ROTATE_UNIT.read_text()

    assert _directives(text, "Slice") == ["breezy-studies.slice"]
    assert _directives(text, "MemoryHigh") and _directives(text, "MemoryMax")
    assert _directives(text, "EnvironmentFile") == ["-%h/.config/breezy/alerts.env"]
    assert _directives(text, "OnFailure") == ["breezy-study-failed@%n.service"]


def test_the_wrapper_resolves_the_catalog_byte_identically_to_the_scorer() -> None:
    assert _CATALOG_LINE in _SCORE_WRAPPER.read_text().splitlines()
    wrapper = _WRAPPER.read_text()
    assert _CATALOG_LINE in wrapper.splitlines()
    assert '--catalog-root "$CATALOG_ROOT"' in wrapper
    assert "scripts/analysis/station_candidate_register.py" in wrapper
    assert os.access(_WRAPPER, os.X_OK)


def test_the_wrapper_takes_the_shared_studies_flock() -> None:
    lines = _WRAPPER.read_text().splitlines()

    assert 'LOCK="$LOCK_DIR/breezy-studies.lock"' in lines
    assert any(line.startswith('exec 9>>"$LOCK"') for line in lines)
    assert any(line.startswith("flock -n 9") and "exit 0" in line for line in lines)


def _run_wrapper(tmp_path: Path, extra_env: dict[str, str]) -> list[str]:
    home = tmp_path / "home"
    runtime = tmp_path / "run"
    home.mkdir()
    runtime.mkdir()
    argv_file = tmp_path / "argv.txt"
    stub = tmp_path / "python"
    stub.write_text(f'#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "{argv_file}"\n')
    stub.chmod(0o755)
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "XDG_RUNTIME_DIR": str(runtime),
        "BREEZY_STATION_CANDIDATES_PYTHON": str(stub),
        "BREEZY_STATION_CANDIDATES_OUTPUT_DIR": str(tmp_path / "out"),
        **extra_env,
    }
    completed = subprocess.run(
        [str(_WRAPPER)], env=env, capture_output=True, text=True, check=False, timeout=30
    )
    assert completed.returncode == 0, completed.stderr
    return argv_file.read_text().splitlines()


def test_the_wrapper_passes_the_env_catalog_root(tmp_path: Path) -> None:
    catalog = tmp_path / "catalog"
    argv = _run_wrapper(tmp_path, {"BREEZY_POLYMARKET_US_QUOTE_TAPE_CATALOG": str(catalog)})

    assert argv[0].endswith("scripts/analysis/station_candidate_register.py")
    assert argv[argv.index("--catalog-root") + 1] == str(catalog)
    assert argv[argv.index("--state-dir") + 1] == str(tmp_path / "out")


def test_the_wrapper_defaults_the_catalog_root_under_home(tmp_path: Path) -> None:
    argv = _run_wrapper(tmp_path, {})

    assert argv[argv.index("--catalog-root") + 1] == str(
        tmp_path / "home" / ".local/share/breezy/catalog/quote_tape/polymarket_us"
    )
