"""AUD-08b §7 step 13: the nightly emitter is its own unit, started by the rotation.

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
_REGISTER_UNIT: Final[Path] = _DEPLOY_DIR / "breezy-station-candidate-register.service"
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


def test_the_rotate_unit_is_its_pre_08b_self_plus_one_non_blocking_start() -> None:
    """Decoupled (review HIGH): the register can never fail, slow or re-slice the rotation.

    ``OnSuccess=`` enqueues the register unit as a SEPARATE job only after the
    rotation finished successfully; the register's own outcome can never
    reach back into this unit's result.
    """
    text = _ROTATE_UNIT.read_text()

    assert _directives(text, "ExecStart") == [
        "/usr/bin/systemctl --user try-restart breezy-quote-tape.service"
    ]
    assert _directives(text, "OnSuccess") == [_REGISTER_UNIT.name]
    assert _directives(text, "ExecStartPost") == []
    for directive in ("Slice", "MemoryHigh", "MemoryMax", "EnvironmentFile"):
        assert _directives(text, directive) == [], directive
    assert _directives(text, "TimeoutStartSec") == ["180"]
    starts = [
        line
        for line in text.splitlines()
        if not line.lstrip().startswith("#") and _REGISTER_UNIT.name in line
    ]
    assert starts == [f"OnSuccess={_REGISTER_UNIT.name}"]


def test_the_rotate_unit_differs_from_its_pre_08b_content_by_directive_only_in_onsuccess() -> None:
    """Every non-comment line of the base unit survives byte-identical."""
    base = subprocess.run(
        ["git", "show", "c527439:deploy/systemd/breezy-quote-tape-rotate.service"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    def directive_lines(text: str) -> list[str]:
        return [line for line in text.splitlines() if line.strip() and not line.startswith("#")]

    current = directive_lines(_ROTATE_UNIT.read_text())
    added = [line for line in current if line not in directive_lines(base)]
    assert added == [f"OnSuccess={_REGISTER_UNIT.name}"]
    assert [line for line in current if not line.startswith("OnSuccess=")] == directive_lines(base)


def test_the_register_unit_carries_its_own_slice_ceiling_alerting_and_wrapper() -> None:
    text = _REGISTER_UNIT.read_text()

    assert _directives(text, "Type") == ["oneshot"]
    assert _directives(text, "ExecStart") == [f"/home/jon/breezy/deploy/systemd/{_WRAPPER.name}"]
    assert _directives(text, "Slice") == ["breezy-studies.slice"]
    assert _directives(text, "MemoryHigh") and _directives(text, "MemoryMax")
    assert _directives(text, "EnvironmentFile") == ["-%h/.config/breezy/alerts.env"]
    assert _directives(text, "OnFailure") == ["breezy-study-failed@%n.service"]
    assert _directives(text, "TimeoutStartSec")
    # Started only by the rotate unit's OnSuccess=: no timer, no [Install].
    assert not (_DEPLOY_DIR / "breezy-station-candidate-register.timer").exists()
    assert "[Install]" not in text.splitlines()


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


def test_the_wrapper_checks_staleness_when_it_skips_on_the_lock() -> None:
    """A study that holds the lock every night must not silently starve the register."""
    lines = _WRAPPER.read_text().splitlines()
    (skip,) = [line for line in lines if line.startswith("flock -n 9")]
    assert "--check-staleness" in skip


def test_the_recorder_unit_loads_the_alert_webhook_so_a_broken_sidecar_can_page() -> None:
    """The sidecar-broken alert is raised INSIDE the recorder; without alerts.env it
    would degrade to a journal line nobody reads."""
    text = (_DEPLOY_DIR / "breezy-quote-tape.service").read_text()

    assert "-%h/.config/breezy/alerts.env" in _directives(text, "EnvironmentFile")
