"""R-5 ruling (`docs/evidence/RULING_R5_prereg_v1_tally_2026-09-24.md`, §4):
``breezy-live-tally`` is retired -- disabled by the coordinator via
``systemctl --user disable --now breezy-live-tally.timer`` (host state, not
this repo's concern). This guard covers what a hermetic CI run CAN observe:
the unit files are present-but-never-deleted, both carry a RETIRED header
naming the ruling, no install step under ``deploy/`` still enables the
timer, and the retirement is documented in ``deploy/systemd/README.md``.

No logic/directive change: this test never touches `live-tally-run.sh`,
`scripts/analysis/live_family_tally.py`, or `mb_current_rung_edge_study.py`
(byte-pinned by `test_prereg_v1_is_byte_unmodified.py`).
"""

from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_SYSTEMD = _REPO / "deploy" / "systemd"
_TIMER = _SYSTEMD / "breezy-live-tally.timer"
_SERVICE = _SYSTEMD / "breezy-live-tally.service"
_README = _SYSTEMD / "README.md"
_RULING = _REPO / "docs" / "evidence" / "RULING_R5_prereg_v1_tally_2026-09-24.md"

_RULING_NAME = "RULING_R5_prereg_v1_tally_2026-09-24.md"


def test_the_ruling_artefact_exists() -> None:
    assert _RULING.exists()


def test_both_unit_files_are_still_present_never_deleted() -> None:
    assert _TIMER.exists()
    assert _SERVICE.exists()


def test_both_unit_files_carry_a_retired_header_naming_the_ruling() -> None:
    for path in (_TIMER, _SERVICE):
        text = path.read_text(encoding="utf-8")
        assert "RETIRED" in text, f"{path} missing RETIRED marker"
        assert _RULING_NAME in text, f"{path} does not name the ruling artefact"


def test_no_install_step_under_deploy_enables_the_retired_timer() -> None:
    offenders: list[str] = []
    for path in _SYSTEMD.rglob("*"):
        if path.is_dir():
            continue
        # The unit files' own descriptive comments about their systemd
        # mechanics ("no [Install] section, X is the only thing to
        # enable") are architecture notes about themselves, not an active
        # install step performed elsewhere -- excluded deliberately.
        if path in (_TIMER, _SERVICE):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if "breezy-live-tally.timer" in line and re.search(r"\benable\b", line, re.IGNORECASE):
                offenders.append(f"{path}:{lineno}: {line.strip()}")
    assert offenders == [], offenders


def test_readme_documents_the_retirement() -> None:
    text = _README.read_text(encoding="utf-8")
    assert "breezy-live-tally" in text
    assert "RETIRED 2026-09-24" in text
    assert _RULING_NAME in text
