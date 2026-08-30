"""Executable gates for the archived backfill separation contract."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Final

from breezy.ingest.shared_state import DEFAULT_ALLOWED_HOSTS

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
SRC_ROOT: Final[Path] = REPO_ROOT / "src" / "breezy"
CATALOG_MODULE: Final[Path] = SRC_ROOT / "persistence" / "catalog.py"
GENERATED_INTERMEDIARY: Final[Path] = (
    SRC_ROOT / "persistence" / "_gate_archive_intermediary.py"
)

_GENERATED_SOURCE = '''"""Synthesised by the archive separation gate test; deleted after."""

from __future__ import annotations

from breezy.persistence.archive_catalog import read_archived_climate_days

__all__ = ["read_archived_climate_days"]
'''

_CATALOG_IMPORT = "\nfrom breezy.persistence import _gate_archive_intermediary\n"


def _run_lint_imports() -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "UV_CACHE_DIR": "/tmp/uv-cache"}
    return subprocess.run(
        [str(REPO_ROOT / ".venv" / "bin" / "lint-imports")],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_lint_imports_catches_archived_records_through_indirect_chain() -> None:
    """Separation mutant: `allow_indirect_imports = true` or readers in catalog."""
    original_catalog = CATALOG_MODULE.read_text(encoding="utf-8")
    GENERATED_INTERMEDIARY.write_text(_GENERATED_SOURCE, encoding="utf-8")
    CATALOG_MODULE.write_text(original_catalog + _CATALOG_IMPORT, encoding="utf-8")

    try:
        result = _run_lint_imports()
    finally:
        CATALOG_MODULE.write_text(original_catalog, encoding="utf-8")
        GENERATED_INTERMEDIARY.unlink(missing_ok=True)

    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "Settlement and strategy code never reaches archived backfill records" in output
    assert "breezy.ingest.nws_actor" in output
    assert "breezy.persistence.archive_catalog" in output


def test_archive_forbidden_contract_is_explicitly_indirect_strict() -> None:
    """Separation mutant: silently relying on or weakening the default."""
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")

    assert (
        'name = "Settlement and strategy code never reaches archived backfill records"' in pyproject
    )
    assert "allow_indirect_imports = false" in pyproject
    assert "breezy.persistence.archive_catalog" in pyproject
    assert "breezy.ingest.archive_records" in pyproject


def test_settlement_transport_hosts_stay_nws_only_and_src_never_names_iem_host() -> None:
    """Separation mutant: moving IEM retrieval into `src/breezy`."""
    assert DEFAULT_ALLOWED_HOSTS == frozenset({"api.weather.gov"})

    offenders: list[Path] = []
    for path in SRC_ROOT.rglob("*.py"):
        if "mesonet.agron.iastate.edu" in path.read_text(encoding="utf-8"):
            offenders.append(path.relative_to(REPO_ROOT))

    assert offenders == []
